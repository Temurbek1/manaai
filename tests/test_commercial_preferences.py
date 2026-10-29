"""One parent preference across proactive commercial owners; no live providers."""

from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pytest import MonkeyPatch

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ParentChatRequest
from app.mana_ai.domain.conversion import ConversionSnapshot
from app.mana_ai.domain.family_agents import (
    AgentQuestionRequest,
    ParentTouchDeliveryRequest,
    ParentTouchMessageRequest,
)
from app.mana_ai.domain.proactive_parent import ParentContactContext, ParentPushOutcome
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.parent_reminder_store import SqliteParentReminderStore
from tests.test_mana_chat_lab import Clock
from tests.test_retention_expiry import setup


def refusal(text: str = "Не присылай предложения") -> ParentTouchMessageRequest:
    return ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=text)


def conversion_event(lab: ChatLab) -> ConversionSnapshot:
    body = next(s.body for s in lab.bootstrap().scenarios if s.key == "conversion")
    return ConversionSnapshot.model_validate(body)


def forbid_work(monkeypatch: MonkeyPatch, lab: ChatLab) -> None:
    async def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError("A contact refusal cannot dispatch a source or model")

    for model in lab._models:
        monkeypatch.setattr(model, "count_input", forbidden)
        monkeypatch.setattr(model, "respond", forbidden)
    monkeypatch.setattr(lab._profiles, "read", forbidden)
    monkeypatch.setattr(lab.catalog, "read", forbidden)


@pytest.mark.parametrize(
    ("message", "prefix"),
    [
        ("Не присылай предложения!", "Больше не буду"),
        ("STOP OFFERS.", "I will stop"),
        ("Taklif yubormang", "Endi tarif"),
        ("Таклиф юборманг", "Энди тариф"),
    ],
)
async def test_refusal_works_without_conversion_retention_or_model_allowance(
    tmp_path: Path, monkeypatch: MonkeyPatch, message: str, prefix: str
) -> None:
    lab, clock = await setup(tmp_path / "refusal")
    try:
        lab.touch.conversion = None
        lab.touch.retention = None
        forbid_work(monkeypatch, lab)
        with lab.store._transaction() as db:
            day, _ = lab.store._period(clock.now())
            db.execute(
                "INSERT INTO parent_chat_quota(parent_id,day,used) VALUES(?,?,5000)",
                (LAB_PARENT, day),
            )
        request = refusal(message)
        state = await lab.touch.admit_message(request)
        assert state.phase == "completed" and state.response
        assert state.response.answer.startswith(prefix)
        assert state.response.usage.input_tokens == state.response.usage.output_tokens == 0
        assert state.response.quota.used_tokens == 5000
        assert state.response.quota.remaining_tokens == 0
        assert await lab.touch.admit_message(request) == state
        with lab.store._connect() as db:
            assert db.execute("SELECT count(*) FROM conversion_opt_outs").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM parent_chat_turns").fetchone()[0] == 1
            assert not db.execute("SELECT 1 FROM child_safety_jobs").fetchone()
            assert not db.execute("SELECT 1 FROM conversion_trial_grants").fetchone()
    finally:
        await lab.close()


async def test_unknown_hold_survives_refusal_restart_and_midnight(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "unknown")
    try:
        unknown = await lab.store.admit(
            ParentChatRequest(parent_id=LAB_PARENT, request_id=uuid4(), message="Earlier task"),
            clock.now(),
        )
        await lab.store.submit(unknown, reserved_tokens=612, now=clock.now())
        command = refusal()
        assert (await lab.touch.admit_message(command)).phase == "completed"
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        quota = (await lab.state()).history.quota
        assert quota.reserved_tokens == 612 and quota.blocked_by_unresolved_request
        clock.value += timedelta(days=1)
        assert (await lab.state()).history.quota.blocked_by_unresolved_request
        await lab.touch.admit_message(command)
        with lab.store._connect() as db:
            assert (
                db.execute(
                    "SELECT reserved FROM parent_chat_turns WHERE id=?", (unknown.turn_id,)
                ).fetchone()[0]
                == 612
            )
            assert db.execute("SELECT count(*) FROM conversion_opt_outs").fetchone()[0] == 1
        with pytest.raises(ParentChatError):
            await lab.touch.admit_message(refusal("Как помочь ребёнку?"))
    finally:
        await lab.close()


