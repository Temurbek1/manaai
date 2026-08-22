import logging
from dataclasses import dataclass
from datetime import datetime
from typing import cast

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
    AgentRunStatus,
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
    ActionExecution,
    AgentConfiguration,
    AgentDefinition,
    AgentReport,
    AgentRun,
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
        canonical_agent_id = self._agents.canonical_id(agent_id)
        definition = self._agents.get(canonical_agent_id).definition
        await self.repository.register_agent(definition)
        await self._audit(
            event_type=AuditEventType.AGENT_REGISTERED,
            actor=actor,
            correlation_id=self._ids.new(),
            agent_id=canonical_agent_id,
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
        canonical_agent_id = self._agents.canonical_id(agent_id)
        definition = await self.repository.set_agent_status(canonical_agent_id, status)
        await self._audit(
            event_type=AuditEventType.AGENT_STATUS_CHANGED,
            actor=actor,
            correlation_id=self._ids.new(),
            agent_id=canonical_agent_id,
            summary=f"Agent status changed to {status.value}",
            details={"status": status.value},
        )
        return definition

    async def create_configuration(
        self,
        *,
        agent_id: str,
        capability_key: str | None,
        values: dict[str, JsonValue],
        actor: ActorContext,
    ) -> AgentConfiguration:
        canonical_agent_id = self._agents.canonical_id(agent_id)
        agent = self._agents.get(canonical_agent_id)
        effective_capability_key = capability_key or agent.definition.default_capability_key
        validated = agent.validate_capability_configuration(effective_capability_key, values)
        latest = await self.repository.latest_configuration(
            canonical_agent_id,
            effective_capability_key,
        )
        version = 1 if latest is None else latest.version + 1
        configuration = AgentConfiguration(
            configuration_id=self._ids.new(),
            agent_id=canonical_agent_id,
            capability_key=effective_capability_key,
            version=version,
            values=validated,
            created_at=self._clock.now(),
            created_by=actor.actor_id,
        )
        existing_schedules = await self.repository.list_schedules(
            canonical_agent_id,
            effective_capability_key,
        )
        configured_schedules = agent.schedules_for_capability_configuration(
            effective_capability_key,
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
            agent_id=canonical_agent_id,
            capability_key=effective_capability_key,
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
        capability_key: str | None,
        job_type: str,
        actor: ActorContext,
        correlation_id: str | None,
        idempotency_key: str | None,
        trigger: TriggerType = TriggerType.USER,
    ) -> AgentRunResult:
        return await self._runner.run_now(
            agent_id=agent_id,
            capability_key=capability_key,
            job_type=job_type,
            trigger=trigger,
            actor_id=actor.actor_id,
            actor_role=actor.role,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

    async def validate_run(self, agent_id: str, capability_key: str | None = None) -> None:
        await self._runner.validate_run(agent_id, capability_key)

    def new_identifier(self) -> str:
        return self._ids.new()

    def canonical_agent_id(self, agent_id: str) -> str:
        return self._agents.canonical_id(agent_id)

    def default_capability_key(self, agent_id: str) -> str:
        return self._agents.default_capability_key(agent_id)

    def agent_identifiers(self, agent_id: str) -> set[str]:
        return self._agents.identifiers_for(agent_id)

    async def list_loaded_agents(self) -> list[AgentDefinition]:
        """Expose only implementations loaded by this runtime, retaining persisted status."""
        definitions: list[AgentDefinition] = []
        for loaded in self._agents.definitions():
            persisted = await self.repository.get_agent(loaded.agent_id)
            definitions.append(
                loaded
                if persisted is None
                else loaded.model_copy(update={"status": persisted.status})
            )
        return definitions

    async def list_runs(
        self,
        *,
        agent_id: str | None,
        capability_key: str | None,
        status: AgentRunStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgentRun], int]:
        if agent_id is None:
            return await self.repository.list_runs(
                capability_key=capability_key,
                status=status,
                limit=limit,
                offset=offset,
            )
        fetch_limit = limit + offset
        items: list[AgentRun] = []
        total = 0
        for identifier in self._agents.identifiers_for(agent_id):
            page, count = await self.repository.list_runs(
                agent_id=identifier,
                capability_key=capability_key,
                status=status,
                limit=fetch_limit,
            )
            items.extend(page)
            total += count
        items.sort(key=lambda item: item.started_at, reverse=True)
        return items[offset : offset + limit], total

    async def list_executions(
        self,
        *,
        agent_id: str | None,
        capability_key: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ActionExecution], int]:
        if agent_id is None:
            return await self.repository.list_executions(
                capability_key=capability_key,
                limit=limit,
                offset=offset,
            )
        fetch_limit = limit + offset
        items: list[ActionExecution] = []
        total = 0
        for identifier in self._agents.identifiers_for(agent_id):
            page, count = await self.repository.list_executions(
                agent_id=identifier,
                capability_key=capability_key,
                limit=fetch_limit,
            )
            items.extend(page)
            total += count
        items.sort(key=lambda item: item.attempted_at, reverse=True)
        return items[offset : offset + limit], total

    async def list_reports(
        self,
        *,
        agent_id: str | None,
        capability_key: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgentReport], int]:
        if agent_id is None:
            return await self.repository.list_reports(
                capability_key=capability_key,
                limit=limit,
                offset=offset,
            )
        fetch_limit = limit + offset
        items: list[AgentReport] = []
        total = 0
        for identifier in self._agents.identifiers_for(agent_id):
            page, count = await self.repository.list_reports(
                agent_id=identifier,
                capability_key=capability_key,
                limit=fetch_limit,
            )
            items.extend(page)
            total += count
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[offset : offset + limit], total

    async def run_in_background(
        self,
        *,
        agent_id: str,
        capability_key: str | None,
        job_type: str,
        actor: ActorContext,
        correlation_id: str,
        idempotency_key: str | None,
    ) -> None:
        try:
            await self.run_now(
                agent_id=agent_id,
                capability_key=capability_key,
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
        capability_key: str | None = None,
        enabled: bool,
        actor: ActorContext,
    ) -> str:
        canonical_agent_id = self._agents.canonical_id(agent_id) if agent_id is not None else None
        if capability_key is not None:
            if canonical_agent_id is None:
                raise ValueError("A capability kill switch requires an agent identifier")
            capability_keys = {
                item.key for item in self._agents.get(canonical_agent_id).capability_definitions()
            }
            if capability_key not in capability_keys:
                raise LookupError(f"Capability {capability_key!r} was not found")
            control_keys = [
                f"capability_kill_switch:{identifier}:{capability_key}"
                for identifier in self._agents.identifiers_for(canonical_agent_id)
            ]
            scope = f"{canonical_agent_id}/{capability_key}"
        elif canonical_agent_id is not None:
            control_keys = [
                f"agent_kill_switch:{identifier}"
                for identifier in self._agents.identifiers_for(canonical_agent_id)
            ]
            scope = canonical_agent_id
        else:
            control_keys = ["global_kill_switch"]
            scope = "global"
        now = self._clock.now()
        for key in control_keys:
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
            agent_id=canonical_agent_id,
            capability_key=capability_key,
            summary=f"Kill switch {scope} set to {enabled}",
            details={
                "enabled": enabled,
                "control_keys": cast(list[JsonValue], control_keys),
            },
        )
        return scope

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
        configuration = await self.repository.latest_configuration(
            "growth-agent",
            "growth.advertising",
        )
        schedules = await self.repository.list_schedules(
            "growth-agent",
            "growth.advertising",
        )
        runs, _ = await self.list_runs(
            agent_id="growth-agent",
            capability_key="growth.advertising",
            status=None,
            limit=100,
            offset=0,
        )
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
        capability_key: str | None = None,
        summary: str,
        details: dict[str, JsonValue],
    ) -> None:
        await self.repository.save_audit_event(
            AuditEvent(
                event_id=self._ids.new(),
                correlation_id=correlation_id,
                agent_id=agent_id,
                capability_key=capability_key,
                event_type=event_type,
                actor_id=actor.actor_id,
                actor_role=actor.role,
                occurred_at=self._clock.now(),
                summary=summary,
                details=details,
            ),
        )
