"""Endpoint-specific app-backend admissions, not a generic inference dispatcher."""

from typing import Literal
from uuid import UUID

from app.mana_ai.domain.child_safety import SafetyJobState, SafetyTarget
from app.mana_ai.domain.enums import ManaAICapability
from app.mana_ai.domain.requests import (
    AdaptiveScreenTimeRequest,
    AIGamingSafetyRequest,
    BehaviourAnomalyRequest,
    ChildSafetyAssistantRequest,
    FamilyAgreementRequest,
    FamilyDigestRequest,
    LocationIntelligenceRequest,
    SafetyMonitorRequest,
    ScamPrivacyShieldRequest,
    SmartContentFilterRequest,
)
from app.mana_ai.domain.responses import (
    AdaptiveScreenTimeResponse,
    AIGamingSafetyResponse,
    BehaviourAnomalyResponse,
    ChildSafetyAssistantResponse,
    FamilyAgreementResponse,
    FamilyDigestResponse,
    LocationIntelligenceResponse,
    ManaAIResponseBase,
    SafetyMonitorResponse,
    ScamPrivacyShieldResponse,
    SmartContentFilterResponse,
)


class SafetyCapabilityReceipt[ResultT: ManaAIResponseBase](SafetyJobState):
    kind: Literal["child_data"] = "child_data"
    visibility: Literal["internal"] = "internal"
    analysis: ResultT | None = None
    question_id: UUID | None = None


class ChildSafetySafetyMonitorRequest(SafetyTarget):
    analysis: SafetyMonitorRequest


class ChildSafetySafetyMonitorResponse(SafetyCapabilityReceipt[SafetyMonitorResponse]):
    capability: Literal[ManaAICapability.SAFETY_MONITOR]


class ChildSafetyFamilyDigestRequest(SafetyTarget):
    analysis: FamilyDigestRequest


class ChildSafetyFamilyDigestResponse(SafetyCapabilityReceipt[FamilyDigestResponse]):
    capability: Literal[ManaAICapability.FAMILY_DIGEST]


class ChildSafetyScreenTimeRequest(SafetyTarget):
    analysis: AdaptiveScreenTimeRequest


class ChildSafetyScreenTimeResponse(SafetyCapabilityReceipt[AdaptiveScreenTimeResponse]):
    capability: Literal[ManaAICapability.ADAPTIVE_SCREEN_TIME]


class ChildSafetyLocationRequest(SafetyTarget):
    analysis: LocationIntelligenceRequest


class ChildSafetyLocationResponse(SafetyCapabilityReceipt[LocationIntelligenceResponse]):
    capability: Literal[ManaAICapability.LOCATION_INTELLIGENCE]


class ChildSafetyContentRequest(SafetyTarget):
    analysis: SmartContentFilterRequest


class ChildSafetyContentResponse(SafetyCapabilityReceipt[SmartContentFilterResponse]):
    capability: Literal[ManaAICapability.SMART_CONTENT_FILTER]


class ChildSafetyScamRequest(SafetyTarget):
    analysis: ScamPrivacyShieldRequest


class ChildSafetyScamResponse(SafetyCapabilityReceipt[ScamPrivacyShieldResponse]):
    capability: Literal[ManaAICapability.SCAM_PRIVACY_SHIELD]


class ChildSafetyGamingRequest(SafetyTarget):
    analysis: AIGamingSafetyRequest


class ChildSafetyGamingResponse(SafetyCapabilityReceipt[AIGamingSafetyResponse]):
    capability: Literal[ManaAICapability.AI_GAMING_SAFETY]


class ChildSafetyAssistantAdmission(SafetyTarget):
    analysis: ChildSafetyAssistantRequest


class ChildSafetyAssistantReceipt(SafetyCapabilityReceipt[ChildSafetyAssistantResponse]):
    capability: Literal[ManaAICapability.CHILD_SAFETY_ASSISTANT]


class ChildSafetyAgreementRequest(SafetyTarget):
    analysis: FamilyAgreementRequest


class ChildSafetyAgreementResponse(SafetyCapabilityReceipt[FamilyAgreementResponse]):
    capability: Literal[ManaAICapability.FAMILY_AGREEMENT]


class ChildSafetyBehaviourRequest(SafetyTarget):
    analysis: BehaviourAnomalyRequest


class ChildSafetyBehaviourResponse(SafetyCapabilityReceipt[BehaviourAnomalyResponse]):
    capability: Literal[ManaAICapability.BEHAVIOUR_ANOMALY]
