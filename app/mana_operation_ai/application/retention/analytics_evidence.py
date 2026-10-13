"""Manual-only scoped evidence inside Retention; never activates a schedule."""

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import cast
from zoneinfo import ZoneInfo

from pydantic import JsonValue

from app.mana_operation_ai.application.ports import (
    Clock,
    IdGenerator,
    OperationRepository,
    ProviderPermanentError,
)
from app.mana_operation_ai.application.retention.analytics_ports import AnalyticsEvidencePort
from app.mana_operation_ai.application.shared_data import SharedDataReader
from app.mana_operation_ai.domain.enums import (
    AgentRunStage,
    AgentRunStatus,
    AuditEventType,
    CapabilityRisk,
    TriggerType,
    UserRole,
)
from app.mana_operation_ai.domain.first_party_analytics import (
    CHILD_TELEMETRY_CAPABILITY,
    PARENT_ACTIVITY_CAPABILITY,
    ChildTelemetryFacts,
    ManualAnalyticsConfiguration,
    ParentAnalyticsFacts,
)
from app.mana_operation_ai.domain.models import (
    AgentConfiguration,
    AgentReport,
    AgentRun,
    AgentRunResult,
    AgentSchedule,
    AuditEvent,
    CapabilityDefinition,
    DataSnapshot,
    EvidenceRef,
    IntegrationHealth,
)
from app.mana_operation_ai.domain.shared_data import SourceBinding
from app.mana_operation_ai.domain.state_machine import RUN_TRANSITIONS, require_transition


