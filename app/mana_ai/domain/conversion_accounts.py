"""Minimized Parent List facts, not a full account snapshot or billing receipt."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId


class ConversionAccountFacts(ChatContract):
    """A selected tariff record does not prove absence of other paid entitlements.

    In particular, created_at has not been confirmed as the free-period start.
    These facts grant neither contact permission nor free days or payment authority.
    """

    source: Literal["manakids_parent_list"] = "manakids_parent_list"
    parent_id: ParentChatId
    collected_at: AwareDatetime
    is_paid: bool | None = Field(strict=True)
    agent_trial_used: bool | None = Field(strict=True)
    created_at: AwareDatetime | None
    payment_date: AwareDatetime | None
    valid_until: AwareDatetime | None

    @model_validator(mode="after")
    def dates_are_observed(self) -> "ConversionAccountFacts":
        for value in (self.created_at, self.payment_date):
            if value and (value - self.collected_at).total_seconds() > 120:
                raise ValueError("Account record dates cannot follow their collection")
        return self


class ConversionAccountRead(ChatContract):
    """Private backend observation; pending/unknown never authorize another read."""

    parent_id: ParentChatId
    event_id: UUID
    revision: int = Field(ge=1, strict=True)
    status: Literal["pending", "verified", "refused", "unknown"]
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    facts: ConversionAccountFacts | None = None


class ConversionAccountReadLimits(ChatContract):
    cooldown_seconds: int = Field(default=21600, ge=60, le=86400, strict=True)
    daily_limit: int = Field(default=100, ge=1, le=100_000, strict=True)
