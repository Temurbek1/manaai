"""Parent-owned assistant reminders; proposals are not scheduled actions."""

import hashlib
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId, ResponseLanguage


class ReminderPolicy(ChatContract):
    version: Literal[1] = 1
    maximum_active_per_parent: int = Field(default=10, ge=1, le=100, strict=True)
    maximum_active_global: int = Field(default=1000, ge=1, le=100000, strict=True)
    parent_commands_per_24h: int = Field(default=20, ge=1, le=1000, strict=True)
    global_commands_per_24h: int = Field(default=500, ge=1, le=100000, strict=True)
    deliveries_per_24h: int = Field(default=100, ge=1, le=100000, strict=True)
    maximum_delay_days: int = Field(default=366, ge=1, le=366, strict=True)
    confirmation_seconds: int = Field(default=1800, ge=60, le=86400, strict=True)
    delivery_grace_seconds: int = Field(default=3600, ge=60, le=86400, strict=True)
    ownership_lease_seconds: int = Field(default=120, ge=30, le=300, strict=True)

    @model_validator(mode="after")
    def ordered_limits(self) -> "ReminderPolicy":
        if (
            self.maximum_active_per_parent > self.maximum_active_global
            or self.parent_commands_per_24h > self.global_commands_per_24h
        ):
            raise ValueError("Parent reminder ceilings cannot exceed global ceilings")
        return self


class ReminderCandidate(ChatContract):
    """Content must be a parent's exact quote, or the frozen pending reminder text."""

    content: str = Field(min_length=1, max_length=250, pattern=r"\S")
    due_at: AwareDatetime | None
    timezone: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def local_time(self) -> "ReminderCandidate":
        try:
            zone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Unknown reminder timezone") from None
        if (
            self.due_at is not None
            and self.due_at.utcoffset() != self.due_at.astimezone(zone).utcoffset()
        ):
            raise ValueError("A reminder preview must express the selected timezone's offset")
        return self

    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


ReminderStatus = Literal[
    "draft", "scheduled", "checking", "ready", "delivered", "cancelled", "expired", "unknown"
]


class ParentReminder(ChatContract):
    reminder_id: UUID
    parent_id: ParentChatId
    origin_turn_id: int = Field(gt=0, strict=True)
    candidate: ReminderCandidate
    status: ReminderStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime
    language: ResponseLanguage
    confirmation_id: UUID
    confirmation_expires_at: AwareDatetime
    confirmation_turn_id: int | None = None
    confirmed_turn_id: int | None = None
    delivered_turn_id: int | None = None
    error_code: str | None = None

    @model_validator(mode="after")
    def lifecycle(self) -> "ParentReminder":
        if self.updated_at < self.created_at or self.confirmation_expires_at <= self.created_at:
            raise ValueError("Reminder lifecycle dates must be ordered")
        if self.status in {"scheduled", "checking", "ready", "delivered"} and (
            self.candidate.due_at is None or self.confirmed_turn_id is None
        ):
            raise ValueError("Only a confirmed complete reminder may be delivered")
        if (self.status == "delivered") != (self.delivered_turn_id is not None):
            raise ValueError("Only a verified chat publication carries its turn ID")
        return self


class ReminderConfirmation(ChatContract):
    confirmation_id: UUID
    reminder_id: UUID
    kind: Literal["details", "approval"]
    candidate: ReminderCandidate
    expires_at: AwareDatetime


class ReminderScope(ChatContract):
    now: AwareDatetime
    default_timezone: str
    timezone_basis: Literal["verified_contact", "application_default_requires_confirmation"]
    active: tuple[ParentReminder, ...] = Field(max_length=100)
    pending: ReminderConfirmation | None


class ReminderDeliveryClaim(ChatContract):
    reminder: ParentReminder
    claim_id: UUID
    lease_expires_at: AwareDatetime
