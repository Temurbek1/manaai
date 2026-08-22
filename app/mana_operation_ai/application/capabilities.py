from collections.abc import Sequence
from typing import Protocol

from pydantic import JsonValue

from app.mana_operation_ai.domain.models import (
    AgentConfiguration,
    AgentRun,
    AgentRunResult,
    AgentSchedule,
    CapabilityDefinition,
    IntegrationHealth,
)


class CapabilityHandler(Protocol):
    @property
    def definition(self) -> CapabilityDefinition: ...

    @property
    def default_configuration(self) -> dict[str, JsonValue]: ...

    def default_schedules(self, agent_id: str) -> list[AgentSchedule]: ...

    def schedules_for_configuration(
        self,
        *,
        agent_id: str,
        values: dict[str, JsonValue],
        existing: Sequence[AgentSchedule],
    ) -> list[AgentSchedule]: ...

    def validate_configuration(self, values: dict[str, JsonValue]) -> dict[str, JsonValue]: ...

    async def health(self) -> list[IntegrationHealth]: ...

    async def execute(
        self,
        *,
        run: AgentRun,
        job_type: str,
        configuration: AgentConfiguration,
    ) -> AgentRunResult: ...

    async def finalize_after_actions(self, run_id: str) -> AgentRunResult: ...


class DuplicateCapabilityError(ValueError):
    """Raised when two handlers claim the same namespaced capability key."""


class UnknownCapabilityError(LookupError):
    """Raised when no loaded handler owns a capability key."""


class CapabilityRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, CapabilityHandler] = {}

    def register(self, handler: CapabilityHandler) -> None:
        key = handler.definition.key
        if key in self._handlers:
            raise DuplicateCapabilityError(f"Capability {key!r} is already registered")
        self._handlers[key] = handler

    def get(self, key: str) -> CapabilityHandler:
        try:
            return self._handlers[key]
        except KeyError as exc:
            raise UnknownCapabilityError(f"Capability {key!r} is not registered") from exc

    def definitions(self) -> list[CapabilityDefinition]:
        return [self._handlers[key].definition for key in sorted(self._handlers)]

    def handlers(self) -> list[CapabilityHandler]:
        return [self._handlers[key] for key in sorted(self._handlers)]
