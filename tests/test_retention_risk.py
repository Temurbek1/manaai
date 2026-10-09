from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from app.mana_operation_ai.application.retention.risk import (
    assess_retention_risk,
    prioritize_retention_risks,
)
from app.mana_operation_ai.domain.retention_risk import (
    CustomerRetentionFacts,
    RetentionRiskBatch,
    RetentionRiskConfiguration,
    RetentionRiskReason,
    RetentionRiskZone,
)

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)
CONFIGURATION = RetentionRiskConfiguration()


def facts_payload() -> dict[str, Any]:
    evidence = {"source": "sandbox", "observed_at": NOW, "evidence_ref": "test-evidence"}
    return {
        "account_ref": "acct_" + "a" * 64,
        "mode": "sandbox",
        "collected_at": NOW,
        "subscription": {
            **evidence,
            "status": "active",
            "paid_until": NOW + timedelta(days=20),
            "auto_renew": True,
        },
        "activity": {
            **evidence,
            "window_start": NOW - timedelta(days=7),
            "window_end": NOW,
            "coverage": "complete",
            "last_open_at": NOW - timedelta(hours=1),
            "active_days": 7,
            "distinct_features": 5,
            "push_opens": 2,
            "cancellation_page_views": 0,
            "uninstall_signal": False,
        },
        "feedback": {**evidence, "rating_known": True, "rating": 5, "open_complaints": 0},
    }


def assess(payload: dict[str, Any]):  # type: ignore[no-untyped-def]
    return assess_retention_risk(
        CustomerRetentionFacts.model_validate(payload), now=NOW, configuration=CONFIGURATION
    )


def test_happy_account_has_explainable_green_and_referral_candidate_not_action_permission() -> None:
    result = assess(facts_payload())
    assert result.zone is RetentionRiskZone.GREEN
    assert result.referral_eligible
    assert result.missing_evidence == []
    assert not result.customer_action_authorized
    assert result.assessment_kind == "rule_based_priority"
    assert {item.reason for item in result.signals} == {
        RetentionRiskReason.DAILY_USE,
        RetentionRiskReason.FEATURE_ADOPTION,
        RetentionRiskReason.PUSH_ENGAGEMENT,
    }
    assert all(item.evidence_ref == "test-evidence" for item in result.signals)


@pytest.mark.parametrize(
    ("days", "zone"),
    [(3, "unknown"), (3.01, "yellow"), (5, "yellow"), (5.01, "red")],
)
def test_inactivity_thresholds_are_strict_and_do_not_infer_daily_use(
    days: float, zone: str
) -> None:
    payload = facts_payload()
    payload["activity"].update(last_open_at=NOW - timedelta(days=days), active_days=1)
    assert assess(payload).zone == zone


def test_no_recorded_open_can_prove_inactivity_only_over_complete_observation_window() -> None:
    payload = facts_payload()
    payload["activity"].update(last_open_at=None, active_days=0)
    assert assess(payload).zone is RetentionRiskZone.RED
    payload["activity"]["coverage"] = "partial"
    result = assess(payload)
    assert result.zone is RetentionRiskZone.UNKNOWN
    assert "activity.coverage" in result.missing_evidence
    payload["activity"]["coverage"] = "complete"
    payload["activity"]["window_start"] = NOW - timedelta(days=1)
    assert assess(payload).zone is RetentionRiskZone.UNKNOWN


def test_old_known_open_with_short_observation_does_not_prove_long_inactivity() -> None:
    payload = facts_payload()
    payload["activity"].update(
        window_start=NOW - timedelta(days=1), last_open_at=NOW - timedelta(days=8), active_days=0
    )
    assert assess(payload).zone is RetentionRiskZone.UNKNOWN


@pytest.mark.parametrize("renewal", [True, False, None])
def test_expiry_rule_distinguishes_payment_period_from_confirmed_end(renewal: bool | None) -> None:
    payload = facts_payload()
    payload["subscription"].update(paid_until=NOW + timedelta(hours=24), auto_renew=renewal)
    result = assess(payload)
    assert result.zone == ("green" if renewal else "red" if renewal is False else "unknown")
    if renewal is None:
        assert "subscription.auto_renew" in result.missing_evidence


