"""The semantic review cannot approve, rewrite, replay or revive a reminder action."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.domain.bound_reminder_review import BoundReminderDecision
from app.mana_ai.domain.chat import ChatTokens, ParentChildContext
from app.mana_ai.domain.family_agents import (
    AgentQuestionRequest,
    ParentTouchMessageRequest,
    ParentTouchReviewedTurn,
)
from app.services import parent_chat_runtime as runtime
from app.services.bound_reminder_review_store import (
    SqliteBoundReminderReviewStore,
    SqliteClosedBoundReminderReviewStore,
)
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.parent_chat_model import OpenAIParentChatModel
from app.services.parent_touch_manager_store import SqliteParentTouchManagerStore
from tests.test_compact_manager_runtime import compact_settings
from tests.test_mana_chat_lab import Clock
from tests.test_saved_observations import snapshot


async def setup(path: Path) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        replace(
            workspace_options(path, clock=clock, worker_enabled=False),
            tariff_handoff=True,
            compact_inputs=True,
            compact_publication=True,
            compact_manager=True,
            saved_observations=True,
            compact_source_tools=True,
            direct_reminders=True,
            compact_decisions=True,
            bound_reminder_reviews=True,
        )
    )
    await lab.start()
    assert isinstance(lab.store, SqliteBoundReminderReviewStore)
    return lab, clock


def request(clock: Clock) -> ParentTouchMessageRequest:
    due = (clock.now() + timedelta(minutes=30)).astimezone(ZoneInfo("Asia/Samarkand"))
    return ParentTouchMessageRequest(
        parent_id=LAB_PARENT,
        request_id=uuid4(),
        message=f"Напомни мне {due:%Y-%m-%d} в {due:%H:%M} по часовому поясу "
        "Asia/Samarkand купить тетради для ребёнка.",
    )


def assert_no_external_work(lab: ChatLab) -> None:
    assert lab.battery.calls == lab.app_usage.calls == lab.catalog.calls == 0
    assert lab.location.calls == lab.day_provider.calls == 0
    with lab.store._connect() as db:
        assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
        assert not db.execute("SELECT 1 FROM child_safety_jobs").fetchone()


async def test_prepare_only_creates_one_exact_preview_then_requires_human_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "prepare")
    original = lab.touch._model.respond
    calls = 0

    async def prepare(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        nonlocal calls
        calls += 1
        assert prompt.bound_reminder_request
        assert prompt.messages[-1][1] == original_request.message
        return await original(prompt, max_output_tokens=max_output_tokens)

    try:
        original_request = request(clock)
        monkeypatch.setattr(lab.touch._model, "respond", prepare)
        await lab.touch.admit_message(original_request)
        assert await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, original_request.request_id)
        assert done.phase == "completed" and done.response and calls == 1
        state = await lab.state()
        pending = state.history.active_confirmation
        assert pending and pending.kind == "approval"
        assert pending.candidate.content == "купить тетради для ребёнка."
        assert pending.candidate.due_at == clock.now() + timedelta(minutes=30)
        assert pending.candidate.timezone == "Asia/Samarkand"
        assert pending.candidate.content in done.response.answer
        assert pending.candidate.due_at
        assert pending.candidate.due_at.strftime("%d.%m.%Y %H:%M") in done.response.answer
        assert state.history.quota.used_tokens == 150
        assert len(state.history.reminders) == 1
        assert state.history.reminders[0].status == "draft"
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM bound_reminder_reviews").fetchone()[0] == 1
            assert (
                db.execute("SELECT request_hash FROM direct_reminder_routes")
                .fetchone()[0]
                .startswith("bound-review-v1:")
            )
            assert not db.execute("SELECT 1 FROM assistant_deliveries").fetchone()
        before = snapshot(lab.store._path)
        assert await lab.touch.admit_message(original_request) == done
        assert not await lab.touch.process_reviewed_message()
        assert snapshot(lab.store._path) == before and calls == 1
        for parent, confirmation_id in (
            ("900003", pending.confirmation_id),
            (LAB_PARENT, uuid4()),
        ):
            with pytest.raises(ParentChatError, match="assistant_confirmation_not_active"):
                await lab.touch.admit_message(
                    ParentTouchMessageRequest(
                        parent_id=parent,
                        request_id=uuid4(),
                        message="Да",
                        reply_to_confirmation_id=confirmation_id,
                    )
                )
        assert snapshot(lab.store._path) == before and calls == 1
        confirm = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Да",
            reply_to_confirmation_id=pending.confirmation_id,
        )
        confirmed = await lab.touch.admit_message(confirm)
        assert confirmed.phase == "completed" and confirmed.response
        assert confirmed.response.usage.total == 0 and calls == 1
        assert (await lab.state()).history.reminders[0].status == "scheduled"
        assert_no_external_work(lab)
    finally:
        await lab.close()


@pytest.mark.parametrize("question", [None, "Вы хотите напомнить об этом только один раз?"])
async def test_reply_refusal_or_essential_question_never_creates_a_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, question: str | None
) -> None:
    lab, clock = await setup(tmp_path / ("question" if question else "refusal"))
    body = "Уточню ваш запрос." if question else "С этим напоминанием я не помогу."

    async def reply(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        assert prompt.bound_reminder_request
        return ChatModelReceipt(
            usage=ChatTokens(input_tokens=100, output_tokens=50),
            model="lab-simulated-not-billed",
            completed=True,
            answer="\n\n".join(part for part in (body, question) if part),
            clarification_question=question,
            bound_reminder_decision=BoundReminderDecision(
                kind="reply", body=body, question=question
            ),
        )

    try:
        monkeypatch.setattr(lab.touch._model, "respond", reply)
        original_request = request(clock)
        await lab.touch.admit_message(original_request)
        assert await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, original_request.request_id)
        assert done.phase == "completed" and done.response
        state = await lab.state()
        assert state.history.quota.used_tokens == 150
        assert not state.history.reminders and state.history.active_confirmation is None
        if question:
            asked = done.response.asked_question
            assert asked and asked.child_id is None and done.response.answer.endswith(question)
            with lab.store._connect() as db:
                row = db.execute(
                    "SELECT q.status,q.child_id,m.phase,m.choice FROM family_questions q "
                    "JOIN parent_clarification_questions c ON c.question_id=q.question_id "
                    "JOIN parent_touch_manager_turns m ON m.turn_id=c.turn_id"
                ).fetchone()
                assert tuple(row) == ("awaiting_reply", None, "finished", "reminder")
            answer = ParentTouchMessageRequest(
                parent_id=LAB_PARENT,
                request_id=uuid4(),
                message="Да, только один раз",
                reply_to_question_id=asked.question_id,
            )
            await lab.touch.admit_message(answer)
            with lab.store._connect() as db:
                row = db.execute("SELECT status,answer_turn_id FROM family_questions").fetchone()
                assert row[0] == "answered" and row[1] is not None
                assert not db.execute("SELECT 1 FROM child_safety_parent_events").fetchone()
        else:
            assert done.response.asked_question is None
        assert_no_external_work(lab)
    finally:
        await lab.close()


@pytest.mark.parametrize("condition", ["disabled", "missing_capture"])
async def test_marked_work_stops_before_profile_count_or_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    lab, clock = await setup(tmp_path / condition)
    assert isinstance(lab.store, SqliteBoundReminderReviewStore)

    async def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("A fenced review must not read profiles, count or infer")

    try:
        original_request = request(clock)
        await lab.touch.admit_message(original_request)
        if condition == "disabled":
            lab.store._bound_reminder_reviews_enabled = False
        else:
            with lab.store._transaction() as db:
                db.execute("DELETE FROM bound_reminder_reviews")
        monkeypatch.setattr(lab.touch._children, "read", forbidden)
        monkeypatch.setattr(lab.touch._model, "count_input", forbidden)
        monkeypatch.setattr(lab.touch._model, "respond", forbidden)
        assert not await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, original_request.request_id)
        assert done.phase == "failed"
        state = await lab.state()
        assert state.history.quota.used_tokens == state.history.quota.reserved_tokens == 0
        assert not state.history.reminders and state.history.active_confirmation is None
        assert_no_external_work(lab)
    finally:
        await lab.close()


@pytest.mark.parametrize(
    "change",
    [
        "disabled",
        "content",
        "date",
        "timezone",
        "missing_decision",
        "lost_capture",
        "lost_marker",
    ],
)
async def test_late_control_or_forged_candidate_keeps_verified_cost_without_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    lab, clock = await setup(tmp_path / change)
    assert isinstance(lab.store, SqliteBoundReminderReviewStore)
    store = lab.store
    original = lab.touch._model.respond

    async def changed(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        receipt = await original(prompt, max_output_tokens=max_output_tokens)
        assert receipt.reminder_candidate
        candidate = receipt.reminder_candidate
        if change == "missing_decision":
            return replace(receipt, bound_reminder_decision=None)
        if change == "disabled":
            store._bound_reminder_reviews_enabled = False
        elif change in {"lost_capture", "lost_marker"}:
            with store._transaction() as db:
                if change == "lost_capture":
                    db.execute("DELETE FROM bound_reminder_reviews")
                else:
                    db.execute(
                        "UPDATE direct_reminder_routes SET request_hash=substr(request_hash,17)"
                    )
        elif change == "content":
            candidate = candidate.model_copy(update={"content": "другая задача"})
        elif change == "date":
            assert candidate.due_at
            candidate = candidate.model_copy(
                update={"due_at": candidate.due_at + timedelta(minutes=1)}
            )
        else:
            candidate = candidate.model_copy(update={"timezone": "Asia/Tashkent"})
        return replace(receipt, reminder_candidate=candidate)

    try:
        monkeypatch.setattr(lab.touch._model, "respond", changed)
        original_request = request(clock)
        await lab.touch.admit_message(original_request)
        assert await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, original_request.request_id)
        assert done.phase == "failed" and done.response is None
        state = await lab.state()
        assert state.history.quota.used_tokens == 150 and state.history.quota.reserved_tokens == 0
        assert not state.history.reminders and state.history.active_confirmation is None
        assert_no_external_work(lab)
    finally:
        await lab.close()


async def test_new_urgent_safety_question_fences_late_prepare_without_refunding_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "urgent-priority")
    original = lab.touch._model.respond

    async def interrupted(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        receipt = await original(prompt, max_output_tokens=max_output_tokens)
        assert receipt.bound_reminder_decision and receipt.bound_reminder_decision.kind == "prepare"
        urgent = AgentQuestionRequest.model_validate(
            next(s.body for s in lab.bootstrap().scenarios if s.key == "question")
        ).model_copy(update={"priority": 3})
        await lab.touch.request_question(urgent)
        return receipt

    try:
        monkeypatch.setattr(lab.touch._model, "respond", interrupted)
        original_request = request(clock)
        await lab.touch.admit_message(original_request)
        assert await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, original_request.request_id)
        assert done.phase == "failed" and done.response is None
        state = await lab.state()
        assert state.history.quota.used_tokens == 150 and state.history.quota.reserved_tokens == 0
        assert not state.history.reminders and state.history.active_confirmation is None
        with lab.store._connect() as db:
            assert tuple(db.execute("SELECT status,priority FROM family_questions").fetchone()) == (
                "queued",
                3,
            )
            assert not db.execute("SELECT 1 FROM assistant_reminders").fetchone()
        assert_no_external_work(lab)
    finally:
        await lab.close()


@pytest.mark.parametrize("control", ["late_disable", "captured_disabled"])
async def test_question_cannot_outlive_current_or_captured_clarification_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, control: str
) -> None:
    lab, clock = await setup(tmp_path / control)
    assert isinstance(lab.store, SqliteBoundReminderReviewStore)
    store = lab.store
    body, question = "Уточню ваш запрос.", "Вы хотите напомнить об этом только один раз?"

    async def unallowed_question(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        assert prompt.bound_reminder_request and prompt.manager_scope
        assert prompt.manager_scope.clarifications_enabled is (control != "captured_disabled")
        receipt = ChatModelReceipt(
            usage=ChatTokens(input_tokens=100, output_tokens=50),
            model="lab-simulated-not-billed",
            completed=True,
            answer=body + "\n\n" + question,
            clarification_question=question,
            bound_reminder_decision=BoundReminderDecision(
                kind="reply", body=body, question=question
            ),
        )
        if control == "late_disable":
            store._clarifications_enabled = False
        return receipt

    try:
        if control == "captured_disabled":
            store._clarifications_enabled = False
        original_request = request(clock)
        await lab.touch.admit_message(original_request)
        with store._connect() as db:
            assert db.execute("SELECT clarifications FROM bound_reminder_reviews").fetchone()[
                0
            ] == (control != "captured_disabled")
        if control == "captured_disabled":
            store._clarifications_enabled = True
        monkeypatch.setattr(lab.touch._model, "respond", unallowed_question)
        assert await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, original_request.request_id)
        assert done.phase == "failed" and done.response is None
        state = await lab.state()
        assert state.history.quota.used_tokens == 150 and state.history.quota.reserved_tokens == 0
        assert state.history.active_question is None
        assert not state.history.reminders and state.history.active_confirmation is None
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM family_questions").fetchone()
            assert not db.execute("SELECT 1 FROM parent_clarification_questions").fetchone()
        assert_no_external_work(lab)
    finally:
        await lab.close()


async def test_parent_touch_keeps_full_profile_context_and_original_request_without_proposal_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "full-input")
    original_read = lab.touch._children.read
    original_count, original_respond = lab.touch._model.count_input, lab.touch._model.respond
    contexts: list[ParentChildContext] = []
    counted: list[ChatPrompt] = []
    generated: list[ChatPrompt] = []

    async def observed_profile(parent_id: str) -> ParentChildContext:
        context = await original_read(parent_id)
        contexts.append(context)
        return context

    async def counted_prompt(prompt: ChatPrompt) -> int:
        counted.append(prompt)
        return await original_count(prompt)

    def assert_input(prompt: ChatPrompt) -> None:
        assert len(contexts) == 1 and len(counted) == 1
        context = contexts[0]
        assert prompt.messages == counted[0].messages
        assert prompt.instructions == counted[0].instructions
        assert prompt.bound_reminder_request == counted[0].bound_reminder_request
        assert prompt.bound_reminder_request
        assert prompt.minimum_output_tokens == 64
        assert prompt.manager_scope
        assert prompt.manager_scope.language_reference == original_request.message
        assert "the last parent message" in prompt.instructions
        data = json.loads(prompt.messages[0][1])
        assert data["profiles"] == {
            "collected_at": context.collected_at.isoformat(),
            "children": [
                {
                    "name": child.name,
                    "age": child.age,
                    "connected": child.connected,
                    "application_backend_observation": None,
                }
                for child in context.children
            ],
            "limitations": context.limitations,
        }
        assert context.tariff
        assert data["parent_tariff"] == context.tariff.model_dump(mode="json")
        assert data["assistant_reminders"] == {
            "now_local": clock.now().astimezone(ZoneInfo("Asia/Samarkand")).isoformat(),
            "default_timezone": "Asia/Samarkand",
            "timezone_basis": "parent_explicit_requires_confirmation",
            "active": [],
            "pending": None,
        }
        assert prompt.messages[-1] == ("user", original_request.message)
        # Inspect the prompt produced by Parent-Touch, then the SDK's actual message projection.
        wire = json.dumps(OpenAIParentChatModel._input(prompt), ensure_ascii=False)
        assert wire.count(original_request.message) == 1
        assert wire.count(prompt.bound_reminder_request.candidate.content) == 1
        assert prompt.bound_reminder_request.candidate.content not in prompt.messages[0][1]
        assert "bound_reminder_request" not in wire
        assert prompt.upsell_scope is None and prompt.retention_scope is None

    async def inspect_input(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        generated.append(prompt)
        return await original_respond(prompt, max_output_tokens=max_output_tokens)

    try:
        monkeypatch.setattr(lab.touch._children, "read", observed_profile)
        monkeypatch.setattr(lab.touch._model, "count_input", counted_prompt)
        monkeypatch.setattr(lab.touch._model, "respond", inspect_input)
        original_request = request(clock)
        await lab.touch.admit_message(original_request)
        assert await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, original_request.request_id)
        assert done.phase == "completed" and done.response and done.response.usage.total == 150
        assert len(generated) == 1
        assert_input(generated[0])
        assert_no_external_work(lab)
    finally:
        await lab.close()


async def test_unknown_review_retains_original_hold_after_restart_day_and_closed45(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "unknown")
    entered = asyncio.Event()

    async def lost(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        assert prompt.bound_reminder_request
        entered.set()
        await asyncio.Future()
        raise AssertionError("unreachable")

    try:
        original_request = request(clock)
        monkeypatch.setattr(lab.touch._model, "respond", lost)
        await lab.touch.admit_message(original_request)
        task = asyncio.create_task(lab.touch.process_reviewed_message())
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        unknown = await lab.touch.message_state(LAB_PARENT, original_request.request_id)
        assert unknown.phase == "unknown"
        quota = (await lab.state()).history.quota
        assert quota.reserved_tokens > 0 and quota.blocked_by_unresolved_request
        before = snapshot(lab.store._path)
        options = lab.options
        await lab.close()
        lab = ChatLab(options)
        await lab.start()
        closed = SqliteClosedBoundReminderReviewStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        assert snapshot(lab.store._path) == before
        clock.value += timedelta(days=1)
        assert (await closed.quota(LAB_PARENT, clock.now())).blocked_by_unresolved_request
        with lab.store._connect() as db:
            assert (
                db.execute(
                    "SELECT reserved FROM parent_chat_turns WHERE status='unknown'"
                ).fetchone()[0]
                == quota.reserved_tokens
            )
        assert await lab.touch.admit_message(original_request) == unknown
        assert not await lab.touch.process_reviewed_message()
        with pytest.raises(ParentChatError, match="previous_request_unresolved"):
            await lab.touch.admit_message(request(clock))
        assert snapshot(lab.store._path) == before
        assert_no_external_work(lab)
    finally:
        await lab.close()


@pytest.mark.parametrize("initial_version", [43, 44])
async def test_old_direct_capture_does_not_gain_semantic_review_after_rearm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, initial_version: int
) -> None:
    provider_calls: list[str] = []

    def deny(http_request: httpx.Request) -> httpx.Response:
        provider_calls.append(http_request.url.host)
        raise AssertionError("A protocol migration must not call a provider")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(deny))
    settings = compact_settings(tmp_path, enabled=initial_version == 44)
    async with runtime.parent_chat_runtime(settings) as service:
        assert service and isinstance(service.store, SqliteParentTouchManagerStore)
        old_store = service.store
    clock = Clock()
    old_request = ParentTouchReviewedTurn(**request(clock).model_dump())
    admitted = await old_store.admit_reviewed(old_request, clock.now(), allow_new=True)
    with old_store._connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == initial_version
        direct = tuple(db.execute("SELECT * FROM direct_reminder_routes").fetchone())
    async with runtime.parent_chat_runtime(
        settings.model_copy(update={"mana_parent_touch_bound_reminder_reviews_enabled": True})
    ) as rearmed:
        assert rearmed and isinstance(rearmed.store, SqliteBoundReminderReviewStore)
        assert (
            await rearmed.store.bound_reminder_review_request(LAB_PARENT, admitted.turn.turn_id)
            is None
        )
        replay = await rearmed.store.admit_reviewed(old_request, clock.now(), allow_new=True)
        assert replay.turn.turn_id == admitted.turn.turn_id
        with rearmed.store._connect() as db:
            assert not db.execute("SELECT 1 FROM bound_reminder_reviews").fetchone()
            assert tuple(db.execute("SELECT * FROM direct_reminder_routes").fetchone()) == direct
    assert not provider_calls
