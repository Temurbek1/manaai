from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.mana_operation_ai.domain.enums import (
    ActionStatus,
    ActionType,
    AgentRunStage,
    AgentRunStatus,
    AgentStatus,
    ApprovalStatus,
    AuditEventType,
    CapabilityRisk,
    DataAvailability,
    ExecutionStatus,
    FindingSeverity,
    GrowthActionType,
    IntegrationStatus,
    OutcomeEvaluationStatus,
    PolicyDecision,
    ProviderMode,
    TriggerType,
    UserRole,
    VerificationStatus,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CapabilityDefinition(DomainModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    agent_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    description: str = Field(min_length=1, max_length=500)
    risk: CapabilityRisk
    minimum_role: UserRole
    input_schema: dict[str, JsonValue] = Field(default_factory=dict)
    output_schema: dict[str, JsonValue] = Field(default_factory=dict)
    required_integrations: list[str] = Field(default_factory=list)
    supported_triggers: set[TriggerType] = Field(default_factory=set)


# Temporary source compatibility for modules that still import the old metadata name.
AgentCapability = CapabilityDefinition


class AgentDefinition(DomainModel):
    agent_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,79}$")
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1_000)
    version: str = Field(min_length=1, max_length=40)
    status: AgentStatus
    capabilities: list[CapabilityDefinition]
    default_capability_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    configuration_schema: dict[str, JsonValue]
    registered_at: datetime


class AgentRegistry(DomainModel):
    agents: list[AgentDefinition]
    generated_at: datetime


class AgentConfiguration(DomainModel):
    configuration_id: str
    agent_id: str
    capability_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    version: int = Field(ge=1)
    values: dict[str, JsonValue]
    created_at: datetime
    created_by: str
    active: bool = True


class AgentSchedule(DomainModel):
    schedule_id: str
    agent_id: str
    capability_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    job_type: str = Field(min_length=1, max_length=80)
    cron_expression: str = Field(min_length=5, max_length=120)
    timezone: str = Field(min_length=1, max_length=64)
    enabled: bool
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None


class AgentRun(DomainModel):
    run_id: str
    agent_id: str
    capability_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    correlation_id: str
    trigger: TriggerType
    initiated_by: str
    status: AgentRunStatus
    current_stage: AgentRunStage | None = None
    configuration_version: int
    idempotency_key: str
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int = Field(default=0, ge=0)


class AgentRunResult(DomainModel):
    run_id: str
    status: AgentRunStatus
    snapshot_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    recommendation_ids: list[str] = Field(default_factory=list)
    action_proposal_ids: list[str] = Field(default_factory=list)
    report_id: str | None = None
    completed_at: datetime | None = None


class Integration(DomainModel):
    integration_id: str
    provider: str
    display_name: str
    capabilities: list[str]
    secret_fields: list[str]


class IntegrationHealth(DomainModel):
    integration_id: str
    status: IntegrationStatus
    checked_at: datetime
    last_success_at: datetime | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    message: str | None = Field(default=None, max_length=500)
    provider_request_id: str | None = None
    diagnostics: dict[str, JsonValue] = Field(default_factory=dict)


class EvidenceRef(DomainModel):
    source: str = Field(min_length=1, max_length=120)
    subject_scope: str = Field(min_length=1, max_length=200)
    period_start: datetime
    period_end: datetime
    collected_at: datetime
    freshness_seconds: int = Field(ge=0)
    completeness: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    checksum: str = Field(min_length=1, max_length=128)
    privacy_classification: str = Field(min_length=1, max_length=80)


class DataSnapshot(DomainModel):
    snapshot_id: str
    run_id: str
    agent_id: str
    capability_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    provider: str
    schema_version: str
    period_start: datetime
    period_end: datetime
    collected_at: datetime
    checksum: str
    provider_request_ids: list[str]
    completeness: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    payload: dict[str, JsonValue]


class MetricValue(DomainModel):
    value: Decimal | None = None
    unit: str
    availability: DataAvailability
    reason: str | None = None

    @model_validator(mode="after")
    def validate_availability(self) -> "MetricValue":
        if self.availability is DataAvailability.AVAILABLE and self.value is None:
            raise ValueError("available metrics require a value")
        if self.availability is DataAvailability.UNAVAILABLE and self.value is not None:
            raise ValueError("unavailable metrics cannot have a value")
        return self


class Analysis(DomainModel):
    analysis_id: str
    run_id: str
    snapshot_id: str
    calculated_at: datetime
    metrics: dict[str, MetricValue]
    baseline_metrics: dict[str, MetricValue]
    data_quality_score: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    notes: list[str] = Field(default_factory=list)


class EvidenceMetric(DomainModel):
    name: str
    current: MetricValue
    baseline: MetricValue | None = None


