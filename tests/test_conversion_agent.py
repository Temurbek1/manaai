"""Fictional adult accounts only; no live providers, Firebase or real grants."""

import asyncio
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.conversion import ConversionService
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.application.parent_touch_offers import render_parent_offer
from app.mana_ai.domain.conversion import (
    ConversionOutcome,
    ConversionPolicy,
    ConversionSnapshot,
    PaidConversionOffer,
    TrialConversionOffer,
    conversion_reason,
)
from app.services.conversion_store import SqliteClosedConversionStore, SqliteConversionStore
from app.services.reviewed_message_store import SqliteReviewedMessageStore
from tests.test_child_safety_store import limits
from tests.test_family_agent_queue import intent
from tests.test_parent_chat import NOW, Children, Model, message


def paid_offer(**changes: Any) -> PaidConversionOffer:
    return PaidConversionOffer.model_validate(
        {
            "offer_id": "approved-15",
            "billing_offer_id": "billing-15",
            "approval_reference": "synthetic-owner-approval",
            "valid_from": NOW - timedelta(days=1),
            "valid_until": NOW + timedelta(days=60),
            "currency": "UZS",
            "list_price_minor": 10000,
            "price_minor": 8500,
            "discount_percent": 15,
            "duration_days": 30,
            "auto_renew": False,
            "checkout_path": "/subscriptions/synthetic-plan",
        }
        | changes
    )


def trial_offer(**changes: Any) -> TrialConversionOffer:
    return TrialConversionOffer.model_validate(
        {
            "offer_id": "trial-3",
            "approval_reference": "synthetic-owner-approval",
            "valid_from": NOW - timedelta(days=1),
            "valid_until": NOW + timedelta(days=60),
            "grant_days": 3,
        }
        | changes
    )


def snapshot(**changes: Any) -> ConversionSnapshot:
    return ConversionSnapshot.model_validate(
        {
            "parent_id": "123",
            "event_id": uuid4(),
            "revision": 1,
            "observed_at": NOW,
            "subscription": "free",
            "free_started_at": NOW - timedelta(days=7),
            "free_access_ends_at": NOW + timedelta(days=1),
            "agent_trial_given": False,
            "marketing_consent": True,
            "consent_observed_at": NOW - timedelta(days=10),
            "language": "ru",
            "timezone": "Asia/Samarkand",
            "last_active_at": NOW,
            "active_days_7d": 3,
            "sessions_7d": 4,
            "paywall_views_7d": 1,
        }
        | changes
    )


async def repository(
    path: Path, *, trial: bool = False, policy: ConversionPolicy | None = None
) -> SqliteConversionStore:
    store = SqliteConversionStore(
        path,
        conversion_policy=policy or ConversionPolicy(),
        conversion_offers=(trial_offer(),) if trial else (paid_offer(),),
        limits=limits(),
        daily_limit=2000,
        timezone="Asia/Samarkand",
    )
    await store.initialize()
    return store


def touch(store: SqliteConversionStore) -> tuple[ParentTouchService, Model, Children]:
    model, children = Model(), Children()
    return (
        ParentTouchService(
            store=store,
            children=children,
            model=model,
            clock=lambda: NOW,
            max_output_tokens=512,
            history_turn_limit=2,
            conversion=ConversionService(store, clock=lambda: NOW),
        ),
        model,
        children,
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, "seven_day_free_use"),
        ({"free_started_at": NOW - timedelta(days=2)}, "hot_free_account"),
        ({"free_started_at": NOW - timedelta(hours=12)}, "not_yet_eligible"),
        ({"subscription": "paid"}, "not_confirmed_free"),
        ({"subscription": "unknown"}, "not_confirmed_free"),
        ({"marketing_consent": False}, "no_marketing_consent"),
        ({"last_active_at": NOW - timedelta(days=3)}, "inactive_account"),
        (
            {"observed_at": NOW - timedelta(hours=1), "last_active_at": NOW - timedelta(hours=1)},
            "snapshot_not_current",
        ),
    ],
)
def test_account_policy_uses_only_confirmed_adult_facts(
    changes: dict[str, Any], expected: str
) -> None:
    assert conversion_reason(snapshot(**changes), ConversionPolicy(), NOW) == expected


