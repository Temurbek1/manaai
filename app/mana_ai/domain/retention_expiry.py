"""Source-backed tariff expiry reminders, not renewal or payment authority."""

from typing import Literal

from pydantic import AwareDatetime, Field

from app.mana_ai.domain.chat import ChatContract, ParentChatId


class RetentionExpiryPolicy(ChatContract):
    notice_within_hours: int = Field(default=72, ge=1, le=168, strict=True)
    maximum_profile_age_seconds: int = Field(default=180, ge=30, le=180, strict=True)
    minimum_outreach_interval_hours: int = Field(default=24, ge=24, le=168, strict=True)
    urgent_notice_cooldown_hours: int = Field(default=24, ge=1, le=168, strict=True)
    maximum_profiles: int = Field(default=10000, ge=1, le=300000, strict=True)
    maximum_changes: int = Field(default=50000, ge=1, le=1000000, strict=True)


class RetentionTariffFact(ChatContract):
    source: Literal["selected_current_manakids_profile_tariff"] = (
        "selected_current_manakids_profile_tariff"
    )
    parent_id: ParentChatId
    collected_at: AwareDatetime
    is_paid: bool | None = Field(strict=True)
    valid_until: AwareDatetime | None
