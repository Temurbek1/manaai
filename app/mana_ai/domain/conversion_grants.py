"""Explicit parent acceptance of a one-time non-paid tariff grant."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId


class TrialAcceptance(ChatContract):
    parent_id: ParentChatId
    event_id: UUID
    proposal_id: UUID
    reply_turn_id: int = Field(gt=0, strict=True)
    confirmed_by_parent: Literal[True]

    @field_validator("confirmed_by_parent", mode="before")
    @classmethod
    def explicit_confirmation(cls, value: object) -> object:
        if value is not True:
            raise ValueError("Explicit parent confirmation is required")
        return value


class TrialGrantResult(ChatContract):
    purchase_id: int = Field(gt=0, strict=True)
    parent_id: ParentChatId
    tariff: str = Field(min_length=1, max_length=100)
    valid_until: AwareDatetime


class TrialGrantState(ChatContract):
    action_id: UUID
    parent_id: ParentChatId
    proposal_id: UUID
    days: int = Field(ge=1, le=30, strict=True)
    status: Literal["submitting", "granted", "rejected", "unknown"]
    result: TrialGrantResult | None = None
    error_code: str | None = None
