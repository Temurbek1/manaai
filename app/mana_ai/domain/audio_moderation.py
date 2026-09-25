from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    field_validator,
    model_validator,
)


class AudioRiskCategory(StrEnum):
    SAFE = "safe"
    NO_SPEECH = "no_speech"
    THREAT_OR_VIOLENCE = "threat_or_violence"
    ABUSE_OR_COERCION = "abuse_or_coercion"
    SEXUAL_RISK = "sexual_risk"
    SELF_HARM = "self_harm"
    WEAPONS_DRUGS_OR_CRIME = "weapons_drugs_or_crime"
    BULLYING_OR_EXTORTION = "bullying_or_extortion"
    MEDICAL_EMERGENCY = "medical_emergency"
    SUSPICIOUS_CONTACT = "suspicious_contact"
    OTHER_CHILD_SAFETY_RISK = "other_child_safety_risk"
    UNCERTAIN = "uncertain"


class AudioRiskSeverity(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AudioModerationCallbackStatus(StrEnum):
    # The 360REC backend exposes APPROVED audio to the parent. In this integration,
    # APPROVED therefore means that guardian attention is required, not that content is safe.
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AudioModerationJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audio_id: int = Field(gt=0)
    audio_url: HttpUrl
    duration: str = Field(min_length=1, max_length=32)
    callback_url: HttpUrl
    callback_token: SecretStr = Field(min_length=16, max_length=8_192)

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, value: str) -> str:
        try:
            duration = Decimal(value)
        except InvalidOperation:
            raise ValueError("duration must be a number encoded as a string") from None
        if not duration.is_finite() or duration < 0 or duration > Decimal("86400"):
            raise ValueError("duration must be between 0 and 86400 seconds")
        return value


class AudioRiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: AudioRiskCategory
    severity: AudioRiskSeverity
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_safe_severity(self) -> "AudioRiskAssessment":
        if (
            self.category in {AudioRiskCategory.SAFE, AudioRiskCategory.NO_SPEECH}
            and self.severity is not AudioRiskSeverity.NONE
        ):
            raise ValueError("safe and no-speech assessments must use severity none")
        if (
            self.category not in {AudioRiskCategory.SAFE, AudioRiskCategory.NO_SPEECH}
            and self.severity is AudioRiskSeverity.NONE
        ):
            raise ValueError("risk and uncertain assessments cannot use severity none")
        return self


class AudioModerationCallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AudioModerationCallbackStatus
    reason: str = Field(min_length=1, max_length=256)


class AudioModerationAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted"] = "accepted"
    audio_id: int = Field(gt=0)
    disposition: Literal["queued", "duplicate"]