class Finding(DomainModel):
    finding_id: str
    run_id: str
    analysis_id: str
    finding_type: str
    severity: FindingSeverity
    title: str
    description: str
    object_type: str | None = None
    provider_object_id: str | None = None
    dimensions: dict[str, str] = Field(default_factory=dict)
    evidence: list[EvidenceMetric]
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    source_snapshot_id: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    attribution_identity: str | None = None
    currency: str | None = None
    deterministic_calculation: str | None = None
    baseline_period_start: datetime | None = None
    baseline_period_end: datetime | None = None
    completeness: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    limitations: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    created_at: datetime


class BudgetActionParameters(DomainModel):
    kind: Literal[ActionType.INCREASE_BUDGET, ActionType.DECREASE_BUDGET]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    current_daily_budget: Decimal = Field(ge=Decimal("0"))
    proposed_daily_budget: Decimal = Field(gt=Decimal("0"))

    @model_validator(mode="after")
    def validate_direction(self) -> "BudgetActionParameters":
        change = self.proposed_daily_budget - self.current_daily_budget
        if self.kind is ActionType.INCREASE_BUDGET and change <= Decimal("0"):
            raise ValueError("increase_budget requires a positive budget change")
        if self.kind is ActionType.DECREASE_BUDGET and change >= Decimal("0"):
            raise ValueError("decrease_budget requires a negative budget change")
        return self


class StatusActionParameters(DomainModel):
    kind: Literal[ActionType.PAUSE, ActionType.RESUME]
    current_status: str
    proposed_status: str

    @model_validator(mode="after")
    def validate_status_change(self) -> "StatusActionParameters":
        required = "PAUSED" if self.kind is ActionType.PAUSE else "ACTIVE"
        if self.proposed_status.upper() != required:
            raise ValueError(f"{self.kind.value} requires proposed_status={required}")
        if self.current_status.upper() == required:
            raise ValueError("status action must change the current status")
        return self


class AudienceActionParameters(DomainModel):
    kind: Literal[ActionType.SCALE_AUDIENCE, ActionType.DISABLE_AUDIENCE]
    audience_id: str
    current_status: str
    proposed_status: str
    budget_change: BudgetActionParameters | None = None

    @model_validator(mode="after")
    def validate_audience_change(self) -> "AudienceActionParameters":
        required = "ACTIVE" if self.kind is ActionType.SCALE_AUDIENCE else "PAUSED"
        if self.proposed_status.upper() != required:
            raise ValueError(f"{self.kind.value} requires proposed_status={required}")
        if self.budget_change is not None and (
            self.kind is not ActionType.SCALE_AUDIENCE
            or self.budget_change.kind is not ActionType.INCREASE_BUDGET
        ):
            raise ValueError("Only scale_audience can carry an increase_budget change")
        return self


class NoChangeActionParameters(DomainModel):
    kind: Literal[ActionType.MAINTAIN, ActionType.OBSERVE]
    observation_until: datetime | None = None


class TestProposalParameters(DomainModel):
    kind: Literal[ActionType.PROPOSE_TEST]
    hypothesis: str = Field(min_length=1, max_length=1_000)
    test_type: str = Field(min_length=1, max_length=120)


class CreateExperimentActionParameters(DomainModel):
    kind: Literal[GrowthActionType.CREATE_EXPERIMENT]
    experiment_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    hypothesis: str = Field(min_length=1, max_length=1_000)
    primary_metric: str = Field(min_length=1, max_length=120)
    audience_segment: str = Field(min_length=1, max_length=120)
    allocation_percent: int = Field(ge=1, le=50)
    duration_days: int = Field(ge=1, le=90)
    proposed_status: Literal["DRAFT"] = "DRAFT"


class StopExperimentActionParameters(DomainModel):
    kind: Literal[GrowthActionType.STOP_EXPERIMENT]
    experiment_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    current_status: Literal["DRAFT", "RUNNING"]
    proposed_status: Literal["STOPPED"] = "STOPPED"


ActionParameters = Annotated[
    BudgetActionParameters
    | StatusActionParameters
    | AudienceActionParameters
    | NoChangeActionParameters
    | TestProposalParameters
    | CreateExperimentActionParameters
    | StopExperimentActionParameters,
    Field(discriminator="kind"),
]

OperationalActionType = ActionType | GrowthActionType


class Recommendation(DomainModel):
    recommendation_id: str
    run_id: str
    finding_ids: list[str]
    object_type: str
    provider_object_id: str
    capability_key: str = Field(default="growth.advertising")
    action_family: str = Field(default="advertising", min_length=1, max_length=80)
    action_type: OperationalActionType
    parameters: ActionParameters
    evidence: list[EvidenceMetric]
    reasoning: str
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    expected_effect: str
    risks: list[str]
    missing_data: list[str]
    expires_at: datetime
    created_at: datetime

    @model_validator(mode="after")
    def validate_action_parameters(self) -> "Recommendation":
        if self.parameters.kind is not self.action_type:
            raise ValueError("action_type must match typed parameters.kind")
        return self


