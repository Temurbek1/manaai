"""MANA adult-account conversion contracts; no child facts or billing authority."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId, ResponseLanguage

ConversionKey = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$", strict=True)
]


class PaidConversionOffer(ChatContract):
    """An owner-configured offer already supported by the application's checkout."""

    kind: Literal["paid_subscription"] = "paid_subscription"
    offer_id: ConversionKey
    billing_offer_id: ConversionKey
    approval_reference: str = Field(min_length=1, max_length=120)
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    currency: Literal["UZS", "USD"]
    list_price_minor: int = Field(gt=0, strict=True)
    price_minor: int = Field(gt=0, strict=True)
    discount_percent: int = Field(default=0, ge=0, le=50, strict=True)
    duration_days: int = Field(ge=1, le=366, strict=True)
    auto_renew: bool = Field(strict=True)
    renewal_price_minor: int | None = Field(default=None, gt=0, strict=True)
    checkout_path: str = Field(pattern=r"^/subscriptions/[a-z0-9_-]{1,80}$")
    priority: int = Field(default=0, ge=0, le=100, strict=True)

    @model_validator(mode="after")
    def validate_terms(self) -> "PaidConversionOffer":
        if self.valid_until <= self.valid_from:
            raise ValueError("Offer validity must be ordered")
        expected = (self.list_price_minor * (100 - self.discount_percent) + 50) // 100
        if self.price_minor != expected:
            raise ValueError("Discount must match the billing-confirmed price in minor units")
        if self.auto_renew != (self.renewal_price_minor is not None):
            raise ValueError("Automatic renewal requires its confirmed recurring price")
        return self


class TrialConversionOffer(ChatContract):
    """One non-paid Maxsus grant; never a discount or payment transaction."""

    kind: Literal["free_premium_days"] = "free_premium_days"
    offer_id: ConversionKey
    approval_reference: str = Field(min_length=1, max_length=120)
    valid_from: AwareDatetime
    valid_until: AwareDatetime
    grant_days: int = Field(ge=1, le=30, strict=True)
    priority: int = Field(default=0, ge=0, le=100, strict=True)

    @model_validator(mode="after")
    def ordered_dates(self) -> "TrialConversionOffer":
        if self.valid_until <= self.valid_from:
            raise ValueError("Offer validity must be ordered")
        return self


ConversionOffer = Annotated[PaidConversionOffer | TrialConversionOffer, Field(discriminator="kind")]


class ConversionPolicy(ChatContract):
    snapshot_max_age_seconds: int = Field(default=900, ge=60, le=3600, strict=True)
    minimum_free_days: int = Field(default=7, ge=1, le=365, strict=True)
    hot_minimum_free_days: int = Field(default=1, ge=1, le=365, strict=True)
    expired_free_access_window_days: int = Field(default=7, ge=1, le=30, strict=True)
    cooldown_days: int = Field(default=7, ge=1, le=90, strict=True)
    monthly_contact_limit: int = Field(default=2, ge=1, le=10, strict=True)
    global_daily_contact_limit: int = Field(default=100, ge=1, le=100_000, strict=True)
    global_daily_trial_grant_limit: int = Field(default=10, ge=1, le=1000, strict=True)
    quiet_start_hour: int = Field(default=20, ge=0, le=23, strict=True)
    quiet_end_hour: int = Field(default=9, ge=0, le=23, strict=True)
    conversation_idle_seconds: int = Field(default=600, ge=60, le=86400, strict=True)

    @model_validator(mode="after")
    def distinct_quiet_hours(self) -> "ConversionPolicy":
        if self.quiet_start_hour == self.quiet_end_hour:
            raise ValueError("Quiet hours must have distinct boundaries")
        return self


class ConversionSnapshot(ChatContract):
    """Authoritative, minimized backend facts about an adult parent's account only."""

    product: Literal["mana"] = "mana"
    parent_id: ParentChatId
    event_id: UUID
    revision: int = Field(ge=1, strict=True)
    observed_at: AwareDatetime
    subscription: Literal["free", "paid", "expired", "unknown"]
    free_started_at: AwareDatetime | None
    free_access_ends_at: AwareDatetime | None = None
    agent_trial_given: bool | None = Field(default=None, strict=True)
    marketing_consent: bool = Field(strict=True)
    consent_observed_at: AwareDatetime
    language: ResponseLanguage
    timezone: str = Field(min_length=1, max_length=64)
    last_active_at: AwareDatetime | None
    active_days_7d: int = Field(ge=0, le=7, strict=True)
    sessions_7d: int = Field(ge=0, le=100_000, strict=True)
    paywall_views_7d: int = Field(ge=0, le=100_000, strict=True)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("An IANA recipient timezone is required") from None
        return value

    @model_validator(mode="after")
    def coherent_dates(self) -> "ConversionSnapshot":
        if self.consent_observed_at > self.observed_at:
            raise ValueError("Consent must precede the account observation")
        if self.subscription == "free" and self.free_started_at is None:
            raise ValueError("Confirmed free use needs its actual start date")
        if self.free_started_at and self.free_started_at > self.observed_at:
            raise ValueError("Free use cannot start after the observation")
        if (
            self.free_access_ends_at
            and self.free_started_at
            and self.free_access_ends_at <= self.free_started_at
        ):
            raise ValueError("Free-access dates must be ordered")
        if self.last_active_at and self.last_active_at > self.observed_at:
            raise ValueError("Activity cannot follow the observation")
        if bool(self.active_days_7d) != bool(self.sessions_7d):
            raise ValueError("Active-day and session counts must agree")
        if self.sessions_7d < self.active_days_7d:
            raise ValueError("Each active day needs a session")
        if (self.sessions_7d or self.paywall_views_7d) and self.last_active_at is None:
            raise ValueError("Usage counts need an actual last activity time")
        if (
            self.sessions_7d
            and self.last_active_at
            and (self.observed_at - self.last_active_at).total_seconds() > 7 * 86400
        ):
            raise ValueError("Seven-day usage cannot have an older last activity")
        return self


