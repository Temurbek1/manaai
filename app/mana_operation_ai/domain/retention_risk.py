"""Purpose-bound adult account facts; raw child content and contact data are forbidden."""

from datetime import timedelta
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from app.mana_operation_ai.domain.models import DomainModel


class RetentionRiskZone(StrEnum):
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    UNKNOWN = "unknown"
    DEPARTED = "departed"
    NOT_APPLICABLE = "not_applicable"


class RetentionRiskReason(StrEnum):
    CANCELLATION_INTENT = "cancellation_intent"
    INACTIVE_RED = "inactive_red"
    INACTIVE_YELLOW = "inactive_yellow"
    PAID_ACCESS_ENDING = "paid_access_ending"
    UNINSTALL_SIGNAL = "uninstall_signal"
    LOW_RATING = "low_rating"
    OPEN_COMPLAINT = "open_complaint"
    DAILY_USE = "daily_use"
    FEATURE_ADOPTION = "feature_adoption"
    PUSH_ENGAGEMENT = "push_engagement"
    PAID_ACCESS_ENDED = "paid_access_ended"
    NOT_PAID = "not_paid"


class RiskEvidence(DomainModel):
    """An adapter's bounded attestation, not an arbitrary provider payload."""

    source: Literal["billing", "mobile_analytics", "support", "app_reviews", "sandbox"]
    evidence_ref: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    observed_at: AwareDatetime


class SubscriptionRiskEvidence(RiskEvidence):
    source: Literal["billing", "sandbox"]
    status: Literal["free", "trial", "active", "expired", "cancelled", "unknown"]
    paid_until: AwareDatetime | None = None
    auto_renew: bool | None = None


class ActivityRiskEvidence(RiskEvidence):
    source: Literal["mobile_analytics", "sandbox"]
    window_start: AwareDatetime
    window_end: AwareDatetime
    coverage: Literal["complete", "partial", "unknown"]
    last_open_at: AwareDatetime | None = None
    # These counters describe exactly the supplied window, never the entire account lifetime.
    active_days: int | None = Field(default=None, ge=0, le=31)
    distinct_features: int | None = Field(default=None, ge=0, le=1_000)
    push_opens: int | None = Field(default=None, ge=0)
    cancellation_page_views: int | None = Field(default=None, ge=0)
    # None means unknown. False is an explicit negative from a complete source.
    uninstall_signal: bool | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "ActivityRiskEvidence":
        if not self.window_start < self.window_end <= self.observed_at:
            raise ValueError("Activity evidence requires an ordered, completed window")
        duration = self.window_end - self.window_start
        if duration > timedelta(days=31):
            raise ValueError("Activity evidence window cannot exceed 31 days")
        if self.last_open_at is not None and self.last_open_at > self.window_end:
            raise ValueError("Last app open cannot be after the evidence window")
        if self.active_days is not None and self.active_days > duration.days + 1:
            raise ValueError("Active-day count exceeds the evidence window")
        if self.coverage == "complete":
            if self.last_open_at is None or self.last_open_at < self.window_start:
                if self.active_days not in {None, 0}:
                    raise ValueError("Active days conflict with last app open")
            elif self.active_days == 0:
                raise ValueError("An app open in the window requires a nonzero active-day count")
        return self


class FeedbackRiskEvidence(RiskEvidence):
    source: Literal["support", "app_reviews", "sandbox"]
    # Unknown is not the same as no rating/no complaint.
    rating_known: bool = False
    rating: int | None = Field(default=None, ge=1, le=5)
    open_complaints: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_rating(self) -> "FeedbackRiskEvidence":
        if self.rating is not None and not self.rating_known:
            raise ValueError("A rating value must be marked as observed")
        return self


class CustomerRetentionFacts(DomainModel):
    schema_version: Literal["customer-retention-v1"] = "customer-retention-v1"
    # The first-party adapter must produce a purpose-specific HMAC, not a raw account ID.
    account_ref: str = Field(pattern=r"^acct_[a-f0-9]{64}$")
    subject_type: Literal["adult_account"] = "adult_account"
    collected_at: AwareDatetime
    mode: Literal["live", "sandbox"]
    subscription: SubscriptionRiskEvidence | None = None
    activity: ActivityRiskEvidence | None = None
    feedback: FeedbackRiskEvidence | None = None

    @model_validator(mode="after")
    def validate_lineage(self) -> "CustomerRetentionFacts":
        for evidence in (self.subscription, self.activity, self.feedback):
            if evidence is None:
                continue
            if evidence.observed_at > self.collected_at:
                raise ValueError("Evidence cannot be observed after collection")
            if (evidence.source == "sandbox") != (self.mode == "sandbox"):
                raise ValueError("Live and sandbox evidence must not be mixed")
        return self


class RetentionRiskConfiguration(DomainModel):
    red_inactivity_days: int = Field(default=5, ge=2, le=30)
    yellow_inactivity_days: int = Field(default=3, ge=1, le=29)
    paid_expiry_hours: int = Field(default=24, ge=1, le=168)
    cancellation_views_threshold: int = Field(default=2, ge=2, le=20)
    maximum_evidence_age_hours: int = Field(default=6, ge=1, le=24)
    engagement_window_days: int = Field(default=7, ge=1, le=30)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "RetentionRiskConfiguration":
        if self.red_inactivity_days <= self.yellow_inactivity_days:
            raise ValueError("Red inactivity must be longer than yellow inactivity")
        return self


class RetentionRiskSignal(DomainModel):
    reason: RetentionRiskReason
    evidence_ref: str
    observed_at: AwareDatetime
    # Rule evidence is not a learned probability or a claim that a customer will leave.
    zone: RetentionRiskZone


class CustomerRetentionRisk(DomainModel):
    account_ref: str
    mode: Literal["live", "sandbox"]
    evaluated_at: AwareDatetime
    zone: RetentionRiskZone
    signals: list[RetentionRiskSignal] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    referral_eligible: bool = False
    assessment_kind: Literal["rule_based_priority"] = "rule_based_priority"
    customer_action_authorized: Literal[False] = False


class RetentionRiskBatch(DomainModel):
    schema_version: Literal["retention-risk-batch-v1"] = "retention-risk-batch-v1"
    facts: list[CustomerRetentionFacts] = Field(max_length=1_000)

    @model_validator(mode="after")
    def validate_subjects(self) -> "RetentionRiskBatch":
        refs = [item.account_ref for item in self.facts]
        if len(set(refs)) != len(refs):
            raise ValueError("An account may appear only once in a risk batch")
        if len({item.mode for item in self.facts}) > 1:
            raise ValueError("A risk batch cannot combine live and sandbox accounts")
        return self
