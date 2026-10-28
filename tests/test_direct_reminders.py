"""Literal routing still performs one owning model review and ordinary confirmation."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt
from app.mana_ai.application.direct_reminders import direct_reminder_request
from app.mana_ai.domain.chat import ChatTokens
from app.mana_ai.domain.family_agents import AgentQuestionRequest, ParentTouchMessageRequest
from app.services.direct_reminder_store import (
    SqliteClosedDirectReminderStore,
    SqliteDirectReminderStore,
)
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from tests.test_mana_chat_lab import Clock
from tests.test_saved_observations import snapshot


@pytest.mark.parametrize("zone", ["UTC", "GMT", "Europe/London"])
def test_bare_explicit_timezone_never_becomes_task_or_contact_default(zone: str) -> None:
    parsed = direct_reminder_request(
        f"Remind me tomorrow at 09:00 {zone} to buy notebooks",
        now=Clock.value,
        timezone="Asia/Samarkand",
        timezone_basis="verified_contact",
    )
    assert parsed and parsed.candidate.timezone == zone
    assert parsed.candidate.content == "buy notebooks"
    assert parsed.timezone_basis == "parent_explicit_requires_confirmation"


@pytest.mark.parametrize(
    "message",
    [
        "Remind me tomorrow at 09:00 MSK to buy notebooks",
        "Remind me tomorrow at 09:00 GMT+5 to buy notebooks",
        "Ertaga soat 09:00da Europe/London daftar sotib olishni eslat",
        "Эртага соат 09:00да Europe/London дафтар сотиб олишни эслат",
        "Remind me 2026-10-25 at 02:30 timezone Europe/Berlin to buy notebooks",
        "Remind me 2026-03-29 at 02:30 timezone Europe/Berlin to buy notebooks",
    ],
)
def test_unknown_or_ambiguous_wall_time_needs_general_model_routing(message: str) -> None:
    assert (
        direct_reminder_request(
            message,
            now=Clock.value,
            timezone="Asia/Samarkand",
            timezone_basis="verified_contact",
        )
        is None
    )


async def setup(path: Path, *, enabled: bool = True) -> tuple[ChatLab, Clock]:
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
            direct_reminders=enabled,
        )
    )
    await lab.start()
    if enabled:
        assert isinstance(lab.store, SqliteDirectReminderStore)
    return lab, clock


@pytest.mark.parametrize(
    "message,task",
    [
        ("Напомни мне завтра в 09:00 купить тетради.", "купить тетради."),
        ("Remind me tomorrow at 09:00 to buy notebooks", "buy notebooks"),
        ("Eslat ertaga soat 09:00 daftar sotib olish", "daftar sotib olish"),
        ("Ertaga soat 09:00da daftar sotib olishni eslat", "daftar sotib olishni"),
        ("Эслат эртага соат 09:00 дафтар сотиб олиш", "дафтар сотиб олиш"),
        ("Эртага соат 09:00да дафтар сотиб олишни эслат", "дафтар сотиб олишни"),
    ],
)
async def test_one_owning_model_exact_task_confirmation_delivery_and_replay(
    tmp_path: Path,
    message: str,
    task: str,
) -> None:
    lab, clock = await setup(tmp_path / "chat")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message=message
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        assert not await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "completed" and state.response and state.response.usage.total == 150
        history = (await lab.state()).history
        pending = history.active_confirmation
        assert pending and pending.kind == "approval" and pending.candidate.content == task
        assert history.quota.used_tokens == 150 and len(history.messages) == 2
        assert (await lab.state()).safety_budget.server_used_tokens == 0
        with lab.store._connect() as db:
            row = db.execute(
                "SELECT phase,choice,call_id,input_tokens,output_tokens "
                "FROM parent_touch_manager_turns"
            ).fetchone()
            assert tuple(row) == ("finished", "reminder", None, 100, 50)
            assert db.execute("SELECT COUNT(*) FROM direct_reminder_routes").fetchone()[0] == 1
        before = snapshot(lab.store._path)
        assert await lab.touch.admit_message(request) == state
        assert snapshot(lab.store._path) == before
        confirm = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Да",
            reply_to_confirmation_id=pending.confirmation_id,
        )
        confirmed = await lab.touch.admit_message(confirm)
        assert (
            confirmed.phase == "completed"
            and confirmed.response
            and confirmed.response.usage.total == 0
        )
        options = lab.options
        before = snapshot(lab.store._path)
        await lab.close()
        lab = ChatLab(options)
        await lab.start()
        assert snapshot(lab.store._path) == before
        assert await lab.touch.admit_message(confirm) == confirmed
        assert snapshot(lab.store._path) == before
        assert pending.candidate.due_at
        clock.value = pending.candidate.due_at + timedelta(seconds=1)
        assert lab.touch.reminders and await lab.touch.reminders.process_one()
        assert not await lab.touch.reminders.process_one()
        history = (await lab.state()).history
        assert not history.reminders and len(history.messages) == 5
        # The requested tomorrow is a new quota day, not a reset of the old receipt.
        assert history.quota.used_tokens == 0
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM assistant_reminders").fetchone()[0] == "delivered"
            assert db.execute("SELECT SUM(used) FROM parent_chat_quota").fetchone()[0] == 150
        assert lab.battery.calls == lab.app_usage.calls == lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_disabling_at_admission_never_upgrades_that_turn_after_rearm(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "old-capture")
    assert isinstance(lab.store, SqliteDirectReminderStore)
    try:
        lab.store._direct_reminders_enabled = False
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Напомни завтра в 09:00 купить тетради",
        )
        await lab.touch.admit_message(request)
        lab.store._direct_reminders_enabled = True
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM direct_reminder_routes").fetchone()
        # This original general-route capture still performs its original two calls.
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert done.phase == "completed" and done.response and done.response.usage.total == 300
    finally:
        await lab.close()


async def test_unknown_owning_model_keeps_hold_closed_reader_restart_and_next_day(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "unknown")
    entered = asyncio.Event()

    class Lost:
        async def count_input(self, prompt: ChatPrompt) -> int:
            assert prompt.manager_scope and prompt.manager_scope.stage == "reminder"
            return 100

        async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
            entered.set()
            await asyncio.Future()
            raise AssertionError("unreachable")

    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Напомни завтра в 09:00 купить тетради",
        )
        await lab.touch.admit_message(request)
        lab.touch._model = Lost()
        task = asyncio.create_task(lab.touch.process_reviewed_message())
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        unknown = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert unknown.phase == "unknown"
        before = snapshot(lab.store._path)
        options = lab.options
        await lab.close()
        lab = ChatLab(options)
        await lab.start()
        assert snapshot(lab.store._path) == before
        closed = SqliteClosedDirectReminderStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        clock.value += timedelta(days=1)
        quota = await closed.quota(LAB_PARENT, clock.now())
        assert quota.blocked_by_unresolved_request
        with lab.store._connect() as db:
            assert (
                db.execute(
                    "SELECT reserved FROM parent_chat_turns WHERE status='unknown'"
                ).fetchone()[0]
                > 0
            )
        assert not await lab.touch.process_reviewed_message()
        assert await lab.touch.admit_message(request) == unknown
        assert snapshot(lab.store._path) == before
    finally:
        await lab.close()


async def test_semantic_refusal_creates_no_draft_or_confirmation(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "refusal")

    class Refuse:
        async def count_input(self, prompt: ChatPrompt) -> int:
            return 100

        async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
            assert "Refuse reminders enabling harm" in prompt.instructions
            return ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=50),
                model="lab-simulated-not-billed",
                completed=True,
                answer="С этим напоминанием я не помогу.",
            )

    try:
        lab.touch._model = Refuse()
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Напомни завтра в 09:00 вымышленная запрещённая задача",
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "completed" and state.response
        history = (await lab.state()).history
        assert not history.reminders and history.active_confirmation is None
        assert history.quota.used_tokens == 150
    finally:
        await lab.close()


async def test_original_relative_day_and_zone_survive_midnight_and_changed_contact(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "midnight")
    # A fresh independent fictional clock; no existing request/cost is moved backward.
    # Recreate before admitting any task so the verified contact is stamped at this time.
    options = lab.options
    await lab.close()
    clock.value = datetime(2026, 10, 24, 18, 59, tzinfo=UTC)
    lab = ChatLab(options)
    await lab.start()
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Напомни завтра в 09:00 купить тетради",
        )
        await lab.touch.admit_message(request)
        clock.value += timedelta(minutes=2)
        assert lab.touch.proactive
        contact = await lab.store.contact_context(LAB_PARENT, clock.now())
        assert contact
        await lab.touch.proactive.register(
            contact.model_copy(
                update={
                    "event_id": uuid4(),
                    "revision": contact.revision + 1,
                    "observed_at": clock.now(),
                    "valid_until": clock.now() + timedelta(days=1),
                    "timezone": "America/New_York",
                }
            )
        )
        assert await lab.touch.process_reviewed_message()
        history = (await lab.state()).history
        pending = history.active_confirmation
        assert pending and pending.candidate.due_at
        assert pending.candidate.due_at.isoformat() == "2026-10-25T09:00:00+05:00"
        assert pending.candidate.timezone == "Asia/Samarkand"
    finally:
        await lab.close()


async def test_submit_time_disable_stops_inference_and_keeps_no_usage(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "submit-stop")
    assert isinstance(lab.store, SqliteDirectReminderStore)
    store = lab.store

    class StopAtCount:
        async def count_input(self, prompt: ChatPrompt) -> int:
            store._direct_reminders_enabled = False
            return 100

        async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
            raise AssertionError("Submission fence must stop before generation")

    try:
        lab.touch._model = StopAtCount()
        req = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Напомни завтра в 09:00 купить тетради",
        )
        await lab.touch.admit_message(req)
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, req.request_id)
        assert state.phase == "failed" and state.error_code == "direct_reminder_disabled"
        h = (await lab.state()).history
        assert h.quota.used_tokens == h.quota.reserved_tokens == 0 and not h.reminders
    finally:
        await lab.close()


async def test_late_safety_priority_keeps_usage_but_discards_draft(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "priority")
    original = lab.touch._model.respond

    class Interrupt:
        async def count_input(self, prompt: ChatPrompt) -> int:
            return 100

        async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
            receipt = await original(prompt, max_output_tokens=max_output_tokens)
            need = AgentQuestionRequest.model_validate(
                next(s.body for s in lab.bootstrap().scenarios if s.key == "question")
            )
            await lab.touch.request_question(need)
            return receipt

    try:
        lab.touch._model = Interrupt()
        req = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Напомни завтра в 09:00 купить тетради",
        )
        await lab.touch.admit_message(req)
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, req.request_id)
        assert state.phase == "failed"
        h = (await lab.state()).history
        assert h.quota.used_tokens == 150 and not h.reminders
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM family_questions").fetchone()[0] == "queued"
    finally:
        await lab.close()


@pytest.mark.parametrize(
    "message",
    [
        "Напомни купить тетради",
        "Напомни мне завтра в 09:00 купить тетради. И помоги с уроками",
        "Напомни завтра в 09:00 купить тетради; проверь заряд",
        "Как помочь ребёнку?",
        "Напомни завтра в 09:00 timezone Atlantis купить тетради",
        "Напомни завтра в 09:00 timezone Mars/Unknown купить тетради",
        "Напомни завтра в 25:00 купить тетради",
        "Напомни 2026-02-30 в 09:00 купить тетради",
    ],
)
def test_incomplete_mixed_or_invalid_requests_retain_general_model_routing(message: str) -> None:
    assert (
        direct_reminder_request(
            message,
            now=Clock.value,
            timezone="Asia/Samarkand",
            timezone_basis="verified_contact",
        )
        is None
    )


@pytest.mark.parametrize(
    "stop", ["before", "late", "date_changed", "content_changed", "zone_changed"]
)
async def test_disabled_or_changed_decisions_never_prepare_a_reminder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stop: str,
) -> None:
    lab, clock = await setup(tmp_path / stop)
    assert isinstance(lab.store, SqliteDirectReminderStore)
    store = lab.store
    original = lab.touch._model.respond

    async def changed(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        receipt = await original(prompt, max_output_tokens=max_output_tokens)
        if stop == "late":
            store._direct_reminders_enabled = False
        elif receipt.reminder_candidate is not None:
            candidate = receipt.reminder_candidate
            if stop == "date_changed":
                candidate = candidate.model_copy(
                    update={
                        "due_at": candidate.due_at + timedelta(days=1) if candidate.due_at else None
                    }
                )
            if stop == "content_changed":
                candidate = candidate.model_copy(update={"content": "another task"})
            if stop == "zone_changed":
                candidate = candidate.model_copy(update={"timezone": "Asia/Tashkent"})
            receipt = replace(receipt, reminder_candidate=candidate)
        return receipt

    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Напомни завтра в 09:00 купить тетради",
        )
        await lab.touch.admit_message(request)
        if stop == "before":
            store._direct_reminders_enabled = False
        monkeypatch.setattr(lab.touch._model, "respond", changed)
        assert await lab.touch.process_reviewed_message() is (stop != "before")
        result = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert result.phase == "failed"
        state = await lab.state()
        assert not state.history.reminders and state.history.active_confirmation is None
        assert state.history.quota.used_tokens == (0 if stop == "before" else 150)
        assert state.history.quota.reserved_tokens == 0
    finally:
        await lab.close()
