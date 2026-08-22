import hashlib
import json
import logging
import time
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal
from typing import cast

from pydantic import JsonValue

from app.mana_operation_ai.application.action_lifecycle import ActionLifecycleService
from app.mana_operation_ai.application.growth.constants import (
    ADVERTISING_CAPABILITY_KEY,
    GROWTH_AGENT_ID,
)
from app.mana_operation_ai.application.marketing.analytics import MarketingAnalyticsEngine
from app.mana_operation_ai.application.marketing.reporting import MarketingReportBuilder
from app.mana_operation_ai.application.ports import (
    AdsPlatform,
    Clock,
    IdGenerator,
    NotificationPort,
    OperationRepository,
)
from app.mana_operation_ai.application.scheduling import next_cron_occurrence
from app.mana_operation_ai.domain.enums import (
    ActionStatus,
    AgentRunStage,
    AgentRunStatus,
    AuditEventType,
    CapabilityRisk,
    ProviderMode,
    TriggerType,
    UserRole,
)
from app.mana_operation_ai.domain.marketing import (
    AdsCollectionRequest,
    AdsSnapshot,
    MarketingAgentConfiguration,
)
from app.mana_operation_ai.domain.models import (
    ActionExecution,
    ActionProposal,
    AgentConfiguration,
    AgentReport,
    AgentRun,
    AgentRunResult,
    AgentSchedule,
    AuditEvent,
    CapabilityDefinition,
    DataSnapshot,
    Finding,
    IntegrationHealth,
    Recommendation,
)
from app.mana_operation_ai.domain.state_machine import RUN_TRANSITIONS, require_transition

logger = logging.getLogger(__name__)


