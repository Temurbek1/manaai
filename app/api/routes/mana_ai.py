from typing import Annotated, Any

from fastapi import APIRouter, Body, status

from app.api.mana_ai_dependencies import ManaAIAnalysisServiceDep
from app.api.mana_ai_examples import (
    CAPABILITY_DESCRIPTIONS,
    CAPABILITY_TITLES,
    request_examples,
)
from app.mana_ai.domain.enums import ManaAICapability
from app.mana_ai.domain.requests import (
    AdaptiveScreenTimeRequest,
    AIGamingSafetyRequest,
    BehaviourAnomalyRequest,
    ChildSafetyAssistantRequest,
    FamilyAgreementRequest,
    FamilyDigestRequest,
    LocationIntelligenceRequest,
    ManaAIRequest,
    ParentCopilotRequest,
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
    ManaAICapabilitiesResponse,
    ManaAICapabilityInfo,
    ManaAIResponseBase,
    ParentCopilotResponse,
    SafetyMonitorResponse,
    ScamPrivacyShieldResponse,
    SmartContentFilterResponse,
)

router = APIRouter()

SHARED_CONTRACT = (
    "---\n\n"
    "Accepts application-supplied, minimized evidence and returns a typed read-only analysis. "
    "This endpoint does not read or mutate application databases and never executes a proposed "
    "action. Reuse `request_id` when retrying the same logical analysis.\n\n"
    "**Always check `status` before trusting the content.** `completed` means the full analysis "
    "ran; `degraded` means a signal was missing or a model claim failed validation — the response "
    "is still usable but reduced, and `data_quality_notes` explains why. Findings that cite "
    "evidence you did not send are dropped, and a summary that contradicts the validated verdict "
    "is replaced."
)


def describe(capability: ManaAICapability) -> str:
    return f"{CAPABILITY_DESCRIPTIONS[capability]}\n\n{SHARED_CONTRACT}"


COMMON_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"description": "Completed or explicitly degraded read-only analysis."},
    401: {"description": "Missing or invalid bearer token."},
    413: {"description": "Request body exceeds MANA_AI_MAX_REQUEST_BODY_BYTES."},
    422: {"description": "The capability-specific request is invalid."},
    429: {
        "description": (
            "Authentication failure limit or request rate limit exceeded; honor Retry-After."
        )
    },
}


def capability_path(capability: ManaAICapability) -> str:
    return f"/{capability.value.replace('_', '-')}"


def public_capability_path(capability: ManaAICapability) -> str:
    return f"/api/v1/mana-ai{capability_path(capability)}"


async def _analyze_as[ResponseT: ManaAIResponseBase](
    payload: ManaAIRequest,
    service: ManaAIAnalysisServiceDep,
    response_type: type[ResponseT],
) -> ResponseT:
    result = await service.analyze(payload)
    return response_type.model_validate(result.model_dump())


@router.get(
    "/capabilities",
    response_model=ManaAICapabilitiesResponse,
    summary="List implemented MANA AI endpoints",
    description="Returns the exact method and path for every independent read-only capability.",
)
async def list_capabilities() -> ManaAICapabilitiesResponse:
    return ManaAICapabilitiesResponse(
        capabilities=[
            ManaAICapabilityInfo(
                capability=capability,
                path=public_capability_path(capability),
            )
            for capability in ManaAICapability
        ]
    )


SafetyMonitorBody = Annotated[
    SafetyMonitorRequest,
    Body(openapi_examples=request_examples(ManaAICapability.SAFETY_MONITOR)),
]


@router.post(
    capability_path(ManaAICapability.SAFETY_MONITOR),
    response_model=SafetyMonitorResponse,
    status_code=status.HTTP_200_OK,
    operation_id="analyze_safety_monitor",
    summary=CAPABILITY_TITLES[ManaAICapability.SAFETY_MONITOR],
    description=describe(ManaAICapability.SAFETY_MONITOR),
    responses=COMMON_RESPONSES,
)
async def analyze_safety_monitor(
    payload: SafetyMonitorBody,
    service: ManaAIAnalysisServiceDep,
) -> SafetyMonitorResponse:
    return await _analyze_as(payload, service, SafetyMonitorResponse)