class ManualAnalyticsEvidenceHandler[T: ParentAnalyticsFacts | ChildTelemetryFacts]:
    def __init__(
        self,
        *,
        source: AnalyticsEvidencePort[T],
        model: type[T],
        binding: SourceBinding,
        shared_reader: SharedDataReader,
        repository: OperationRepository,
        clock: Clock,
        ids: IdGenerator,
        cache_parameters: dict[str, object] | None = None,
    ) -> None:
        if (
            model not in (ParentAnalyticsFacts, ChildTelemetryFacts)
            or binding.product.value != "mana"
        ):
            raise ValueError("Manual MANA analytics requires its exact source/product contract")
        self._source, self._model, self._binding = source, model, binding
        self._reader, self._repository, self._clock, self._ids = (
            shared_reader,
            repository,
            clock,
            ids,
        )
        parent = model is ParentAnalyticsFacts
        self._cache_parameters = {
            "contract": "manual-mana-analytics-v1",
            **(cache_parameters or {}),
        }
        self._key = PARENT_ACTIVITY_CAPABILITY if parent else CHILD_TELEMETRY_CAPABILITY
        expected_source = (
            "mana_ga4_parent_analytics" if parent else "mana_firestore_child_telemetry"
        )
        if binding.source != expected_source:
            raise ValueError("The source binding differs from its analytics contract")

    @property
    def definition(self) -> CapabilityDefinition:
        return CapabilityDefinition(
            key=self._key,
            agent_id="retention-agent",
            risk=CapabilityRisk.READ,
            minimum_role=UserRole.OPERATOR,
            description=(
                "Manual MANA parent-stream GA4 activity, mature exact-day retention and push "
                "engagement funnel; no billing, children or external writes."
                if self._model is ParentAnalyticsFacts
                else "Manual MANA child-device battery/GPS field-quality prefix samples: at most "
                "100 documents per collection, not parent activity or population estimates."
            ),
            input_schema=cast(
                dict[str, JsonValue], ManualAnalyticsConfiguration.model_json_schema()
            ),
            output_schema=cast(dict[str, JsonValue], AgentRunResult.model_json_schema()),
            required_integrations=[self._binding.source],
            supported_triggers={TriggerType.USER},
        )

    @property
    def default_configuration(self) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], ManualAnalyticsConfiguration().model_dump(mode="json"))

    def validate_configuration(self, values: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return cast(
            dict[str, JsonValue],
            ManualAnalyticsConfiguration.model_validate(values).model_dump(mode="json"),
        )

    def default_schedules(self, agent_id: str) -> list[AgentSchedule]:
        return []

    def schedules_for_configuration(
        self, *, agent_id: str, values: dict[str, JsonValue], existing: Sequence[AgentSchedule]
    ) -> list[AgentSchedule]:
        self.validate_configuration(values)
        return []

    async def health(self) -> list[IntegrationHealth]:
        # Health/status/catalog polling observes SQL only; no credential refresh or source I/O.
        return []

    async def execute(
        self, *, run: AgentRun, job_type: str, configuration: AgentConfiguration
    ) -> AgentRunResult:
        self.validate_configuration(configuration.values)
        if (
            run.trigger is not TriggerType.USER
            or job_type != "analysis"
            or (run.capability_key != self._key or configuration.capability_key != self._key)
        ):
            raise ProviderPermanentError("MANA analytics supports scoped manual analysis only")
        run = await self._transition(run, AgentRunStatus.COLLECTING, AgentRunStage.COLLECT)
        facts = await self._reader.read(
            binding=self._binding,
            parameters=self._cache_parameters,
            model=self._model,
            load=self._source.collect,
        )
        run = await self._transition(run, AgentRunStatus.NORMALIZING, AgentRunStage.NORMALIZE)
        if facts.source != self._binding.source or facts.product_scope is not self._binding.product:
            raise ProviderPermanentError("MANA analytics result has a different source scope")
        payload = cast(dict[str, JsonValue], facts.model_dump(mode="json"))
        payload.update(product="mana", scope_verified=True, scope_basis="approved_source_binding")
        checksum = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        period_start, period_end = _period(facts)
        snapshot = DataSnapshot(
            snapshot_id=self._ids.new(),
            run_id=run.run_id,
            agent_id="retention-agent",
            capability_key=self._key,
            provider=facts.source,
            schema_version="mana-manual-analytics-v1",
            period_start=period_start,
            period_end=period_end,
            collected_at=facts.collected_at,
            checksum=checksum,
            completeness=Decimal(1) if _complete_parent_contract(facts) else Decimal(0),
            payload=payload,
            provider_request_ids=facts.source_request_ids,
            evidence_refs=[
                EvidenceRef(
                    source=facts.source,
                    subject_scope=f"mana:{facts.population}",
                    period_start=period_start,
                    period_end=period_end,
                    collected_at=facts.collected_at,
                    freshness_seconds=max(
                        0, int((self._clock.now() - facts.collected_at).total_seconds())
                    ),
                    completeness=Decimal(1) if _complete_parent_contract(facts) else Decimal(0),
                    checksum=checksum,
                    privacy_classification="minimized_aggregate",
                )
            ],
        )
        await self._repository.save_snapshot(snapshot)
        for status, stage in [
            (AgentRunStatus.ANALYZING, AgentRunStage.ANALYZE),
            (AgentRunStatus.PROPOSING, AgentRunStage.PROPOSE),
            (AgentRunStatus.POLICY_CHECK, AgentRunStage.POLICY_CHECK),
            (AgentRunStatus.REPORTING, AgentRunStage.REPORT),
        ]:
            run = await self._transition(run, status, stage)
        report = AgentReport(
            report_id=self._ids.new(),
            run_id=run.run_id,
            agent_id="retention-agent",
            capability_key=self._key,
            report_type="mana_first_party_analytics",
            period_start=period_start,
            period_end=period_end,
            created_at=self._clock.now(),
            structured=payload,
            human_readable=render_analytics(facts),
            data_quality_notes=facts.limitations,
        )
        await self._repository.save_report(report)
        run = await self._transition(run, AgentRunStatus.COMPLETED, AgentRunStage.REPORT)
        return AgentRunResult(
            run_id=run.run_id,
            status=run.status,
            snapshot_ids=[snapshot.snapshot_id],
            report_id=report.report_id,
            completed_at=run.completed_at,
        )

    async def finalize_after_actions(self, run_id: str) -> AgentRunResult:
        raise ValueError("Manual analytics has no actions to finalize")

    async def _transition(
        self, run: AgentRun, status: AgentRunStatus, stage: AgentRunStage
    ) -> AgentRun:
        require_transition(run.status, status, RUN_TRANSITIONS)
        updated = run.model_copy(
            update={
                "status": status,
                "current_stage": stage,
                "updated_at": self._clock.now(),
                "completed_at": self._clock.now() if status is AgentRunStatus.COMPLETED else None,
            }
        )
        await self._repository.update_run(updated)
        await self._repository.save_audit_event(
            AuditEvent(
                event_id=self._ids.new(),
                correlation_id=run.correlation_id,
                agent_id=run.agent_id,
                capability_key=run.capability_key,
                run_id=run.run_id,
                event_type=AuditEventType.RUN_STAGE_CHANGED,
                actor_id=run.initiated_by,
                actor_role=UserRole.OPERATOR,
                occurred_at=self._clock.now(),
                summary=f"Manual MANA analytics moved to {status.value}",
                details={"stage": stage.value},
            )
        )
        return updated


def _period(facts: ParentAnalyticsFacts | ChildTelemetryFacts) -> tuple[datetime, datetime]:
    if isinstance(facts, ParentAnalyticsFacts):
        timezone = ZoneInfo(facts.property_timezone)
        return (
            datetime.combine(facts.period_start, time.min, timezone).astimezone(UTC),
            datetime.combine(facts.period_end + timedelta(days=1), time.min, timezone).astimezone(
                UTC
            ),
        )
    return facts.collected_at, facts.collected_at


def _complete_parent_contract(facts: ParentAnalyticsFacts | ChildTelemetryFacts) -> bool:
    return (
        isinstance(facts, ParentAnalyticsFacts)
        and len(facts.windows) == 3
        and facts.event_inventory_complete
        and len(facts.cohorts) == 2
        and all(cohort.quality == "complete" for cohort in facts.cohorts)
        and facts.notification_funnel is not None
        and facts.notification_funnel.quality == "complete"
        and len(facts.breakdowns) == 6
        and all(item.quality == "complete" for item in facts.breakdowns)
    )


def render_analytics(facts: ParentAnalyticsFacts | ChildTelemetryFacts) -> str:
    lines = [
        f"MANA · наблюдения получены {facts.collected_at.isoformat()} · {facts.refresh_status}."
    ]
    if isinstance(facts, ParentAnalyticsFacts):
        lines.append(
            f"Родительский GA4-поток {facts.stream_id}, {facts.property_timezone}; "
            f"период {facts.period_start} — {facts.period_end}. Это аналитические "
            "идентификаторы приложения, не backend-аккаунты или дети."
        )
        for window in facts.windows:
            lines.append(
                f"За {window.days} дней: активных пользователей {window.active_users}; "
                f"сессий {window.sessions}; вовлечённых сессий {window.engaged_sessions}; "
                f"время вовлечения {window.engagement_seconds} сек."
            )
        lines.append(
            f"События · {facts.event_quality} (имя: количество): "
            + json.dumps(facts.event_counts, sort_keys=True)
        )
        for cohort in facts.cohorts:
            rows = {row.day: row for row in cohort.days}
            if cohort.quality != "complete":
                lines.append(
                    f"Когорта первой сессии {cohort.first_session_date}: "
                    f"{cohort.quality}. Полный D1/D7/D30 не подтверждён; пропуск не ноль."
                )
                continue
            denominator = rows[0].total_users
            results = "; ".join(
                f"D{day}: {rows[day].active_users}/{denominator} "
                f"({Decimal(rows[day].active_users) / denominator * 100:.2f}%)"
                for day in [1, 7, 30]
            )
            lines.append(
                f"Когорта {cohort.first_session_date}: {results}. "
                "Это возврат в конкретный день, не накопленный возврат за период."
            )
        funnel = facts.notification_funnel
        if funnel is None:
            lines.append("Push-воронка не наблюдалась; это не измеренная нулевая конверсия.")
        else:
            lines.append(
                "Push-воронка receive → open → button_click, 24 часа между этапами: "
                + " → ".join(str(value) for value in funnel.users)
                + f"; {funnel.quality}."
            )
            if funnel.quality == "complete":
                for index in [0, 1]:
                    before, after = funnel.users[index : index + 2]
                    rate = f"{Decimal(after) / before * 100:.2f}%" if before else "не определена"
                    lines.append(
                        f"Этап {index + 1} → {index + 2}: конверсия {rate}; "
                        f"отвал {before - after}. Это вовлечение, не платёж или причинный эффект."
                    )
        titles = {
            "screens": "Экраны",
            "devices": "Устройства родительского приложения",
            "geography": "География активности (не продажи)",
            "acquisition": "Атрибуция первого привлечения (не оплаты)",
            "weekday_hour": "День недели и час в timezone свойства (0 — воскресенье)",
            "notification_open_minutes": "Последние минуты открытия push (не доставка)",
        }
        for breakdown in facts.breakdowns:
            lines.append(
                f"{titles[breakdown.kind]}: {breakdown.quality}; "
                f"показано групп {len(breakdown.rows)}/{breakdown.total_groups}; "
                f"скрыто длинных/потенциально личных значений: {breakdown.withheld_rows}."
            )
            for row in breakdown.rows:
                lines.append(
                    json.dumps(
                        {
                            "labels": row.labels,
                            "measures": {key: str(value) for key, value in row.measures.items()},
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
        lines.append("Это ограниченные срезы; пользователей между группами нельзя складывать.")
    else:
        lines.append(
            "Детские устройства: ограниченная выборка по ID документов. "
            "Она не репрезентативна и не измеряет всю базу или родительское удержание."
        )
        for sample in facts.samples:
            lines.append(
                f"{sample.collection}: документов {sample.sampled_documents}, "
                f"валидных полей {sample.valid_observations}, "
                f"невалидных {sample.invalid_observations}; "
                f"есть ещё документы: {sample.more_documents}. "
                f"Серверных обновлений в последние 6ч: {sample.recent_server_updates}; "
                f"будущих клиентских дат: {sample.future_client_dates}; "
                f"неизвестное время/timezone: {sample.unknown_client_timezone}. "
                f"Серверный updateTime: {sample.source_updated_min} — {sample.source_updated_max}."
            )
            if sample.low_battery_observations is not None:
                lines.append(
                    f"Полей заряда ≤20%: {sample.low_battery_observations}; "
                    "это не подтверждённое текущее состояние всех устройств."
                )
            if sample.precise_location_observations is not None:
                lines.append(
                    "Недавних не-mock GPS наблюдений с точностью "
                    f"≤{facts.precise_accuracy_limit_meters}м: "
                    f"{sample.precise_location_observations}; "
                    f"mock: {sample.mock_location_observations}."
                )
    lines.extend(["Ограничения:", *facts.limitations])
    return "\n".join(lines)
