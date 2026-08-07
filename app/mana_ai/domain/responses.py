from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from app.mana_ai.domain.enums import (
    ActionKind,
    AnalysisStatus,
    AnalysisVerdict,
    AppCategory,
    CheckStatus,
    ExecutionPolicy,
    FindingCategory,
    ManaAICapability,
    ReputationVerdict,
    RiskLevel,
)
from app.mana_ai.domain.signals import StrictModel


class FindingDraft(StrictModel):
    category: FindingCategory
    risk_level: RiskLevel
    confidence: int = Field(ge=0, le=100)
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(
        min_length=1,
        max_length=700,
        description="Minimized context; must not reproduce full private content.",
    )
    evidence_ids: list[str] = Field(min_length=1, max_length=50)
    recommendation: str = Field(min_length=1, max_length=700)


class CheckResult(StrictModel):
    category: FindingCategory
    status: CheckStatus
    explanation: str = Field(min_length=1, max_length=400)


class NotifyParentAction(StrictModel):
    kind: Literal[ActionKind.NOTIFY_PARENT]
    urgency: RiskLevel
    message: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)


class WarnChildAction(StrictModel):
    kind: Literal[ActionKind.WARN_CHILD]
    message: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)


class RequestCheckInAction(StrictModel):
    kind: Literal[ActionKind.REQUEST_CHECK_IN]
    reason: str = Field(min_length=1, max_length=500)


class LimitChangeAction(StrictModel):
    kind: Literal[ActionKind.PROPOSE_LIMIT_CHANGE]
    target_kind: Literal["application", "category"]
    target: str = Field(min_length=1, max_length=255)
    proposed_daily_limit_minutes: int = Field(ge=1, le=1_440)
    rationale: str = Field(min_length=1, max_length=500)


class StudyModeAction(StrictModel):
    kind: Literal[ActionKind.PROPOSE_STUDY_MODE]
    enabled: bool
    duration_minutes: int = Field(ge=1, le=1_440)
    rationale: str = Field(min_length=1, max_length=500)


class GeofenceAction(StrictModel):
    kind: Literal[ActionKind.PROPOSE_GEOFENCE]
    label: str = Field(min_length=1, max_length=80)
    center_evidence_id: str = Field(
        min_length=1,
        max_length=128,
        description="Location evidence ID resolved to coordinates by the application.",
    )
    radius_meters: int = Field(ge=25, le=50_000)
    rationale: str = Field(min_length=1, max_length=500)


class AppRestrictionAction(StrictModel):
    kind: Literal[ActionKind.PROPOSE_APP_RESTRICTION]
    package_name: str = Field(min_length=1, max_length=255)
    mode: Literal["warn", "limit", "block"]
    duration_minutes: int | None = Field(default=None, ge=1, le=43_200)
    rationale: str = Field(min_length=1, max_length=500)


class TemporaryAccessAction(StrictModel):
    kind: Literal[ActionKind.PROPOSE_TEMPORARY_ACCESS]
    package_name: str = Field(min_length=1, max_length=255)
    duration_minutes: int = Field(ge=1, le=1_440)
    rationale: str = Field(min_length=1, max_length=500)


class FamilyReportAction(StrictModel):
    kind: Literal[ActionKind.GENERATE_FAMILY_REPORT]
    period: Literal["daily", "weekly"]


class ResourceBlockAction(StrictModel):
    kind: Literal[ActionKind.PROPOSE_RESOURCE_BLOCK]
    resource_evidence_id: str = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=1, max_length=500)


class ContactParentAction(StrictModel):
    kind: Literal[ActionKind.CONTACT_PARENT]
    reason: str = Field(min_length=1, max_length=500)


class SubmitExtraTimeRequestAction(StrictModel):
    kind: Literal[ActionKind.SUBMIT_EXTRA_TIME_REQUEST]
    package_name: str = Field(min_length=1, max_length=255)
    requested_minutes: int = Field(ge=1, le=1_440)
    reason: str = Field(min_length=1, max_length=500)


class SubmitIncidentReportAction(StrictModel):
    kind: Literal[ActionKind.SUBMIT_INCIDENT_REPORT]
    summary: str = Field(min_length=1, max_length=700)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)


