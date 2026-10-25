"""A captured communication scope is not permission to analyse arbitrary children."""

from typing import Literal

from pydantic import Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ResponseLanguage
from app.mana_ai.domain.family_agents import ParentTouchText

ManagerTarget = Literal["child_safety", "upsell", "reminder"]


class ParentTouchManagerScope(ChatContract):
    language: ResponseLanguage
    stage: Literal["route", "child_safety", "upsell", "reminder"] = "route"
    upsell_enabled: bool = False
    reminders_enabled: bool = False


class ParentTouchManagerHandoff(ChatContract):
    target: ManagerTarget
    call_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,200}$")


class ParentTouchManagerReply(ChatContract):
    body: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def ordinary_statement(self) -> "ParentTouchManagerReply":
        ParentTouchText(body=self.body, question=None)
        return self


CHILD_REVIEW_TOOL = "request_child_safety_review"
UPSELL_TOOL = "request_tariff_help"
REMINDER_TOOL = "request_reminder_help"
