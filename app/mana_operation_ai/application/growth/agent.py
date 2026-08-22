from collections.abc import Sequence
from typing import cast

from pydantic import JsonValue

from app.mana_operation_ai.application.capabilities import CapabilityRegistry
from app.mana_operation_ai.application.growth.constants import (
    ADVERTISING_CAPABILITY_KEY,
    GROWTH_AGENT_ID,
)
from app.mana_operation_ai.application.ports import Clock, OperationRepository
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


class GrowthAgent:
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
            raise ValueError("Growth Agent requires at least one capability")
        if any(item.agent_id != GROWTH_AGENT_ID for item in definitions):
            raise ValueError("Every Growth capability must be owned by growth-agent")
        self._definition = AgentDefinition(
            agent_id=GROWTH_AGENT_ID,
            display_name="Growth & Conversion Agent",
            description=(
                "Acquires qualified users and improves paid conversion through governed, "
                "independently configured growth capabilities."
            ),
            version="2.0.0",
            status=AgentStatus.ENABLED,
            capabilities=definitions,
            default_capability_key=ADVERTISING_CAPABILITY_KEY,
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
        return self.capabilities.get(self._definition.default_capability_key).default_configuration

    def default_schedules(self) -> list[AgentSchedule]:
        return [
            schedule
            for handler in self.capabilities.handlers()
            for schedule in handler.default_schedules(GROWTH_AGENT_ID)
        ]

    def capability_definitions(self) -> list[CapabilityDefinition]:
        return self.capabilities.definitions()

    def default_configuration_for(self, capability_key: str) -> dict[str, JsonValue]:
        return self.capabilities.get(capability_key).default_configuration

    def default_schedules_for(self, capability_key: str) -> list[AgentSchedule]:
        return self.capabilities.get(capability_key).default_schedules(GROWTH_AGENT_ID)

    def schedules_for_configuration(
        self,
        values: dict[str, JsonValue],
        existing: Sequence[AgentSchedule],
    ) -> list[AgentSchedule]:
        return self.schedules_for_capability_configuration(
            self._definition.default_capability_key,
            values,
            existing,
        )

    def schedules_for_capability_configuration(
        self,
        capability_key: str,
        values: dict[str, JsonValue],
        existing: Sequence[AgentSchedule],
    ) -> list[AgentSchedule]:
        return self.capabilities.get(capability_key).schedules_for_configuration(
            agent_id=GROWTH_AGENT_ID,
            values=values,
            existing=existing,
        )

    def validate_configuration(self, values: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return self.validate_capability_configuration(
            self._definition.default_capability_key,
            values,
        )

    def validate_capability_configuration(
        self,
        capability_key: str,
        values: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        return self.capabilities.get(capability_key).validate_configuration(values)

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