class AgreementUpdateAction(StrictModel):
    kind: Literal[ActionKind.PROPOSE_AGREEMENT_UPDATE]
    proposed_changes: list[str] = Field(min_length=1, max_length=30)
    rationale: str = Field(min_length=1, max_length=500)


ActionValue = (
    NotifyParentAction
    | WarnChildAction
    | RequestCheckInAction
    | LimitChangeAction
    | StudyModeAction
    | GeofenceAction
    | AppRestrictionAction
    | TemporaryAccessAction
    | FamilyReportAction
    | ResourceBlockAction
    | ContactParentAction
    | SubmitExtraTimeRequestAction
    | SubmitIncidentReportAction
    | AgreementUpdateAction
)

Action = Annotated[
    ActionValue,
    Field(discriminator="kind"),
]

SafetyMonitorAction = Annotated[
    NotifyParentAction
    | WarnChildAction
    | RequestCheckInAction
    | ResourceBlockAction
    | ContactParentAction
    | SubmitIncidentReportAction,
    Field(discriminator="kind"),
]
FamilyDigestAction = Annotated[
    NotifyParentAction | RequestCheckInAction | FamilyReportAction,
    Field(discriminator="kind"),
]
AdaptiveScreenTimeAction = Annotated[
    NotifyParentAction
    | WarnChildAction
    | LimitChangeAction
    | StudyModeAction
    | AppRestrictionAction
    | TemporaryAccessAction,
    Field(discriminator="kind"),
]
LocationIntelligenceAction = Annotated[
    NotifyParentAction | RequestCheckInAction | GeofenceAction,
    Field(discriminator="kind"),
]
SmartContentFilterAction = Annotated[
    NotifyParentAction | WarnChildAction | ResourceBlockAction,
    Field(discriminator="kind"),
]
ScamPrivacyShieldAction = Annotated[
    NotifyParentAction
    | WarnChildAction
    | ResourceBlockAction
    | ContactParentAction
    | SubmitIncidentReportAction,
    Field(discriminator="kind"),
]
AIGamingSafetyAction = Annotated[
    NotifyParentAction | WarnChildAction | LimitChangeAction | AppRestrictionAction,
    Field(discriminator="kind"),
]
ParentCopilotAction = Annotated[
    LimitChangeAction
    | StudyModeAction
    | GeofenceAction
    | AppRestrictionAction
    | TemporaryAccessAction
    | FamilyReportAction,
    Field(discriminator="kind"),
]
ChildSafetyAssistantAction = Annotated[
    WarnChildAction
    | ContactParentAction
    | SubmitExtraTimeRequestAction
    | SubmitIncidentReportAction,
    Field(discriminator="kind"),
]
FamilyAgreementAction = Annotated[
    AgreementUpdateAction | SubmitExtraTimeRequestAction,
    Field(discriminator="kind"),
]
BehaviourAnomalyAction = Annotated[
    NotifyParentAction | WarnChildAction | RequestCheckInAction,
    Field(discriminator="kind"),
]


class AppClassification(StrictModel):
    package_name: str = Field(min_length=1, max_length=255)
    category: AppCategory
    explanation: str = Field(min_length=1, max_length=400)


class ProposedFamilyRule(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1_000)
    requires_parent_confirmation: bool = True


class SafetyMonitorDetails(StrictModel):
    parent_context: str = Field(min_length=1, max_length=700)
    significant_event_count: int = Field(ge=0, le=100)
    all_clear_categories: list[FindingCategory] = Field(default_factory=list, max_length=50)


class FamilyDigestDetails(StrictModel):
    period_summary: str = Field(min_length=1, max_length=1_000)
    highlights: list[str] = Field(default_factory=list, max_length=30)
    positive_changes: list[str] = Field(default_factory=list, max_length=30)
    minor_anomalies: list[str] = Field(default_factory=list, max_length=30)


class AdaptiveScreenTimeDetails(StrictModel):
    app_classifications: list[AppClassification] = Field(default_factory=list, max_length=500)
    limit_assessment: list[str] = Field(default_factory=list, max_length=100)


class LocationIntelligenceDetails(StrictModel):
    route_status: Literal["usual", "deviated", "delayed", "unknown"]
    estimated_arrival_at: AwareDatetime | None = None
    eta_confidence: int | None = Field(default=None, ge=0, le=100)
    explanation: str = Field(min_length=1, max_length=700)


