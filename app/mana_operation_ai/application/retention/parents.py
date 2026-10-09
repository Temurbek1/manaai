import hashlib
import json
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from typing import cast

from pydantic import JsonValue

from app.mana_operation_ai.application.ports import (
    Clock,
    IdGenerator,
    OperationRepository,
    ProviderOperationError,
    ProviderPermanentError,
)
from app.mana_operation_ai.application.retention.constants import (
    PARENTS_CAPABILITY_KEY,
    RETENTION_AGENT_ID,
)
from app.mana_operation_ai.application.retention.parent_ports import (
    ParentReadCooldownError,
    ParentSummaryPort,
)
from app.mana_operation_ai.domain.enums import (
    AgentRunStage,
    AgentRunStatus,
    AuditEventType,
    CapabilityRisk,
    TriggerType,
    UserRole,
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
from app.mana_operation_ai.domain.parents import ParentSummaryConfiguration
from app.mana_operation_ai.domain.state_machine import RUN_TRANSITIONS, require_transition


class ParentSummaryCapabilityHandler:
    """Manual-only, minimized MANA inventory. No Firestore, model calls or customer actions."""

    def __init__(
        self,
        *,
        source: ParentSummaryPort,
        repository: OperationRepository,
        clock: Clock,
        ids: IdGenerator,
        minimum_interval_seconds: int = 21600,
    ) -> None:
        self._source = source
        self._repository = repository
        self._clock = clock
        self._ids = ids
        self._minimum_interval = minimum_interval_seconds

    @property
    def definition(self) -> CapabilityDefinition:
        return CapabilityDefinition(
            key=PARENTS_CAPABILITY_KEY,
            agent_id=RETENTION_AGENT_ID,
            description="Manual bounded MANA parent and tariff summary, not payment evidence.",
            risk=CapabilityRisk.READ,
            minimum_role=UserRole.OPERATOR,
            input_schema=cast(dict[str, JsonValue], ParentSummaryConfiguration.model_json_schema()),
            output_schema=cast(dict[str, JsonValue], AgentRunResult.model_json_schema()),
            required_integrations=[self._source.integration_id],
            supported_triggers={TriggerType.USER},
        )

    @property
    def default_configuration(self) -> dict[str, JsonValue]:
        return cast(dict[str, JsonValue], ParentSummaryConfiguration().model_dump(mode="json"))

    def validate_configuration(self, values: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return cast(
            dict[str, JsonValue],
            ParentSummaryConfiguration.model_validate(values).model_dump(mode="json"),
        )

    def default_schedules(self, agent_id: str) -> list[AgentSchedule]:
        return []

    def schedules_for_configuration(
        self,
        *,
        agent_id: str,
        values: dict[str, JsonValue],
        existing: Sequence[AgentSchedule],
    ) -> list[AgentSchedule]:
        self.validate_configuration(values)
        return []

    async def health(self) -> list[IntegrationHealth]:
        # Saved run evidence is authoritative; a page refresh never probes the provider.
        return []

    async def execute(
        self,
        *,
        run: AgentRun,
        job_type: str,
        configuration: AgentConfiguration,
    ) -> AgentRunResult:
        try:
            return await self._execute(run=run, job_type=job_type, configuration=configuration)
        except ProviderOperationError as exc:
            current = await self._repository.get_run(run.run_id)
            if current is not None:
                failed = await self._transition(
                    current,
                    AgentRunStatus.FAILED,
                    current.current_stage or AgentRunStage.COLLECT,
                )
                await self._repository.update_run(
                    failed.model_copy(
                        update={
                            "error_code": type(exc).__name__,
                            "error_message": (
                                "Повторное чтение Parent API пока запрещено защитным интервалом. "
                                "Используйте сохранённую сводку; автоматического повтора нет."
                                if isinstance(exc, ParentReadCooldownError)
                                else "Сводку Parent API получить не удалось. "
                                "Проверьте доступ и контракт; "
                                "автоматического повтора нет."
                            ),
                        }
                    )
                )
            raise

    async def _execute(
        self,
        *,
        run: AgentRun,
        job_type: str,
        configuration: AgentConfiguration,
    ) -> AgentRunResult:
        self.validate_configuration(configuration.values)
        if run.trigger is not TriggerType.USER or job_type != "analysis":
            raise ProviderPermanentError(
                "MANA parent summary supports explicit manual analysis only"
            )
        now = self._clock.now()
        # Persist admission BEFORE network I/O. Failures consume the same cooldown;
        # process restarts, multiple administrators and new UUIDs cannot bypass it.
        admitted = await self._repository.acquire_lock(
            key="source-read:mana:parent-summary",
            owner_id=run.run_id,
            now=now,
            expires_at=now + timedelta(seconds=self._minimum_interval),
        )
        if not admitted:
            raise ParentReadCooldownError("Parent API cooldown is active; use the saved report")
        run = await self._transition(run, AgentRunStatus.COLLECTING, AgentRunStage.COLLECT)
        facts = await self._source.collect_summary()
        run = await self._transition(run, AgentRunStatus.NORMALIZING, AgentRunStage.NORMALIZE)
        payload = cast(dict[str, JsonValue], facts.model_dump(mode="json"))
        checksum = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        coverage = (
            Decimal(facts.sampled_parents) / Decimal(facts.total_parents)
            if facts.total_parents
            else Decimal(1)
        )
        evidence = EvidenceRef(
            source=facts.source,
            subject_scope="mana_parent_inventory_prefix_sample",
            period_start=now,
            period_end=facts.collected_at,
            collected_at=facts.collected_at,
            freshness_seconds=0,
            completeness=coverage,
            checksum=checksum,
            privacy_classification="aggregate_parent_profile_minimized",
        )
        snapshot = DataSnapshot(
            snapshot_id=self._ids.new(),
            run_id=run.run_id,
            agent_id=RETENTION_AGENT_ID,
            capability_key=PARENTS_CAPABILITY_KEY,
            provider=facts.source,
            schema_version="mana-parent-summary-v1",
            period_start=now,
            period_end=facts.collected_at,
            collected_at=facts.collected_at,
            checksum=checksum,
            completeness=coverage,
            evidence_refs=[evidence],
            payload=payload,
            provider_request_ids=facts.source_request_ids,
        )
        await self._repository.save_snapshot(snapshot)
        for status, stage in [
            (AgentRunStatus.ANALYZING, AgentRunStage.ANALYZE),
            (AgentRunStatus.PROPOSING, AgentRunStage.PROPOSE),
            (AgentRunStatus.POLICY_CHECK, AgentRunStage.POLICY_CHECK),
            (AgentRunStatus.REPORTING, AgentRunStage.REPORT),
        ]:
            run = await self._transition(run, status, stage)
        summary = (
            f"MANA · {'тестовая сводка' if facts.mode == 'demo' else 'Parent API'}. "
            f"Всего родителей по count API: {facts.total_parents}. "
            f"Прочитано {facts.sampled_parents} родителей (ограниченная первая страница). "
            f"Только в этой выборке: текущий тариф — {facts.parents_with_current_tariff}, "
            f"нет текущего тарифа — {facts.parents_without_current_tariff}, "
            f"неполные тарифные данные — {facts.parents_with_inconsistent_tariff}; "
            f"истечение в 7 дней — {facts.tariffs_expiring_within_7_days}, "
            f"в 30 дней — {facts.tariffs_expiring_within_30_days}. "
            f"Есть дети — {facts.parents_with_children}, есть подключённые дети — "
            f"{facts.parents_with_connected_children}. "
            f"Заполнено имя — {facts.parents_with_name}, телефон — {facts.parents_with_phone}, "
            f"возраст — {facts.parents_with_known_age}, регион — {facts.parents_with_region}, "
            f"район — {facts.parents_with_district}. "
            f"Дата записи покупки известна — {facts.parents_with_purchase_date}. "
            "Тариф может быть бесплатным: оплаченные подписки, выручка и отток неизвестны. "
            "На всю базу показатели выборки не распространяются."
        )
        report = AgentReport(
            report_id=self._ids.new(),
            agent_id=RETENTION_AGENT_ID,
            capability_key=PARENTS_CAPABILITY_KEY,
            run_id=run.run_id,
            report_type="mana_parent_summary",
            period_start=now,
            period_end=facts.collected_at,
            structured=payload,
            human_readable=summary,
            data_quality_notes=facts.limitations,
            created_at=self._clock.now(),
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
        raise ValueError("Parent summary has no actions to finalize")

    async def _transition(
        self, run: AgentRun, status: AgentRunStatus, stage: AgentRunStage
    ) -> AgentRun:
        require_transition(run.status, status, RUN_TRANSITIONS)
        updated = run.model_copy(
            update={
                "status": status,
                "current_stage": stage,
                "updated_at": self._clock.now(),
                "completed_at": self._clock.now()
                if status in {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED}
                else None,
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
                summary=f"MANA parent summary moved to {status.value}",
                details={"stage": stage.value},
            )
        )
        return updated
