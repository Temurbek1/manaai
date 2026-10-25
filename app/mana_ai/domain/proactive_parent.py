"""Verified recipient preferences and durable, non-delivery push observations."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId, ResponseLanguage
from app.mana_ai.domain.parent_notifications import ParentPushMessage


class ParentContactContext(ChatContract):
    """Backend-verified presentation and independently granted contact permissions."""

    parent_id: ParentChatId
    event_id: UUID
    revision: int = Field(ge=1, strict=True)
    observed_at: AwareDatetime
    valid_until: AwareDatetime
    language: ResponseLanguage
    timezone: str = Field(min_length=1, max_length=64)
    safety_chat_consent: bool = Field(strict=True)
    safety_push_consent: bool = Field(strict=True)
    marketing_push_consent: bool = Field(strict=True)
    assistant_chat_consent: bool | None = Field(
        default=None, strict=True, exclude_if=lambda v: v is None
    )
    assistant_push_consent: bool = Field(default=False, strict=True, exclude_if=lambda v: not v)

    @field_validator("parent_id")
    @classmethod
    def upstream_identifier_range(cls, value: str) -> str:
        if int(value) > 2**63 - 1:
            raise ValueError("The recipient identifier exceeds the application's integer range")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("An IANA recipient timezone is required") from None
        return value

    @model_validator(mode="after")
    def bounded_validity(self) -> "ParentContactContext":
        if not 0 < (self.valid_until - self.observed_at).total_seconds() <= 7 * 86400:
            raise ValueError("Contact preferences need an explicit validity of at most seven days")
        return self


ParentPushPurpose = Literal["safety", "marketing", "assistant"]
ParentPushStatus = Literal[
    "queued", "submitting", "queued_by_provider", "not_queued", "unknown", "suppressed"
]


class ParentPushState(ChatContract):
    """Provider queueing is not evidence of delivery, opening or parent awareness."""

    push_id: UUID
    parent_id: ParentChatId
    turn_id: int = Field(gt=0, strict=True)
    purpose: ParentPushPurpose
    status: ParentPushStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime
    queued_devices: int | None = Field(default=None, ge=0, strict=True)
    error_code: str | None = None


@dataclass(frozen=True)
class ParentPushClaim:
    """Private worker claim; never an input that an untrusted client may supply."""

    notification: ParentPushState
    claim_id: UUID
    title: str
    description: str

    @property
    def message(self) -> ParentPushMessage:
        return ParentPushMessage(
            parent_id=self.notification.parent_id, title=self.title, description=self.description
        )


class ParentPushOutcome(ChatContract):
    status: Literal["queued_by_provider", "not_queued", "unknown"]
    queued_devices: int | None = Field(default=None, ge=0, strict=True)
    error_code: (
        Literal[
            "parent_push_auth_rejected",
            "parent_push_not_authorized",
            "parent_push_invalid_message",
            "parent_push_parent_not_found",
            "parent_push_auth_unavailable",
            "parent_push_outcome_unknown",
            "parent_push_no_registered_devices",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def coherent_queue_receipt(self) -> "ParentPushOutcome":
        if self.status == "queued_by_provider":
            if not self.queued_devices or self.error_code is not None:
                raise ValueError("Provider queueing needs a positive verified device count")
        elif self.queued_devices not in {None, 0}:
            raise ValueError("A non-queued outcome cannot claim queued devices")
        if self.status == "unknown" and self.queued_devices is not None:
            raise ValueError("Unknown queueing has no verified device count")
        return self


class ParentPushPage(ChatContract):
    parent_id: ParentChatId
    pushes: list[ParentPushState]
    next_after: int | None = None
