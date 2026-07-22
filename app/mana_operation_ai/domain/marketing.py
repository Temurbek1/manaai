from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.mana_operation_ai.domain.enums import ActionType, DataAvailability, ProviderMode
from app.mana_operation_ai.domain.models import (
    ActionPolicyConfiguration,
    AgentConfiguration,
    AgentSchedule,
    IntegrationHealth,
)


class MarketingDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class MarketingObjective(StrEnum):
    LEADS = "leads"
    PURCHASES = "purchases"
    CONVERSIONS = "conversions"
    CUSTOM = "custom"


class AdEntityType(StrEnum):
    ACCOUNT = "account"
    CAMPAIGN = "campaign"
    AD_SET = "ad_set"
    AD = "ad"
    CREATIVE = "creative"
    AUDIENCE = "audience"


class Breakdown(StrEnum):
    PLACEMENT = "placement"
    REGION = "region"
    AGE = "age"
    GENDER = "gender"
    HOUR = "hour"
    DAY = "day"


class CompatibilityStatus(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    PERMISSION_DENIED = "permission_denied"
    UNAVAILABLE = "unavailable"
    EMPTY = "empty"
    DELAYED = "delayed"
    PARTIAL = "partial"
    RATE_LIMITED = "rate_limited"
    INVALID_COMBINATION = "invalid_combination"


class Metric(MarketingDomainModel):
    value: Decimal | None
    availability: DataAvailability
    reason: str | None = None

    @model_validator(mode="after")
    def validate_availability(self) -> "Metric":
        if self.availability is DataAvailability.AVAILABLE and self.value is None:
            raise ValueError("available metric requires a value")
        if self.availability is DataAvailability.UNAVAILABLE and self.value is not None:
            raise ValueError("unavailable metric cannot carry a value")
        return self


class PerformanceMetrics(MarketingDomainModel):
    spend: Metric
    impressions: Metric
    reach: Metric
    clicks: Metric
    link_clicks: Metric
    conversions: Metric
    leads: Metric
    revenue: Metric
    ctr: Metric
    cpc: Metric
    cpm: Metric
    cpl: Metric
    cpa: Metric
    roas: Metric
    frequency: Metric


class AdAccount(MarketingDomainModel):
    provider_id: str
    name: str
    currency: str | None
    minimum_daily_budget: Decimal | None = Field(default=None, ge=Decimal("0"))
    timezone: str
    status: str


class AdEntity(MarketingDomainModel):
    provider_id: str
    entity_type: AdEntityType
    account_id: str
    parent_id: str | None = None
    name: str
    status: str
    effective_status: str
    daily_budget: Decimal | None = Field(default=None, ge=Decimal("0"))
    lifetime_budget: Decimal | None = Field(default=None, ge=Decimal("0"))
    currency: str | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    updated_at: datetime | None = None


class Creative(MarketingDomainModel):
    provider_id: str
    account_id: str
    name: str
    title: str | None = None
    body: str | None = None
    format: str | None = None
    preview_url: str | None = None


class Audience(MarketingDomainModel):
    provider_id: str
    account_id: str
    name: str
    subtype: str
    status: str
    targeting_attributes: dict[str, JsonValue] = Field(default_factory=dict)


class InsightRow(MarketingDomainModel):
    row_id: str
    account_id: str
    entity_type: AdEntityType
    entity_id: str
    entity_name: str
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    attribution_window: str = Field(min_length=1, max_length=64)
    campaign_id: str | None = None
    ad_set_id: str | None = None
    ad_id: str | None = None
    creative_id: str | None = None
    audience_id: str | None = None
    date_start: date
    date_stop: date
    dimensions: dict[str, str] = Field(default_factory=dict)
    metrics: PerformanceMetrics


class ProviderDiagnostic(MarketingDomainModel):
    request_id: str | None = None
    operation: str
    status_code: int | None = None
    retry_count: int = Field(default=0, ge=0)
    rate_limit_observed: bool = False
    rate_limit_usage_percent: int | None = Field(default=None, ge=0)
    retry_after_seconds: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    message: str | None = None


class ProviderRequestBudget(MarketingDomainModel):
    correlation_id: str
    max_requests: int = Field(ge=1)
    max_duration_seconds: int = Field(ge=1)
    max_total_retries: int = Field(ge=0)
    max_pages: int = Field(ge=1)
    requests_used: int = Field(ge=0)
    retries_used: int = Field(ge=0)
    pages_fetched: int = Field(ge=0)
    rows_received: int = Field(ge=0)
    duplicate_rows_rejected: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0)
    cancelled: bool = False
    run_id: str | None = None


