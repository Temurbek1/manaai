from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ManaAICapability(StrEnum):
    SAFETY_MONITOR = "safety_monitor"
    FAMILY_DIGEST = "family_digest"
    ADAPTIVE_SCREEN_TIME = "adaptive_screen_time"
    LOCATION_INTELLIGENCE = "location_intelligence"
    SMART_CONTENT_FILTER = "smart_content_filter"
    SCAM_PRIVACY_SHIELD = "scam_privacy_shield"
    AI_GAMING_SAFETY = "ai_gaming_safety"
    PARENT_COPILOT = "parent_copilot"
    CHILD_SAFETY_ASSISTANT = "child_safety_assistant"
    FAMILY_AGREEMENT = "family_agreement"
    BEHAVIOUR_ANOMALY = "behaviour_anomaly"


class ManaAIRequest(BaseModel):
    """Self-contained product inference request.

    Every datum needed for inference must be supplied in this payload. Implementations
    are not allowed to enrich it from operational repositories or company integrations.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=128)
    capability: ManaAICapability
    occurred_at: datetime
    locale: str = Field(default="en", min_length=2, max_length=16)
    payload: dict[str, JsonValue]


class ManaAIFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=80)
    severity: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    recommended_action: str | None = Field(default=None, max_length=800)


class ManaAIResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    capability: ManaAICapability
    processed_at: datetime
    findings: list[ManaAIFinding]
    data_quality_notes: list[str] = Field(default_factory=list, max_length=20)
    model_name: str


class ManaAICapabilityInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: ManaAICapability
    status: str
    accepts_payload_only: bool = True


class ManaAICapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bounded_context: str = "mana_ai"
    capabilities: list[ManaAICapabilityInfo]
