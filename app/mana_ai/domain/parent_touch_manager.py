"""A captured communication scope is not permission to analyse arbitrary children."""

from typing import Literal

from pydantic import Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ResponseLanguage
from app.mana_ai.domain.client_upsell import UpsellEnquiry
from app.mana_ai.domain.family_agents import ParentTouchText

ManagerTarget = Literal["child_safety", "upsell", "reminder"]


class ParentTouchManagerScope(ChatContract):
    language: ResponseLanguage
    stage: Literal["route", "child_safety", "upsell", "reminder"] = "route"
    upsell_enabled: bool = False
    reminders_enabled: bool = False
    clarifications_enabled: bool = Field(default=False, exclude_if=lambda v: not v)
    tariff_handoff_enabled: bool = Field(default=False, exclude_if=lambda v: not v)
    setup_help_protocol: Literal[1] | None = Field(default=None, exclude_if=lambda v: v is None)
    compact_decision_protocol: Literal[1, 2] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    language_reference: str | None = Field(
        default=None, max_length=2000, exclude_if=lambda v: v is None
    )


class ParentTouchManagerHandoff(ChatContract):
    target: ManagerTarget
    call_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,200}$")
    tariff_enquiry: UpsellEnquiry | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def owning_arguments(self) -> "ParentTouchManagerHandoff":
        if self.tariff_enquiry is not None and self.target != "upsell":
            raise ValueError("Tariff arguments belong only to the tariff owner")
        return self


class ParentTouchTariffCall(ChatContract):
    """New captured native call; null retains ordinary account-help delegation."""

    enquiry: UpsellEnquiry | None


class ParentTouchManagerReply(ChatContract):
    body: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def ordinary_statement(self) -> "ParentTouchManagerReply":
        ParentTouchText(body=self.body, question=None)
        return self


class ParentTouchClarificationReply(ParentTouchText):
    """One reactive clarification, never a specialist result or action request."""

    question: str | None = Field(max_length=400, pattern=r"^[^?\u061f\uff1f]*[?\u061f\uff1f]$")


CHILD_REVIEW_TOOL = "request_child_safety_review"
UPSELL_TOOL = "request_tariff_help"
REMINDER_TOOL = "request_reminder_help"
