"""Typed confirmation cards. The first implementation executes simulations only."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId
from app.mana_ai.domain.conversion_grants import TrialGrantState

CardText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CardStatus = Literal["pending", "executing", "completed", "cancelled", "expired", "unknown"]


class ChatActionButton(ChatContract):
    id: Literal["confirm", "cancel"]
    label: CardText = Field(max_length=80)


class ChatActionCreate(ChatContract):
    parent_id: ParentChatId
    request_id: UUID
    action_type: Literal["sandbox_demo"]
    title: CardText = Field(max_length=120)
    text: CardText = Field(max_length=1000)
    buttons: tuple[ChatActionButton, ChatActionButton]
    expires_in_seconds: int = Field(default=900, ge=60, le=3600, strict=True)

    @model_validator(mode="after")
    def check_buttons(self) -> "ChatActionCreate":
        if {button.id for button in self.buttons} != {"confirm", "cancel"}:
            raise ValueError("Provide exactly one confirm and one cancel button")
        if self.buttons[0].label.casefold() == self.buttons[1].label.casefold():
            raise ValueError("Button labels must be distinct")
        return self


class ChatActionClick(ChatContract):
    parent_id: ParentChatId
    request_id: UUID
    button_id: Literal["confirm", "cancel"]
    definition_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class ChatActionResult(ChatContract):
    mode: Literal["simulation"] = "simulation"
    execution_id: UUID
    outcome: Literal["simulated_success"] = "simulated_success"


class TrialChatActionResult(ChatContract):
    """A real owning-lifecycle receipt obtained exclusively from the lab's fake gateway."""

    mode: Literal["simulation"] = "simulation"
    execution_id: UUID
    outcome: Literal["trial_granted", "trial_rejected", "trial_unknown"]
    grant: TrialGrantState

    @model_validator(mode="after")
    def coherent_outcome(self) -> "TrialChatActionResult":
        expected = {
            "granted": "trial_granted",
            "rejected": "trial_rejected",
            "unknown": "trial_unknown",
        }
        if expected.get(self.grant.status) != self.outcome:
            raise ValueError("Trial outcome must match its owning receipt")
        return self


class TrialCardTerms(ChatContract):
    proposal_id: UUID
    grant_days: int = Field(ge=1, le=30, strict=True)


class ChatActionCard(ChatContract):
    sequence: int = Field(gt=0)
    card_id: UUID
    parent_id: ParentChatId
    request_id: UUID
    turn_id: int = Field(gt=0)
    mode: Literal["simulation"] = "simulation"
    action_type: Literal["sandbox_demo", "free_trial_days"]
    title: str
    text: str
    buttons: tuple[ChatActionButton, ChatActionButton]
    definition_hash: str
    created_at: AwareDatetime
    expires_at: AwareDatetime
    status: CardStatus
    selected_button: Literal["confirm", "cancel"] | None = None
    result: ChatActionResult | TrialChatActionResult | None = None
    trial: TrialCardTerms | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def coherent_kind(self) -> "ChatActionCard":
        if self.action_type == "sandbox_demo":
            if self.trial is not None or isinstance(self.result, TrialChatActionResult):
                raise ValueError("A demo card cannot hold trial authority or receipts")
        elif self.trial is None or isinstance(self.result, ChatActionResult):
            raise ValueError("A trial card requires exact terms and an owning receipt")
        return self


class ChatActionPage(ChatContract):
    parent_id: ParentChatId
    cards: tuple[ChatActionCard, ...]
    next_after: int | None = None


class ChatActionClaim(ChatContract):
    card: ChatActionCard
    execution_id: UUID
