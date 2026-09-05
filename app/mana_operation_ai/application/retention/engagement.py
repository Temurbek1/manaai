import asyncio
import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

from pydantic import JsonValue

from app.mana_operation_ai.application.ports import (
    BackendActivityPort,
    Clock,
    IdGenerator,
    MobileActivityPort,
    OperationRepository,
)
from app.mana_operation_ai.application.retention.constants import (
    ENGAGEMENT_CAPABILITY_KEY,
    RETENTION_AGENT_ID,
)
from app.mana_operation_ai.application.scheduling import next_cron_occurrence
from app.mana_operation_ai.domain.enums import (
    ActivityEventType,
    AgentRunStage,
    AgentRunStatus,
    AuditEventType,
    CapabilityRisk,
    DataAvailability,
    FindingSeverity,
    TriggerType,
    UserRole,
)
from app.mana_operation_ai.domain.models import (
    AgentConfiguration,
    AgentReport,
    AgentRun,
    AgentRunResult,
    AgentSchedule,
    Analysis,
    AuditEvent,
    CapabilityDefinition,
    DataSnapshot,
    EvidenceMetric,
    EvidenceRef,
    Finding,
    IntegrationHealth,
    MetricValue,
)
from app.mana_operation_ai.domain.retention import (
    BackendActivityFacts,
    MobileActivityFacts,
    RetentionEngagementConfiguration,
    RetentionEngagementSnapshot,
)
from app.mana_operation_ai.domain.state_machine import RUN_TRANSITIONS, require_transition


