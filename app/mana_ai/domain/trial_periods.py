"""Confirmed non-paid grant periods, never profile-date or tariff-name guesses."""

import hashlib
from datetime import timedelta
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId


class TrialPeriodMetadata(ChatContract):
    created_at: AwareDatetime
    is_paid: bool = Field(strict=True)
    agent_trial_used: bool = Field(strict=True)

    @model_validator(mode="after")
    def non_paid_consumed_grant(self) -> "TrialPeriodMetadata":
        if self.is_paid or not self.agent_trial_used:
            raise ValueError("A trial period needs a verified consumed non-paid receipt")
        return self


class KnownTrialPeriod(ChatContract):
    action_id: UUID
    parent_id: ParentChatId
    purchase_id: int = Field(gt=0, strict=True)
    days: int = Field(ge=1, le=30, strict=True)
    started_at: AwareDatetime
    valid_until: AwareDatetime
    recorded_at: AwareDatetime

    @model_validator(mode="after")
    def exact_requested_period(self) -> "KnownTrialPeriod":
        if (
            self.valid_until <= self.started_at
            or abs((self.valid_until - self.started_at - timedelta(days=self.days)).total_seconds())
            > 300
        ):
            raise ValueError("A confirmed trial must match the requested grant period")
        return self

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()
