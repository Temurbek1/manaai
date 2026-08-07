from typing import ClassVar, Literal, Self

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.mana_ai.domain.enums import ActionKind, AgreementMode, ManaAICapability
from app.mana_ai.domain.signals import (
    AppLimit,
    AppUsageSignal,
    BatterySignal,
    ExtraTimeRequest,
    FamilyPreferences,
    FamilyRule,
    Geofence,
    LocationPoint,
    MetricComparison,
    NotificationActivity,
    NotificationPreviewSignal,
    ProtectionStateSignal,
    ResourceSignal,
    RouteContext,
    SafetyEventSignal,
    ScheduleWindow,
    StrictModel,
    SubjectContext,
    UsageBaseline,
    WebsiteActivitySignal,
)

ParentCopilotAllowedActionKind = Literal[
    ActionKind.PROPOSE_LIMIT_CHANGE,
    ActionKind.PROPOSE_STUDY_MODE,
    ActionKind.PROPOSE_GEOFENCE,
    ActionKind.PROPOSE_APP_RESTRICTION,
    ActionKind.PROPOSE_TEMPORARY_ACCESS,
    ActionKind.GENERATE_FAMILY_REPORT,
]


class SafetyMonitorInput(StrictModel):
    capability: ClassVar[ManaAICapability] = ManaAICapability.SAFETY_MONITOR
    notifications: list[NotificationPreviewSignal] = Field(default_factory=list, max_length=100)
    resources: list[ResourceSignal] = Field(default_factory=list, max_length=100)
    websites: list[WebsiteActivitySignal] = Field(default_factory=list, max_length=500)
    app_usage: list[AppUsageSignal] = Field(default_factory=list, max_length=500)
    locations: list[LocationPoint] = Field(default_factory=list, max_length=2_000)
    battery: list[BatterySignal] = Field(default_factory=list, max_length=500)
    protection_state: ProtectionStateSignal | None = None

    @model_validator(mode="after")
    def require_signal(self) -> "SafetyMonitorInput":
        if not any(
            (
                self.notifications,
                self.resources,
                self.websites,
                self.app_usage,
                self.locations,
                self.battery,
                self.protection_state,
            )
        ):
            raise ValueError("At least one safety signal is required")
        return self


class FamilyDigestInput(StrictModel):
    capability: ClassVar[ManaAICapability] = ManaAICapability.FAMILY_DIGEST
    period_start: AwareDatetime
    period_end: AwareDatetime
    app_usage: list[AppUsageSignal] = Field(default_factory=list, max_length=2_000)
    usage_baselines: list[UsageBaseline] = Field(default_factory=list, max_length=500)
    notification_activity: list[NotificationActivity] = Field(default_factory=list, max_length=500)
    websites: list[WebsiteActivitySignal] = Field(default_factory=list, max_length=2_000)
    metrics: list[MetricComparison] = Field(default_factory=list, max_length=500)
    locations: list[LocationPoint] = Field(default_factory=list, max_length=5_000)
    battery: list[BatterySignal] = Field(default_factory=list, max_length=2_000)
    protection_state: ProtectionStateSignal | None = None
    safety_events: list[SafetyEventSignal] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_period(self) -> "FamilyDigestInput":
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be later than period_start")
        return self


class AdaptiveScreenTimeInput(StrictModel):
    capability: ClassVar[ManaAICapability] = ManaAICapability.ADAPTIVE_SCREEN_TIME
    app_usage: list[AppUsageSignal] = Field(min_length=1, max_length=2_000)
    usage_baselines: list[UsageBaseline] = Field(default_factory=list, max_length=500)
    schedules: list[ScheduleWindow] = Field(default_factory=list, max_length=100)
    limits: list[AppLimit] = Field(default_factory=list, max_length=500)
    extra_time_requests: list[ExtraTimeRequest] = Field(default_factory=list, max_length=500)
    family_rules: list[FamilyRule] = Field(default_factory=list, max_length=200)


class LocationIntelligenceInput(StrictModel):
    capability: ClassVar[ManaAICapability] = ManaAICapability.LOCATION_INTELLIGENCE
    points: list[LocationPoint] = Field(min_length=1, max_length=5_000)
    geofences: list[Geofence] = Field(default_factory=list, max_length=200)
    route: RouteContext | None = None
    battery: list[BatterySignal] = Field(default_factory=list, max_length=1_000)


class SmartContentFilterInput(StrictModel):
    capability: ClassVar[ManaAICapability] = ManaAICapability.SMART_CONTENT_FILTER
    resource: ResourceSignal
    notification_context: NotificationPreviewSignal | None = None
    blocked_categories: list[str] = Field(default_factory=list, max_length=100)
    family_rules: list[FamilyRule] = Field(default_factory=list, max_length=200)


class ScamPrivacyShieldInput(StrictModel):
    capability: ClassVar[ManaAICapability] = ManaAICapability.SCAM_PRIVACY_SHIELD
    notifications: list[NotificationPreviewSignal] = Field(default_factory=list, max_length=100)
    resources: list[ResourceSignal] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def require_signal(self) -> "ScamPrivacyShieldInput":
        if not self.notifications and not self.resources:
            raise ValueError("At least one notification or resource is required")
        return self


class AIGamingSafetyInput(StrictModel):
    capability: ClassVar[ManaAICapability] = ManaAICapability.AI_GAMING_SAFETY
    app_usage: list[AppUsageSignal] = Field(min_length=1, max_length=2_000)
    usage_baselines: list[UsageBaseline] = Field(default_factory=list, max_length=500)
    limits: list[AppLimit] = Field(default_factory=list, max_length=500)
    schedules: list[ScheduleWindow] = Field(default_factory=list, max_length=100)
    extra_time_requests: list[ExtraTimeRequest] = Field(default_factory=list, max_length=500)