FamilyDigestBody = Annotated[
    FamilyDigestRequest,
    Body(openapi_examples=request_examples(ManaAICapability.FAMILY_DIGEST)),
]


@router.post(
    capability_path(ManaAICapability.FAMILY_DIGEST),
    response_model=FamilyDigestResponse,
    operation_id="generate_family_digest",
    summary=CAPABILITY_TITLES[ManaAICapability.FAMILY_DIGEST],
    description=describe(ManaAICapability.FAMILY_DIGEST),
    responses=COMMON_RESPONSES,
)
async def generate_family_digest(
    payload: FamilyDigestBody,
    service: ManaAIAnalysisServiceDep,
) -> FamilyDigestResponse:
    return await _analyze_as(payload, service, FamilyDigestResponse)


AdaptiveScreenTimeBody = Annotated[
    AdaptiveScreenTimeRequest,
    Body(openapi_examples=request_examples(ManaAICapability.ADAPTIVE_SCREEN_TIME)),
]


@router.post(
    capability_path(ManaAICapability.ADAPTIVE_SCREEN_TIME),
    response_model=AdaptiveScreenTimeResponse,
    operation_id="analyze_adaptive_screen_time",
    summary=CAPABILITY_TITLES[ManaAICapability.ADAPTIVE_SCREEN_TIME],
    description=describe(ManaAICapability.ADAPTIVE_SCREEN_TIME),
    responses=COMMON_RESPONSES,
)
async def analyze_adaptive_screen_time(
    payload: AdaptiveScreenTimeBody,
    service: ManaAIAnalysisServiceDep,
) -> AdaptiveScreenTimeResponse:
    return await _analyze_as(payload, service, AdaptiveScreenTimeResponse)


LocationIntelligenceBody = Annotated[
    LocationIntelligenceRequest,
    Body(openapi_examples=request_examples(ManaAICapability.LOCATION_INTELLIGENCE)),
]


@router.post(
    capability_path(ManaAICapability.LOCATION_INTELLIGENCE),
    response_model=LocationIntelligenceResponse,
    operation_id="analyze_location_intelligence",
    summary=CAPABILITY_TITLES[ManaAICapability.LOCATION_INTELLIGENCE],
    description=describe(ManaAICapability.LOCATION_INTELLIGENCE),
    responses=COMMON_RESPONSES,
)
async def analyze_location_intelligence(
    payload: LocationIntelligenceBody,
    service: ManaAIAnalysisServiceDep,
) -> LocationIntelligenceResponse:
    return await _analyze_as(payload, service, LocationIntelligenceResponse)


SmartContentFilterBody = Annotated[
    SmartContentFilterRequest,
    Body(openapi_examples=request_examples(ManaAICapability.SMART_CONTENT_FILTER)),
]


@router.post(
    capability_path(ManaAICapability.SMART_CONTENT_FILTER),
    response_model=SmartContentFilterResponse,
    operation_id="check_smart_content_filter",
    summary=CAPABILITY_TITLES[ManaAICapability.SMART_CONTENT_FILTER],
    description=describe(ManaAICapability.SMART_CONTENT_FILTER),
    responses=COMMON_RESPONSES,
)
async def check_smart_content_filter(
    payload: SmartContentFilterBody,
    service: ManaAIAnalysisServiceDep,
) -> SmartContentFilterResponse:
    return await _analyze_as(payload, service, SmartContentFilterResponse)


ScamPrivacyShieldBody = Annotated[
    ScamPrivacyShieldRequest,
    Body(openapi_examples=request_examples(ManaAICapability.SCAM_PRIVACY_SHIELD)),
]


@router.post(
    capability_path(ManaAICapability.SCAM_PRIVACY_SHIELD),
    response_model=ScamPrivacyShieldResponse,
    operation_id="check_scam_privacy_shield",
    summary=CAPABILITY_TITLES[ManaAICapability.SCAM_PRIVACY_SHIELD],
    description=describe(ManaAICapability.SCAM_PRIVACY_SHIELD),
    responses=COMMON_RESPONSES,
)
async def check_scam_privacy_shield(
    payload: ScamPrivacyShieldBody,
    service: ManaAIAnalysisServiceDep,
) -> ScamPrivacyShieldResponse:
    return await _analyze_as(payload, service, ScamPrivacyShieldResponse)


