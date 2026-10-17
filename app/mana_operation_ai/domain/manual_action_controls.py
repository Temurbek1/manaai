"""Manual action controls are not scheduled analysis capabilities or write grants."""

from typing import Final, Literal

from pydantic import ConfigDict, Field, field_validator

from app.mana_operation_ai.domain.enums import AgentStatus
from app.mana_operation_ai.domain.models import DomainModel

RETENTION_CONTACT_CONTROL_KEY: Final[Literal["retention.contact.sandbox"]] = (
    "retention.contact.sandbox"
)


class ManualActionControlDefinition(DomainModel):
    model_config = ConfigDict(frozen=True)

    agent_id: Literal["retention-agent"] = "retention-agent"
    capability_key: Literal["retention.contact.sandbox"] = RETENTION_CONTACT_CONTROL_KEY
    product: Literal["mana"] = "mana"
    provider: Literal["fake_retention_contact"] = "fake_retention_contact"
    execution_mode: Literal["human_review_sandbox"] = "human_review_sandbox"


class ManualActionControlView(DomainModel):
    definition: ManualActionControlDefinition
    capability_kill_switch: bool
    agent_kill_switch: bool
    global_kill_switch: bool
    agent_status: AgentStatus | None = None


class ManualActionControlPage(DomainModel):
    items: list[ManualActionControlView] = Field(default_factory=list, max_length=10)


class ManualActionControlChange(DomainModel):
    confirmed: Literal[True]
    enabled: bool = Field(strict=True)

    @field_validator("confirmed", mode="before")
    @classmethod
    def literal_confirmation(cls, value: object) -> bool:
        if value is not True:
            raise ValueError("Manual control changes require literal confirmation")
        return True