class ProviderCompatibilityCheck(MarketingDomainModel):
    operation: str
    level: str | None = None
    breakdowns: list[str] = Field(default_factory=list)
    status: CompatibilityStatus
    row_count: int = Field(default=0, ge=0)
    reason_code: str | None = None


class ProviderObservability(MarketingDomainModel):
    request_count: int = Field(default=0, ge=0)
    successful_requests: int = Field(default=0, ge=0)
    transient_errors: int = Field(default=0, ge=0)
    permanent_errors: int = Field(default=0, ge=0)
    rate_limit_events: int = Field(default=0, ge=0)
    permission_errors: int = Field(default=0, ge=0)
    token_errors: int = Field(default=0, ge=0)
    request_duration_ms: int = Field(default=0, ge=0)
    pages_fetched: int = Field(default=0, ge=0)
    rows_normalized: int = Field(default=0, ge=0)
    duplicate_rows_rejected: int = Field(default=0, ge=0)
    unavailable_metrics: int = Field(default=0, ge=0)
    data_freshness_days: int | None = Field(default=None, ge=0)


class AdsSnapshot(MarketingDomainModel):
    provider: str
    provider_mode: ProviderMode = ProviderMode.FAKE_EXECUTABLE
    api_version: str | None = None
    schema_version: str = "1"
    collected_at: datetime
    period_start: datetime
    period_end: datetime
    attribution_window: str = Field(min_length=1, max_length=64)
    accounts: list[AdAccount]
    campaigns: list[AdEntity]
    ad_sets: list[AdEntity]
    ads: list[AdEntity]
    creatives: list[Creative]
    audiences: list[Audience]
    available_targeting_attributes: dict[str, list[str]]
    insights: list[InsightRow]
    diagnostics: list[ProviderDiagnostic]
    request_budget: ProviderRequestBudget | None = None
    compatibility_matrix: list[ProviderCompatibilityCheck] = Field(default_factory=list)
    observability: ProviderObservability = Field(default_factory=ProviderObservability)
    data_quality_notes: list[str] = Field(default_factory=list)


class BreakdownPerformance(MarketingDomainModel):
    dimension: Breakdown
    value: str
    metrics: PerformanceMetrics


class MarketingOverview(MarketingDomainModel):
    integration_health: IntegrationHealth
    last_synchronized_at: datetime | None
    snapshot: AdsSnapshot | None
    breakdown_performance: list[BreakdownPerformance]
    configuration: AgentConfiguration | None
    schedules: list[AgentSchedule]


class AdsCollectionRequest(MarketingDomainModel):
    run_id: str | None = None
    correlation_id: str | None = None
    account_ids: list[str] | None = None
    date_start: date
    date_stop: date
    attribution_window: str
    requested_breakdowns: list[Breakdown]

    @model_validator(mode="after")
    def validate_period(self) -> "AdsCollectionRequest":
        if self.date_start > self.date_stop:
            raise ValueError("date_start must be before or equal to date_stop")
        return self


class ProviderObjectState(MarketingDomainModel):
    provider: str
    object_type: AdEntityType
    provider_object_id: str
    status: str
    daily_budget: Decimal | None = None
    currency: str | None = None
    updated_at: datetime | None = None
    state_hash: str
    raw_safe: dict[str, JsonValue] = Field(default_factory=dict)


