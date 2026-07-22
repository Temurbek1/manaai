import logging
from dataclasses import dataclass
from datetime import datetime

from croniter import croniter
from pydantic import JsonValue

from app.mana_operation_ai.application.action_lifecycle import (
    ActionLifecycleResult,
    ActionLifecycleService,
    StaleProposalError,
)
from app.mana_operation_ai.application.agent_service import AgentService
from app.mana_operation_ai.application.marketing.analytics import aggregate_metrics, group_rows
from app.mana_operation_ai.application.ports import (
    Clock,
    ConcurrentOperationError,
    IdGenerator,
    OperationRepository,
)
from app.mana_operation_ai.application.registry import AdsPlatformRegistry, AgentRegistry
from app.mana_operation_ai.application.scheduling import next_cron_occurrence
from app.mana_operation_ai.domain.enums import (
    ActionStatus,
    ActionType,
    AgentStatus,
    ApprovalStatus,
    AuditEventType,
    TriggerType,
    UserRole,
)
from app.mana_operation_ai.domain.marketing import (
    AdsSnapshot,
    Breakdown,
    BreakdownPerformance,
    MarketingOverview,
)
from app.mana_operation_ai.domain.models import (
    AgentConfiguration,
    AgentDefinition,
    AgentRunResult,
    AgentSchedule,
    ApprovalDecision,
    AuditEvent,
    IntegrationHealth,
)
from app.mana_operation_ai.domain.state_machine import ACTION_TRANSITIONS, require_transition

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ActorContext:
    actor_id: str
    role: UserRole


class UnsafeBulkApprovalError(ValueError):
    """Raised when a bulk decision combines actions outside the safe subset."""