class AdvertisingCapabilityHandler:
    def __init__(
        self,
        *,
        provider: AdsPlatform,
        repository: OperationRepository,
        analytics: MarketingAnalyticsEngine,
        actions: ActionLifecycleService,
        reports: MarketingReportBuilder,
        notifications: NotificationPort,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._analytics = analytics
        self._actions = actions
        self._reports = reports
        self._notifications = notifications
        self._clock = clock
        self._ids = ids
        risk = (
            CapabilityRisk.FINANCIAL
            if provider.provider_mode is ProviderMode.FAKE_EXECUTABLE
            else CapabilityRisk.PROPOSE
        )
        self._definition = CapabilityDefinition(
            key=ADVERTISING_CAPABILITY_KEY,
            agent_id=GROWTH_AGENT_ID,
            description=(
                "Collects and analyzes live advertising data as read-only advisory intelligence."
                if provider.provider_mode is ProviderMode.LIVE_READ_ONLY
                else "Collects, analyzes, proposes, and safely executes sandbox actions."
            ),
            risk=risk,
            minimum_role=UserRole.OPERATOR,
            input_schema=cast(
                dict[str, JsonValue],
                MarketingAgentConfiguration.model_json_schema(),
            ),
            output_schema=cast(dict[str, JsonValue], AgentRunResult.model_json_schema()),
            required_integrations=[provider.provider_name],
            supported_triggers={TriggerType.USER, TriggerType.SCHEDULE},
        )

    @property
    def definition(self) -> CapabilityDefinition:
        return self._definition

    @property
    def default_configuration(self) -> dict[str, JsonValue]:
        return cast(
            dict[str, JsonValue],
            MarketingAgentConfiguration().model_dump(mode="json"),
        )

    def default_schedules(self, agent_id: str) -> list[AgentSchedule]:
        configuration = MarketingAgentConfiguration()
        now = self._clock.now()
        return [
            AgentSchedule(
                schedule_id="growth-advertising-analysis",
                agent_id=agent_id,
                capability_key=ADVERTISING_CAPABILITY_KEY,
                job_type="analysis",
                cron_expression=configuration.analysis_schedule,
                timezone=configuration.timezone,
                enabled=True,
                next_run_at=next_cron_occurrence(
                    configuration.analysis_schedule,
                    configuration.timezone,
                    now,
                ),
            ),
            AgentSchedule(
                schedule_id="growth-advertising-nightly-report",
                agent_id=agent_id,
                capability_key=ADVERTISING_CAPABILITY_KEY,
                job_type="nightly_report",
                cron_expression=configuration.nightly_report_schedule,
                timezone=configuration.timezone,
                enabled=True,
                next_run_at=next_cron_occurrence(
                    configuration.nightly_report_schedule,
                    configuration.timezone,
                    now,
                ),
            ),
        ]

    def schedules_for_configuration(
        self,
        *,
        agent_id: str,
        values: dict[str, JsonValue],
        existing: Sequence[AgentSchedule],
    ) -> list[AgentSchedule]:
        configuration = MarketingAgentConfiguration.model_validate(values)
        current = {schedule.schedule_id: schedule for schedule in existing}
        now = self._clock.now()
        schedules: list[AgentSchedule] = []
        for schedule_id, job_type, expression in [
            ("growth-advertising-analysis", "analysis", configuration.analysis_schedule),
            (
                "growth-advertising-nightly-report",
                "nightly_report",
                configuration.nightly_report_schedule,
            ),
        ]:
            previous = current.get(schedule_id)
            schedules.append(
                AgentSchedule(
                    schedule_id=schedule_id,
                    agent_id=agent_id,
                    capability_key=ADVERTISING_CAPABILITY_KEY,
                    job_type=job_type,
                    cron_expression=expression,
                    timezone=configuration.timezone,
                    enabled=previous.enabled if previous is not None else True,
                    next_run_at=next_cron_occurrence(
                        expression,
                        configuration.timezone,
                        now,
                    ),
                    last_run_at=previous.last_run_at if previous is not None else None,
                ),
            )
        return schedules

    def validate_configuration(self, values: dict[str, JsonValue]) -> dict[str, JsonValue]:
        configuration = MarketingAgentConfiguration.model_validate(values)
        return cast(dict[str, JsonValue], configuration.model_dump(mode="json"))

    async def health(self) -> list[IntegrationHealth]:
        return [await self._provider.health()]

    async def execute(
        self,
        *,
        run: AgentRun,
        job_type: str,
        configuration: AgentConfiguration,
    ) -> AgentRunResult:
        if job_type not in {"analysis", "meta_sync", "nightly_report"}:
            raise ValueError(f"Unsupported Marketing Agent job type {job_type!r}")
        typed_configuration = MarketingAgentConfiguration.model_validate(configuration.values)
        try:
            run = await self._transition(
                run,
                AgentRunStatus.COLLECTING,
                AgentRunStage.COLLECT,
            )
            effective_end = self._clock.now().date()
            if self._provider.provider_mode is ProviderMode.LIVE_READ_ONLY:
                effective_end -= timedelta(days=1)
            request = AdsCollectionRequest(
                run_id=run.run_id,
                correlation_id=run.correlation_id,
                account_ids=typed_configuration.account_ids or None,
                date_start=(
                    effective_end
                    - timedelta(
                        days=(
                            typed_configuration.baseline_period_days
                            + typed_configuration.comparison_period_days
                            - 1
                        ),
                    )
                ),
                date_stop=effective_end,
                attribution_window=typed_configuration.attribution_window,
                requested_breakdowns=typed_configuration.requested_breakdowns,
            )
            normalized = await self._provider.collect(request)
            run = await self._transition(
                run,
                AgentRunStatus.NORMALIZING,
                AgentRunStage.NORMALIZE,
            )
            snapshot = self._snapshot(run, normalized)
            await self._repository.save_snapshot(snapshot)
            effective_configuration = typed_configuration.effective_for(
                provider=normalized.provider,
                account_id=(
                    normalized.accounts[0].provider_id if len(normalized.accounts) == 1 else None
                ),
            )

            run = await self._transition(
                run,
                AgentRunStatus.ANALYZING,
                AgentRunStage.ANALYZE,
            )
            analysis_started_at = time.perf_counter()
            bundle = self._analytics.analyze(
                run_id=run.run_id,
                snapshot_id=snapshot.snapshot_id,
                snapshot=normalized,
                configuration=effective_configuration,
                now=self._clock.now(),
            )
            analysis_duration_ms = max(
                int((time.perf_counter() - analysis_started_at) * 1_000),
                0,
            )
            await self._repository.save_analysis(bundle.analysis)
            await self._repository.save_findings(bundle.findings)

            run = await self._transition(
                run,
                AgentRunStatus.PROPOSING,
                AgentRunStage.PROPOSE,
            )
            await self._repository.save_recommendations(bundle.recommendations)
            run = await self._transition(
                run,
                AgentRunStatus.POLICY_CHECK,
                AgentRunStage.POLICY_CHECK,
            )
            proposals: list[ActionProposal] = []
            pending_approval_ids: list[str] = []
            auto_approved: list[ActionProposal] = []
            for recommendation in bundle.recommendations:
                creation = await self._actions.create_proposal(
                    agent_id=run.agent_id,
                    provider_name=self._provider.provider_name,
                    run_id=run.run_id,
                    correlation_id=run.correlation_id,
                    recommendation=recommendation,
                    configuration=cast(
                        dict[str, JsonValue],
                        effective_configuration.action_policy_configuration().model_dump(
                            mode="json",
                        ),
                    ),
                    configuration_version=configuration.version,
                    requested_by=run.initiated_by,
                )
                if creation is None:
                    continue
                proposals.append(creation.proposal)
                if creation.approval is not None:
                    pending_approval_ids.append(creation.approval.approval_id)
                elif (
                    creation.proposal.status is ActionStatus.APPROVED
                    and not creation.proposal.execution_forbidden
                ):
                    auto_approved.append(creation.proposal)

            executions: list[ActionExecution] = []
            if pending_approval_ids:
                if job_type == "nightly_report":
                    return await self._finish(
                        run=run,
                        snapshot=normalized,
                        findings=bundle.findings,
                        recommendations=bundle.recommendations,
                        proposals=proposals,
                        executions=[],
                        report_type="nightly",
                        notification_channels=typed_configuration.notification_channels,
                        analysis_duration_ms=analysis_duration_ms,
                    )
                run = await self._transition(
                    run,
                    AgentRunStatus.WAITING_APPROVAL,
                    AgentRunStage.APPROVAL,
                )
                return AgentRunResult(
                    run_id=run.run_id,
                    status=run.status,
                    snapshot_ids=[snapshot.snapshot_id],
                    finding_ids=[item.finding_id for item in bundle.findings],
                    recommendation_ids=[item.recommendation_id for item in bundle.recommendations],
                    action_proposal_ids=[item.proposal_id for item in proposals],
                )

            if auto_approved:
                run = await self._transition(
                    run,
                    AgentRunStatus.EXECUTING,
                    AgentRunStage.EXECUTE,
                )
                for proposal in auto_approved:
                    lifecycle = await self._actions.execute_proposal(
                        proposal=proposal,
                        actor_id="system",
                        actor_role=UserRole.ADMIN,
                        correlation_id=run.correlation_id,
                    )
                    proposals = [
                        lifecycle.proposal if item.proposal_id == proposal.proposal_id else item
                        for item in proposals
                    ]
                    if lifecycle.execution is not None:
                        executions.append(lifecycle.execution)
                run = await self._transition(
                    run,
                    AgentRunStatus.VERIFYING,
                    AgentRunStage.VERIFY,
                )
            return await self._finish(
                run=run,
                snapshot=normalized,
                findings=bundle.findings,
                recommendations=bundle.recommendations,
                proposals=proposals,
                executions=executions,
                report_type="nightly" if job_type == "nightly_report" else "analysis",
                notification_channels=typed_configuration.notification_channels,
                analysis_duration_ms=analysis_duration_ms,
            )
        except Exception as exc:
            require_transition(run.status, AgentRunStatus.FAILED, RUN_TRANSITIONS)
            failed = run.model_copy(
                update={
                    "status": AgentRunStatus.FAILED,
                    "updated_at": self._clock.now(),
                    "completed_at": self._clock.now(),
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
        if run.status is not AgentRunStatus.WAITING_APPROVAL:
            return AgentRunResult(run_id=run.run_id, status=run.status)
        proposals, _ = await self._repository.list_proposals(run_id=run_id, limit=1_000)
        if any(
            item.status in {ActionStatus.AWAITING_APPROVAL, ActionStatus.EXECUTING}
            or (item.status is ActionStatus.APPROVED and not item.execution_forbidden)
            for item in proposals
        ):
            return AgentRunResult(
                run_id=run.run_id,
                status=run.status,
                action_proposal_ids=[item.proposal_id for item in proposals],
            )
        snapshots = await self._repository.list_snapshots(run_id)
        if not snapshots:
            raise RuntimeError("The run has no persisted data snapshot")
        snapshot = AdsSnapshot.model_validate(snapshots[-1].payload)
        findings, _ = await self._repository.list_findings(run_id=run_id, limit=1_000)
        recommendations, _ = await self._repository.list_recommendations(
            run_id=run_id,
            limit=1_000,
        )
        all_executions, _ = await self._repository.list_executions(limit=1_000)
        executions = [item for item in all_executions if item.run_id == run_id]
        if executions:
            run = await self._transition(
                run,
                AgentRunStatus.EXECUTING,
                AgentRunStage.EXECUTE,
            )
            run = await self._transition(
                run,
                AgentRunStatus.VERIFYING,
                AgentRunStage.VERIFY,
            )
        return await self._finish(
            run=run,
            snapshot=snapshot,
            findings=findings,
            recommendations=recommendations,
            proposals=proposals,
            executions=executions,
            report_type="analysis",
            notification_channels=[],
            analysis_duration_ms=None,
        )

    async def _finish(
        self,
        *,
        run: AgentRun,
        snapshot: AdsSnapshot,
        findings: list[Finding],
        recommendations: list[Recommendation],
        proposals: list[ActionProposal],
        executions: list[ActionExecution],
        report_type: str,
        notification_channels: list[str],
        analysis_duration_ms: int | None,
    ) -> AgentRunResult:
        run = await self._transition(
            run,
            AgentRunStatus.REPORTING,
            AgentRunStage.REPORT,
        )
        report: AgentReport = self._reports.build(
            report_id=self._ids.new(),
            run_id=run.run_id,
            agent_id=run.agent_id,
            snapshot=snapshot,
            findings=findings,
            recommendations=recommendations,
            proposals=proposals,
            executions=executions,
            created_at=self._clock.now(),
            report_type=report_type,
            analysis_duration_ms=analysis_duration_ms,
        )
        await self._repository.save_report(report)
        await self._repository.save_audit_event(
            AuditEvent(
                event_id=self._ids.new(),
                correlation_id=run.correlation_id,
                agent_id=run.agent_id,
                capability_key=run.capability_key,
                run_id=run.run_id,
                event_type=AuditEventType.REPORT_CREATED,
                actor_id=run.initiated_by,
                actor_role=UserRole.OPERATOR,
                occurred_at=self._clock.now(),
                summary=f"{report_type} report created",
                details={"report_id": report.report_id},
            ),
        )
        if report_type == "nightly" and notification_channels:
            try:
                await self._notifications.send(
                    channels=notification_channels,
                    subject="MANA Marketing Agent nightly report",
                    message=report.human_readable,
                    metadata={"report_id": report.report_id, "run_id": report.run_id},
                )
            except Exception:
                logger.exception(
                    "Nightly report notification failed",
                    extra={"report_id": report.report_id, "run_id": report.run_id},
                )
        run = await self._transition(run, AgentRunStatus.COMPLETED, AgentRunStage.REPORT)
        return AgentRunResult(
            run_id=run.run_id,
            status=run.status,
            snapshot_ids=[
                item.snapshot_id for item in await self._repository.list_snapshots(run.run_id)
            ],
            finding_ids=[item.finding_id for item in findings],
            recommendation_ids=[item.recommendation_id for item in recommendations],
            action_proposal_ids=[item.proposal_id for item in proposals],
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

    def _snapshot(self, run: AgentRun, snapshot: AdsSnapshot) -> DataSnapshot:
        payload = cast(dict[str, JsonValue], snapshot.model_dump(mode="json"))
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        request_ids = [
            item.request_id for item in snapshot.diagnostics if item.request_id is not None
        ]
        completeness = Decimal("1") if snapshot.insights else Decimal("0")
        return DataSnapshot(
            snapshot_id=self._ids.new(),
            run_id=run.run_id,
            agent_id=run.agent_id,
            capability_key=run.capability_key,
            provider=snapshot.provider,
            schema_version=snapshot.schema_version,
            period_start=snapshot.period_start,
            period_end=snapshot.period_end,
            collected_at=snapshot.collected_at,
            checksum=hashlib.sha256(serialized.encode()).hexdigest(),
            provider_request_ids=request_ids,
            completeness=completeness,
            payload=payload,
        )