class ActionPolicy(DomainModel):
    policy_id: str
    agent_id: str
    capability_key: str = Field(default="growth.advertising")
    action_family: str = Field(default="advertising", min_length=1, max_length=80)
    action_type: OperationalActionType
    decision: PolicyDecision
    reasons: list[str]
    checked_at: datetime
    configuration_version: int


class ActionPolicyConfiguration(DomainModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    minimum_confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    maximum_budget_increase_factor: Decimal = Field(ge=Decimal("1"))
    maximum_budget_decrease: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    maximum_absolute_daily_budget_change: Decimal = Field(ge=Decimal("0"))
    cooldown_hours: int = Field(ge=0)
    allowed_action_types: set[ActionType]
    approval_required: dict[ActionType, bool]
    allowed_currencies: set[str]
    minimum_daily_budget_by_currency: dict[str, Decimal]


class ActionProposal(DomainModel):
    proposal_id: str
    run_id: str
    recommendation_id: str
    agent_id: str
    capability_key: str = Field(default="growth.advertising")
    action_family: str = Field(default="advertising", min_length=1, max_length=80)
    provider: str
    provider_mode: ProviderMode = ProviderMode.FAKE_EXECUTABLE
    execution_forbidden: bool = False
    object_type: str
    provider_object_id: str
    action_type: OperationalActionType
    parameters: ActionParameters
    evidence: list[EvidenceMetric]
    reasoning: str
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    expected_effect: str
    risks: list[str]
    missing_data: list[str]
    manual_action_instructions: list[str] = Field(default_factory=list)
    policy: ActionPolicy
    status: ActionStatus
    idempotency_key: str
    current_state_hash: str
    expires_at: datetime
    created_at: datetime

    @model_validator(mode="after")
    def validate_action_parameters(self) -> "ActionProposal":
        if self.parameters.kind is not self.action_type:
            raise ValueError("action_type must match typed parameters.kind")
        if self.provider_mode is ProviderMode.LIVE_READ_ONLY and not self.execution_forbidden:
            raise ValueError("live_read_only proposals must forbid execution")
        return self


class ApprovalRequest(DomainModel):
    approval_id: str
    proposal_id: str
    requested_at: datetime
    expires_at: datetime
    requested_by: str
    required_role: UserRole
    status: ApprovalStatus


class ApprovalDecision(DomainModel):
    approval_id: str
    proposal_id: str
    status: ApprovalStatus
    decided_at: datetime
    decided_by: str
    reason: str


class ActionExecution(DomainModel):
    execution_id: str
    proposal_id: str
    run_id: str
    idempotency_key: str
    status: ExecutionStatus
    attempted_at: datetime
    completed_at: datetime | None = None
    provider_request_id: str | None = None
    before_state: dict[str, JsonValue]
    requested_change: dict[str, JsonValue]
    provider_response: dict[str, JsonValue]
    error_code: str | None = None
    error_message: str | None = None


class ActionVerification(DomainModel):
    verification_id: str
    execution_id: str
    status: VerificationStatus
    checked_at: datetime
    expected_state: dict[str, JsonValue]
    observed_state: dict[str, JsonValue]
    differences: list[str]


class AgentReport(DomainModel):
    report_id: str
    agent_id: str
    capability_key: str = Field(default="growth.advertising")
    run_id: str
    report_type: str
    period_start: datetime
    period_end: datetime
    structured: dict[str, JsonValue]
    human_readable: str
    data_quality_notes: list[str]
    created_at: datetime


class AuditEvent(DomainModel):
    event_id: str
    correlation_id: str
    agent_id: str | None = None
    capability_key: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_.-]{1,79}$",
    )
    run_id: str | None = None
    event_type: AuditEventType
    actor_id: str
    actor_role: UserRole
    occurred_at: datetime
    summary: str
    details: dict[str, JsonValue]


class OutcomeEvaluation(DomainModel):
    evaluation_id: str
    run_id: str
    proposal_id: str | None = None
    agent_id: str
    capability_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,79}$")
    metric_name: str = Field(min_length=1, max_length=120)
    baseline_value: Decimal | None = None
    observed_value: Decimal | None = None
    target_value: Decimal | None = None
    status: OutcomeEvaluationStatus
    attribution_limitations: list[str] = Field(default_factory=list)
    measurement_due_at: datetime | None = None
    evaluated_at: datetime