class SmartContentFilterDetails(StrictModel):
    decision: Literal["allow", "observe", "warn", "block"]
    category: str | None = Field(default=None, min_length=1, max_length=80)
    reputation: ReputationVerdict
    explanation: str = Field(min_length=1, max_length=700)


class ScamPrivacyShieldDetails(StrictModel):
    detected_patterns: list[str] = Field(default_factory=list, max_length=30)
    requested_data_types: list[str] = Field(default_factory=list, max_length=30)
    explanation: str = Field(min_length=1, max_length=700)


class AIGamingSafetyDetails(StrictModel):
    ai_service_summary: str = Field(min_length=1, max_length=700)
    gaming_summary: str = Field(min_length=1, max_length=700)
    affected_packages: list[str] = Field(default_factory=list, max_length=500)


class ParentCopilotDetails(StrictModel):
    answer: str = Field(min_length=1, max_length=2_000)
    suggested_sequence: list[str] = Field(default_factory=list, max_length=20)


class ChildSafetyAssistantDetails(StrictModel):
    answer: str = Field(min_length=1, max_length=1_500)
    explanation: str = Field(min_length=1, max_length=700)
    should_contact_parent: bool


class FamilyAgreementDetails(StrictModel):
    draft_rules: list[ProposedFamilyRule] = Field(default_factory=list, max_length=100)
    request_context: str | None = Field(default=None, max_length=700)


class BehaviourAnomalyDetails(StrictModel):
    changed_metrics: list[str] = Field(default_factory=list, max_length=100)
    explanation: str = Field(min_length=1, max_length=700)
    diagnosis_made: Literal[False] = False


CapabilityDetailsValue = (
    SafetyMonitorDetails
    | FamilyDigestDetails
    | AdaptiveScreenTimeDetails
    | LocationIntelligenceDetails
    | SmartContentFilterDetails
    | ScamPrivacyShieldDetails
    | AIGamingSafetyDetails
    | ParentCopilotDetails
    | ChildSafetyAssistantDetails
    | FamilyAgreementDetails
    | BehaviourAnomalyDetails
)


class ModelAnalysis(StrictModel):
    verdict: AnalysisVerdict
    summary: str = Field(min_length=1, max_length=1_500)
    details: CapabilityDetailsValue
    findings: list[FindingDraft] = Field(default_factory=list, max_length=100)
    checks: list[CheckResult] = Field(default_factory=list, max_length=100)
    proposed_actions: list[ActionValue] = Field(default_factory=list, max_length=30)
    data_quality_notes: list[str] = Field(default_factory=list, max_length=30)


class ManaAIFinding(FindingDraft):
    finding_id: str = Field(min_length=1, max_length=160)


class ManaAIActionProposal(StrictModel):
    proposal_id: str = Field(min_length=1, max_length=160)
    action: Action
    execution_policy: ExecutionPolicy
    requires_parent_confirmation: bool
    proposal_only: Literal[True] = True
    executed: Literal[False] = False


class SafetyMonitorActionProposal(ManaAIActionProposal):
    action: SafetyMonitorAction


class FamilyDigestActionProposal(ManaAIActionProposal):
    action: FamilyDigestAction


class AdaptiveScreenTimeActionProposal(ManaAIActionProposal):
    action: AdaptiveScreenTimeAction


class LocationIntelligenceActionProposal(ManaAIActionProposal):
    action: LocationIntelligenceAction


class SmartContentFilterActionProposal(ManaAIActionProposal):
    action: SmartContentFilterAction


class ScamPrivacyShieldActionProposal(ManaAIActionProposal):
    action: ScamPrivacyShieldAction


class AIGamingSafetyActionProposal(ManaAIActionProposal):
    action: AIGamingSafetyAction


class ParentCopilotActionProposal(ManaAIActionProposal):
    action: ParentCopilotAction


class ChildSafetyAssistantActionProposal(ManaAIActionProposal):
    action: ChildSafetyAssistantAction


class FamilyAgreementActionProposal(ManaAIActionProposal):
    action: FamilyAgreementAction


class BehaviourAnomalyActionProposal(ManaAIActionProposal):
    action: BehaviourAnomalyAction


class PrivacyGuarantees(StrictModel):
    application_data_mutated: Literal[False] = False
    raw_input_returned: Literal[False] = False
    provider_store_disabled: Literal[True] = True