AIGamingSafetyBody = Annotated[
    AIGamingSafetyRequest,
    Body(openapi_examples=request_examples(ManaAICapability.AI_GAMING_SAFETY)),
]


@router.post(
    capability_path(ManaAICapability.AI_GAMING_SAFETY),
    response_model=AIGamingSafetyResponse,
    operation_id="analyze_ai_gaming_safety",
    summary=CAPABILITY_TITLES[ManaAICapability.AI_GAMING_SAFETY],
    description=describe(ManaAICapability.AI_GAMING_SAFETY),
    responses=COMMON_RESPONSES,
)
async def analyze_ai_gaming_safety(
    payload: AIGamingSafetyBody,
    service: ManaAIAnalysisServiceDep,
) -> AIGamingSafetyResponse:
    return await _analyze_as(payload, service, AIGamingSafetyResponse)


ParentCopilotBody = Annotated[
    ParentCopilotRequest,
    Body(openapi_examples=request_examples(ManaAICapability.PARENT_COPILOT)),
]


@router.post(
    capability_path(ManaAICapability.PARENT_COPILOT),
    response_model=ParentCopilotResponse,
    operation_id="respond_with_parent_copilot",
    summary=CAPABILITY_TITLES[ManaAICapability.PARENT_COPILOT],
    description=describe(ManaAICapability.PARENT_COPILOT),
    responses=COMMON_RESPONSES,
)
async def respond_with_parent_copilot(
    payload: ParentCopilotBody,
    service: ManaAIAnalysisServiceDep,
) -> ParentCopilotResponse:
    return await _analyze_as(payload, service, ParentCopilotResponse)


ChildSafetyAssistantBody = Annotated[
    ChildSafetyAssistantRequest,
    Body(openapi_examples=request_examples(ManaAICapability.CHILD_SAFETY_ASSISTANT)),
]


@router.post(
    capability_path(ManaAICapability.CHILD_SAFETY_ASSISTANT),
    response_model=ChildSafetyAssistantResponse,
    operation_id="respond_with_child_safety_assistant",
    summary=CAPABILITY_TITLES[ManaAICapability.CHILD_SAFETY_ASSISTANT],
    description=describe(ManaAICapability.CHILD_SAFETY_ASSISTANT),
    responses=COMMON_RESPONSES,
)
async def respond_with_child_safety_assistant(
    payload: ChildSafetyAssistantBody,
    service: ManaAIAnalysisServiceDep,
) -> ChildSafetyAssistantResponse:
    return await _analyze_as(payload, service, ChildSafetyAssistantResponse)


FamilyAgreementBody = Annotated[
    FamilyAgreementRequest,
    Body(openapi_examples=request_examples(ManaAICapability.FAMILY_AGREEMENT)),
]


@router.post(
    capability_path(ManaAICapability.FAMILY_AGREEMENT),
    response_model=FamilyAgreementResponse,
    operation_id="generate_family_agreement",
    summary=CAPABILITY_TITLES[ManaAICapability.FAMILY_AGREEMENT],
    description=describe(ManaAICapability.FAMILY_AGREEMENT),
    responses=COMMON_RESPONSES,
)
async def generate_family_agreement(
    payload: FamilyAgreementBody,
    service: ManaAIAnalysisServiceDep,
) -> FamilyAgreementResponse:
    return await _analyze_as(payload, service, FamilyAgreementResponse)


BehaviourAnomalyBody = Annotated[
    BehaviourAnomalyRequest,
    Body(openapi_examples=request_examples(ManaAICapability.BEHAVIOUR_ANOMALY)),
]


@router.post(
    capability_path(ManaAICapability.BEHAVIOUR_ANOMALY),
    response_model=BehaviourAnomalyResponse,
    operation_id="analyze_behaviour_anomaly",
    summary=CAPABILITY_TITLES[ManaAICapability.BEHAVIOUR_ANOMALY],
    description=describe(ManaAICapability.BEHAVIOUR_ANOMALY),
    responses=COMMON_RESPONSES,
)
async def analyze_behaviour_anomaly(
    payload: BehaviourAnomalyBody,
    service: ManaAIAnalysisServiceDep,
) -> BehaviourAnomalyResponse:
    return await _analyze_as(payload, service, BehaviourAnomalyResponse)
