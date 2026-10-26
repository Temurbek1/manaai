"""Typed confirmation cards. The first implementation executes simulations only."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId

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


class ChatActionCard(ChatContract):
    sequence: int = Field(gt=0)
    card_id: UUID
    parent_id: ParentChatId
    request_id: UUID
    turn_id: int = Field(gt=0)
    mode: Literal["simulation"] = "simulation"
    action_type: Literal["sandbox_demo"]
    title: str
    text: str
    buttons: tuple[ChatActionButton, ChatActionButton]
    definition_hash: str
    created_at: AwareDatetime
    expires_at: AwareDatetime
    status: CardStatus
    selected_button: Literal["confirm", "cancel"] | None = None
    result: ChatActionResult | None = None


class ChatActionPage(ChatContract):
    parent_id: ParentChatId
    cards: tuple[ChatActionCard, ...]
    next_after: int | None = None


class ChatActionClaim(ChatContract):
    card: ChatActionCard
    execution_id: UUID
