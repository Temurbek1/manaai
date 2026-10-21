"""Typed expiry policy only; no subscription discovery, sends, model or billing calls."""

from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.mana_ai.domain.conversion import (
    ConversionPolicy,
    ConversionProposal,
    ConversionSnapshot,
    conversion_reason,
    elapsed_free_days,
)

NOW = datetime(2026, 10, 22, 7, tzinfo=UTC)


def snapshot(**changes: Any) -> ConversionSnapshot:
    return ConversionSnapshot.model_validate(
        {
            "parent_id": "123",
            "event_id": uuid4(),
            "revision": 1,
            "observed_at": NOW,
            "subscription": "expired",
            "free_started_at": NOW - timedelta(days=3, hours=1),
            "free_access_ends_at": NOW - timedelta(hours=1),
            "agent_trial_given": True,
            "marketing_consent": True,
            "consent_observed_at": NOW - timedelta(days=10),
            "language": "ru",
            "timezone": "Asia/Samarkand",
            "last_active_at": NOW,
            "active_days_7d": 1,
            "sessions_7d": 1,
            "paywall_views_7d": 0,
        }
        | changes
    )


@pytest.mark.parametrize("subscription", ["free", "expired"])
@pytest.mark.parametrize("agent_trial_given", [False, True, None])
def test_fresh_confirmed_expiry_is_a_distinct_opt_in_reason_not_a_paid_conversion(
    subscription: str, agent_trial_given: bool | None
) -> None:
    account = snapshot(subscription=subscription, agent_trial_given=agent_trial_given)

    assert (
        conversion_reason(account, ConversionPolicy(), NOW, include_expired=True)
        == "free_access_expired"
    )
    assert account.subscription == subscription
    assert account.agent_trial_given is agent_trial_given
    assert elapsed_free_days(account, NOW) == 3
    assert "payment_id" not in account.model_dump()
    assert "purchase_id" not in account.model_dump()


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"subscription": "paid"}, "not_confirmed_free"),
        ({"subscription": "unknown"}, "not_confirmed_free"),
        ({"free_started_at": None}, "not_confirmed_free"),
        ({"free_access_ends_at": None}, "not_confirmed_free"),
        ({"free_access_ends_at": NOW + timedelta(hours=1)}, "not_confirmed_free"),
        ({"marketing_consent": False}, "no_marketing_consent"),
        ({"last_active_at": NOW - timedelta(days=3)}, "inactive_account"),
        (
            {"active_days_7d": 0, "sessions_7d": 0, "last_active_at": None},
            "inactive_account",
        ),
        (
            {
                "observed_at": NOW - timedelta(seconds=901),
                "last_active_at": NOW - timedelta(hours=1),
            },
            "snapshot_not_current",
        ),
        ({"observed_at": NOW + timedelta(seconds=121)}, "snapshot_not_current"),
    ],
)
def test_expiry_keeps_existing_freshness_consent_activity_and_explicit_status_boundaries(
    changes: dict[str, Any], expected: str
) -> None:
    assert (
        conversion_reason(snapshot(**changes), ConversionPolicy(), NOW, include_expired=True)
        == expected
    )


def test_clock_crossing_expiry_requires_a_new_backend_observation() -> None:
    account = snapshot(
        subscription="free",
        observed_at=NOW - timedelta(minutes=2),
        last_active_at=NOW - timedelta(minutes=2),
        free_access_ends_at=NOW - timedelta(minutes=1),
    )

    assert (
        conversion_reason(account, ConversionPolicy(), NOW, include_expired=True)
        == "free_access_expiry_not_confirmed"
    )
    confirmed = account.model_copy(update={"observed_at": NOW, "revision": 2})
    assert (
        conversion_reason(confirmed, ConversionPolicy(), NOW, include_expired=True)
        == "free_access_expired"
    )


def test_future_dated_observation_cannot_announce_expiry_before_it_happens() -> None:
    account = snapshot(
        observed_at=NOW + timedelta(seconds=60),
        free_access_ends_at=NOW + timedelta(seconds=30),
    )
    assert (
        conversion_reason(account, ConversionPolicy(), NOW, include_expired=True)
        == "free_access_expiry_not_confirmed"
    )


@pytest.mark.parametrize("seconds_after_expiry", [0, 1, 7 * 86400])
def test_expiry_outreach_window_includes_exact_boundaries(seconds_after_expiry: int) -> None:
    ended = NOW - timedelta(seconds=seconds_after_expiry)
    account = snapshot(free_started_at=ended - timedelta(days=3), free_access_ends_at=ended)
    assert (
        conversion_reason(account, ConversionPolicy(), NOW, include_expired=True)
        == "free_access_expired"
    )


