"""Private, host-rendered proof for one exact approved free-day offer."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId, ResponseLanguage
from app.mana_ai.domain.chat_actions import ChatActionButton
from app.mana_ai.domain.conversion import ConversionProposal


class TrialCardDefinition(ChatContract):
    protocol: Literal[1] = 1
    action_type: Literal["free_trial_days"] = "free_trial_days"
    parent_id: ParentChatId
    request_id: UUID
    proposal: ConversionProposal
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=1000)
    buttons: tuple[ChatActionButton, ChatActionButton]
    language: ResponseLanguage
    timezone: str = Field(min_length=1, max_length=64)
    snapshot_revision: int = Field(ge=1, strict=True)
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def exact_trial(self) -> "TrialCardDefinition":
        if (
            self.proposal.parent_id != self.parent_id
            or self.proposal.offer.kind != "free_premium_days"
            or self.proposal.status != "published"
            or self.proposal.turn_id is None
            or {button.id for button in self.buttons} != {"confirm", "cancel"}
            or not 0 < (self.expires_at - self.created_at).total_seconds() <= 900
        ):
            raise ValueError("A card requires one published, exact and bounded trial proposal")
        return self
