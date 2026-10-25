"""One parent chat, independent communication and durable specialist handoffs."""

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from pytest import MonkeyPatch

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.parent_touch_manager import manager_prompt
from app.mana_ai.domain.chat import ChatTokens
from app.mana_ai.domain.child_safety import SafetyTarget
from app.mana_ai.domain.family_agents import AgentQuestionRequest, ParentTouchMessageRequest
from app.mana_ai.domain.parent_reminders import ReminderCandidate
from app.mana_ai.domain.parent_touch_manager import (
    ParentTouchManagerHandoff,
    ParentTouchManagerScope,
)
from app.services.mana_chat_lab import LAB_PARENT, ChatLab, LabOptions
from app.services.parent_touch_manager_store import SqliteParentTouchManagerStore
from tests.test_child_safety_store import analysis
from tests.test_mana_chat_lab import Clock


def test_specialist_publication_retains_all_context_without_other_tools() -> None:
    data: dict[str, object] = {
        "profiles": {"children": [{"name": "Fictional child", "connected": True}]},
        "specialist_guidance": {
            "advice": "Try a consistent bedtime.",
            "source_observations": [{"battery_percent": 23, "observed_at": "2026-10-21"}],
            "limitations": ["Partial counters, unknown measurement period."],
        },
        "historical_context": "Keep every word of this dated qualification.",
    }
    original = (("user", json.dumps(data)), ("user", "Help my child sleep."))
    template = ChatPrompt(
        "Original specialist publication",
        original,
        structured_reply=True,
        slot_reply=True,
        required_observation_dates=("2026-10-21",),
        minimum_output_tokens=256,
    )
    prompt = manager_prompt(
        ParentTouchManagerScope(language="en", stage="child_safety"),
        data,
        original,
        template=template,
    )
    assert json.loads(prompt.messages[0][1]) == data
    assert prompt.messages[1:] == original[1:]
    assert prompt.required_observation_dates == ("2026-10-21",)
    assert prompt.minimum_output_tokens == 256
    assert prompt.slot_reply
    assert prompt.reminder_scope is None and prompt.upsell_scope is None
    assert "Collection/write time is not observation time" in prompt.instructions


async def test_selected_child_owner_cannot_create_an_unselected_reminder(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    lab, clock, store = await setup(tmp_path / "selected-owner")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Ребёнок плохо спит. Напомни завтра в 9 купить тетради.",
        )

        async def contradict_selected_owner(
            prompt: ChatPrompt, *, max_output_tokens: int
        ) -> ChatModelReceipt:
            assert prompt.manager_scope is not None
            if prompt.manager_scope.stage == "route":
                return ChatModelReceipt(
                    usage=ChatTokens(input_tokens=100, output_tokens=50),
                    model="lab-simulated-not-billed",
                    answer=None,
                    completed=True,
                    manager_handoff=ParentTouchManagerHandoff(
                        target="child_safety", call_id="call-selected-child"
                    ),
                )
            return ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=50),
                model="lab-simulated-not-billed",
                answer="",
                completed=True,
                reminder_candidate=ReminderCandidate(
                    content="купить тетради",
                    due_at=(clock.now() + timedelta(days=1))
                    .astimezone(ZoneInfo("Asia/Samarkand"))
                    .replace(hour=9, minute=0),
                    timezone="Asia/Samarkand",
                ),
            )

        monkeypatch.setattr(lab.touch._model, "respond", contradict_selected_owner)
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        assert (
            await lab.touch.message_state(LAB_PARENT, request.request_id)
        ).phase == "awaiting_review"
        review = await lab.safety.process_one()
        assert review is not None and review.status == "completed"
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed" and state.response is None
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM assistant_reminders").fetchone()
        history = (await lab.state()).history
        assert [m.role for m in history.messages] == ["user"]
        assert history.quota.used_tokens == 300
        assert history.quota.reserved_tokens == 0
    finally:
        await lab.close()


