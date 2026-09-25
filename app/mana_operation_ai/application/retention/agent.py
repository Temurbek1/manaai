from collections.abc import Sequence
from typing import cast

from pydantic import JsonValue

from app.mana_operation_ai.application.capabilities import CapabilityRegistry
from app.mana_operation_ai.application.ports import Clock, OperationRepository
from app.mana_operation_ai.application.retention.constants import (
    ENGAGEMENT_CAPABILITY_KEY,
    RETENTION_AGENT_ID,
)
from app.mana_operation_ai.domain.enums import AgentStatus
from app.mana_operation_ai.domain.models import (
    AgentConfiguration,
    AgentDefinition,
    AgentRun,
    AgentRunResult,
    AgentSchedule,
    CapabilityDefinition,
    IntegrationHealth,
)


class RetentionAgent:
    def __init__(
        self,
        *,
        capabilities: CapabilityRegistry,
        repository: OperationRepository,
        clock: Clock,
    ) -> None:
        self.capabilities = capabilities
        self._repository = repository
        definitions = capabilities.definitions()
        if not definitions:
            raise ValueError("Retention Agent requires at least one capability")
        if any(item.agent_id != RETENTION_AGENT_ID for item in definitions):
            raise ValueError("Every Retention capability must be owned by retention-agent")
        self._definition = AgentDefinition(
            agent_id=RETENTION_AGENT_ID,
            display_name="Retention & Loyalty Agent",
            description=(
                "Measures first-party product engagement and prepares governed retention "
                "classification and reporting without exposing raw user activity."
            ),
            version="1.0.0",
            status=AgentStatus.ENABLED,
            capabilities=definitions,
            default_capability_key=ENGAGEMENT_CAPABILITY_KEY,
            configuration_schema={
                item.key: cast(JsonValue, item.input_schema) for item in definitions
            },
            registered_at=clock.now(),
        )

    @property
    def definition(self) -> AgentDefinition:
        return self._definition

    @property
    def default_configuration(self) -> dict[str, JsonValue]:
        return self.capabilities.get(ENGAGEMENT_CAPABILITY_KEY).default_configuration

    def default_schedules(self) -> list[AgentSchedule]:
        return [
            schedule
            for handler in self.capabilities.handlers()
            for schedule in handler.default_schedules(RETENTION_AGENT_ID)
        ]

    def capability_definitions(self) -> list[CapabilityDefinition]:
        return self.capabilities.definitions()

    def default_configuration_for(self, capability_key: str) -> dict[str, JsonValue]:
        return self.capabilities.get(capability_key).default_configuration

    def default_schedules_for(self, capability_key: str) -> list[AgentSchedule]:
        return self.capabilities.get(capability_key).default_schedules(RETENTION_AGENT_ID)

    def schedules_for_configuration(
        self,
        values: dict[str, JsonValue],
        existing: Sequence[AgentSchedule],
    ) -> list[AgentSchedule]:
        return self.schedules_for_capability_configuration(
            ENGAGEMENT_CAPABILITY_KEY,
            values,
            existing,
        )

    def validate_configuration(self, values: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return self.validate_capability_configuration(ENGAGEMENT_CAPABILITY_KEY, values)

    def validate_capability_configuration(
        self,
        capability_key: str,
        values: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        return self.capabilities.get(capability_key).validate_configuration(values)

    def schedules_for_capability_configuration(
        self,
        capability_key: str,
        values: dict[str, JsonValue],
        existing: Sequence[AgentSchedule],
    ) -> list[AgentSchedule]:
        return self.capabilities.get(capability_key).schedules_for_configuration(
            agent_id=RETENTION_AGENT_ID,
            values=values,
            existing=existing,
        )

    async def health(self) -> list[IntegrationHealth]:
        checks: dict[str, IntegrationHealth] = {}
        for handler in self.capabilities.handlers():
            for health in await handler.health():
                checks[health.integration_id] = health
        return [checks[key] for key in sorted(checks)]

    async def execute(
        self,
        *,
        run: AgentRun,
        capability_key: str,
        job_type: str,
        configuration: AgentConfiguration,
    ) -> AgentRunResult:
        if run.capability_key != capability_key or configuration.capability_key != capability_key:
            raise ValueError("Run and configuration must belong to the dispatched capability")
        return await self.capabilities.get(capability_key).execute(
            run=run,
            job_type=job_type,
            configuration=configuration,
        )

    async def finalize_after_actions(self, run_id: str) -> AgentRunResult:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise LookupError(f"Run {run_id!r} was not found")
        return await self.capabilities.get(run.capability_key).finalize_after_actions(run_id)