class RetentionEngagementCapabilityHandler:
    def __init__(
        self,
        *,
        backend_activity: BackendActivityPort,
        mobile_activity: MobileActivityPort,
        repository: OperationRepository,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._backend_activity = backend_activity
        self._mobile_activity = mobile_activity
        self._repository = repository
        self._clock = clock
        self._ids = ids
        self._definition = CapabilityDefinition(
            key=ENGAGEMENT_CAPABILITY_KEY,
            agent_id=RETENTION_AGENT_ID,
            description=(
                "Combines privacy-minimized Manakids backend aggregates with mobile Firebase "
                "activity events to measure first-party engagement and data coverage."
            ),
            risk=CapabilityRisk.READ,
            minimum_role=UserRole.OPERATOR,
            input_schema=cast(
                dict[str, JsonValue],
                RetentionEngagementConfiguration.model_json_schema(),
            ),
            output_schema=cast(dict[str, JsonValue], AgentRunResult.model_json_schema()),
            required_integrations=[
                backend_activity.integration_id,
                mobile_activity.integration_id,
            ],
            supported_triggers={TriggerType.USER, TriggerType.SCHEDULE},
        )

    @property
    def definition(self) -> CapabilityDefinition:
        return self._definition

    @property
    def default_configuration(self) -> dict[str, JsonValue]:
        return cast(
            dict[str, JsonValue],
            RetentionEngagementConfiguration().model_dump(mode="json"),
        )

    def default_schedules(self, agent_id: str) -> list[AgentSchedule]:
        configuration = RetentionEngagementConfiguration()
        return [self._schedule(agent_id, configuration, None)]

    def schedules_for_configuration(
        self,
        *,
        agent_id: str,
        values: dict[str, JsonValue],
        existing: Sequence[AgentSchedule],
    ) -> list[AgentSchedule]:
        configuration = RetentionEngagementConfiguration.model_validate(values)
        previous = next(
            (item for item in existing if item.schedule_id == "retention-engagement-analysis"),
            None,
        )
        return [self._schedule(agent_id, configuration, previous)]

    def validate_configuration(self, values: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return cast(
            dict[str, JsonValue],
            RetentionEngagementConfiguration.model_validate(values).model_dump(mode="json"),
        )

    async def health(self) -> list[IntegrationHealth]:
        backend, mobile = await asyncio.gather(
            self._backend_activity.health(),
            self._mobile_activity.health(),
        )
        return [backend, mobile]

    async def execute(
        self,
        *,
        run: AgentRun,
        job_type: str,
        configuration: AgentConfiguration,
    ) -> AgentRunResult:
        if job_type != "analysis":
            raise ValueError(f"Unsupported retention engagement job type {job_type!r}")
        typed_configuration = RetentionEngagementConfiguration.model_validate(
            configuration.values,
        )
        try:
            run = await self._transition(run, AgentRunStatus.COLLECTING, AgentRunStage.COLLECT)
            period_end = self._clock.now()
            period_start = period_end - timedelta(days=typed_configuration.lookback_days)
            backend, mobile = await asyncio.gather(
                self._backend_activity.collect_activity(
                    period_start=period_start,
                    period_end=period_end,
                ),
                self._mobile_activity.collect_activity(
                    period_start=period_start,
                    period_end=period_end,
                ),
            )

            run = await self._transition(
                run,
                AgentRunStatus.NORMALIZING,
                AgentRunStage.NORMALIZE,
            )
            normalized = _normalize(backend, mobile, self._clock.now())
            snapshot = self._snapshot(
                run,
                normalized,
                [*backend.source_request_ids, *mobile.source_request_ids],
            )
            await self._repository.save_snapshot(snapshot)

            run = await self._transition(run, AgentRunStatus.ANALYZING, AgentRunStage.ANALYZE)
            analysis, findings = self._analyze(
                run=run,
                snapshot=snapshot,
                normalized=normalized,
                configuration=typed_configuration,
            )
            await self._repository.save_analysis(analysis)
            await self._repository.save_findings(findings)

            run = await self._transition(run, AgentRunStatus.PROPOSING, AgentRunStage.PROPOSE)
            await self._repository.save_recommendations([])
            run = await self._transition(
                run,
                AgentRunStatus.POLICY_CHECK,
                AgentRunStage.POLICY_CHECK,
            )
            return await self._finish(run=run, snapshot=normalized, findings=findings)
        except Exception as exc:
            if run.status is not AgentRunStatus.FAILED:
                require_transition(run.status, AgentRunStatus.FAILED, RUN_TRANSITIONS)
                now = self._clock.now()
                failed = run.model_copy(
                    update={
                        "status": AgentRunStatus.FAILED,
                        "updated_at": now,
                        "completed_at": now,
                        "error_code": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                await self._repository.update_run(failed)
            raise

    async def finalize_after_actions(self, run_id: str) -> AgentRunResult:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise LookupError(f"Run {run_id!r} was not found")
        return AgentRunResult(
            run_id=run.run_id,
            status=run.status,
            completed_at=run.completed_at,
        )

    def _analyze(
        self,
        *,
        run: AgentRun,
        snapshot: DataSnapshot,
        normalized: RetentionEngagementSnapshot,
        configuration: RetentionEngagementConfiguration,
    ) -> tuple[Analysis, list[Finding]]:
        backend_active_ratio = _ratio_metric(
            numerator=normalized.backend_active_children,
            denominator=normalized.total_children,
        )
        metrics: dict[str, MetricValue] = {
            "backend_active_child_ratio": backend_active_ratio,
            "total_children": _count_metric(normalized.total_children),
            "backend_active_children": _count_metric(normalized.backend_active_children),
            "mobile_active_subjects": _count_metric(normalized.mobile_active_subjects),
            "mobile_sessions": _count_metric(normalized.mobile_sessions),
            "mobile_screen_time_seconds": _count_metric(
                normalized.mobile_screen_time_seconds,
                unit="seconds",
            ),
            "new_parent_accounts": _count_metric(normalized.parent_accounts_joined),
            "new_child_accounts": _count_metric(normalized.child_accounts_joined),
        }
        metrics.update(
            {
                f"mobile_{event_type.value}": _count_metric(count)
                for event_type, count in normalized.mobile_event_counts.items()
            },
        )
        analysis = Analysis(
            analysis_id=self._ids.new(),
            run_id=run.run_id,
            snapshot_id=snapshot.snapshot_id,
            calculated_at=self._clock.now(),
            metrics=metrics,
            baseline_metrics={},
            data_quality_score=normalized.completeness,
            notes=[
                "Metrics are deterministic calculations over aggregate first-party facts.",
                "Raw names, phone numbers, child IDs, session IDs, GPS, and search text are not "
                "persisted by this capability.",
                *normalized.limitations,
            ],
        )
        findings: list[Finding] = []
        if normalized.completeness < configuration.minimum_completeness:
            findings.append(
                self._finding(
                    run=run,
                    analysis=analysis,
                    snapshot=snapshot,
                    normalized=normalized,
                    finding_type="engagement_data_incomplete",
                    title="Engagement data coverage is incomplete",
                    description=(
                        f"Combined source completeness {normalized.completeness:.4f} is below "
                        f"the configured minimum {configuration.minimum_completeness:.4f}."
                    ),
                    metric_name="data_completeness",
                    metric=MetricValue(
                        value=normalized.completeness,
                        unit="ratio",
                        availability=DataAvailability.AVAILABLE,
                    ),
                ),
            )
            return analysis, findings
        if (
            backend_active_ratio.value is not None
            and backend_active_ratio.value < configuration.minimum_active_child_ratio
        ):
            findings.append(
                self._finding(
                    run=run,
                    analysis=analysis,
                    snapshot=snapshot,
                    normalized=normalized,
                    finding_type="low_backend_engagement",
                    title="Backend-measured child engagement is low",
                    description=(
                        f"The active-child ratio {backend_active_ratio.value:.4f} is below "
                        f"the configured minimum {configuration.minimum_active_child_ratio:.4f}."
                    ),
                    metric_name="backend_active_child_ratio",
                    metric=backend_active_ratio,
                ),
            )
        if sum(normalized.mobile_event_counts.values()) == 0:
            findings.append(
                self._finding(
                    run=run,
                    analysis=analysis,
                    snapshot=snapshot,
                    normalized=normalized,
                    finding_type="mobile_activity_missing",
                    title="No mobile product activity was observed",
                    description=(
                        "The Firebase activity collection returned no supported events for the "
                        "analysis window."
                    ),
                    metric_name="mobile_event_count",
                    metric=_count_metric(0),
                ),
            )
        return analysis, findings

    def _finding(
        self,
        *,
        run: AgentRun,
        analysis: Analysis,
        snapshot: DataSnapshot,
        normalized: RetentionEngagementSnapshot,
        finding_type: str,
        title: str,
        description: str,
        metric_name: str,
        metric: MetricValue,
    ) -> Finding:
        return Finding(
            finding_id=self._ids.new(),
            run_id=run.run_id,
            analysis_id=analysis.analysis_id,
            finding_type=finding_type,
            severity=FindingSeverity.WARNING,
            title=title,
            description=description,
            object_type="engagement_cohort",
            provider_object_id="all_children",
            evidence=[EvidenceMetric(name=metric_name, current=metric)],
            confidence=normalized.completeness,
            source_snapshot_id=snapshot.snapshot_id,
            period_start=normalized.period_start,
            period_end=normalized.period_end,
            attribution_identity="aggregate_first_party_activity",
            deterministic_calculation="aggregate counts and ratios over the configured window",
            completeness=normalized.completeness,
            limitations=normalized.limitations,
            created_at=self._clock.now(),
        )

    async def _finish(
        self,
        *,
        run: AgentRun,
        snapshot: RetentionEngagementSnapshot,
        findings: list[Finding],
    ) -> AgentRunResult:
        run = await self._transition(run, AgentRunStatus.REPORTING, AgentRunStage.REPORT)
        report = AgentReport(
            report_id=self._ids.new(),
            agent_id=run.agent_id,
            capability_key=run.capability_key,
            run_id=run.run_id,
            report_type="retention_engagement_analysis",
            period_start=snapshot.period_start,
            period_end=snapshot.period_end,
            structured={
                "total_children": snapshot.total_children,
                "backend_active_children": snapshot.backend_active_children,
                "mobile_active_subjects": snapshot.mobile_active_subjects,
                "mobile_sessions": snapshot.mobile_sessions,
                "mobile_event_counts": {
                    key.value: value for key, value in snapshot.mobile_event_counts.items()
                },
                "mobile_dimension_counts": snapshot.mobile_dimension_counts,
                "mobile_sequence_counts": snapshot.mobile_sequence_counts,
                "mobile_screen_time_seconds": snapshot.mobile_screen_time_seconds,
                "parent_accounts_joined": snapshot.parent_accounts_joined,
                "child_accounts_joined": snapshot.child_accounts_joined,
                "completeness": str(snapshot.completeness),
                "finding_ids": [item.finding_id for item in findings],
            },
            human_readable=(
                f"Engagement analyzed for {snapshot.total_children} children: "
                f"{snapshot.backend_active_children} had backend activity and "
                f"{snapshot.mobile_active_subjects} appeared in mobile telemetry."
            ),
            data_quality_notes=snapshot.limitations,
            created_at=self._clock.now(),
        )
        await self._repository.save_report(report)
        run = await self._transition(run, AgentRunStatus.COMPLETED, AgentRunStage.REPORT)
        return AgentRunResult(
            run_id=run.run_id,
            status=run.status,
            snapshot_ids=[
                item.snapshot_id for item in await self._repository.list_snapshots(run.run_id)
            ],
            finding_ids=[item.finding_id for item in findings],
            report_id=report.report_id,
            completed_at=run.completed_at,
        )

    async def _transition(
        self,
        run: AgentRun,
        target: AgentRunStatus,
        stage: AgentRunStage,
    ) -> AgentRun:
        require_transition(run.status, target, RUN_TRANSITIONS)
        now = self._clock.now()
        updated = run.model_copy(
            update={
                "status": target,
                "current_stage": stage,
                "updated_at": now,
                "completed_at": now if target is AgentRunStatus.COMPLETED else None,
            },
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
                occurred_at=now,
                summary=f"Run moved to {target.value}",
                details={"stage": stage.value},
            ),
        )
        return updated

    def _snapshot(
        self,
        run: AgentRun,
        snapshot: RetentionEngagementSnapshot,
        provider_request_ids: list[str],
    ) -> DataSnapshot:
        payload = cast(dict[str, JsonValue], snapshot.model_dump(mode="json"))
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return DataSnapshot(
            snapshot_id=self._ids.new(),
            run_id=run.run_id,
            agent_id=run.agent_id,
            capability_key=run.capability_key,
            provider="normalized_first_party_activity",
            schema_version=snapshot.schema_version,
            period_start=snapshot.period_start,
            period_end=snapshot.period_end,
            collected_at=snapshot.collected_at,
            checksum=hashlib.sha256(serialized.encode()).hexdigest(),
            provider_request_ids=provider_request_ids,
            completeness=snapshot.completeness,
            evidence_refs=snapshot.evidence_refs,
            payload=payload,
        )

    def _schedule(
        self,
        agent_id: str,
        configuration: RetentionEngagementConfiguration,
        previous: AgentSchedule | None,
    ) -> AgentSchedule:
        return AgentSchedule(
            schedule_id="retention-engagement-analysis",
            agent_id=agent_id,
            capability_key=ENGAGEMENT_CAPABILITY_KEY,
            job_type="analysis",
            cron_expression=configuration.schedule,
            timezone=configuration.timezone,
            enabled=previous.enabled if previous is not None else True,
            next_run_at=next_cron_occurrence(
                configuration.schedule,
                configuration.timezone,
                self._clock.now(),
            ),
            last_run_at=previous.last_run_at if previous is not None else None,
        )


def _normalize(
    backend: BackendActivityFacts,
    mobile: MobileActivityFacts,
    collected_at: datetime,
) -> RetentionEngagementSnapshot:
    limitations = [*backend.limitations, *mobile.limitations]
    raw_backend_active = max(
        backend.children_with_app_usage,
        backend.children_with_realtime_feature_usage,
    )
    if backend.total_children and raw_backend_active > backend.total_children:
        limitations.append(
            "Backend activity row counts exceed the current child inventory; counts were capped.",
        )
    elif not backend.total_children and raw_backend_active:
        limitations.append(
            "Backend activity exists while the current child inventory is zero; the activity "
            "count is reported but its ratio is unavailable.",
        )
    backend_active = (
        min(raw_backend_active, backend.total_children)
        if backend.total_children
        else raw_backend_active
    )
    if backend_active and mobile.active_subjects:
        limitations.append(
            "Backend and Firebase subject populations cannot yet be safely deduplicated; they are "
            "reported separately.",
        )
    return RetentionEngagementSnapshot(
        period_start=max(backend.period_start, mobile.period_start),
        period_end=min(backend.period_end, mobile.period_end),
        collected_at=collected_at,
        parent_accounts_joined=backend.parent_accounts_joined,
        child_accounts_joined=backend.child_accounts_joined,
        total_children=backend.total_children,
        backend_active_children=backend_active,
        mobile_active_subjects=mobile.active_subjects,
        mobile_sessions=mobile.sessions,
        mobile_screen_time_seconds=mobile.screen_time_seconds,
        mobile_event_counts={
            event_type: mobile.event_counts.get(event_type, 0) for event_type in ActivityEventType
        },
        mobile_dimension_counts=mobile.dimension_counts,
        mobile_sequence_counts=mobile.sequence_counts,
        completeness=min(backend.completeness, mobile.completeness),
        evidence_refs=[
            _evidence_ref(backend, collected_at),
            _evidence_ref(mobile, collected_at),
        ],
        limitations=limitations,
    )


def _evidence_ref(
    facts: BackendActivityFacts | MobileActivityFacts,
    collected_at: datetime,
) -> EvidenceRef:
    payload = facts.model_dump(mode="json")
    checksum = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
    ).hexdigest()
    return EvidenceRef(
        source=facts.source,
        subject_scope="aggregate_product_activity",
        period_start=facts.period_start,
        period_end=facts.period_end,
        collected_at=facts.collected_at,
        freshness_seconds=max(int((collected_at - facts.collected_at).total_seconds()), 0),
        completeness=facts.completeness,
        checksum=checksum,
        privacy_classification="user_behavioral_high_minimized",
    )


def _count_metric(value: int, *, unit: str = "count") -> MetricValue:
    return MetricValue(
        value=Decimal(value),
        unit=unit,
        availability=DataAvailability.AVAILABLE,
    )


def _ratio_metric(*, numerator: int, denominator: int) -> MetricValue:
    if denominator == 0:
        return MetricValue(
            value=None,
            unit="ratio",
            availability=DataAvailability.UNAVAILABLE,
            reason="No children are present in the backend inventory.",
        )
    return MetricValue(
        value=Decimal(numerator) / Decimal(denominator),
        unit="ratio",
        availability=DataAvailability.AVAILABLE,
    )
