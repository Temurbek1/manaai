"""One communication decision, never a specialist receipt or execution grant."""

from typing import Literal

from pydantic import Field, model_validator

from app.mana_ai.domain.chat import ChatContract
from app.mana_ai.domain.client_upsell import UpsellEnquiry
from app.mana_ai.domain.parent_touch_manager import ParentTouchClarificationReply

COMPACT_MANAGER_DECISION_TOOL = "choose_parent_touch_response"


class CompactManagerDecision(ChatContract):
    """All native slots are explicit; owning workflows still validate handoffs."""

    kind: Literal["reply", "child_safety", "reminder", "upsell"]
    body: str | None
    question: str | None
    enquiry: UpsellEnquiry | None

    @model_validator(mode="after")
    def exclusive_response(self) -> "CompactManagerDecision":
        if self.kind == "reply":
            if self.body is None or self.enquiry is not None:
                raise ValueError("A manager reply requires text without a tariff enquiry")
            ParentTouchClarificationReply(body=self.body, question=self.question)
        else:
            if self.body is not None or self.question is not None:
                raise ValueError("A manager handoff cannot contain a reply or question")
            if self.enquiry is not None and self.kind != "upsell":
                raise ValueError("A tariff enquiry belongs only to its owning handoff")
        return self


class CompactManagerInvocation(ChatContract):
    """A model decision's native pairing, never a host execution receipt."""

    call_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,200}$", strict=True)
    decision: CompactManagerDecision