ConversionReason = Literal["seven_day_free_use", "hot_free_account", "free_access_expired"]
ProposalStatus = Literal[
    "queued", "published", "interested", "declined", "opted_out", "converted", "cancelled"
]


class ConversionProposal(ChatContract):
    proposal_id: UUID
    parent_id: ParentChatId
    snapshot_revision: int
    reason: ConversionReason
    status: ProposalStatus
    offer: ConversionOffer
    created_at: AwareDatetime
    published_at: AwareDatetime | None = None
    turn_id: int | None = None
    closed_reason: str | None = None


class ConversionAdmission(ChatContract):
    parent_id: ParentChatId
    event_id: UUID
    decision: str
    proposal: ConversionProposal | None


class ConversionOutcome(ChatContract):
    parent_id: ParentChatId
    event_id: UUID
    proposal_id: UUID
    observed_at: AwareDatetime
    kind: Literal["interested", "declined", "opted_out", "payment_confirmed"]
    payment_id: ConversionKey | None = None
    amount_minor: int | None = Field(default=None, gt=0, strict=True)
    currency: Literal["UZS", "USD"] | None = None
    billing_offer_id: ConversionKey | None = None

    @model_validator(mode="after")
    def payment_is_explicit(self) -> "ConversionOutcome":
        values = (self.payment_id, self.amount_minor, self.currency, self.billing_offer_id)
        if self.kind == "payment_confirmed":
            if any(value is None for value in values):
                raise ValueError("Conversion needs a verified backend billing receipt")
        elif any(value is not None for value in values):
            raise ValueError("A parent reaction is not a payment")
        return self


class ConversionProposalPage(ChatContract):
    parent_id: ParentChatId
    proposals: list[ConversionProposal]
    next_after: int | None = None


def conversion_reason(
    snapshot: ConversionSnapshot,
    policy: ConversionPolicy,
    now: datetime,
    *,
    include_expired: bool = False,
) -> ConversionReason | str:
    """Deterministic admission, not a payment prediction or a model's permission.

    Expiry admission belongs only to a captured compatible runtime. Old callers
    preserve their original reasons and do not acquire the new proposal contract.
    An expiry invitation requires a paid offer; it does not authorize another
    trial grant, claim a charge or attest to paid subscription status.
    """
    age = (now - snapshot.observed_at).total_seconds()
    if age < -120 or age > policy.snapshot_max_age_seconds:
        return "snapshot_not_current"
    expiry_candidate = (
        include_expired
        and snapshot.subscription in {"free", "expired"}
        and snapshot.free_started_at is not None
        and snapshot.free_access_ends_at is not None
    )
    if snapshot.subscription != "free" and not expiry_candidate:
        return "not_confirmed_free"
    if not snapshot.marketing_consent:
        return "no_marketing_consent"
    if (
        not snapshot.active_days_7d
        or snapshot.last_active_at is None
        or (now - snapshot.last_active_at).total_seconds() > 2 * 86400
    ):
        return "inactive_account"
    if expiry_candidate:
        assert snapshot.free_access_ends_at is not None
        ended_at = snapshot.free_access_ends_at
        if ended_at <= snapshot.observed_at:
            if ended_at > now:
                return "free_access_expiry_not_confirmed"
            elapsed = (now.astimezone(UTC) - ended_at.astimezone(UTC)).total_seconds()
            if elapsed > policy.expired_free_access_window_days * 86400:
                return "free_access_expiry_window_elapsed"
            return "free_access_expired"
        if ended_at <= now:
            # A timer cannot turn an older pre-expiry account observation into
            # proof that access actually ended without payment or extension.
            return "free_access_expiry_not_confirmed"
    if snapshot.subscription != "free":
        return "not_confirmed_free"
    assert snapshot.free_started_at is not None
    free_days = (now - snapshot.free_started_at).total_seconds() // 86400
    if free_days >= policy.minimum_free_days:
        return "seven_day_free_use"
    if (
        free_days >= policy.hot_minimum_free_days
        and snapshot.active_days_7d >= 2
        and snapshot.sessions_7d >= 3
        and snapshot.paywall_views_7d >= 1
    ):
        return "hot_free_account"
    return "not_yet_eligible"


def elapsed_free_days(snapshot: ConversionSnapshot, now: datetime) -> int:
    """Whole elapsed free-access days, capped at its confirmed end when supplied.

    This is presentation data, not an eligibility decision, active-day measurement
    or evidence of a payment. Callers must independently validate current facts,
    recipient policy and the chosen offer before publishing a message.
    """
    if now.utcoffset() is None:
        raise ValueError("An aware observation clock is required")
    if snapshot.free_started_at is None:
        raise ValueError("Elapsed free access needs its confirmed start date")
    end = now.astimezone(UTC)
    if snapshot.free_access_ends_at is not None:
        end = min(end, snapshot.free_access_ends_at.astimezone(UTC))
    seconds = (end - snapshot.free_started_at.astimezone(UTC)).total_seconds()
    return max(0, int(seconds // 86400))
