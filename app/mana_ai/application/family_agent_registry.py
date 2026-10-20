from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.enums import ManaAICapability
from app.mana_ai.domain.family_agents import FamilyAgentDefinition


class FamilyAgentRegistry:
    """An injected immutable registry, not a model-supplied identity or credential."""

    def __init__(self, definitions: tuple[FamilyAgentDefinition, ...]) -> None:
        self._definitions = {definition.agent_id: definition for definition in definitions}
        if len(self._definitions) != len(definitions):
            raise ValueError("Family agent identities must be unique")
        if [d.agent_id for d in definitions if d.speaks_to_parent] != ["parent-touch"]:
            raise ValueError("Parent-Touch must be the only family conversation speaker")

    def definitions(self) -> tuple[FamilyAgentDefinition, ...]:
        return tuple(self._definitions.values())

    def require_specialist(self, agent_id: str) -> FamilyAgentDefinition:
        definition = self._definitions.get(agent_id)
        if definition is None or definition.speaks_to_parent:
            raise ParentChatError("specialist_not_registered", 403)
        return definition


def default_family_agents() -> FamilyAgentRegistry:
    return FamilyAgentRegistry(
        (
            FamilyAgentDefinition(
                agent_id="parent-touch", title="Parent-Touch", speaks_to_parent=True
            ),
            FamilyAgentDefinition(
                agent_id="child-safety",
                title="Child-Safety",
                speaks_to_parent=False,
                capabilities=tuple(
                    capability
                    for capability in ManaAICapability
                    if capability != ManaAICapability.PARENT_COPILOT
                ),
            ),
        )
    )
