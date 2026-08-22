import asyncio
import hashlib
from datetime import timedelta

from pydantic import JsonValue

from app.mana_operation_ai.application.ports import (
    Clock,
    ConcurrentOperationError,
    IdGenerator,
    OperationalAgent,
    OperationRepository,
)
from app.mana_operation_ai.application.registry import AgentRegistry
from app.mana_operation_ai.domain.enums import (
    AgentRunStatus,
    AgentStatus,
    AuditEventType,
    TriggerType,
    UserRole,
)
from app.mana_operation_ai.domain.models import (
    AgentConfiguration,
    AgentRun,
    AgentRunResult,
    AuditEvent,
)
from app.mana_operation_ai.domain.state_machine import RUN_TRANSITIONS, require_transition


class AgentUnavailableError(RuntimeError):
    """Raised when status, configuration, or a kill switch prevents a run."""


class AgentRunLockedError(RuntimeError):
    """Raised when the agent already has an active run lock."""


class AgentRunTimeoutError(RuntimeError):
    """Raised after an agent job exceeds its configured execution deadline."""


class AgentService:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        repository: OperationRepository,
        clock: Clock,
        ids: IdGenerator,
        job_timeout_seconds: int,
        global_kill_switch_default: bool,
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._clock = clock
        self._ids = ids
        self._job_timeout_seconds = job_timeout_seconds
        self._global_kill_switch_default = global_kill_switch_default

    async def bootstrap(self, *, actor_id: str = "system") -> None:
        now = self._clock.now()
        for agent in (self._registry.get(item.agent_id) for item in self._registry.definitions()):
            current = await self._repository.get_agent(agent.definition.agent_id)
            definition = agent.definition
            if current is not None:
                definition = definition.model_copy(update={"status": current.status})
            await self._repository.register_agent(definition)

            for capability in agent.capability_definitions():
                if (
                    await self._repository.latest_configuration(
                        definition.agent_id,
                        capability.key,
                    )
                    is None
                ):
                    configuration = AgentConfiguration(
                        configuration_id=self._ids.new(),
                        agent_id=definition.agent_id,
                        capability_key=capability.key,
                        version=1,
                        values=agent.default_configuration_for(capability.key),
                        created_at=now,
                        created_by=actor_id,
                    )
                    try:
                        await self._repository.save_configuration(configuration)
                    except ConcurrentOperationError:
                        persisted_configuration = await self._repository.latest_configuration(
                            definition.agent_id,
                            capability.key,
                        )
                        if persisted_configuration is None:
                            raise
                        configuration = persisted_configuration
                    await self._audit(
                        agent_id=definition.agent_id,
                        capability_key=capability.key,
                        correlation_id=configuration.configuration_id,
                        event_type=AuditEventType.CONFIGURATION_CREATED,
                        actor_id=actor_id,
                        actor_role=UserRole.ADMIN,
                        summary="Default capability configuration created",
                        details={"version": 1},
                    )

                existing_schedule_ids = {
                    schedule.schedule_id
                    for schedule in await self._repository.list_schedules(
                        definition.agent_id,
                        capability.key,
                    )
                }
                for schedule in agent.default_schedules_for(capability.key):
                    if schedule.schedule_id not in existing_schedule_ids:
                        await self._repository.save_schedule(schedule)

    async def run_now(
        self,
        *,
        agent_id: str,
        capability_key: str | None,
        job_type: str,
        trigger: TriggerType,
        actor_id: str,
        actor_role: UserRole,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> AgentRunResult:
        canonical_agent_id = self._registry.canonical_id(agent_id)
        effective_capability_key = capability_key or self._registry.default_capability_key(
            canonical_agent_id
        )
        agent, configuration = await self.validate_run(
            canonical_agent_id,
            effective_capability_key,
        )
        now = self._clock.now()
        run_key = idempotency_key or self._run_key(
            canonical_agent_id,
            effective_capability_key,
            job_type,
            now.isoformat(),
        )
        run = AgentRun(
            run_id=self._ids.new(),
            agent_id=canonical_agent_id,
            capability_key=effective_capability_key,
            correlation_id=correlation_id or self._ids.new(),
            trigger=trigger,
            initiated_by=actor_id,
            status=AgentRunStatus.QUEUED,
            configuration_version=configuration.version,
            idempotency_key=run_key,
            started_at=now,
            updated_at=now,
        )
        run = await self._repository.create_run(run)
        if run.status is AgentRunStatus.FAILED:
            require_transition(run.status, AgentRunStatus.QUEUED, RUN_TRANSITIONS)
            run = run.model_copy(
                update={
                    "status": AgentRunStatus.QUEUED,
                    "updated_at": now,
                    "completed_at": None,
                    "error_code": None,
                    "error_message": None,
                    "retry_count": run.retry_count + 1,
                },
            )
            await self._repository.update_run(run)
        if run.status is not AgentRunStatus.QUEUED:
            return AgentRunResult(run_id=run.run_id, status=run.status)

        owner_id = self._ids.new()
        lock_key = f"capability-run:{canonical_agent_id}:{effective_capability_key}"
        acquired = await self._repository.acquire_lock(
            key=lock_key,
            owner_id=owner_id,
            now=now,
            expires_at=now + timedelta(seconds=self._job_timeout_seconds),
        )
        if not acquired:
            raise AgentRunLockedError(
                f"Capability {effective_capability_key!r} already has an active run",
            )
        try:
            try:
                async with asyncio.timeout(self._job_timeout_seconds):
                    return await agent.execute(
                        run=run,
                        capability_key=effective_capability_key,
                        job_type=job_type,
                        configuration=configuration,
                    )
            except TimeoutError as exc:
                persisted = await self._repository.get_run(run.run_id)
                if persisted is not None and persisted.status not in {
                    AgentRunStatus.COMPLETED,
                    AgentRunStatus.FAILED,
                    AgentRunStatus.CANCELLED,
                    AgentRunStatus.WAITING_APPROVAL,
                }:
                    require_transition(
                        persisted.status,
                        AgentRunStatus.FAILED,
                        RUN_TRANSITIONS,
                    )
                    failed = persisted.model_copy(
                        update={
                            "status": AgentRunStatus.FAILED,
                            "updated_at": self._clock.now(),
                            "completed_at": self._clock.now(),
                            "error_code": "job_timeout",
                            "error_message": "The agent job exceeded its configured timeout.",
                        },
                    )
                    await self._repository.update_run(failed)
                raise AgentRunTimeoutError(
                    f"Capability {effective_capability_key!r} exceeded the configured job timeout",
                ) from exc
        finally:
            await self._repository.release_lock(key=lock_key, owner_id=owner_id)

    async def validate_run(
        self,
        agent_id: str,
        capability_key: str | None = None,
    ) -> tuple[OperationalAgent, AgentConfiguration]:
        canonical_agent_id = self._registry.canonical_id(agent_id)
        agent = self._registry.get(canonical_agent_id)
        effective_capability_key = capability_key or agent.definition.default_capability_key
        agent.capability_definitions()
        if effective_capability_key not in {item.key for item in agent.capability_definitions()}:
            raise AgentUnavailableError(
                f"Capability {effective_capability_key!r} is not loaded for {canonical_agent_id!r}",
            )
        persisted = await self._repository.get_agent(canonical_agent_id)
        if persisted is None or persisted.status is not AgentStatus.ENABLED:
            raise AgentUnavailableError(f"Agent {agent_id!r} is not enabled")
        if await self._repository.get_control(
            "global_kill_switch",
            default=self._global_kill_switch_default,
        ):
            raise AgentUnavailableError("The global operation kill switch is enabled")
        if await self._repository.get_control(f"agent_kill_switch:{canonical_agent_id}"):
            raise AgentUnavailableError(
                f"The kill switch for {canonical_agent_id!r} is enabled",
            )
        if await self._repository.get_control(
            f"capability_kill_switch:{canonical_agent_id}:{effective_capability_key}",
        ):
            raise AgentUnavailableError(
                f"The kill switch for capability {effective_capability_key!r} is enabled",
            )

        configuration = await self._repository.latest_configuration(
            canonical_agent_id,
            effective_capability_key,
        )
        if configuration is None:
            raise AgentUnavailableError(f"Agent {agent_id!r} has no configuration")
        return agent, configuration

    async def _audit(
        self,
        *,
        agent_id: str,
        capability_key: str | None,
        correlation_id: str,
        event_type: AuditEventType,
        actor_id: str,
        actor_role: UserRole,
        summary: str,
        details: dict[str, JsonValue],
    ) -> None:
        await self._repository.save_audit_event(
            AuditEvent(
                event_id=self._ids.new(),
                correlation_id=correlation_id,
                agent_id=agent_id,
                capability_key=capability_key,
                event_type=event_type,
                actor_id=actor_id,
                actor_role=actor_role,
                occurred_at=self._clock.now(),
                summary=summary,
                details=details,
            ),
        )

    @staticmethod
    def _run_key(
        agent_id: str,
        capability_key: str,
        job_type: str,
        marker: str,
    ) -> str:
        source = f"{agent_id}:{capability_key}:{job_type}:{marker}".encode()
        return hashlib.sha256(source).hexdigest()
