"""Deterministic eligibility is never a customer-contact approval."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.mana_operation_ai.application.retention.risk import assess_retention_risk
from app.mana_operation_ai.domain.retention_contact import (
    RetentionContactParameters,
    RetentionContactPolicyResult,
    RetentionContactTarget,
)
from app.mana_operation_ai.domain.retention_risk import (
    RetentionRiskConfiguration,
    RetentionRiskReason,
    RetentionRiskZone,
)


def contact_fingerprint(value: RetentionContactTarget | RetentionContactParameters) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def evaluate_contact(
    parameters: RetentionContactParameters,
    target: RetentionContactTarget,
    *,
    now: datetime,
) -> RetentionContactPolicyResult:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Policy time must include a timezone")
    reasons: list[str] = []
    risk_zone = RetentionRiskZone.UNKNOWN
    if target.facts.account_ref != parameters.account_ref:
        reasons.append("account_binding_mismatch")
    times = [target.observed_at, target.consent_observed_at, target.facts.collected_at]
    if any(value > now or now - value > timedelta(hours=6) for value in times):
        reasons.append("stale_or_future_evidence")
    else:
        risk = assess_retention_risk(
            target.facts,
            now=now,
            configuration=RetentionRiskConfiguration(),
        )
        risk_zone = risk.zone
        if risk.zone not in {RetentionRiskZone.RED, RetentionRiskZone.YELLOW}:
            reasons.append("no_evidenced_contact_priority")
        if risk.missing_evidence:
            reasons.append("incomplete_risk_evidence")
        if parameters.template == "renewal_reminder" and not any(
            item.reason == RetentionRiskReason.PAID_ACCESS_ENDING for item in risk.signals
        ):
            reasons.append("renewal_not_confirmed")
    subscription = target.facts.subscription
    if (
        subscription is None
        or subscription.status != "active"
        or (subscription.paid_until is None or subscription.paid_until <= now)
    ):
        reasons.append("paid_adult_access_not_confirmed")
    if target.consent is not True or target.consent_expires_at <= now:
        reasons.append("contact_consent_missing_or_expired")
    if (
        target.consent_channel != parameters.channel
        or target.consent_purpose != "retention_support"
        or not target.consent_evidence_ref
    ):
        reasons.append("purpose_bound_contact_consent_missing")
    if target.preferred_language != parameters.language:
        reasons.append("preferred_language_unknown_or_unsupported")
    if target.suppressed is not False:
        reasons.append("contact_suppressed_or_unknown")
    if not target.contact_history_complete or len(target.deliveries) >= 100:
        reasons.append("contact_history_incomplete")
    if any(now - item.accepted_at < timedelta(days=7) for item in target.deliveries):
        reasons.append("seven_day_contact_cooldown")
    if target.facts.feedback is None or target.facts.feedback.open_complaints != 0:
        reasons.append("complaint_state_unsafe_or_unknown")
    try:
        hour = now.astimezone(ZoneInfo(target.timezone)).hour
        if hour < 9 or hour >= 21:
            reasons.append("recipient_quiet_hours")
    except (ValueError, ZoneInfoNotFoundError):
        reasons.append("recipient_timezone_unknown")
    return RetentionContactPolicyResult(
        eligible_for_review=not reasons,
        zone=risk_zone,
        reasons=reasons,
    )
