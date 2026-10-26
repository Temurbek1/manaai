"""Explicit parent acceptance of a one-time non-paid tariff grant."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, PrivateAttr, field_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId
from app.mana_ai.domain.trial_periods import TrialPeriodMetadata


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


class TrialButtonAcceptance(ChatContract):
    """Internal proof of an authenticated, definition-bound confirmation click."""

    parent_id: ParentChatId
    event_id: UUID
    proposal_id: UUID
    confirmation_card_id: UUID
    execution_id: UUID
    click_request_id: UUID
    definition_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class TrialGrantResult(ChatContract):
    purchase_id: int = Field(gt=0, strict=True)
    parent_id: ParentChatId
    tariff: str = Field(min_length=1, max_length=100)
    valid_until: AwareDatetime
    _period_metadata: TrialPeriodMetadata | None = PrivateAttr(default=None)

    @property
    def period_metadata(self) -> TrialPeriodMetadata | None:
        return self._period_metadata

    def with_period_metadata(self, metadata: TrialPeriodMetadata | None) -> "TrialGrantResult":
        result = self.model_copy()
        result._period_metadata = metadata
        return result


class TrialGrantState(ChatContract):
    action_id: UUID
    parent_id: ParentChatId
    proposal_id: UUID
    days: int = Field(ge=1, le=30, strict=True)
    status: Literal["submitting", "granted", "rejected", "unknown"]
    result: TrialGrantResult | None = None
    error_code: str | None = None
