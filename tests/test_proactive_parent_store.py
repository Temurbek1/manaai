"""Synthetic families only; these checks perform no network/model/push calls."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.application.parent_touch_offers import render_parent_offer
from app.mana_ai.domain.chat import ChatTokens
from app.mana_ai.domain.conversion import ConversionOffer, ConversionOutcome, ConversionPolicy
from app.mana_ai.domain.family_agents import ParentTouchDeliveryTurn
from app.mana_ai.domain.proactive_parent import (
    ParentContactContext,
    ParentPushOutcome,
    ParentPushPurpose,
)
from app.services.conversion_store import SqliteClosedConversionStore
from app.services.proactive_parent_store import (
    SqliteClosedProactiveParentStore,
    SqliteProactiveParentStore,
)
from tests.test_child_safety_store import limits
from tests.test_conversion_agent import paid_offer, snapshot
from tests.test_conversion_agent import repository as conversion_repository
from tests.test_family_agent_queue import intent
from tests.test_parent_chat import NOW, message


def contact(**changes: Any) -> ParentContactContext:
    return ParentContactContext.model_validate(
        {
            "parent_id": "123",
            "event_id": uuid4(),
            "revision": 1,
            "observed_at": NOW,
            "valid_until": NOW + timedelta(hours=2),
            "language": "ru",
            "timezone": "Asia/Samarkand",
            "safety_chat_consent": True,
            "safety_push_consent": True,
            "marketing_push_consent": True,
        }
        | changes
    )


async def repository(
    path: Path, *, offers: tuple[ConversionOffer, ...] | None = None, **changes: Any
) -> SqliteProactiveParentStore:
    store = SqliteProactiveParentStore(
        path,
        conversion_policy=ConversionPolicy(global_daily_contact_limit=1000),
        conversion_offers=(paid_offer(),) if offers is None else offers,
        limits=limits(),
        daily_limit=2000,
        timezone="Asia/Samarkand",
        **changes,
    )
    await store.initialize()
    return store


async def host_publication(
    store: SqliteProactiveParentStore,
    *,
    parent: str = "123",
    purpose: ParentPushPurpose = "safety",
) -> int:
    """Test-only host template publication, no fabricated provider/usage receipt."""
    with store._transaction() as connection:
        cursor = connection.execute(
            "INSERT INTO parent_chat_turns(parent_id,request_id,message,request_digest,day,"
            "status,reserved,created_at,updated_at,answer,model) "
            "VALUES(?,?,'','unit-host-template',?,'completed',0,?,?,?,'unit-host-template')",
            (
                parent,
                str(uuid4()),
                NOW.date().isoformat(),
                NOW.isoformat(),
                NOW.isoformat(),
                "Private fictional child facts, never a notification body",
            ),
        )
        assert cursor.lastrowid
        store._queue_push(connection, parent, cursor.lastrowid, purpose, NOW)
        return cursor.lastrowid


async def delivery(store: SqliteProactiveParentStore) -> ParentTouchDeliveryTurn:
    selected = await store.next_delivery(NOW)
    assert selected is not None
    return ParentTouchDeliveryTurn(parent_id=selected.parent_id, request_id=selected.request_id)


@pytest.mark.parametrize("language", ["ru", "uz-Latn", "uz-Cyrl", "en"])
async def test_first_ever_safety_message_and_push_share_one_chat_and_exact_locale(
    tmp_path: Path, language: Any
) -> None:
    store = await repository(tmp_path / "family.db")
    await store.ingest_contact_context(contact(language=language), NOW)
    question = (await store.enqueue(intent(), NOW)).question
    request = await delivery(store)
    assert await store.history("123", before=None, limit=20, now=NOW)
    admitted = await store.admit(request, NOW)
    assert admitted.message == ""
    assert await store.language_hint("123", admitted.turn_id) == language
    assert await store.language_hint("456", admitted.turn_id) is None
    await store.submit(admitted, reserved_tokens=200, now=NOW)
    result = await store.settle(
        admitted,
        receipt=ChatModelReceipt(
            usage=ChatTokens(input_tokens=100, output_tokens=20),
            model="fake-model",
            answer="Synthetic single specialist question?",
            completed=True,
            question_id=question.question_id,
        ),
        now=NOW,
        history_turns=0,
        context_at=NOW,
    )
    assert await store.admit(request, NOW + timedelta(days=1)) == result_turn(
        store, admitted.turn_id
    )
    history = await store.history("123", before=None, limit=20, now=NOW)
    assert len(history.messages) == 1 and history.messages[0].role == "assistant"
    assert result.usage.total == history.quota.used_tokens == 120
    page = await store.pushes("123")
    assert len(page.pushes) == 1 and page.pushes[0].turn_id == admitted.turn_id
    assert page.pushes[0].status == "queued"
    assert (await store.pushes("456")).pushes == []
    claim = await store.claim_push(NOW)
    assert claim and claim.notification.push_id == page.pushes[0].push_id
    assert claim.message.parent_id == "123" and claim.message.title == "MANA"
    assert "Synthetic" not in claim.message.description and "child" not in claim.description
    assert await store.claim_push(NOW) is None
    with store._connect() as connection:
        metadata = connection.execute("SELECT * FROM family_turn_metadata").fetchone()
        assert metadata["language_turn_id"] == -1
        assert metadata["language_reference"] == language
        assert (
            connection.execute("SELECT COUNT(*) FROM child_safety_parent_events").fetchone()[0] == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM parent_contact_turns").fetchone()[0] == 1


def result_turn(store: SqliteProactiveParentStore, turn_id: int) -> Any:
    with store._connect() as connection:
        return store._turn(
            connection.execute("SELECT * FROM parent_chat_turns WHERE id=?", (turn_id,)).fetchone()
        )


async def test_context_event_replay_never_regrants_revoked_or_expired_permissions(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "context.db")
    original = contact()
    assert await store.ingest_contact_context(original, NOW) == original
    revoked = contact(revision=2, safety_chat_consent=False, safety_push_consent=False)
    await store.ingest_contact_context(revoked, NOW)
    assert await store.ingest_contact_context(original, NOW + timedelta(days=10)) == original
    assert await store.contact_context("123", NOW) == revoked
    assert await store.contact_context("123", NOW + timedelta(days=1)) is None
    assert await store.contact_context("456", NOW) is None
    with pytest.raises(ParentChatError, match="parent_contact_event_conflict"):
        await store.ingest_contact_context(original.model_copy(update={"language": "en"}), NOW)
    with pytest.raises(ParentChatError, match="parent_contact_context_out_of_order"):
        await store.ingest_contact_context(contact(), NOW)
    with pytest.raises(ParentChatError, match="parent_contact_context_in_future"):
        await store.ingest_contact_context(
            contact(parent_id="456", observed_at=NOW + timedelta(minutes=3)), NOW
        )
    with pytest.raises(ParentChatError, match="parent_contact_context_expired"):
        await store.ingest_contact_context(contact(parent_id="456"), NOW + timedelta(days=1))
    await store.enqueue(intent(), NOW)
    assert await store.next_delivery(NOW) is None


@pytest.mark.parametrize(
    "field", ["safety_chat_consent", "safety_push_consent", "marketing_push_consent"]
)
def test_permissions_have_no_implicit_defaults(field: str) -> None:
    source = contact().model_dump()
    del source[field]
    with pytest.raises(ValidationError):
        ParentContactContext.model_validate(source)
    with pytest.raises(ValidationError):
        contact(**{field: "yes"})


async def test_first_contact_requires_explicit_context_even_when_historical_parent_text_exists(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "consent.db")
    old = await store.admit(message(text="Salom"), NOW)
    await store.fail(old, code="synthetic_before_generation")
    await store.enqueue(intent(), NOW)
    assert await store.next_delivery(NOW) is None
    with pytest.raises(ParentChatError, match="parent_proactive_chat_not_authorized"):
        await store.admit(ParentTouchDeliveryTurn(parent_id="123", request_id=uuid4()), NOW)
    assert await store.language_hint("123", old.turn_id) is None
    await store.ingest_contact_context(contact(language="en"), NOW)
    assert await store.next_delivery(NOW) is not None


async def test_revocation_after_submission_accounts_verified_cost_but_blocks_publication(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "late.db")
    await store.ingest_contact_context(contact(), NOW)
    question = (await store.enqueue(intent(), NOW)).question
    admitted = await store.admit(await delivery(store), NOW)
    await store.submit(admitted, reserved_tokens=200, now=NOW)
    await store.ingest_contact_context(contact(revision=2, safety_chat_consent=False), NOW)
    with pytest.raises(ParentChatError, match="model_answer_unavailable"):
        await store.settle(
            admitted,
            receipt=ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=20),
                model="fake",
                answer="Must not publish",
                completed=True,
                question_id=question.question_id,
            ),
            now=NOW,
            history_turns=0,
            context_at=NOW,
        )
    history = await store.history("123", before=None, limit=20, now=NOW)
    assert history.messages == [] and history.quota.used_tokens == 120
    assert (await store.pushes("123")).pushes == []
    await store.ingest_contact_context(contact(revision=3), NOW)
    assert await store.next_delivery(NOW + timedelta(days=1)) is None


async def test_new_contact_revision_and_midnight_do_not_retry_unknown_safety_turn(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unknown.db"
    store = await repository(path)
    await store.ingest_contact_context(contact(), NOW)
    await store.enqueue(intent(), NOW)
    admitted = await store.admit(await delivery(store), NOW)
    await store.submit(admitted, reserved_tokens=200, now=NOW)
    await store.fail(admitted, code="synthetic_lost_receipt", unknown=True)
    await store.ingest_contact_context(
        contact(revision=2, valid_until=NOW + timedelta(days=3)), NOW
    )
    restarted = await repository(path)
    assert await restarted.next_delivery(NOW + timedelta(days=1)) is None
    quota = await restarted.quota("123", NOW)
    assert quota.reserved_tokens == 200 and quota.blocked_by_unresolved_request
    assert (await restarted.pushes("123")).pushes == []


async def test_conversion_first_message_queues_atomic_generic_push_without_inference(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "conversion.db")
    await store.ingest_contact_context(contact(language="uz-Latn"), NOW)
    accepted = await store.ingest_conversion(snapshot(language="uz-Latn"), NOW)
    assert accepted.proposal
    assert await store.publish_conversion(NOW, render_parent_offer)
    assert not await store.publish_conversion(NOW, render_parent_offer)
    history = await store.history("123", before=None, limit=20, now=NOW)
    assert len(history.messages) == 1 and history.messages[0].role == "assistant"
    assert "15%" in history.messages[0].content
    page = await store.pushes("123")
    assert len(page.pushes) == 1 and page.pushes[0].purpose == "marketing"
    claim = await store.claim_push(NOW)
    assert claim and claim.message.description == "MANA chatida yangi xabar bor. Ilovani oching."
    assert "15%" not in claim.description
    with store._connect() as connection:
        row = connection.execute("SELECT * FROM parent_chat_turns").fetchone()
        assert row["message"] == "" and row["result"] is None and row["input_tokens"] is None
        assert connection.execute("SELECT COUNT(*) FROM child_safety_jobs").fetchone()[0] == 0


@pytest.mark.parametrize("context_changes", [None, {"marketing_push_consent": False}])
async def test_chat_publication_does_not_manufacture_or_require_notification_permission(
    tmp_path: Path, context_changes: dict[str, Any] | None
) -> None:
    store = await repository(tmp_path / "no-push.db")
    if context_changes is not None:
        await store.ingest_contact_context(contact(**context_changes), NOW)
    await store.ingest_conversion(snapshot(), NOW)
    assert await store.publish_conversion(NOW, render_parent_offer)
    assert len((await store.history("123", before=None, limit=20, now=NOW)).messages) == 1
    assert (await store.pushes("123")).pushes == []


async def test_publication_and_push_are_one_transaction_on_outbox_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = await repository(tmp_path / "atomic.db")
    await store.ingest_contact_context(contact(), NOW)
    admission = await store.ingest_conversion(snapshot(), NOW)
    assert admission.proposal

    def reject(*args: object) -> None:
        raise ParentChatError("synthetic_sql_refusal", 503)

    monkeypatch.setattr(store, "_queue_push", reject)
    with pytest.raises(ParentChatError, match="synthetic_sql_refusal"):
        await store.publish_conversion(NOW, render_parent_offer)
    assert (await store.history("123", before=None, limit=20, now=NOW)).messages == []
    assert (await store.pushes("123")).pushes == []
    assert (
        await store.conversion_proposal("123", admission.proposal.proposal_id)
    ).status == "queued"


@pytest.mark.parametrize(
    "outcome",
    [
        ParentPushOutcome(status="queued_by_provider", queued_devices=2),
        ParentPushOutcome(status="not_queued", queued_devices=0),
        ParentPushOutcome(status="not_queued", error_code="parent_push_not_authorized"),
        ParentPushOutcome(status="unknown", error_code="parent_push_outcome_unknown"),
    ],
)
async def test_claim_receipt_is_durable_idempotent_and_never_a_device_delivery(
    tmp_path: Path, outcome: ParentPushOutcome
) -> None:
    path = tmp_path / "receipt.db"
    store = await repository(path)
    await store.ingest_contact_context(contact(), NOW)
    turn_id = await host_publication(store)
    claims = await asyncio.gather(*(store.claim_push(NOW) for _ in range(4)))
    actual = [claim for claim in claims if claim is not None]
    assert len(actual) == 1
    claim = actual[0]
    assert claim.notification.turn_id == turn_id
    assert (await store.push("123", claim.notification.push_id)).status == "submitting"
    result = await store.finish_push(claim, outcome, NOW)
    assert result.status == outcome.status and result.queued_devices == outcome.queued_devices
    assert await store.finish_push(claim, outcome, NOW + timedelta(days=1)) == result
    assert await (await repository(path)).claim_push(NOW + timedelta(days=1)) is None
    with pytest.raises(ParentChatError, match="parent_push_not_found"):
        await store.push("456", result.push_id)
    with pytest.raises(ParentChatError, match="parent_push_claim_mismatch"):
        await store.finish_push(replace(claim, claim_id=uuid4()), outcome, NOW)
    changed = (
        ParentPushOutcome(status="unknown")
        if outcome.status != "unknown"
        else ParentPushOutcome(status="not_queued")
    )
    with pytest.raises(ParentChatError, match="parent_push_receipt_already_final"):
        await store.finish_push(claim, changed, NOW)


async def test_lost_submitting_claim_survives_restart_status_reads_and_midnight_without_retry(
    tmp_path: Path,
) -> None:
    path = tmp_path / "lost.db"
    store = await repository(path)
    await store.ingest_contact_context(contact(), NOW)
    await host_publication(store)
    claim = await store.claim_push(NOW)
    assert claim
    current = await repository(path)
    assert (await current.push("123", claim.notification.push_id)).status == "submitting"
    assert len((await current.pushes("123")).pushes) == 1
    assert await current.claim_push(NOW + timedelta(days=1)) is None


@pytest.mark.parametrize("change", ["revoked", "expired", "language_changed"])
async def test_current_contact_scope_is_rechecked_before_push_claim(
    tmp_path: Path, change: str
) -> None:
    store = await repository(tmp_path / "recheck.db")
    await store.ingest_contact_context(contact(), NOW)
    await host_publication(store)
    if change == "revoked":
        await store.ingest_contact_context(contact(revision=2, safety_push_consent=False), NOW)
    if change == "language_changed":
        await store.ingest_contact_context(contact(revision=2, language="en"), NOW)
    assert await store.claim_push(NOW + timedelta(hours=2) if change == "expired" else NOW) is None
    assert (await store.pushes("123")).pushes[0].status == "suppressed"


async def test_push_attempt_cap_counts_unknown_and_rejected_claims_sql_atomically(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "cap.db", push_daily_attempt_limit=2)
    await store.ingest_contact_context(contact(), NOW)
    for _ in range(4):
        await host_publication(store)
    first, second, third = await asyncio.gather(*(store.claim_push(NOW) for _ in range(3)))
    claims = [claim for claim in (first, second, third) if claim is not None]
    assert len(claims) == 2
    await store.finish_push(claims[0], ParentPushOutcome(status="unknown"), NOW)
    await store.finish_push(claims[1], ParentPushOutcome(status="not_queued"), NOW)
    assert await store.claim_push(NOW) is None


async def test_bounded_candidate_scan_rotates_past_quiet_marketing_to_safety(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "rotation.db")
    for index in range(101):
        parent = str(index + 1)
        await store.ingest_contact_context(
            contact(parent_id=parent, timezone="America/New_York"), NOW
        )
        if index < 100:
            await store.ingest_conversion(snapshot(parent_id=parent), NOW)
            assert await store.publish_conversion(NOW, render_parent_offer)
        else:
            await host_publication(store, parent=parent, purpose="safety")
    assert await store.claim_push(NOW) is None
    claim = await store.claim_push(NOW)
    assert (
        claim and claim.notification.parent_id == "101" and claim.notification.purpose == "safety"
    )


async def test_queue_ceiling_suppresses_notification_without_rolling_back_chat(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "ceiling.db", push_queue_limit=1)
    await store.ingest_contact_context(contact(), NOW)
    await host_publication(store)
    await host_publication(store)
    assert [p.status for p in (await store.pushes("123")).pushes] == ["queued", "suppressed"]
    assert len((await store.history("123", before=None, limit=20, now=NOW)).messages) == 2


async def test_additive_v8_migration_and_closed_reader_preserve_old_unknown_holds(
    tmp_path: Path,
) -> None:
    path = tmp_path / "migration.db"
    previous = await conversion_repository(path)
    request = message()
    old = await previous.admit(request, NOW)
    await previous.submit(old, reserved_tokens=200, now=NOW)
    await previous.fail(old, code="synthetic_unknown", unknown=True)
    with previous._connect() as connection:
        before = [tuple(row) for row in connection.execute("SELECT * FROM parent_chat_turns")]
    current = await repository(path)
    with current._connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
        assert [
            tuple(row) for row in connection.execute("SELECT * FROM parent_chat_turns")
        ] == before
        assert connection.execute("SELECT COUNT(*) FROM parent_push_outbox").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM parent_contact_turns").fetchone()[0] == 0
    await current.ingest_contact_context(contact(), NOW)
    closed = SqliteClosedProactiveParentStore(
        path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
    )
    await closed.initialize()
    assert await closed.contact_context("123", NOW) is not None
    assert (await closed.pushes("123")).pushes == []
    assert not hasattr(closed, "claim_push") and not hasattr(closed, "publish_conversion")
    with pytest.raises(ParentChatError):
        await closed.admit(message(parent_id="456"), NOW)
    quota = await closed.quota("123", NOW)
    assert quota.reserved_tokens == 200 and quota.blocked_by_unresolved_request
    old_closed = SqliteClosedConversionStore(path, daily_limit=2000, timezone="Asia/Samarkand")
    with pytest.raises(RuntimeError):
        await old_closed.initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"


@pytest.mark.parametrize(
    "changes",
    [
        {"valid_until": NOW + timedelta(days=8)},
        {"valid_until": NOW},
        {"language": "default"},
        {"timezone": "not-a-timezone"},
        {"parent_id": "9999999999999999999"},
        {"safety_chat_consent": 1},
    ],
)
def test_unverified_recipient_presentation_or_permission_is_not_admissible(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        contact(**changes)


async def test_push_disable_preserves_chat_and_existing_outbox_without_claims(
    tmp_path: Path,
) -> None:
    path = tmp_path / "push-off.db"
    active = await repository(path)
    await active.ingest_contact_context(contact(), NOW)
    await host_publication(active)
    disabled = await repository(path, push_enabled=False)
    assert await disabled.claim_push(NOW) is None
    assert (await disabled.pushes("123")).pushes[0].status == "queued"
    await disabled.ingest_conversion(snapshot(), NOW)
    assert await disabled.publish_conversion(NOW, render_parent_offer)
    assert len((await disabled.history("123", before=None, limit=20, now=NOW)).messages) == 2
    assert len((await disabled.pushes("123")).pushes) == 1


async def test_proactive_disable_retains_v8_hints_but_fences_late_paid_decision(
    tmp_path: Path,
) -> None:
    path = tmp_path / "proactive-off.db"
    active = await repository(path)
    await active.ingest_contact_context(contact(language="uz-Cyrl"), NOW)
    question = (await active.enqueue(intent(), NOW)).question
    request = await delivery(active)
    admitted = await active.admit(request, NOW)
    await active.submit(admitted, reserved_tokens=200, now=NOW)
    disabled = await repository(path, proactive_enabled=False)
    assert await disabled.language_hint("123", admitted.turn_id) == "uz-Cyrl"
    assert await disabled.next_delivery(NOW) is None
    assert await disabled.claim_push(NOW) is None
    with pytest.raises(ParentChatError, match="model_answer_unavailable"):
        await disabled.settle(
            admitted,
            receipt=ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=20),
                model="fake",
                answer="Must not publish after deactivation",
                completed=True,
                question_id=question.question_id,
            ),
            now=NOW,
            history_turns=0,
            context_at=NOW,
        )
    assert (await disabled.quota("123", NOW)).used_tokens == 120
    assert (await disabled.history("123", before=None, limit=20, now=NOW)).messages == []
    closed = SqliteClosedProactiveParentStore(
        path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
    )
    await closed.initialize()
    assert await closed.language_hint("123", admitted.turn_id) == "uz-Cyrl"
    assert not hasattr(closed, "claim_push")


async def test_proactive_disable_uses_legacy_language_gate_without_first_contact(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "legacy-gate.db", proactive_enabled=False)
    await store.ingest_contact_context(contact(), NOW)
    await store.enqueue(intent(), NOW)
    assert await store.next_delivery(NOW) is None
    with pytest.raises(ParentChatError, match="parent_language_not_established"):
        await store.admit(ParentTouchDeliveryTurn(parent_id="123", request_id=uuid4()), NOW)


@pytest.mark.parametrize("offset", [-7, 7])
async def test_offset_contact_expiry_is_stored_utc_without_changing_frozen_context(
    tmp_path: Path, offset: int
) -> None:
    store = await repository(tmp_path / "offset.db")
    end = NOW + timedelta(minutes=30)
    original = contact(valid_until=end.astimezone(timezone(timedelta(hours=offset))))
    await store.ingest_contact_context(original, NOW)
    await host_publication(store)
    with store._connect() as connection:
        row = connection.execute(
            "SELECT expires_at,contact_digest FROM parent_push_outbox"
        ).fetchone()
        context = connection.execute(
            "SELECT payload,digest FROM parent_contact_contexts"
        ).fetchone()
        assert row["expires_at"] == end.isoformat()
        assert context["payload"] == original.model_dump_json()
        assert row["contact_digest"] == context["digest"]
    assert await store.claim_push(end) is None
    assert (await store.pushes("123")).pushes[0].status == "suppressed"


@pytest.mark.parametrize(
    "change",
    [
        "own_opt_out",
        "paid_snapshot",
        "paid_receipt_latch",
        "marketing_consent_revoked",
        "expired_offer",
        "revoked_catalog_offer",
        "declined_offer",
        "stale_account_facts",
    ],
)
async def test_unclaimed_marketing_push_loses_permission_without_erasing_published_chat(
    tmp_path: Path, change: str
) -> None:
    path = tmp_path / "marketing-revalidation.db"
    approved = paid_offer(
        valid_until=NOW + timedelta(minutes=1)
        if change == "expired_offer"
        else NOW + timedelta(days=1)
    )
    store = await repository(path, offers=(approved,))
    original_context = contact()
    await store.ingest_contact_context(original_context, NOW)
    admission = await store.ingest_conversion(snapshot(), NOW)
    assert admission.proposal
    assert await store.publish_conversion(NOW, render_parent_offer)
    published = await store.history("123", before=None, limit=20, now=NOW)
    assert len(published.messages) == 1
    assert (await store.pushes("123")).pushes[0].status == "queued"
    claim_at = NOW
    if change == "own_opt_out":
        await store.suppress_conversion("123", NOW)
    elif change == "paid_snapshot":
        await store.ingest_conversion(snapshot(revision=2, subscription="paid"), NOW)
    elif change == "paid_receipt_latch":
        await store.conversion_outcome(
            ConversionOutcome(
                parent_id="123",
                event_id=uuid4(),
                proposal_id=admission.proposal.proposal_id,
                observed_at=NOW,
                kind="payment_confirmed",
                payment_id="synthetic-paid-receipt",
                amount_minor=approved.price_minor,
                currency=approved.currency,
                billing_offer_id=approved.billing_offer_id,
            ),
            NOW,
        )
        # A later free-looking snapshot must not clear the confirmed payment latch.
        await store.ingest_conversion(snapshot(revision=2), NOW)
    elif change == "marketing_consent_revoked":
        await store.ingest_conversion(snapshot(revision=2, marketing_consent=False), NOW)
    elif change == "expired_offer":
        claim_at = NOW + timedelta(minutes=2)
    elif change == "revoked_catalog_offer":
        store = await repository(path, offers=())
    elif change == "declined_offer":
        await store.conversion_outcome(
            ConversionOutcome(
                parent_id="123",
                event_id=uuid4(),
                proposal_id=admission.proposal.proposal_id,
                observed_at=NOW,
                kind="declined",
            ),
            NOW,
        )
    elif change == "stale_account_facts":
        claim_at = NOW + timedelta(minutes=16)
    assert await store.contact_context("123", claim_at) == original_context
    assert await store.claim_push(claim_at) is None
    history = await store.history("123", before=None, limit=20, now=claim_at)
    assert history.messages == published.messages
    row = (await store.pushes("123")).pushes[0]
    assert row.status == "suppressed" and row.error_code
    assert row.error_code.startswith("parent_push_marketing_")
    assert history.quota.used_tokens == history.quota.reserved_tokens == 0
    with store._connect() as connection:
        claim = connection.execute("SELECT claim_id,claimed_at FROM parent_push_outbox").fetchone()
        assert claim["claim_id"] is None and claim["claimed_at"] is None


async def test_marketing_push_revalidation_does_not_apply_its_own_contact_cooldown(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "own-cooldown.db")
    await store.ingest_contact_context(contact(), NOW)
    await store.ingest_conversion(snapshot(), NOW)
    assert await store.publish_conversion(NOW, render_parent_offer)
    with store._connect() as connection:
        assert store._frequency_block(connection, "123", NOW) == "contact_cooldown"
    claim = await store.claim_push(NOW)
    assert claim and claim.notification.purpose == "marketing"


async def test_opt_out_does_not_reclaim_or_reissue_an_already_claimed_marketing_push(
    tmp_path: Path,
) -> None:
    path = tmp_path / "already-claimed.db"
    store = await repository(path)
    await store.ingest_contact_context(contact(), NOW)
    await store.ingest_conversion(snapshot(), NOW)
    assert await store.publish_conversion(NOW, render_parent_offer)
    claim = await store.claim_push(NOW)
    assert claim
    await store.suppress_conversion("123", NOW)
    assert (await store.push("123", claim.notification.push_id)).status == "submitting"
    await store.finish_push(
        claim,
        ParentPushOutcome(status="unknown", error_code="parent_push_outcome_unknown"),
        NOW,
    )
    assert await (await repository(path)).claim_push(NOW + timedelta(days=1)) is None
    history = await store.history("123", before=None, limit=20, now=NOW)
    assert len(history.messages) == 1 and history.messages[0].role == "assistant"