class ParentCopilotInput(StrictModel):
    capability: ClassVar[ManaAICapability] = ManaAICapability.PARENT_COPILOT
    message: str = Field(min_length=1, max_length=4_000)
    safety_events: list[SafetyEventSignal] = Field(default_factory=list, max_length=200)
    family_rules: list[FamilyRule] = Field(default_factory=list, max_length=200)
    app_usage: list[AppUsageSignal] = Field(default_factory=list, max_length=500)
    locations: list[LocationPoint] = Field(default_factory=list, max_length=500)
    allowed_action_kinds: list[ParentCopilotAllowedActionKind] = Field(
        default_factory=list,
        max_length=6,
    )


class ChildSafetyAssistantInput(StrictModel):
    capability: ClassVar[ManaAICapability] = ManaAICapability.CHILD_SAFETY_ASSISTANT
    message: str = Field(min_length=1, max_length=4_000)
    current_resource: ResourceSignal | None = None
    active_rules: list[FamilyRule] = Field(default_factory=list, max_length=200)
    current_usage: AppUsageSignal | None = None


class FamilyAgreementInput(StrictModel):
    capability: ClassVar[ManaAICapability] = ManaAICapability.FAMILY_AGREEMENT
    mode: AgreementMode
    preferences: FamilyPreferences
    current_rules: list[FamilyRule] = Field(default_factory=list, max_length=200)
    child_request: ExtraTimeRequest | None = None

    @model_validator(mode="after")
    def validate_mode_payload(self) -> "FamilyAgreementInput":
        if self.mode is AgreementMode.CHILD_REQUEST and self.child_request is None:
            raise ValueError("child_request is required in child_request mode")
        return self


class BehaviourAnomalyInput(StrictModel):
    capability: ClassVar[ManaAICapability] = ManaAICapability.BEHAVIOUR_ANOMALY
    metrics: list[MetricComparison] = Field(default_factory=list, max_length=500)
    protection_state: ProtectionStateSignal | None = None
    app_usage: list[AppUsageSignal] = Field(default_factory=list, max_length=2_000)
    usage_baselines: list[UsageBaseline] = Field(default_factory=list, max_length=500)
    locations: list[LocationPoint] = Field(default_factory=list, max_length=2_000)
    battery: list[BatterySignal] = Field(default_factory=list, max_length=1_000)

    @model_validator(mode="after")
    def require_signal(self) -> "BehaviourAnomalyInput":
        if not any(
            (
                self.metrics,
                self.protection_state,
                self.app_usage,
                self.locations,
                self.battery,
            )
        ):
            raise ValueError("At least one behavioral signal is required")
        return self


CapabilityInput = (
    SafetyMonitorInput
    | FamilyDigestInput
    | AdaptiveScreenTimeInput
    | LocationIntelligenceInput
    | SmartContentFilterInput
    | ScamPrivacyShieldInput
    | AIGamingSafetyInput
    | ParentCopilotInput
    | ChildSafetyAssistantInput
    | FamilyAgreementInput
    | BehaviourAnomalyInput
)


class ManaAIRequestBase[InputT: StrictModel](StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    occurred_at: AwareDatetime
    locale: str = Field(default="ru", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    subject: SubjectContext
    input: InputT
    data_minimized: Literal[True] = Field(
        description="Confirms that the application minimized sensitive content before submission."
    )

    @model_validator(mode="after")
    def require_unique_evidence_ids(self) -> Self:
        evidence_ids = _collect_evidence_ids(self.input)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence_id values must be unique within a request")
        return self


class SafetyMonitorRequest(ManaAIRequestBase[SafetyMonitorInput]):
    pass


class FamilyDigestRequest(ManaAIRequestBase[FamilyDigestInput]):
    pass


class AdaptiveScreenTimeRequest(ManaAIRequestBase[AdaptiveScreenTimeInput]):
    pass


class LocationIntelligenceRequest(ManaAIRequestBase[LocationIntelligenceInput]):
    pass


class SmartContentFilterRequest(ManaAIRequestBase[SmartContentFilterInput]):
    pass


class ScamPrivacyShieldRequest(ManaAIRequestBase[ScamPrivacyShieldInput]):
    pass


class AIGamingSafetyRequest(ManaAIRequestBase[AIGamingSafetyInput]):
    pass


class ParentCopilotRequest(ManaAIRequestBase[ParentCopilotInput]):
    pass


class ChildSafetyAssistantRequest(ManaAIRequestBase[ChildSafetyAssistantInput]):
    pass


class FamilyAgreementRequest(ManaAIRequestBase[FamilyAgreementInput]):
    pass


class BehaviourAnomalyRequest(ManaAIRequestBase[BehaviourAnomalyInput]):
    pass


ManaAIRequest = (
    SafetyMonitorRequest
    | FamilyDigestRequest
    | AdaptiveScreenTimeRequest
    | LocationIntelligenceRequest
    | SmartContentFilterRequest
    | ScamPrivacyShieldRequest
    | AIGamingSafetyRequest
    | ParentCopilotRequest
    | ChildSafetyAssistantRequest
    | FamilyAgreementRequest
    | BehaviourAnomalyRequest
)


def _collect_evidence_ids(value: object) -> list[str]:
    if isinstance(value, BaseModel):
        result: list[str] = []
        evidence_id = getattr(value, "evidence_id", None)
        if isinstance(evidence_id, str):
            result.append(evidence_id)
        for field_name in type(value).model_fields:
            result.extend(_collect_evidence_ids(getattr(value, field_name)))
        return result
    if isinstance(value, list | tuple):
        return [evidence_id for item in value for evidence_id in _collect_evidence_ids(item)]
    return []