async def test_expiry_waits_for_idle_and_fresh_source(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "idle")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Привет"
        )
        await lab.touch.admit_message(request)
        await lab.touch.process_reviewed_message()
        assert not await lab.touch.process_retention()
        clock.value += timedelta(seconds=601)
        assert not await lab.touch.process_retention()
        await lab.touch._children.read(LAB_PARENT)
        assert await lab.touch.process_retention()
        assert len((await lab.state()).history.messages) == 3
        assert (await lab.state()).history.quota.used_tokens == 150
    finally:
        await lab.close()


async def test_reminder_stays_unconfirmed_without_safety_tokens(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "reminder")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Напомни завтра в 9 купить тетради"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_reviewed_message()
        current = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert current.response and current.response.usage.total == 300
        history = (await lab.state()).history
        assert history.active_confirmation is not None
        with store._connect() as db:
            assert db.execute("SELECT status FROM assistant_reminders").fetchone()[0] == "draft"
            assert not db.execute("SELECT 1 FROM child_safety_parent_events").fetchone()
        assert (await lab.state()).safety_budget.server_used_tokens == 0
    finally:
        await lab.close()


async def test_bound_question_answer_keeps_original_review_first_protocol(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "bound-question")
    try:
        request = AgentQuestionRequest.model_validate(
            next(s.body for s in lab.bootstrap().scenarios if s.key == "question")
        )
        await store.enqueue(request, clock.now())
        delivery = await store.next_delivery(clock.now())
        assert delivery is not None
        spoken = await lab.touch.deliver(delivery)
        assert spoken.asked_question is not None
        answer = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Около восьми часов",
            reply_to_question_id=spoken.asked_question.question_id,
        )
        state = await lab.touch.admit_message(answer)
        assert state.phase == "awaiting_review"
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM parent_touch_manager_turns").fetchone()
            assert db.execute("SELECT COUNT(*) FROM child_safety_parent_events").fetchone()[0] == 1
    finally:
        await lab.close()


async def test_late_ordinary_receipt_after_unknown_only_reconciles_cost(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "late-ordinary")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Привет"
        )
        await lab.touch.admit_message(request)
        claimed = await store.claim_reviewed_response(clock.now())
        assert claimed is not None
        turn, _ = claimed
        await store.submit(turn.turn, reserved_tokens=500, now=clock.now())
        await store.fail(turn.turn, code="fictional_cancelled_receipt", unknown=True)
        with pytest.raises(ParentChatError):
            await store.settle(
                turn.turn,
                receipt=ChatModelReceipt(
                    usage=ChatTokens(input_tokens=100, output_tokens=50),
                    model="lab-simulated-not-billed",
                    answer="Здравствуйте.",
                    completed=True,
                ),
                now=clock.now(),
                history_turns=0,
                context_at=clock.now(),
            )
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed" and state.response is None
        quota = (await lab.state()).history.quota
        assert quota.used_tokens == 150 and quota.reserved_tokens == 0
        assert [m.role for m in (await lab.state()).history.messages] == ["user"]
    finally:
        await lab.close()


async def setup(path: Path) -> tuple[ChatLab, Clock, SqliteParentTouchManagerStore]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        LabOptions(
            path,
            clock=clock,
            worker_enabled=False,
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
            retention=True,
            upsell=True,
            tariff_context=True,
            expiry=True,
            manager=True,
        )
    )
    await lab.start()
    assert isinstance(lab.store, SqliteParentTouchManagerStore)
    return lab, clock, lab.store


async def test_greeting_uses_parent_budget_without_child_safety_job(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "greeting")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Привет"
        )
        state = await lab.touch.admit_message(request)
        assert state.phase == "responding"
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM child_safety_parent_events").fetchone()
            assert not db.execute("SELECT 1 FROM child_safety_jobs").fetchone()
        assert await lab.touch.process_reviewed_message()
        result = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert result.phase == "completed" and result.response
        assert result.response.usage.total == 150
        assert result.response.quota.used_tokens == 150
        assert (await lab.state()).safety_budget.server_used_tokens == 0
        assert await lab.touch.admit_message(request) == result
    finally:
        await lab.close()


