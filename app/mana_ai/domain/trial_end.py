"""One service notice after a verified granted free period, never a paid offer."""

from pydantic import Field

from app.mana_ai.domain.chat import ChatContract


class TrialEndPolicy(ChatContract):
    maximum_age_days: int = Field(default=7, ge=1, le=7, strict=True)
    maximum_captures: int = Field(default=10000, ge=1, le=300000, strict=True)