@pytest.mark.parametrize(
    "changes",
    [
        {"discount_percent": 16},
        {"price_minor": 0},
        {"auto_renew": True},
        {"checkout_path": "https://untrusted.invalid/buy"},
        {"valid_until": NOW - timedelta(days=2)},
    ],
)
def test_invalid_or_misleading_offer_terms_fail(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        paid_offer(**changes)


async def test_end_to_end_one_speaker_one_chat_without_inference_or_provider_receipt(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "family.db")
    service, model, children = touch(store)
    event = snapshot()
    admission = await service.conversion.observe(event) if service.conversion else None
    assert admission and admission.proposal
    assert await service.process_conversion()
    assert not await service.process_conversion()
    assert service.conversion
    saved = await service.conversion.proposal("123", admission.proposal.proposal_id)
    assert saved.status == "published" and saved.turn_id
    history = await service.read_touch_history("123", before=None, limit=20)
    assert len(history.messages) == 1 and history.messages[0].role == "assistant"
    assert "15%" in history.messages[0].content and "85.00 UZS" in history.messages[0].content
    assert history.quota.used_tokens == history.quota.reserved_tokens == 0
    assert model.calls == model.counts == children.calls == 0
    with store._connect() as connection:
        row = connection.execute("SELECT * FROM parent_chat_turns").fetchone()
        assert row["result"] is None and row["input_tokens"] is None and row["message"] == ""
        assert (
            connection.execute("SELECT COUNT(*) FROM child_safety_parent_events").fetchone()[0] == 0
        )
    assert await service.conversion.observe(event) == admission
    assert not (await service.read_touch_history("456", before=None, limit=20)).messages


async def test_concurrent_processes_and_restart_publish_once(tmp_path: Path) -> None:
    path = tmp_path / "race.db"
    first, second = await repository(path), await repository(path)
    event = snapshot()
    admitted = await asyncio.gather(
        first.ingest_conversion(event, NOW), second.ingest_conversion(event, NOW)
    )
    assert admitted[0] == admitted[1]
    results = await asyncio.gather(
        first.publish_conversion(NOW, render_parent_offer),
        second.publish_conversion(NOW, render_parent_offer),
    )
    assert sorted(results) == [False, True]
    restarted = await repository(path)
    assert not await restarted.publish_conversion(NOW, render_parent_offer)
    assert len((await restarted.history("123", before=None, limit=100, now=NOW)).messages) == 1


async def test_paid_update_stale_data_and_revocation_fence_delivery(tmp_path: Path) -> None:
    store = await repository(tmp_path / "state.db")
    event = snapshot()
    admitted = await store.ingest_conversion(event, NOW)
    assert admitted.proposal
    with pytest.raises(ParentChatError, match="conversion_event_conflict"):
        await store.ingest_conversion(event.model_copy(update={"subscription": "paid"}), NOW)
    paid = snapshot(revision=2, subscription="paid")
    assert (await store.ingest_conversion(paid, NOW)).proposal is None
    assert not await store.publish_conversion(NOW, render_parent_offer)
    assert (
        await store.conversion_proposal("123", admitted.proposal.proposal_id)
    ).status == "cancelled"
    with pytest.raises(ParentChatError, match="out_of_order"):
        await store.ingest_conversion(snapshot(revision=1), NOW)
    fresh = await store.ingest_conversion(snapshot(revision=3), NOW)
    assert fresh.proposal
    assert not await store.publish_conversion(NOW + timedelta(minutes=16), render_parent_offer)
    renewed = await store.ingest_conversion(snapshot(revision=4), NOW)
    assert renewed.proposal
    store._conversion_offers = {}
    assert not await store.publish_conversion(NOW, render_parent_offer)


async def test_questions_quiet_hours_and_server_limit_take_priority(tmp_path: Path) -> None:
    store = await repository(
        tmp_path / "queue.db", policy=ConversionPolicy(global_daily_contact_limit=1)
    )
    await store.ingest_conversion(snapshot(), NOW)
    await store.enqueue(intent(), NOW)
    assert not await store.publish_conversion(NOW, render_parent_offer)
    await store.ingest_conversion(snapshot(parent_id="456"), NOW)
    assert await store.publish_conversion(NOW, render_parent_offer)
    assert not await store.publish_conversion(NOW, render_parent_offer)
    night = NOW + timedelta(hours=6)
    store2 = await repository(tmp_path / "night.db")
    await store2.ingest_conversion(snapshot(observed_at=night, last_active_at=night), night)
    assert not await store2.publish_conversion(night, render_parent_offer)


async def test_cooldown_opt_out_and_actual_payment_are_distinct(tmp_path: Path) -> None:
    store = await repository(tmp_path / "outcomes.db")
    event = snapshot()
    admission = await store.ingest_conversion(event, NOW)
    assert admission.proposal
    await store.publish_conversion(NOW, render_parent_offer)
    interested = ConversionOutcome(
        parent_id="123",
        event_id=uuid4(),
        proposal_id=admission.proposal.proposal_id,
        observed_at=NOW,
        kind="interested",
    )
    assert (await store.conversion_outcome(interested, NOW)).status == "interested"
    assert (await store.ingest_conversion(snapshot(revision=2), NOW)).decision == "contact_cooldown"
    paid = ConversionOutcome(
        parent_id="123",
        event_id=uuid4(),
        proposal_id=admission.proposal.proposal_id,
        observed_at=NOW,
        kind="payment_confirmed",
        payment_id="receipt-1",
        amount_minor=8500,
        currency="UZS",
        billing_offer_id="billing-15",
    )
    result = await store.conversion_outcome(paid, NOW)
    assert result.status == "converted" and await store.conversion_outcome(paid, NOW) == result
    later = NOW + timedelta(days=8)
    # A newer free-state event cannot undo a recorded payment and start remarketing.
    refreshed = snapshot(revision=3, observed_at=later, last_active_at=later)
    assert (await store.ingest_conversion(refreshed, later)).decision == "already_converted"
    await store.suppress_conversion("456", NOW)
    blocked = await store.ingest_conversion(snapshot(parent_id="456"), NOW)
    assert blocked.decision == "parent_opted_out" and blocked.proposal is None


async def test_explicit_opt_out_works_even_when_paid_chat_cannot_admit(tmp_path: Path) -> None:
    store = await repository(tmp_path / "optout.db")
    service, _, _ = touch(store)
    await store.ingest_conversion(snapshot(), NOW)
    with store._transaction() as connection:
        connection.execute(
            "INSERT INTO parent_chat_quota(parent_id,day,used,attempts) VALUES(?,?,2000,0)",
            ("123", NOW.date().isoformat()),
        )
    with pytest.raises(ParentChatError, match="daily_token_budget_exceeded"):
        await service.send(message(text="Не присылай предложения"))
    assert not await service.process_conversion()
    assert (await store.conversion_proposals("123", 0, 20)).proposals[0].status != "published"


async def test_conflicting_replayed_text_cannot_create_a_new_opt_out(tmp_path: Path) -> None:
    store = await repository(tmp_path / "conflicting-optout.db")
    service, _, _ = touch(store)
    original = message(text="Салом")
    await service.send(original)
    with pytest.raises(ParentChatError, match="request_id_conflict"):
        await service.send(original.model_copy(update={"message": "stop offers"}))
    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversion_opt_outs").fetchone()[0] == 0


async def test_only_expired_unsubmitted_questions_stop_blocking_offers(tmp_path: Path) -> None:
    store = await repository(tmp_path / "expired-question.db")
    question = intent().model_copy(update={"expires_at": NOW + timedelta(seconds=60)})
    await store.enqueue(question, NOW)
    later = NOW + timedelta(minutes=2)
    await store.ingest_conversion(snapshot(observed_at=later, last_active_at=later), later)
    assert await store.publish_conversion(later, render_parent_offer)
    # Held/possibly visible questions remain fences even after their expiry.
    other = await repository(tmp_path / "held-question.db")
    receipt = await other.enqueue(question, NOW)
    with other._transaction() as connection:
        connection.execute(
            "UPDATE family_questions SET status='held' WHERE question_id=?",
            (str(receipt.question.question_id),),
        )
    await other.ingest_conversion(snapshot(observed_at=later, last_active_at=later), later)
    assert not await other.publish_conversion(later, render_parent_offer)


async def test_trial_needs_verified_eligibility_and_is_never_a_payment(tmp_path: Path) -> None:
    store = await repository(tmp_path / "trial.db", trial=True)
    denied = await store.ingest_conversion(snapshot(agent_trial_given=None), NOW)
    assert denied.decision == "no_approved_offer" and denied.proposal is None
    accepted = await store.ingest_conversion(snapshot(revision=2), NOW)
    assert accepted.proposal
    await store.publish_conversion(NOW, render_parent_offer)
    paid = ConversionOutcome(
        parent_id="123",
        event_id=uuid4(),
        proposal_id=accepted.proposal.proposal_id,
        observed_at=NOW,
        kind="payment_confirmed",
        payment_id="not-a-real-payment",
        amount_minor=1,
        currency="UZS",
        billing_offer_id="not-a-paid-offer",
    )
    with pytest.raises(ParentChatError, match="free_days_are_not_a_paid_conversion"):
        await store.conversion_outcome(paid, NOW)


async def test_additive_v6_migration_preserves_history_and_closed_reader(tmp_path: Path) -> None:
    path = tmp_path / "migration.db"
    original = SqliteReviewedMessageStore(
        path, limits=limits(), daily_limit=2000, timezone="Asia/Samarkand"
    )
    await original.initialize()
    request = message()
    admitted = await original.admit(request, NOW)
    with original._connect() as connection:
        before = [tuple(row) for row in connection.execute("SELECT * FROM parent_chat_turns")]
    current = await repository(path)
    with current._connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
        assert [
            tuple(row) for row in connection.execute("SELECT * FROM parent_chat_turns")
        ] == before
    with pytest.raises(ParentChatError, match="request_in_progress"):
        await current.admit(request, NOW)
    assert admitted.turn_id == 1
    closed = SqliteClosedConversionStore(
        path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
    )
    await closed.initialize()
    with pytest.raises(ParentChatError):
        await closed.admit(message(parent_id="456"), NOW)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 7


@pytest.mark.parametrize("language", ["ru", "uz-Latn", "uz-Cyrl", "en"])
def test_parent_touch_templates_keep_exact_paid_and_free_terms(language: Any) -> None:
    paid = render_parent_offer(paid_offer(auto_renew=True, renewal_price_minor=10000), 7, language)
    assert "15%" in paid and "85.00 UZS" in paid and "100.00 UZS" in paid
    free = render_parent_offer(trial_offer(), 7, language)
    assert "Maxsus" in free and "3" in free and "%" not in free and "UZS" not in free