@pytest.mark.parametrize("status", ["expired", "cancelled"])
def test_departed_requires_paid_through_access_to_have_ended(status: str) -> None:
    payload = facts_payload()
    payload["subscription"].update(status=status, paid_until=NOW, auto_renew=False)
    assert assess(payload).zone is RetentionRiskZone.DEPARTED
    payload["subscription"]["paid_until"] = NOW + timedelta(hours=1)
    assert assess(payload).zone is RetentionRiskZone.RED


def test_active_subscription_with_past_paid_until_is_unknown_not_departed_or_green() -> None:
    payload = facts_payload()
    payload["subscription"]["paid_until"] = NOW - timedelta(hours=1)
    result = assess(payload)
    assert result.zone is RetentionRiskZone.UNKNOWN
    assert "subscription.renewal_confirmation" in result.missing_evidence


@pytest.mark.parametrize("status", ["free", "trial"])
def test_non_paying_accounts_are_not_retention_customers(status: str) -> None:
    payload = facts_payload()
    payload["subscription"]["status"] = status
    payload["activity"]["cancellation_page_views"] = 8
    result = assess(payload)
    assert result.zone is RetentionRiskZone.NOT_APPLICABLE
    assert not result.referral_eligible


@pytest.mark.parametrize("missing", ["subscription", "activity", "feedback"])
def test_missing_evidence_does_not_become_green(missing: str) -> None:
    payload = facts_payload()
    payload[missing] = None
    result = assess(payload)
    assert result.zone is RetentionRiskZone.UNKNOWN
    assert missing in result.missing_evidence
    assert not result.referral_eligible


@pytest.mark.parametrize("source", ["subscription", "activity", "feedback"])
def test_stale_evidence_cannot_establish_current_risk(source: str) -> None:
    payload = facts_payload()
    payload[source]["observed_at"] = NOW - timedelta(hours=7)
    if source == "activity":
        payload[source]["window_end"] = NOW - timedelta(hours=7)
        payload[source]["last_open_at"] = NOW - timedelta(hours=8)
        payload[source]["cancellation_page_views"] = 4
    result = assess(payload)
    assert result.zone is RetentionRiskZone.UNKNOWN
    assert f"{source}.freshness" in result.missing_evidence


def test_refreshing_collection_timestamp_does_not_refresh_old_activity_window() -> None:
    payload = facts_payload()
    payload["activity"].update(
        window_start=NOW - timedelta(days=8),
        window_end=NOW - timedelta(days=1),
        last_open_at=NOW - timedelta(days=1),
        cancellation_page_views=10,
    )
    result = assess(payload)
    assert result.zone is RetentionRiskZone.UNKNOWN
    assert "activity.window_freshness" in result.missing_evidence


def test_verified_red_signal_survives_missing_secondary_data_but_is_not_full_coverage() -> None:
    payload = facts_payload()
    payload["activity"]["cancellation_page_views"] = 2
    payload["feedback"] = None
    result = assess(payload)
    assert result.zone is RetentionRiskZone.RED
    assert "feedback" in result.missing_evidence
    assert not result.referral_eligible


@pytest.mark.parametrize("rating", [1, 2, 3])
def test_low_rating_is_yellow_even_with_high_usage(rating: int) -> None:
    payload = facts_payload()
    payload["feedback"]["rating"] = rating
    result = assess(payload)
    assert result.zone is RetentionRiskZone.YELLOW
    assert RetentionRiskReason.LOW_RATING in [item.reason for item in result.signals]
    assert not result.referral_eligible


def test_complaint_and_uninstall_are_reasons_not_predictions() -> None:
    payload = facts_payload()
    payload["feedback"]["open_complaints"] = 1
    payload["activity"]["uninstall_signal"] = True
    result = assess(payload)
    assert result.zone is RetentionRiskZone.YELLOW
    assert {RetentionRiskReason.OPEN_COMPLAINT, RetentionRiskReason.UNINSTALL_SIGNAL} <= {
        item.reason for item in result.signals
    }


def test_unknown_negative_values_prevent_green_and_referral() -> None:
    payload = facts_payload()
    payload["activity"]["uninstall_signal"] = None
    payload["feedback"].update(rating_known=False, rating=None, open_complaints=None)
    result = assess(payload)
    assert result.zone is RetentionRiskZone.UNKNOWN
    assert "activity.uninstall_signal" in result.missing_evidence
    assert "feedback.rating" in result.missing_evidence
    assert "feedback.open_complaints" in result.missing_evidence