class ProviderActionResult(MarketingDomainModel):
    provider_request_id: str | None
    accepted: bool
    applied_state: ProviderObjectState | None = None
    diagnostics: dict[str, JsonValue] = Field(default_factory=dict)


def default_allowed_actions() -> set[ActionType]:
    return set(ActionType)


def default_approval_requirements() -> dict[ActionType, bool]:
    return {
        ActionType.INCREASE_BUDGET: True,
        ActionType.DECREASE_BUDGET: True,
        ActionType.PAUSE: True,
        ActionType.RESUME: True,
        ActionType.SCALE_AUDIENCE: True,
        ActionType.DISABLE_AUDIENCE: True,
        ActionType.MAINTAIN: False,
        ActionType.OBSERVE: False,
        ActionType.PROPOSE_TEST: False,
    }


class MarketingThresholdOverrides(MarketingDomainModel):
    minimum_spend: Decimal | None = Field(default=None, ge=Decimal("0"))
    minimum_impressions: int | None = Field(default=None, ge=0)
    minimum_clicks: int | None = Field(default=None, ge=0)
    minimum_conversions: Decimal | None = Field(default=None, ge=Decimal("0"))
    baseline_period_days: int | None = Field(default=None, ge=1, le=365)
    comparison_period_days: int | None = Field(default=None, ge=1, le=90)
    acceptable_cpl_cpa: Decimal | None = Field(default=None, gt=Decimal("0"))
    target_roas: Decimal | None = Field(default=None, gt=Decimal("0"))
    maximum_frequency: Decimal | None = Field(default=None, gt=Decimal("0"))
    ctr_decline_threshold: Decimal | None = Field(
        default=None,
        gt=Decimal("0"),
        le=Decimal("1"),
    )
    cpl_cpa_increase_threshold: Decimal | None = Field(
        default=None,
        gt=Decimal("0"),
        le=Decimal("5"),
    )
    anomaly_threshold: Decimal | None = Field(default=None, gt=Decimal("0"))
    minimum_confidence: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    data_completeness_threshold: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    conversion_lag_days: int | None = Field(default=None, ge=0, le=28)


class AccountCalibration(MarketingDomainModel):
    account_id: str
    provider: str
    source_snapshot_id: str
    calibrated_at: datetime
    thresholds: MarketingThresholdOverrides
    rationale: list[str] = Field(min_length=1)