@pytest.mark.parametrize("window_days", [1, 7, 30])
def test_expiry_outreach_does_not_reopen_an_old_period_after_its_configured_window(
    window_days: int,
) -> None:
    ended = NOW - timedelta(days=window_days, microseconds=1)
    account = snapshot(free_started_at=ended - timedelta(days=3), free_access_ends_at=ended)
    assert (
        conversion_reason(
            account,
            ConversionPolicy(expired_free_access_window_days=window_days),
            NOW,
            include_expired=True,
        )
        == "free_access_expiry_window_elapsed"
    )


@pytest.mark.parametrize("invalid_window", [0, 31, True, 7.0, "7"])
def test_expiry_window_has_explicit_strict_server_bounds(invalid_window: object) -> None:
    with pytest.raises(ValidationError):
        ConversionPolicy.model_validate({"expired_free_access_window_days": invalid_window})


@pytest.mark.parametrize(
    ("days", "active_days", "sessions", "paywall_views", "expected"),
    [
        (7, 1, 1, 0, "seven_day_free_use"),
        (2, 2, 3, 1, "hot_free_account"),
        (2, 1, 1, 0, "not_yet_eligible"),
        (0, 2, 3, 1, "not_yet_eligible"),
    ],
)
@pytest.mark.parametrize("include_expired", [False, True])
def test_accounts_without_an_end_date_preserve_existing_seven_day_and_hot_policy(
    days: int,
    active_days: int,
    sessions: int,
    paywall_views: int,
    expected: str,
    include_expired: bool,
) -> None:
    account = snapshot(
        subscription="free",
        free_started_at=NOW - timedelta(days=days),
        free_access_ends_at=None,
        active_days_7d=active_days,
        sessions_7d=sessions,
        paywall_views_7d=paywall_views,
    )
    assert (
        conversion_reason(account, ConversionPolicy(), NOW, include_expired=include_expired)
        == expected
    )


def test_default_callers_never_acquire_the_expiry_reason_from_old_free_snapshots() -> None:
    account = snapshot(subscription="free", free_started_at=NOW - timedelta(days=7))
    original = account.model_dump_json()
    assert conversion_reason(account, ConversionPolicy(), NOW) == "seven_day_free_use"
    assert (
        conversion_reason(account, ConversionPolicy(), NOW, include_expired=False)
        == "seven_day_free_use"
    )
    assert account.model_dump_json() == original
    assert conversion_reason(snapshot(), ConversionPolicy(), NOW) == "not_confirmed_free"


@pytest.mark.parametrize("reason", ["seven_day_free_use", "hot_free_account"])
def test_old_proposal_payloads_round_trip_without_new_fields_or_rewritten_reasons(
    reason: str,
) -> None:
    payload: dict[str, Any] = {
        "proposal_id": str(uuid4()),
        "parent_id": "123",
        "snapshot_revision": 1,
        "reason": reason,
        "status": "published",
        "offer": {
            "kind": "free_premium_days",
            "offer_id": "fake-trial",
            "approval_reference": "fake-owner-approval",
            "valid_from": NOW - timedelta(days=1),
            "valid_until": NOW + timedelta(days=1),
            "grant_days": 3,
            "priority": 0,
        },
        "created_at": NOW,
        "published_at": NOW,
        "turn_id": 1,
        "closed_reason": None,
    }
    original = ConversionProposal.model_validate(payload).model_dump_json()
    decoded = ConversionProposal.model_validate_json(original)
    assert decoded.model_dump_json() == original
    assert decoded.reason == reason
    assert set(decoded.model_dump()) == set(payload)


def test_elapsed_free_days_stops_at_the_actual_end_not_later_contact_time() -> None:
    account = snapshot()
    assert elapsed_free_days(account, NOW) == 3
    assert elapsed_free_days(account, NOW + timedelta(days=30)) == 3
    assert elapsed_free_days(account, account.free_started_at or NOW) == 0
    assert elapsed_free_days(account, NOW - timedelta(days=30)) == 0


def test_elapsed_free_days_uses_elapsed_time_not_local_calendar_day_changes() -> None:
    local_zone = timezone(timedelta(hours=5))
    account = snapshot(
        free_started_at=datetime(2026, 10, 18, 23, tzinfo=local_zone),
        free_access_ends_at=datetime(2026, 10, 21, 22, tzinfo=local_zone),
    )
    assert elapsed_free_days(account, NOW) == 2
    ongoing = snapshot(subscription="free", free_access_ends_at=None)
    assert elapsed_free_days(ongoing, NOW) == 3


def test_elapsed_free_days_cannot_invent_missing_start_or_assume_a_naive_clock() -> None:
    with pytest.raises(ValueError, match="confirmed start"):
        elapsed_free_days(snapshot(free_started_at=None), NOW)
    with pytest.raises(ValueError, match="aware"):
        elapsed_free_days(snapshot(), NOW.replace(tzinfo=None))
