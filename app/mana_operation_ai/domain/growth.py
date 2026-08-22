from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from app.mana_operation_ai.domain.models import DomainModel, EvidenceRef


class GrowthFunnelConfiguration(DomainModel):
    schedule: str = "0 */12 * * *"
    timezone: str = "UTC"
    lookback_days: int = Field(default=14, ge=1, le=90)
    minimum_completeness: Decimal = Field(
        default=Decimal("0.90"),
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    minimum_stage_conversion: Decimal = Field(
        default=Decimal("0.20"),
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    experiment_mode: Literal["shadow", "sandbox"] = "shadow"
    experiment_allocation_percent: int = Field(default=10, ge=1, le=50)
    experiment_duration_days: int = Field(default=14, ge=1, le=90)
    proposal_ttl_hours: int = Field(default=24, ge=1, le=168)


class ProductAnalyticsFacts(DomainModel):
    source: str
    period_start: datetime
    period_end: datetime
    collected_at: datetime
    visitors: int = Field(ge=0)
    signups: int = Field(ge=0)
    activated_users: int = Field(ge=0)
    completeness: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    source_request_id: str

    @model_validator(mode="after")
    def validate_funnel_order(self) -> "ProductAnalyticsFacts":
        if self.signups > self.visitors or self.activated_users > self.signups:
            raise ValueError("Product funnel counts must be monotonically non-increasing")
        return self


class BillingFunnelFacts(DomainModel):
    source: str
    period_start: datetime
    period_end: datetime
    collected_at: datetime
    activated_users: int = Field(ge=0)
    trials_started: int = Field(ge=0)
    paid_subscriptions: int = Field(ge=0)
    recognized_revenue: Decimal = Field(ge=Decimal("0"))
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    completeness: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    source_request_id: str

    @model_validator(mode="after")
    def validate_funnel_order(self) -> "BillingFunnelFacts":
        if self.trials_started > self.activated_users:
            raise ValueError("Trial count cannot exceed the billing activation cohort")
        if self.paid_subscriptions > self.trials_started:
            raise ValueError("Paid subscription count cannot exceed trial starts")
        return self


class AttributionChannelFacts(DomainModel):
    channel: str = Field(min_length=1, max_length=80)
    visitors: int = Field(ge=0)
    paid_subscriptions: int = Field(ge=0)


class AttributionFacts(DomainModel):
    source: str
    period_start: datetime
    period_end: datetime
    collected_at: datetime
    channels: list[AttributionChannelFacts]
    completeness: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    source_request_id: str


class GrowthFunnelSnapshot(DomainModel):
    schema_version: Literal["growth-funnel-v1"] = "growth-funnel-v1"
    period_start: datetime
    period_end: datetime
    collected_at: datetime
    visitors: int = Field(ge=0)
    signups: int = Field(ge=0)
    activated_users: int = Field(ge=0)
    trials_started: int = Field(ge=0)
    paid_subscriptions: int = Field(ge=0)
    recognized_revenue: Decimal = Field(ge=Decimal("0"))
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    channels: list[AttributionChannelFacts]
    completeness: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    evidence_refs: list[EvidenceRef]
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_funnel_order(self) -> "GrowthFunnelSnapshot":
        counts = [
            self.visitors,
            self.signups,
            self.activated_users,
            self.trials_started,
            self.paid_subscriptions,
        ]
        if any(current < following for current, following in zip(counts, counts[1:], strict=False)):
            raise ValueError("Normalized funnel counts must be monotonically non-increasing")
        return self


class ExperimentTargetState(DomainModel):
    provider: str
    experiment_key: str
    status: Literal["ABSENT", "DRAFT", "RUNNING", "STOPPED"]
    allocation_percent: int | None = Field(default=None, ge=1, le=100)
    state_hash: str
    raw_safe: dict[str, JsonValue]


class ExperimentDispatchResult(DomainModel):
    provider_request_id: str
    state: ExperimentTargetState