async def test_child_request_keeps_same_message_pending_until_real_specialist_receipt(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "child")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Ребёнок плохо спит. Помоги разобраться.",
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        pending = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert pending.phase == "awaiting_review" and pending.response is None
        assert (await lab.state()).history.quota.used_tokens == 150
        with store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM parent_chat_turns").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM child_safety_parent_events").fetchone()[0] == 1
        review = await lab.safety.process_one()
        assert review is not None and review.status == "completed"
        assert await lab.touch.process_reviewed_message()
        complete = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert complete.phase == "completed" and complete.response
        assert complete.response.usage.total == 300
        assert complete.response.quota.used_tokens == 300
        history = (await lab.state()).history
        assert [m.role for m in history.messages] == ["user", "assistant"]
        assert await lab.touch.admit_message(request) == complete
    finally:
        await lab.close()


async def test_tariff_enquiry_runs_without_safety_review(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "tariff")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Покажи самый дешёвый тариф на 90 дней в UZS",
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        assert (await lab.touch.message_state(LAB_PARENT, request.request_id)).phase == "responding"
        assert await lab.touch.process_reviewed_message()
        complete = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert complete.phase == "completed" and complete.response
        assert complete.response.usage.total == 300
        assert await lab.touch.process_upsell()
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM child_safety_parent_events").fetchone()
            assert not db.execute("SELECT 1 FROM child_safety_jobs").fetchone()
        assert (await lab.state()).safety_budget.server_used_tokens == 0
    finally:
        await lab.close()


async def test_exhausted_global_safety_budget_does_not_block_general_chat_or_catalogue(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "global-budget")
    try:
        historical = await store.admit_analysis(
            target=SafetyTarget(
                parent_id="900003",
                child_id=900004,
                request_id=uuid4(),
                source_revision="synthetic-paid-history",
            ),
            analysis=analysis(900004),
            now=clock.now(),
        )
        # A fictional historical priced failure, not a live generation or policy change.
        with store._connect() as db:
            db.execute(
                "UPDATE child_safety_jobs SET status='failed',day=?,input_tokens=1800,"
                "output_tokens=200,reserved=0 WHERE job_id=?",
                (store._period(clock.now())[0], str(historical.job_id)),
            )
        assert (await lab.state()).safety_budget.server_remaining_tokens == 0
        for text in ("Привет", "Покажи тариф на 90 дней в UZS"):
            request = ParentTouchMessageRequest(
                parent_id=LAB_PARENT, request_id=uuid4(), message=text
            )
            await lab.touch.admit_message(request)
            assert await lab.touch.process_reviewed_message()
            if "тариф" in text:
                assert await lab.touch.process_reviewed_message()
                assert await lab.touch.process_upsell()
            current = await lab.touch.message_state(LAB_PARENT, request.request_id)
            assert current.phase == "completed"
        assert (await lab.state()).safety_budget.server_used_tokens == 2000
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM child_safety_parent_events").fetchone()
            assert db.execute("SELECT COUNT(*) FROM child_safety_jobs").fetchone()[0] == 1
    finally:
        await lab.close()