def test_known_no_rating_can_be_green_but_not_a_referral_candidate() -> None:
    payload = facts_payload()
    payload["feedback"]["rating"] = None
    result = assess(payload)
    assert result.zone is RetentionRiskZone.GREEN
    assert not result.referral_eligible


def test_referral_requires_more_than_four_features() -> None:
    payload = facts_payload()
    payload["activity"]["distinct_features"] = 4
    result = assess(payload)
    assert result.zone is RetentionRiskZone.GREEN
    assert not result.referral_eligible


def test_risk_ranking_does_not_include_unknown_green_or_departed_accounts() -> None:
    payload = facts_payload()
    green = assess(payload)
    payload["account_ref"] = "acct_" + "b" * 64
    payload["feedback"]["rating"] = 2
    yellow = assess(payload)
    payload["account_ref"] = "acct_" + "c" * 64
    payload["activity"]["cancellation_page_views"] = 2
    red = assess(payload)
    assert prioritize_retention_risks([green, yellow, red]) == [red, yellow]
    assert prioritize_retention_risks([green, yellow, red], limit=1) == [red]
    with pytest.raises(ValueError):
        prioritize_retention_risks([red], limit=0)


@pytest.mark.parametrize("field", ["phone", "email", "name", "child_id", "raw_payload", "gps"])
def test_purpose_bound_contract_rejects_unexpected_personal_data(field: str) -> None:
    payload = facts_payload()
    payload[field] = "not permitted"
    with pytest.raises(ValidationError, match="Extra inputs"):
        CustomerRetentionFacts.model_validate(payload)


@pytest.mark.parametrize("reference", ["12345", "child_123", "email@example.com"])
def test_contract_requires_purpose_specific_pseudonym_not_contact_or_raw_id(reference: str) -> None:
    payload = facts_payload()
    payload["account_ref"] = reference
    with pytest.raises(ValidationError, match="pattern"):
        CustomerRetentionFacts.model_validate(payload)


def test_contract_rejects_mixed_modes_duplicate_accounts_and_oversized_batch() -> None:
    payload = facts_payload()
    payload["mode"] = "live"
    with pytest.raises(ValidationError, match="must not be mixed"):
        CustomerRetentionFacts.model_validate(payload)
    payload["mode"] = "sandbox"
    with pytest.raises(ValidationError, match="once"):
        RetentionRiskBatch.model_validate({"facts": [payload, payload]})
    with pytest.raises(ValidationError):
        RetentionRiskBatch.model_validate({"facts": [payload] * 1_001})


def test_contract_rejects_naive_future_and_conflicting_evidence() -> None:
    payload = facts_payload()
    payload["collected_at"] = NOW.replace(tzinfo=None)
    with pytest.raises(ValidationError, match="timezone"):
        CustomerRetentionFacts.model_validate(payload)
    payload = facts_payload()
    payload["feedback"]["observed_at"] = NOW + timedelta(hours=1)
    with pytest.raises(ValidationError, match="after collection"):
        CustomerRetentionFacts.model_validate(payload)
    payload = facts_payload()
    payload["activity"]["last_open_at"] = NOW + timedelta(seconds=1)
    with pytest.raises(ValidationError, match="after the evidence window"):
        CustomerRetentionFacts.model_validate(payload)
    payload = facts_payload()
    payload["activity"]["last_open_at"] = None
    with pytest.raises(ValidationError, match="conflict"):
        CustomerRetentionFacts.model_validate(payload)


def test_evaluation_rejects_clock_errors_and_invalid_thresholds() -> None:
    facts = CustomerRetentionFacts.model_validate(facts_payload())
    with pytest.raises(ValueError, match="future"):
        assess_retention_risk(facts, now=NOW - timedelta(seconds=1), configuration=CONFIGURATION)
    with pytest.raises(ValueError, match="timezone"):
        assess_retention_risk(facts, now=NOW.replace(tzinfo=None), configuration=CONFIGURATION)
    with pytest.raises(ValidationError, match="longer"):
        RetentionRiskConfiguration(red_inactivity_days=2, yellow_inactivity_days=3)