async def test_refusal_nonce_conflict_has_no_preference_side_effect(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "conflict")
    try:
        assert isinstance(lab.store, SqliteParentReminderStore)
        command = refusal()
        with lab.store._transaction() as db:
            lab.store._host_reply(
                db,
                command.model_copy(update={"message": "Original"}),
                LAB_PARENT,
                command.request_id,
                "Original response",
                clock.now(),
            )
        with pytest.raises(ParentChatError, match="request_id_conflict"):
            await lab.touch.admit_message(command)
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM conversion_opt_outs").fetchone()
    finally:
        await lab.close()


async def enable_push(lab: ChatLab, clock: Clock) -> None:
    assert lab.touch.proactive
    prior = await lab.store.contact_context(LAB_PARENT, clock.now())
    assert prior
    await lab.touch.proactive.register(
        ParentContactContext.model_validate(
            prior.model_dump()
            | {
                "event_id": uuid4(),
                "revision": prior.revision + 1,
                "marketing_push_consent": True,
                "retention_push_consent": True,
                "safety_push_consent": True,
            }
        )
    )
    lab.store._push_enabled = True


async def test_refusal_closes_queued_offer_and_suppresses_marketing_push_only(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "queued")
    try:
        await enable_push(lab, clock)
        assert lab.touch.conversion
        admission = await lab.touch.conversion.observe(conversion_event(lab))
        assert admission.proposal and admission.proposal.status == "queued"
        assert isinstance(lab.store, SqliteParentReminderStore)
        with lab.store._transaction() as db:
            turn = lab.store._host_reply(
                db, None, LAB_PARENT, uuid4(), "Earlier message", clock.now()
            )
            lab.store._queue_push(db, LAB_PARENT, turn.turn_id, "marketing", clock.now())
            safety_turn = lab.store._host_reply(
                db, None, LAB_PARENT, uuid4(), "Earlier safety notice", clock.now()
            )
            lab.store._queue_push(db, LAB_PARENT, safety_turn.turn_id, "safety", clock.now())
        await lab.touch.admit_message(refusal())
        proposal = await lab.touch.conversion.proposal(LAB_PARENT, admission.proposal.proposal_id)
        assert proposal.status == "cancelled" and proposal.closed_reason == "parent_opted_out"
        with lab.store._connect() as db:
            rows = dict(db.execute("SELECT purpose,status FROM parent_push_outbox"))
            assert rows == {"marketing": "suppressed", "safety": "queued"}
            assert not db.execute("SELECT 1 FROM retention_opt_outs").fetchone()
        assert not await lab.touch.process_conversion()
    finally:
        await lab.close()


async def test_submitted_unknown_push_is_retained_after_refusal(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "push-unknown")
    try:
        await enable_push(lab, clock)
        assert lab.touch.conversion
        await lab.touch.conversion.observe(conversion_event(lab))
        assert await lab.touch.process_conversion()
        claim = await lab.store.claim_push(clock.now())
        assert claim and claim.notification.purpose == "marketing"
        await lab.store.finish_push(
            claim,
            ParentPushOutcome(status="unknown", error_code="parent_push_outcome_unknown"),
            clock.now(),
        )
        with lab.store._connect() as db:
            original = tuple(db.execute("SELECT * FROM parent_push_outbox").fetchone())
        await lab.touch.admit_message(refusal())
        with lab.store._connect() as db:
            assert tuple(db.execute("SELECT * FROM parent_push_outbox").fetchone()) == original
    finally:
        await lab.close()


