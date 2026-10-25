"""Shared selected-tariff observations can veto an offer, never prove eligibility."""

from pydantic import Field

from app.mana_ai.domain.chat import ChatContract


class SharedConversionProfilePolicy(ChatContract):
    maximum_age_seconds: int = Field(default=180, ge=30, le=180, strict=True)
    maximum_profiles: int = Field(default=10000, ge=1, le=300000, strict=True)
