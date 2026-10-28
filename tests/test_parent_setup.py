"""Complete existing profile -> one support question -> bound same-chat help."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
import pytest

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.parent_setup import SetupProfileSource
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.parent_setup import ParentSetupFact
from app.mana_ai.domain.proactive_parent import ParentContactContext
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import LAB_CHILD, LAB_PARENT, ChatLab
from app.services.parent_setup_store import SqliteClosedParentSetupStore, SqliteParentSetupStore
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
            parent_setup=True,
        )
    )
    await lab.start()
    assert isinstance(lab.store, SqliteParentSetupStore)
    return lab, clock


def fact(
    now: datetime, children: tuple[int, ...] = (), parent: str = LAB_PARENT
) -> ParentSetupFact:
    return ParentSetupFact(parent_id=parent, collected_at=now, connected_child_ids=children)


async def contact(
    lab: ChatLab,
    language: Literal["ru", "uz-Latn"] = "ru",
    *,
    consent: bool = True,
    parent_id: str = LAB_PARENT,
) -> None:
    now = lab.options.clock.now()
    assert lab.touch.proactive
    await lab.touch.proactive.register(
        ParentContactContext(
            parent_id=parent_id,
            event_id=uuid4(),
            revision=int(now.timestamp() * 1000000) + 2,
            observed_at=now,
            valid_until=now + timedelta(days=1),
            language=language,
            timezone="Asia/Samarkand",
            safety_chat_consent=True,
            safety_push_consent=False,
            retention_chat_consent=consent,
            retention_push_consent=False,
            marketing_push_consent=False,
        )
    )


@pytest.mark.parametrize("language", ["ru", "uz-Latn"])
async def test_first_contact_same_chat_exact_answer_and_restart(
    tmp_path: Path, language: Literal["ru", "uz-Latn"]
) -> None:
    lab, clock = await setup(tmp_path / "chat")
    try:
        assert isinstance(lab.store, SqliteParentSetupStore)
        await contact(lab, language)
        assert (await lab.prepare_parent_setup())["status"] == "completed"
        assert await lab.touch.process_retention()
        state = await lab.state()
        assert len(state.history.messages) == 1 and state.history.messages[0].role == "assistant"
        q = state.history.active_question
        assert q and q.scope == "parent" and q.child_id is None
        assert (
            "нет подключённого ребёнка" if language == "ru" else "ulangan bola yo‘q"
        ) in state.history.messages[0].content
        assert state.history.quota.used_tokens == state.safety_budget.server_used_tokens == 0
        assert not await lab.touch.process_retention()
        req = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Да" if language == "ru" else "Ha",
            reply_to_question_id=q.question_id,
        )
        await lab.touch.admit_message(req)
        assert await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, req.request_id)
        assert done.phase == "completed" and done.response and done.response.asked_question
        device = done.response.asked_question
        answer = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Android",
            reply_to_question_id=device.question_id,
        )
        await lab.touch.admit_message(answer)
        assert await lab.touch.process_reviewed_message()
        completed = await lab.touch.message_state(LAB_PARENT, answer.request_id)
        assert completed.phase == "completed" and completed.response
        assert (
            "подключения ребёнка" if language == "ru" else "bolani ulash"
        ) in completed.response.answer
        with lab.store._connect() as db:
            assert [
                tuple(r)
                for r in db.execute(
                    "SELECT turn_id,depth,protocol FROM setup_help_captures ORDER BY turn_id"
                )
            ] == [(done.turn_id, 1, 1), (completed.turn_id, 2, 1)]
        assert (await lab.state()).safety_budget.server_used_tokens == 0
        before = snapshot(lab.store._path)
        options = lab.options
        await lab.close()
        lab = ChatLab(options)
        await lab.start()
        assert snapshot(lab.store._path) == before
        assert await lab.touch.admit_message(req) == done
        assert await lab.touch.admit_message(answer) == completed
        assert snapshot(lab.store._path) == before
        closed = SqliteClosedParentSetupStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        await closed.touch_history(LAB_PARENT, before=None, limit=20, now=clock.now())
        assert snapshot(lab.store._path) == before
        assert lab.battery.calls == lab.app_usage.calls == lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_old_reply_capture_never_gains_new_setup_help_instructions(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "old-capture")
    assert isinstance(lab.store, SqliteParentSetupStore)
    try:
        await contact(lab)
        await lab.prepare_parent_setup()
        assert await lab.store.publish_setup(clock.now())
        q = (await lab.state()).history.active_question
        assert q
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Да",
            reply_to_question_id=q.question_id,
        )
        await lab.touch.admit_message(request)
        with lab.store._transaction() as db:
            # Reconstruct the first local v42 capture: its original stop fence exists,
            # but the new prompt protocol was not captured at admission.
            db.execute("DELETE FROM setup_help_captures")
        assert await lab.store.claim_reviewed_response(clock.now()) is not None
        before = snapshot(lab.store._path)
        options = lab.options
        await lab.close()
        lab = ChatLab(options)
        await lab.start()
        assert isinstance(lab.store, SqliteParentSetupStore)
        assert snapshot(lab.store._path) == before
        with lab.store._connect() as db:
            turn = db.execute("SELECT turn_id FROM setup_reply_captures").fetchone()[0]
        scope = await lab.store.manager_scope(LAB_PARENT, turn)
        assert scope and scope.setup_help_protocol is None
        assert snapshot(lab.store._path) == before
    finally:
        await lab.close()


async def test_shared_daily_outreach_limit_is_global_not_per_family(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "global")
    assert isinstance(lab.store, SqliteParentSetupStore)
    try:
        for parent in (str(900001 + i) for i in range(21)):
            await contact(lab, parent_id=parent)
            assert await lab.store.observe_setup_facts(
                (fact(clock.now(), parent=parent),), clock.now()
            )
        for _ in range(20):
            assert await lab.store.publish_setup(clock.now())
        assert not await lab.store.publish_setup(clock.now())
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM setup_notices").fetchone()[0] == 20
            assert (
                db.execute("SELECT COUNT(DISTINCT parent_id) FROM setup_notices").fetchone()[0]
                == 20
            )
            assert (
                db.execute("SELECT COUNT(*) FROM setup_epochs WHERE phase='pending'").fetchone()[0]
                == 1
            )
            assert lab.store._retention_daily_count(db, clock.now()) == 20
        assert lab.battery.calls == lab.app_usage.calls == lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_unknown_setup_reply_survives_restart_and_next_day_without_dispatch(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "unknown")
    entered = asyncio.Event()

    class Lost:
        async def count_input(self, prompt: ChatPrompt) -> int:
            assert prompt.manager_scope and prompt.manager_scope.setup_help_protocol == 1
            return 100

        async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
            entered.set()
            await asyncio.Future()
            raise AssertionError("unreachable")

    try:
        await contact(lab)
        await lab.prepare_parent_setup()
        assert isinstance(lab.store, SqliteParentSetupStore)
        assert await lab.store.publish_setup(clock.now())
        q = (await lab.state()).history.active_question
        assert q
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Да",
            reply_to_question_id=q.question_id,
        )
        await lab.touch.admit_message(request)
        lab.touch._model = Lost()
        task = asyncio.create_task(lab.touch.process_reviewed_message())
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "unknown"
        before = snapshot(lab.store._path)
        options = lab.options
        await lab.close()
        lab = ChatLab(options)
        await lab.start()
        assert snapshot(lab.store._path) == before
        clock.value += timedelta(days=1)
        closed = SqliteClosedParentSetupStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        assert (await closed.quota(LAB_PARENT, clock.now())).blocked_by_unresolved_request
        assert await lab.touch.admit_message(request) == state
        assert not await lab.touch.process_reviewed_message()
        assert snapshot(lab.store._path) == before
        assert lab.battery.calls == lab.app_usage.calls == lab.catalog.calls == 0
    finally:
        await lab.close()


@pytest.mark.parametrize(
    "condition",
    ["disabled", "no_consent", "stale", "unknown", "connected", "quiet", "auth", "priority"],
)
async def test_no_contact_without_current_permission_and_empty_linkage(
    tmp_path: Path, condition: str
) -> None:
    lab, clock = await setup(tmp_path / condition)
    try:
        assert isinstance(lab.store, SqliteParentSetupStore)
        await contact(lab, consent=condition != "no_consent")
        if condition == "disabled":
            lab.store._parent_setup_enabled = False
        if condition == "quiet":
            clock.value = clock.value.replace(hour=20)
        await lab.store.observe_setup_facts((fact(clock.now()),), clock.now())
        if condition == "stale":
            clock.value += timedelta(seconds=181)
        if condition == "unknown":
            await lab.store.invalidate_setup_profile(LAB_PARENT, clock.now())
        if condition == "connected":
            clock.value += timedelta(seconds=1)
            await lab.store.observe_setup_facts((fact(clock.now(), (LAB_CHILD,)),), clock.now())
        if condition == "auth":
            await lab.store.close_setup_source()
        if condition == "priority":
            await lab.touch.admit_message(
                ParentTouchMessageRequest(
                    parent_id=LAB_PARENT, request_id=uuid4(), message="Какой заряд?"
                )
            )
        assert not await lab.store.publish_setup(clock.now())
        assert not any(m.role == "assistant" for m in (await lab.state()).history.messages)
    finally:
        await lab.close()


async def test_unchanged_zero_epoch_disable_rearm_and_new_connected_veto(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "epochs")
    try:
        assert isinstance(lab.store, SqliteParentSetupStore)
        await contact(lab)
        lab.store._parent_setup_enabled = False
        await lab.store.observe_setup_facts((fact(clock.now()),), clock.now())
        lab.store._parent_setup_enabled = True
        clock.value += timedelta(seconds=1)
        await lab.store.observe_setup_facts((fact(clock.now()),), clock.now())
        assert not await lab.store.publish_setup(clock.now())
        clock.value += timedelta(seconds=1)
        await lab.store.observe_setup_facts((fact(clock.now(), (LAB_CHILD,)),), clock.now())
        clock.value += timedelta(seconds=1)
        await lab.store.observe_setup_facts((fact(clock.now()),), clock.now())
        assert await lab.store.publish_setup(clock.now())
        q = (await lab.state()).history.active_question
        assert q
        clock.value += timedelta(seconds=1)
        await lab.store.observe_setup_facts((fact(clock.now(), (LAB_CHILD,)),), clock.now())
        assert (await lab.state()).history.active_question is None
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM setup_notices").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM retention_intents").fetchone()[0] == 0
    finally:
        await lab.close()


async def test_wrapper_single_read_complete_coverage_and_unknown_invalidation(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "wrapper")

    class Profiles:
        calls = 0
        complete: Literal[True] | None = True
        error: BaseException | None = None

        async def read(self, parent_id: str) -> ParentChildContext:
            self.calls += 1
            if self.error:
                raise self.error
            return ParentChildContext(
                parent_id=parent_id,
                children=[],
                children_complete=self.complete,
                collected_at=clock.now(),
                limitations=[],
            )

    assert isinstance(lab.store, SqliteParentSetupStore)
    profiles = Profiles()
    source = SetupProfileSource(profiles, lab.store, clock=clock.now)
    try:
        await contact(lab)
        profiles.complete = None
        await source.read(LAB_PARENT)
        assert profiles.calls == 1 and not await lab.store.publish_setup(clock.now())
        profiles.complete = True
        await source.read(LAB_PARENT)
        assert profiles.calls == 2
        profiles.error = httpx.ReadTimeout("fake unknown")
        with pytest.raises(httpx.ReadTimeout):
            await source.read(LAB_PARENT)
        assert profiles.calls == 3 and not await lab.store.publish_setup(clock.now())
        profiles.error = ParentChatError("child_source_auth_denied", 503)
        with pytest.raises(ParentChatError):
            await source.read(LAB_PARENT)
        with lab.store._connect() as db:
            assert db.execute("SELECT closed FROM setup_policy").fetchone()[0] == "source_closed"
    finally:
        await lab.close()


@pytest.mark.parametrize("stop", ["flag", "auth"])
async def test_late_reply_stop_accounts_usage_without_new_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop: str
) -> None:
    lab, clock = await setup(tmp_path / stop)
    assert isinstance(lab.store, SqliteParentSetupStore)
    store = lab.store
    original = lab.touch._model.respond

    async def respond(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        receipt = await original(prompt, max_output_tokens=max_output_tokens)
        if stop == "flag":
            store._parent_setup_enabled = False
        else:
            await store.close_setup_source()
        return receipt

    try:
        await contact(lab)
        await lab.prepare_parent_setup()
        assert await lab.store.publish_setup(clock.now())
        q = (await lab.state()).history.active_question
        assert q
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Да",
            reply_to_question_id=q.question_id,
        )
        await lab.touch.admit_message(request)
        monkeypatch.setattr(lab.touch._model, "respond", respond)
        assert await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert done.phase == "failed" and done.response is None
        state = await lab.state()
        assert state.history.quota.used_tokens == 150 and state.history.quota.reserved_tokens == 0
        assert state.history.active_question is None
        assert len([m for m in state.history.messages if m.role == "assistant"]) == 1
        assert state.safety_budget.server_used_tokens == 0
    finally:
        await lab.close()


async def test_optout_never_resurrects_the_same_zero_child_epoch(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "limits")
    assert isinstance(lab.store, SqliteParentSetupStore)
    try:
        await contact(lab)
        await lab.prepare_parent_setup()
        assert await lab.store.publish_setup(clock.now())
        q = (await lab.state()).history.active_question
        assert q
        no = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="не пиши первым",
            reply_to_question_id=q.question_id,
        )
        result = await lab.touch.admit_message(no)
        assert result.phase == "completed" and result.response and result.response.usage.total == 0
        assert (await lab.state()).history.active_question is None
        clock.value += timedelta(seconds=1)
        await lab.store.observe_setup_facts((fact(clock.now()),), clock.now())
        assert not await lab.store.publish_setup(clock.now())
        resume = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="возобнови напоминания об этом чате"
        )
        await lab.touch.admit_message(resume)
        assert not await lab.store.publish_setup(clock.now())
        # No reset of a disabled/cancelled/published zero-link epoch or second intro.
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM setup_notices").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM retention_intents").fetchone()[0] == 0
    finally:
        await lab.close()
