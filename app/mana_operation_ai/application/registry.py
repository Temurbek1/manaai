from app.mana_operation_ai.application.ports import AdsPlatform, OperationalAgent
from app.mana_operation_ai.domain.models import AgentDefinition


class DuplicateAgentError(ValueError):
    """Raised when two implementations claim the same agent identifier."""


class UnknownAgentError(LookupError):
    """Raised when an agent identifier has no loaded implementation."""


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, OperationalAgent] = {}
        self._aliases: dict[str, str] = {}

    def register(self, agent: OperationalAgent) -> None:
        agent_id = agent.definition.agent_id
        if agent_id in self._agents:
            raise DuplicateAgentError(f"Agent {agent_id!r} is already registered")
        self._agents[agent_id] = agent

    def get(self, agent_id: str) -> OperationalAgent:
        agent_id = self.canonical_id(agent_id)
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise UnknownAgentError(f"Agent {agent_id!r} is not registered") from exc

    def register_alias(self, alias: str, canonical_agent_id: str) -> None:
        if alias in self._agents or alias in self._aliases:
            raise DuplicateAgentError(f"Agent identifier {alias!r} is already registered")
        if canonical_agent_id not in self._agents:
            raise UnknownAgentError(
                f"Canonical agent {canonical_agent_id!r} must be registered before its alias",
            )
        self._aliases[alias] = canonical_agent_id

    def canonical_id(self, agent_id: str) -> str:
        return self._aliases.get(agent_id, agent_id)

    def default_capability_key(self, agent_id: str) -> str:
        return self.get(agent_id).definition.default_capability_key

    def definitions(self) -> list[AgentDefinition]:
        return [self._agents[key].definition for key in sorted(self._agents)]

    def identifiers_for(self, agent_id: str) -> set[str]:
        """Return the canonical identifier and every compatibility alias for it."""
        canonical_agent_id = self.canonical_id(agent_id)
        return {
            canonical_agent_id,
            *(alias for alias, target in self._aliases.items() if target == canonical_agent_id),
        }


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