class ManaAIResponseBase(StrictModel):
    request_id: str
    processed_at: AwareDatetime
    status: AnalysisStatus
    verdict: AnalysisVerdict
    summary: str
    findings: list[ManaAIFinding]
    checks: list[CheckResult]
    data_quality_notes: list[str]
    model_name: str
    read_only: Literal[True] = True
    privacy: PrivacyGuarantees = Field(default_factory=PrivacyGuarantees)


class ManaAIAnalysisResult(ManaAIResponseBase):
    capability: ManaAICapability
    details: CapabilityDetailsValue
    proposed_actions: list[ManaAIActionProposal]


class SafetyMonitorResponse(ManaAIResponseBase):
    capability: Literal[ManaAICapability.SAFETY_MONITOR]
    details: SafetyMonitorDetails
    proposed_actions: list[SafetyMonitorActionProposal]


class FamilyDigestResponse(ManaAIResponseBase):
    capability: Literal[ManaAICapability.FAMILY_DIGEST]
    details: FamilyDigestDetails
    proposed_actions: list[FamilyDigestActionProposal]


class AdaptiveScreenTimeResponse(ManaAIResponseBase):
    capability: Literal[ManaAICapability.ADAPTIVE_SCREEN_TIME]
    details: AdaptiveScreenTimeDetails
    proposed_actions: list[AdaptiveScreenTimeActionProposal]


class LocationIntelligenceResponse(ManaAIResponseBase):
    capability: Literal[ManaAICapability.LOCATION_INTELLIGENCE]
    details: LocationIntelligenceDetails
    proposed_actions: list[LocationIntelligenceActionProposal]


class SmartContentFilterResponse(ManaAIResponseBase):
    capability: Literal[ManaAICapability.SMART_CONTENT_FILTER]
    details: SmartContentFilterDetails
    proposed_actions: list[SmartContentFilterActionProposal]


class ScamPrivacyShieldResponse(ManaAIResponseBase):
    capability: Literal[ManaAICapability.SCAM_PRIVACY_SHIELD]
    details: ScamPrivacyShieldDetails
    proposed_actions: list[ScamPrivacyShieldActionProposal]


class AIGamingSafetyResponse(ManaAIResponseBase):
    capability: Literal[ManaAICapability.AI_GAMING_SAFETY]
    details: AIGamingSafetyDetails
    proposed_actions: list[AIGamingSafetyActionProposal]


class ParentCopilotResponse(ManaAIResponseBase):
    capability: Literal[ManaAICapability.PARENT_COPILOT]
    details: ParentCopilotDetails
    proposed_actions: list[ParentCopilotActionProposal]


class ChildSafetyAssistantResponse(ManaAIResponseBase):
    capability: Literal[ManaAICapability.CHILD_SAFETY_ASSISTANT]
    details: ChildSafetyAssistantDetails
    proposed_actions: list[ChildSafetyAssistantActionProposal]


class FamilyAgreementResponse(ManaAIResponseBase):
    capability: Literal[ManaAICapability.FAMILY_AGREEMENT]
    details: FamilyAgreementDetails
    proposed_actions: list[FamilyAgreementActionProposal]


class BehaviourAnomalyResponse(ManaAIResponseBase):
    capability: Literal[ManaAICapability.BEHAVIOUR_ANOMALY]
    details: BehaviourAnomalyDetails
    proposed_actions: list[BehaviourAnomalyActionProposal]


ManaAIResponse = (
    SafetyMonitorResponse
    | FamilyDigestResponse
    | AdaptiveScreenTimeResponse
    | LocationIntelligenceResponse
    | SmartContentFilterResponse
    | ScamPrivacyShieldResponse
    | AIGamingSafetyResponse
    | ParentCopilotResponse
    | ChildSafetyAssistantResponse
    | FamilyAgreementResponse
    | BehaviourAnomalyResponse
)


class ManaAICapabilityInfo(StrictModel):
    capability: ManaAICapability
    method: Literal["POST"] = "POST"
    path: str = Field(pattern=r"^/api/v1/mana-ai/[a-z-]+$")
    status: Literal["implemented"] = "implemented"
    request_response_only: Literal[True] = True
    mutates_application_data: Literal[False] = False


class ManaAICapabilitiesResponse(StrictModel):
    bounded_context: Literal["mana_ai"] = "mana_ai"
    capabilities: list[ManaAICapabilityInfo]
