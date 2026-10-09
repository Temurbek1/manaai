"""Deterministic paid-adult-account prioritization; never reads providers or sends offers."""

from datetime import datetime, timedelta

from app.mana_operation_ai.domain.retention_risk import (
    CustomerRetentionFacts,
    CustomerRetentionRisk,
    RetentionRiskConfiguration,
    RetentionRiskReason,
    RetentionRiskSignal,
    RetentionRiskZone,
    RiskEvidence,
)


def assess_retention_risk(
    facts: CustomerRetentionFacts,
    *,
    now: datetime,
    configuration: RetentionRiskConfiguration,
) -> CustomerRetentionRisk:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Risk evaluation time must include a timezone")
    if facts.collected_at > now:
        raise ValueError("Risk facts cannot be collected in the future")
    result = CustomerRetentionRisk(
        account_ref=facts.account_ref,
        mode=facts.mode,
        evaluated_at=now,
        zone=RetentionRiskZone.UNKNOWN,
    )
    max_age = timedelta(hours=configuration.maximum_evidence_age_hours)

    def usable(evidence: RiskEvidence | None, name: str) -> bool:
        if evidence is None:
            result.missing_evidence.append(name)
            return False
        if now - evidence.observed_at > max_age:
            result.missing_evidence.append(f"{name}.freshness")
            return False
        return True

    def signal(
        reason: RetentionRiskReason, zone: RetentionRiskZone, evidence: RiskEvidence
    ) -> None:
        result.signals.append(
            RetentionRiskSignal(
                reason=reason,
                zone=zone,
                evidence_ref=evidence.evidence_ref,
                observed_at=evidence.observed_at,
            ),
        )

    subscription = facts.subscription
    if not usable(subscription, "subscription") or subscription is None:
        return result
    if subscription.status == "unknown":
        result.missing_evidence.append("subscription.status")
        return result
    if subscription.status in {"free", "trial"}:
        result.zone = RetentionRiskZone.NOT_APPLICABLE
        signal(RetentionRiskReason.NOT_PAID, result.zone, subscription)
        return result
    # Expired/cancelled records may still have paid-through access. Never invent departure.
    paid_until = subscription.paid_until
    if paid_until is None:
        result.missing_evidence.append("subscription.paid_until")
    elif paid_until <= now:
        if subscription.status in {"expired", "cancelled"}:
            result.zone = RetentionRiskZone.DEPARTED
            signal(RetentionRiskReason.PAID_ACCESS_ENDED, result.zone, subscription)
            return result
        result.missing_evidence.append("subscription.renewal_confirmation")
    if subscription.auto_renew is None:
        result.missing_evidence.append("subscription.auto_renew")
    if (
        paid_until is not None
        and now < paid_until <= now + timedelta(hours=configuration.paid_expiry_hours)
        and subscription.auto_renew is False
    ):
        signal(RetentionRiskReason.PAID_ACCESS_ENDING, RetentionRiskZone.RED, subscription)
    if subscription.status == "cancelled" and paid_until is not None and paid_until > now:
        signal(RetentionRiskReason.CANCELLATION_INTENT, RetentionRiskZone.RED, subscription)

    activity = facts.activity
    activity_usable = usable(activity, "activity")
    if activity is not None and activity_usable:
        if now - activity.window_end > max_age:
            result.missing_evidence.append("activity.window_freshness")
            activity_usable = False
        else:
            complete = activity.coverage == "complete"
            if not complete:
                result.missing_evidence.append("activity.coverage")
            # Absence is only evidence when observation covers the absence interval.
            anchor = activity.last_open_at or activity.window_start
            observed_since = max(anchor, activity.window_start)
            inactivity = activity.window_end - observed_since
            if complete and inactivity > timedelta(days=configuration.red_inactivity_days):
                signal(RetentionRiskReason.INACTIVE_RED, RetentionRiskZone.RED, activity)
            elif complete and inactivity > timedelta(days=configuration.yellow_inactivity_days):
                signal(RetentionRiskReason.INACTIVE_YELLOW, RetentionRiskZone.YELLOW, activity)
            # Positive events remain useful in partial windows, but cannot establish low risk.
            views = activity.cancellation_page_views
            if views is None:
                result.missing_evidence.append("activity.cancellation_page_views")
            elif views >= configuration.cancellation_views_threshold:
                signal(RetentionRiskReason.CANCELLATION_INTENT, RetentionRiskZone.RED, activity)
            if activity.uninstall_signal is None:
                result.missing_evidence.append("activity.uninstall_signal")
            elif activity.uninstall_signal:
                signal(RetentionRiskReason.UNINSTALL_SIGNAL, RetentionRiskZone.YELLOW, activity)
            if activity.active_days is None:
                result.missing_evidence.append("activity.active_days")
            if activity.distinct_features is None:
                result.missing_evidence.append("activity.distinct_features")
            if activity.push_opens is None:
                result.missing_evidence.append("activity.push_opens")
            if activity.window_end - activity.window_start != timedelta(
                days=configuration.engagement_window_days,
            ):
                result.missing_evidence.append("activity.engagement_window")
            recent_open = (
                activity.last_open_at is not None
                and now - activity.last_open_at <= timedelta(days=1)
            )
            if recent_open:
                if activity.active_days == configuration.engagement_window_days:
                    signal(RetentionRiskReason.DAILY_USE, RetentionRiskZone.GREEN, activity)
                if activity.distinct_features is not None and activity.distinct_features > 3:
                    signal(RetentionRiskReason.FEATURE_ADOPTION, RetentionRiskZone.GREEN, activity)
                if activity.push_opens is not None and activity.push_opens > 0:
                    signal(RetentionRiskReason.PUSH_ENGAGEMENT, RetentionRiskZone.GREEN, activity)

    feedback = facts.feedback
    feedback_usable = usable(feedback, "feedback")
    if feedback is not None and feedback_usable:
        if not feedback.rating_known:
            result.missing_evidence.append("feedback.rating")
        elif feedback.rating is not None and feedback.rating <= 3:
            signal(RetentionRiskReason.LOW_RATING, RetentionRiskZone.YELLOW, feedback)
        if feedback.open_complaints is None:
            result.missing_evidence.append("feedback.open_complaints")
        elif feedback.open_complaints > 0:
            signal(RetentionRiskReason.OPEN_COMPLAINT, RetentionRiskZone.YELLOW, feedback)

    zones = {item.zone for item in result.signals}
    if RetentionRiskZone.RED in zones:
        result.zone = RetentionRiskZone.RED
    elif RetentionRiskZone.YELLOW in zones:
        result.zone = RetentionRiskZone.YELLOW
    elif RetentionRiskZone.GREEN in zones and not result.missing_evidence:
        result.zone = RetentionRiskZone.GREEN
    # Referral eligibility is a candidate for approval, not permission to send or grant a reward.
    result.referral_eligible = bool(
        result.zone == RetentionRiskZone.GREEN
        and activity_usable
        and feedback_usable
        and activity is not None
        and feedback is not None
        and activity.active_days == configuration.engagement_window_days
        and activity.distinct_features is not None
        and activity.distinct_features > 4
        and feedback.open_complaints == 0
        and feedback.rating_known
        and feedback.rating is not None
        and feedback.rating >= 4
    )
    return result


def prioritize_retention_risks(
    results: list[CustomerRetentionRisk], *, limit: int = 50
) -> list[CustomerRetentionRisk]:
    """Only evidenced red/yellow cases; no fabricated churn probability or unstable ties."""
    if not 1 <= limit <= 1_000:
        raise ValueError("Risk ranking limit must be between 1 and 1000")
    rank = {RetentionRiskZone.RED: 0, RetentionRiskZone.YELLOW: 1}
    eligible = [item for item in results if item.zone in rank]
    return sorted(eligible, key=lambda item: (rank[item.zone], item.account_ref))[:limit]
