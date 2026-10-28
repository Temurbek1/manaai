"""A semantic reminder review, never a prepared action or execution receipt."""

from typing import Literal

from pydantic import model_validator

from app.mana_ai.domain.chat import ChatContract
from app.mana_ai.domain.parent_touch_manager import ParentTouchClarificationReply


class BoundReminderDecision(ChatContract):
    """The host binds a prepare choice to its own complete frozen candidate."""

    kind: Literal["prepare", "reply"]
    body: str | None
    question: str | None

    @model_validator(mode="after")
    def exclusive_choice(self) -> "BoundReminderDecision":
        if self.kind == "prepare":
            if self.body is not None or self.question is not None:
                raise ValueError("A prepare choice contains no parent-facing text")
        else:
            if self.body is None:
                raise ValueError("A reminder review reply requires its statements field")
            ParentTouchClarificationReply(body=self.body, question=self.question)
        return self


class BoundReminderPrepareWire(ChatContract):
    kind: Literal["prepare"]


class BoundReminderReplyWire(ParentTouchClarificationReply):
    kind: Literal["reply"]


class BoundReminderReviewWire(ChatContract):
    decision: BoundReminderPrepareWire | BoundReminderReplyWire