class MarketingAgentConfiguration(MarketingDomainModel):
    primary_objective: MarketingObjective = MarketingObjective.LEADS
    custom_conversion_action: str | None = None
    attribution_window: str = "7d_click"
    minimum_spend: Decimal = Field(default=Decimal("10"), ge=Decimal("0"))
    minimum_impressions: int = Field(default=1_000, ge=0)
    minimum_clicks: int = Field(default=20, ge=0)
    minimum_conversions: Decimal = Field(default=Decimal("3"), ge=Decimal("0"))
    baseline_period_days: int = Field(default=14, ge=1, le=365)
    comparison_period_days: int = Field(default=7, ge=1, le=90)
    acceptable_cpl_cpa: Decimal = Field(default=Decimal("10"), gt=Decimal("0"))
    target_roas: Decimal = Field(default=Decimal("2"), gt=Decimal("0"))
    maximum_frequency: Decimal = Field(default=Decimal("3.5"), gt=Decimal("0"))
    ctr_decline_threshold: Decimal = Field(
        default=Decimal("0.25"),
        gt=Decimal("0"),
        le=Decimal("1"),
    )
    cpl_cpa_increase_threshold: Decimal = Field(
        default=Decimal("0.30"),
        gt=Decimal("0"),
        le=Decimal("5"),
    )
    anomaly_threshold: Decimal = Field(default=Decimal("1"), gt=Decimal("0"))
    minimum_confidence: Decimal = Field(
        default=Decimal("0.70"),
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    data_completeness_threshold: Decimal = Field(
        default=Decimal("0.75"),
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    maximum_budget_increase_factor: Decimal = Field(
        default=Decimal("1.20"),
        ge=Decimal("1"),
        le=Decimal("5"),
    )
    maximum_budget_decrease: Decimal = Field(
        default=Decimal("0.20"),
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    maximum_absolute_daily_budget_change: Decimal = Field(
        default=Decimal("100"),
        ge=Decimal("0"),
    )
    cooldown_hours: int = Field(default=24, ge=0, le=720)
    allowed_currencies: set[str] = Field(default_factory=lambda: {"USD"})
    minimum_daily_budget_by_currency: dict[str, Decimal] = Field(
        default_factory=lambda: {"USD": Decimal("1")},
    )
    conversion_lag_days: int = Field(default=0, ge=0, le=28)
    allowed_action_types: set[ActionType] = Field(default_factory=default_allowed_actions)
    approval_required: dict[ActionType, bool] = Field(
        default_factory=default_approval_requirements,
    )
    analysis_schedule: str = "0 */6 * * *"
    nightly_report_schedule: str = "0 2 * * *"
    timezone: str = "UTC"
    notification_channels: list[str] = Field(default_factory=list)
    proposal_ttl_hours: int = Field(default=24, ge=1, le=168)
    account_ids: list[str] = Field(default_factory=list)
    provider_defaults: dict[str, MarketingThresholdOverrides] = Field(default_factory=dict)
    account_calibrations: dict[str, AccountCalibration] = Field(default_factory=dict)
    campaign_overrides: dict[str, MarketingThresholdOverrides] = Field(default_factory=dict)
    objective_overrides: dict[MarketingObjective, MarketingThresholdOverrides] = Field(
        default_factory=dict,
    )
    requested_breakdowns: list[Breakdown] = Field(
        default_factory=lambda: [
            Breakdown.PLACEMENT,
            Breakdown.REGION,
            Breakdown.AGE,
            Breakdown.GENDER,
            Breakdown.HOUR,
            Breakdown.DAY,
        ],
    )

    @model_validator(mode="after")
    def validate_custom_objective(self) -> "MarketingAgentConfiguration":
        if (
            self.primary_objective is MarketingObjective.CUSTOM
            and not self.custom_conversion_action
        ):
            raise ValueError("custom_conversion_action is required for the custom objective")
        normalized_currencies = {currency.upper() for currency in self.allowed_currencies}
        if any(len(currency) != 3 or not currency.isalpha() for currency in normalized_currencies):
            raise ValueError("allowed_currencies must contain three-letter currency codes")
        normalized_minimums = {
            currency.upper(): amount
            for currency, amount in self.minimum_daily_budget_by_currency.items()
        }
        if any(
            len(currency) != 3 or not currency.isalpha() or amount <= Decimal("0")
            for currency, amount in normalized_minimums.items()
        ):
            raise ValueError(
                "minimum_daily_budget_by_currency requires positive three-letter entries",
            )
        if not normalized_currencies.issubset(normalized_minimums):
            raise ValueError("Every allowed currency requires an explicit minimum daily budget")
        object.__setattr__(self, "allowed_currencies", normalized_currencies)
        object.__setattr__(self, "minimum_daily_budget_by_currency", normalized_minimums)
        return self

    def action_policy_configuration(self) -> ActionPolicyConfiguration:
        return ActionPolicyConfiguration.model_validate(self.model_dump())

    def effective_for(
        self,
        *,
        provider: str,
        account_id: str | None = None,
        campaign_id: str | None = None,
        objective: MarketingObjective | None = None,
    ) -> "MarketingAgentConfiguration":
        values = self.model_dump()
        layers = [self.provider_defaults.get(provider)]
        if account_id is not None:
            calibration = self.account_calibrations.get(account_id)
            layers.append(calibration.thresholds if calibration is not None else None)
        layers.append(self.objective_overrides.get(objective or self.primary_objective))
        if campaign_id is not None:
            layers.append(self.campaign_overrides.get(campaign_id))
        for layer in layers:
            if layer is not None:
                values.update(layer.model_dump(exclude_none=True))
        return MarketingAgentConfiguration.model_validate(values)
