from app.mana_operation_ai.application.ports import AdsPlatform, OperationalAgent
from app.mana_operation_ai.domain.models import AgentDefinition


class DuplicateAgentError(ValueError):
    """Raised when two implementations claim the same agent identifier."""


class UnknownAgentError(LookupError):
    """Raised when an agent identifier has no loaded implementation."""


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, OperationalAgent] = {}

    def register(self, agent: OperationalAgent) -> None:
        agent_id = agent.definition.agent_id
        if agent_id in self._agents:
            raise DuplicateAgentError(f"Agent {agent_id!r} is already registered")
        self._agents[agent_id] = agent

    def get(self, agent_id: str) -> OperationalAgent:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise UnknownAgentError(f"Agent {agent_id!r} is not registered") from exc

    def definitions(self) -> list[AgentDefinition]:
        return [self._agents[key].definition for key in sorted(self._agents)]


class AdsPlatformRegistry:
    def __init__(self) -> None:
        self._platforms: dict[str, AdsPlatform] = {}

    def register(self, platform: AdsPlatform) -> None:
        if platform.provider_name in self._platforms:
            raise ValueError(f"Ads platform {platform.provider_name!r} is already registered")
        self._platforms[platform.provider_name] = platform

    def get(self, provider_name: str) -> AdsPlatform:
        try:
            return self._platforms[provider_name]
        except KeyError as exc:
            raise LookupError(f"Ads platform {provider_name!r} is not registered") from exc