async def test_unknown_manager_receipt_keeps_hold_and_never_retries_after_restart(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    lab, clock, store = await setup(tmp_path / "unknown")
    calls = 0

    async def lost(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise TimeoutError("fictional lost receipt")

    monkeypatch.setattr(lab.touch._model, "respond", lost)
    request = ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message="Привет")
    try:
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "unknown"
        budget = (await lab.state()).history.quota
        assert budget.used_tokens == 0 and budget.reserved_tokens > 0
        assert budget.blocked_by_unresolved_request and calls == 1
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        assert await lab.touch.admit_message(request) == state
        assert not await lab.touch.process_reviewed_message()
        with pytest.raises(ParentChatError):
            await lab.touch.admit_message(request.model_copy(update={"request_id": uuid4()}))
        clock.value += timedelta(days=1)
        assert (await lab.state()).history.quota.blocked_by_unresolved_request
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM child_safety_parent_events").fetchone()
            assert (
                db.execute("SELECT phase FROM parent_touch_manager_turns").fetchone()[0]
                == "unknown"
            )
    finally:
        await lab.close()


async def test_handoff_replay_and_restart_never_reclassify_or_duplicate_child_review(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "handoff-restart")
    request = ParentTouchMessageRequest(
        parent_id=LAB_PARENT, request_id=uuid4(), message="Ребёнок плохо спит"
    )
    try:
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        original = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert original.phase == "awaiting_review"
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        assert await lab.touch.admit_message(request) == original
        assert not await lab.touch.process_reviewed_message()
        review = await lab.safety.process_one()
        assert review and review.status == "completed"
        assert await lab.touch.process_reviewed_message()
        result = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert (
            result.phase == "completed" and result.response and result.response.usage.total == 300
        )
        with store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM child_safety_parent_events").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM parent_touch_manager_turns").fetchone()[0] == 1
            assert (
                db.execute(
                    "SELECT input_tokens+output_tokens FROM parent_touch_manager_turns"
                ).fetchone()[0]
                == 150
            )
    finally:
        await lab.close()


async def test_stopped_queued_manager_never_falls_back_to_a_paid_safety_review(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "stop")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Привет"
        )
        await lab.touch.admit_message(request)
        store._manager_enabled = False
        assert not await lab.touch.process_reviewed_message()
        result = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert result.phase == "failed" and result.error_code == "parent_manager_disabled"
        assert (await lab.state()).history.quota.used_tokens == 0
        store._manager_enabled = True
        assert await lab.touch.admit_message(request) == result
        assert not await lab.touch.process_reviewed_message()
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM child_safety_parent_events").fetchone()
    finally:
        await lab.close()


async def test_stopping_during_router_inference_keeps_verified_cost_but_dispatches_nothing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    lab, clock, store = await setup(tmp_path / "late-stop")
    original = lab.touch._model.respond

    async def stopped(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        store._manager_enabled = False
        return result

    monkeypatch.setattr(lab.touch._model, "respond", stopped)
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Ребёнок плохо спит"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        result = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert result.phase == "failed"
        assert (await lab.state()).history.quota.used_tokens == 150
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM child_safety_parent_events").fetchone()
            assert not db.execute("SELECT 1 FROM child_safety_jobs").fetchone()
    finally:
        await lab.close()


async def test_enabling_does_not_upgrade_a_legacy_review_first_admission(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "legacy")
    try:
        store._manager_enabled = False
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Ребёнок плохо спит"
        )
        original = await lab.touch.admit_message(request)
        assert original.phase == "awaiting_review"
        store._manager_enabled = True
        assert await lab.touch.admit_message(request) == original
        assert not await lab.touch.process_reviewed_message()
        review = await lab.safety.process_one()
        assert review and review.status == "completed"
        assert await lab.touch.process_reviewed_message()
        result = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert result.response and result.response.usage.total == 150
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM parent_touch_manager_turns").fetchone()
    finally:
        await lab.close()


async def test_concurrent_claims_generate_one_manager_reply_only(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "concurrent")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Salom"
        )
        await lab.touch.admit_message(request)
        results = await asyncio.gather(*(lab.touch.process_reviewed_message() for _ in range(6)))
        assert results.count(True) == 1
        result = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert result.response and result.response.usage.total == 150
        assert result.response.quota.used_tokens == 150
        assert "Salom" in result.response.answer
    finally:
        await lab.close()


async def test_changed_model_binding_stops_old_captured_work_before_generation(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "model-change")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Привет"
        )
        await lab.touch.admit_message(request)
        store._manager_binding = "another-explicit-model-profile"
        assert not await lab.touch.process_reviewed_message()
        result = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert result.phase == "failed" and result.error_code == "parent_manager_profile_changed"
        assert (await lab.state()).history.quota.used_tokens == 0
    finally:
        await lab.close()