async def test_expiry_offer_is_suppressed_but_explicit_tariff_request_still_works(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "explicit")
    try:
        await lab.prepare_expiry_scenario()
        await lab.touch.admit_message(refusal())
        assert not await lab.touch.process_retention()
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM retention_expiry_notices").fetchone()
        request = refusal("Покажи самый дешёвый тариф на 90 дней в UZS")
        await lab.touch.admit_message(request)
        review = await lab.safety.process_one()
        assert review and review.status == "completed"
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_upsell()
        history = (await lab.state()).history
        assert "162 000.00 UZS" in history.messages[-1].content
        assert history.quota.used_tokens == 150
    finally:
        await lab.close()


async def test_refusal_preserves_unrelated_pending_question(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "question")
    try:
        body = next(s.body for s in lab.bootstrap().scenarios if s.key == "question")
        question = await lab.touch.request_question(AgentQuestionRequest.model_validate(body))
        assert question
        await lab.touch.deliver(
            ParentTouchDeliveryRequest(parent_id=LAB_PARENT, request_id=uuid4())
        )
        before = await lab.store.questions(LAB_PARENT)
        assert before.questions[0].status == "awaiting_reply"
        command = refusal().model_copy(
            update={"reply_to_question_id": before.questions[0].question_id}
        )
        await lab.touch.admit_message(command)
        assert await lab.store.questions(LAB_PARENT) == before
    finally:
        await lab.close()


@pytest.mark.parametrize("ended", [False, True])
async def test_known_free_period_does_not_bypass_commercial_preference(
    tmp_path: Path, ended: bool
) -> None:
    from tests.test_trial_end import start
    from tests.test_trial_periods import setup as trial_setup

    lab, clock, store = (
        await start(tmp_path / "ended") if ended else await trial_setup(tmp_path / "period")
    )
    try:
        if ended:
            with store._connect() as db:
                prior = ParentContactContext.model_validate_json(
                    db.execute("SELECT payload FROM parent_contact_contexts").fetchone()[0]
                )
            clock.value += timedelta(days=2)
            assert lab.touch.proactive
            await lab.touch.proactive.register(
                prior.model_copy(
                    update={
                        "event_id": uuid4(),
                        "revision": prior.revision + 1,
                        "observed_at": clock.now(),
                        "valid_until": clock.now() + timedelta(days=1),
                    }
                )
            )
            await lab._profiles.read(LAB_PARENT)
        grant = await store.trial_grant(LAB_PARENT)
        await lab.touch.admit_message(refusal())
        clock.value += timedelta(seconds=601)
        await lab._profiles.read(LAB_PARENT)
        before = (await lab.state()).history.messages
        assert not await lab.touch.process_retention()
        assert (await lab.state()).history.messages == before
        assert await store.trial_grant(LAB_PARENT) == grant
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM retention_expiry_notices").fetchone()
        # This proves the owning lifecycle is otherwise eligible, rather than
        # confusing the preference veto with the ordinary idle/source gates.
        with store._transaction() as db:
            db.execute("DELETE FROM conversion_opt_outs WHERE parent_id=?", (LAB_PARENT,))
        assert await lab.touch.process_retention()
    finally:
        await lab.close()


async def test_saved_expiry_message_remains_but_pending_push_is_vetoed(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "expiry-push")
    try:
        await enable_push(lab, clock)
        await lab.prepare_expiry_scenario()
        assert await lab.touch.process_retention()
        saved = (await lab.state()).history.messages[0]
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM parent_push_outbox").fetchone()[0] == "queued"
        await lab.touch.admit_message(refusal())
        assert await lab.store.claim_push(clock.now()) is None
        assert (await lab.state()).history.messages[0] == saved
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM parent_push_outbox").fetchone()[0] == "suppressed"
    finally:
        await lab.close()


def test_exact_negative_commands_never_infer_positive_consent_or_parse_quoted_text() -> None:
    from app.mana_ai.application.contact_preferences import commercial_refusal_language

    for text in ('Explain "stop offers"', "Do not stop offers", "Возобнови предложения", "yes"):
        assert commercial_refusal_language(text) is None