class OperationAdminService:
    def __init__(
        self,
        *,
        repository: OperationRepository,
        agents: AgentRegistry,
        platforms: AdsPlatformRegistry,
        runner: AgentService,
        actions: ActionLifecycleService,
        clock: Clock,
        ids: IdGenerator,
        default_ads_provider: str,
    ) -> None:
        self.repository = repository
        self._agents = agents
        self._platforms = platforms
        self._runner = runner
        self._actions = actions
        self._clock = clock
        self._ids = ids
        self._default_ads_provider = default_ads_provider

    async def register_loaded_agent(
        self,
        *,
        agent_id: str,
        actor: ActorContext,
    ) -> AgentDefinition:
        definition = self._agents.get(agent_id).definition
        await self.repository.register_agent(definition)
        await self._audit(
            event_type=AuditEventType.AGENT_REGISTERED,
            actor=actor,
            correlation_id=self._ids.new(),
            agent_id=agent_id,
            summary="Loaded agent registered in the operational catalog",
            details={"version": definition.version},
        )
        return definition

    async def set_agent_status(
        self,
        *,
        agent_id: str,
        status: AgentStatus,
        actor: ActorContext,
    ) -> AgentDefinition:
        definition = await self.repository.set_agent_status(agent_id, status)
        await self._audit(
            event_type=AuditEventType.AGENT_STATUS_CHANGED,
            actor=actor,
            correlation_id=self._ids.new(),
            agent_id=agent_id,
            summary=f"Agent status changed to {status.value}",
            details={"status": status.value},
        )
        return definition

    async def create_configuration(
        self,
        *,
        agent_id: str,
        values: dict[str, JsonValue],
        actor: ActorContext,
    ) -> AgentConfiguration:
        agent = self._agents.get(agent_id)
        validated = agent.validate_configuration(values)
        latest = await self.repository.latest_configuration(agent_id)
        version = 1 if latest is None else latest.version + 1
        configuration = AgentConfiguration(
            configuration_id=self._ids.new(),
            agent_id=agent_id,
            version=version,
            values=validated,
            created_at=self._clock.now(),
            created_by=actor.actor_id,
        )
        existing_schedules = await self.repository.list_schedules(agent_id)
        configured_schedules = agent.schedules_for_configuration(
            validated,
            existing_schedules,
        )
        await self.repository.save_configuration(configuration)
        for schedule in configured_schedules:
            await self.repository.save_schedule(schedule)
        await self._audit(
            event_type=AuditEventType.CONFIGURATION_CREATED,
            actor=actor,
            correlation_id=configuration.configuration_id,
            agent_id=agent_id,
            summary=f"Agent configuration version {version} created",
            details={"version": version},
        )
        return configuration

    async def update_schedule(
        self,
        *,
        schedule_id: str,
        cron_expression: str,
        timezone: str,
        enabled: bool,
        actor: ActorContext,
    ) -> AgentSchedule:
        if not croniter.is_valid(cron_expression):
            raise ValueError("Invalid cron expression")
        existing = next(
            (
                schedule
                for schedule in await self.repository.list_schedules()
                if schedule.schedule_id == schedule_id
            ),
            None,
        )
        if existing is None:
            raise LookupError(f"Schedule {schedule_id!r} was not found")
        schedule = existing.model_copy(
            update={
                "cron_expression": cron_expression,
                "timezone": timezone,
                "enabled": enabled,
                "next_run_at": next_cron_occurrence(
                    cron_expression,
                    timezone,
                    self._clock.now(),
                ),
            },
        )
        await self.repository.save_schedule(schedule)
        await self._audit(
            event_type=AuditEventType.SCHEDULE_CHANGED,
            actor=actor,
            correlation_id=schedule.schedule_id,
            agent_id=schedule.agent_id,
            summary=f"Schedule {schedule.schedule_id} updated",
            details={"enabled": schedule.enabled},
        )
        return schedule

    async def run_now(
        self,
        *,
        agent_id: str,
        job_type: str,
        actor: ActorContext,
        correlation_id: str | None,
        idempotency_key: str | None,
        trigger: TriggerType = TriggerType.USER,
    ) -> AgentRunResult:
        return await self._runner.run_now(
            agent_id=agent_id,
            job_type=job_type,
            trigger=trigger,
            actor_id=actor.actor_id,
            actor_role=actor.role,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

    async def validate_run(self, agent_id: str) -> None:
        await self._runner.validate_run(agent_id)

    def new_identifier(self) -> str:
        return self._ids.new()

    async def run_in_background(
        self,
        *,
        agent_id: str,
        job_type: str,
        actor: ActorContext,
        correlation_id: str,
        idempotency_key: str | None,
    ) -> None:
        try:
            await self.run_now(
                agent_id=agent_id,
                job_type=job_type,
                actor=actor,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
            )
        except Exception:
            logger.exception(
                "Background agent run failed",
                extra={"agent_id": agent_id, "correlation_id": correlation_id},
            )

    async def decide_approval(
        self,
        *,
        proposal_id: str,
        approve: bool,
        reason: str,
        actor: ActorContext,
        correlation_id: str,
    ) -> tuple[ActionLifecycleResult, AgentRunResult]:
        try:
            lifecycle = await self._actions.decide(
                proposal_id=proposal_id,
                approve=approve,
                actor_id=actor.actor_id,
                actor_role=actor.role,
                reason=reason,
                correlation_id=correlation_id,
            )
        except StaleProposalError:
            proposal = await self.repository.get_proposal(proposal_id)
            if proposal is not None:
                await self._agents.get(proposal.agent_id).finalize_after_actions(
                    proposal.run_id,
                )
            raise
        agent = self._agents.get(lifecycle.proposal.agent_id)
        run_result = await agent.finalize_after_actions(lifecycle.proposal.run_id)
        return lifecycle, run_result

    async def execute_approved(
        self,
        *,
        proposal_id: str,
        actor: ActorContext,
        correlation_id: str,
    ) -> tuple[ActionLifecycleResult, AgentRunResult]:
        proposal = await self.repository.get_proposal(proposal_id)
        if proposal is None:
            raise LookupError(f"Proposal {proposal_id!r} was not found")
        lifecycle = await self._actions.execute_proposal(
            proposal=proposal,
            actor_id=actor.actor_id,
            actor_role=actor.role,
            correlation_id=correlation_id,
        )
        agent = self._agents.get(proposal.agent_id)
        run_result = await agent.finalize_after_actions(proposal.run_id)
        return lifecycle, run_result

    async def bulk_decide(
        self,
        *,
        proposal_ids: list[str],
        approve: bool,
        reason: str,
        actor: ActorContext,
        correlation_id: str,
    ) -> list[tuple[ActionLifecycleResult, AgentRunResult]]:
        proposals = [await self.repository.get_proposal(item) for item in proposal_ids]
        if any(item is None for item in proposals):
            raise LookupError("One or more proposals were not found")
        action_types = {item.action_type for item in proposals if item is not None}
        if len(action_types) != 1:
            raise UnsafeBulkApprovalError("Bulk decisions require one homogeneous action type")
        action_type = next(iter(action_types))
        if approve and action_type is not ActionType.DECREASE_BUDGET:
            raise UnsafeBulkApprovalError(
                "Bulk approval is limited to homogeneous budget-decrease actions",
            )
        results: list[tuple[ActionLifecycleResult, AgentRunResult]] = []
        for proposal_id in proposal_ids:
            results.append(
                await self.decide_approval(
                    proposal_id=proposal_id,
                    approve=approve,
                    reason=reason,
                    actor=actor,
                    correlation_id=correlation_id,
                ),
            )
        return results

    async def set_kill_switch(
        self,
        *,
        agent_id: str | None,
        enabled: bool,
        actor: ActorContext,
    ) -> None:
        key = "global_kill_switch" if agent_id is None else f"agent_kill_switch:{agent_id}"
        now = self._clock.now()
        await self.repository.set_control(
            key=key,
            enabled=enabled,
            updated_at=now,
            updated_by=actor.actor_id,
        )
        await self._audit(
            event_type=AuditEventType.KILL_SWITCH_CHANGED,
            actor=actor,
            correlation_id=self._ids.new(),
            agent_id=agent_id,
            summary=f"Kill switch {key} set to {enabled}",
            details={"enabled": enabled},
        )

    async def integration_health(self, provider: str) -> IntegrationHealth:
        health = await self._platforms.get(provider).health()
        await self.repository.save_integration_health(health)
        return health

    async def agent_health(self, agent_id: str) -> list[IntegrationHealth]:
        health_checks = await self._agents.get(agent_id).health()
        for health in health_checks:
            await self.repository.save_integration_health(health)
        return health_checks

    async def marketing_overview(self) -> MarketingOverview:
        health = await self.integration_health(self._default_ads_provider)
        configuration = await self.repository.latest_configuration("marketing-agent")
        schedules = await self.repository.list_schedules("marketing-agent")
        runs, _ = await self.repository.list_runs(agent_id="marketing-agent", limit=100)
        snapshot: AdsSnapshot | None = None
        for run in runs:
            snapshots = await self.repository.list_snapshots(run.run_id)
            if snapshots:
                snapshot = AdsSnapshot.model_validate(snapshots[-1].payload)
                break
        breakdown_performance: list[BreakdownPerformance] = []
        if snapshot is not None:
            for dimension in Breakdown:
                grouped = group_rows(snapshot.insights, key=dimension.value, dimension=True)
                breakdown_performance.extend(
                    BreakdownPerformance(
                        dimension=dimension,
                        value=value,
                        metrics=aggregate_metrics(rows),
                    )
                    for value, rows in sorted(grouped.items())
                )
        return MarketingOverview(
            integration_health=health,
            last_synchronized_at=snapshot.collected_at if snapshot is not None else None,
            snapshot=snapshot,
            breakdown_performance=breakdown_performance,
            configuration=configuration,
            schedules=schedules,
        )

    async def expire_approvals(self, now: datetime) -> int:
        approvals, _ = await self.repository.list_approvals(
            status=ApprovalStatus.PENDING,
            limit=10_000,
        )
        expired = 0
        for approval in approvals:
            if approval.expires_at <= now:
                proposal = await self.repository.get_proposal(approval.proposal_id)
                if proposal is not None and proposal.status is ActionStatus.AWAITING_APPROVAL:
                    require_transition(proposal.status, ActionStatus.EXPIRED, ACTION_TRANSITIONS)
                    expired_request = approval.model_copy(update={"status": ApprovalStatus.EXPIRED})
                    expired_proposal = proposal.model_copy(update={"status": ActionStatus.EXPIRED})
                    decision = ApprovalDecision(
                        approval_id=approval.approval_id,
                        proposal_id=proposal.proposal_id,
                        status=ApprovalStatus.EXPIRED,
                        decided_at=now,
                        decided_by="approval-expiration-job",
                        reason="The approval request expired before a decision.",
                    )
                    try:
                        await self.repository.apply_approval_decision(
                            expired_request,
                            decision,
                            expired_proposal,
                        )
                    except ConcurrentOperationError:
                        continue
                    await self._audit(
                        event_type=AuditEventType.APPROVAL_DECIDED,
                        actor=ActorContext(
                            actor_id="approval-expiration-job",
                            role=UserRole.ADMIN,
                        ),
                        correlation_id=proposal.run_id,
                        agent_id=proposal.agent_id,
                        summary="Approval request expired",
                        details={"proposal_id": proposal.proposal_id},
                    )
                    expired += 1
        return expired

    async def _audit(
        self,
        *,
        event_type: AuditEventType,
        actor: ActorContext,
        correlation_id: str,
        agent_id: str | None,
        summary: str,
        details: dict[str, JsonValue],
    ) -> None:
        await self.repository.save_audit_event(
            AuditEvent(
                event_id=self._ids.new(),
                correlation_id=correlation_id,
                agent_id=agent_id,
                event_type=event_type,
                actor_id=actor.actor_id,
                actor_role=actor.role,
                occurred_at=self._clock.now(),
                summary=summary,
                details=details,
            ),
        )
