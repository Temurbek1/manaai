"""Compact manager capture preserves tools, full input and durable cost fences."""

import asyncio
import json
from contextlib import suppress
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.mana_ai.application import parent_touch as touch_module
from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt
from app.mana_ai.application.compact_parent_manager import compact_manager_route
from app.mana_ai.application.compact_parent_publication import compact_child_publication
from app.mana_ai.application.parent_touch_manager import manager_prompt
from app.mana_ai.application.source_tool_ports import SourceModelReceipt, SourceToolPrompt
from app.mana_ai.application.source_tool_workflow import SourceToolWorkflow
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.parent_touch_manager import ParentTouchManagerScope
from app.services.compact_parent_publication_store import (
    SqliteClosedCompactParentPublicationStore,
    SqliteCompactParentPublicationStore,
)
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.parent_chat_model import OpenAIParentChatModel
from tests.test_mana_chat_lab import Clock
from tests.test_parent_chat_adapters import settings as model_settings
from tests.test_trial_action_cards import snapshot


async def setup(path: Path, *, compact: bool = True) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        replace(
            workspace_options(path, clock=clock, worker_enabled=False),
            tariff_handoff=True,
            compact_inputs=True,
            compact_publication=True,
            compact_manager=compact,
        )
    )
    await lab.start()
    assert isinstance(lab.store, SqliteCompactParentPublicationStore)
    return lab, clock


def ask(message: str = "Какой заряд у ребёнка?") -> ParentTouchMessageRequest:
    return ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=message)


async def test_sdk_and_full_workflow_retain_messages_tools_schema_floors_and_pairing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "full")
    sdk = OpenAIParentChatModel(model_settings())
    original = lab.touch._model.respond
    stages = []

    async def observe(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        scope = prompt.manager_scope
        assert scope
        old = manager_prompt(
            scope, json.loads(prompt.messages[0][1]), prompt.messages, template=prompt
        )
        old = replace(old, input_presentation=1)
        assert old.messages == prompt.messages
        assert old.minimum_output_tokens == prompt.minimum_output_tokens == 128
        assert sdk._text(old) == sdk._text(prompt)
        assert sdk._manager_tools(old) == sdk._manager_tools(prompt)
        if scope.stage == "route":
            assert prompt.instructions == compact_manager_route(scope, bound_support=False)
            assert len(prompt.instructions) < len(old.instructions)
        else:
            assert scope.stage == "child_safety"
            assert prompt.instructions == compact_child_publication(
                scope, version=5, battery_source=prompt.battery_source_publication
            )
        stages.append(scope.stage)
        return await original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(lab.touch._model, "respond", observe)
    try:
        request = ask()
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        result = await lab.safety.process_one()
        assert result and result.status == "completed"
        assert await lab.touch.process_reviewed_message()
        completed = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert completed.phase == "completed" and stages == ["route", "child_safety"]
        state = await lab.state()
        assert state.history.quota.used_tokens == state.safety_budget.server_used_tokens == 300
        assert lab.battery.calls == 1
        with lab.store._connect() as db:
            assert (
                json.loads(db.execute("SELECT profile FROM source_tool_turns").fetchone()[0])[
                    "parent_publication"
                ]
                == 5
            )
        before = snapshot(lab.store)
        assert await lab.touch.admit_message(request) == completed
        assert snapshot(lab.store) == before and lab.battery.calls == 1
    finally:
        await sdk.close()
        await lab.close()


async def test_tariff_keeps_one_extraction_bound_currency_answer_and_owning_quote(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "price")
    try:
        request = ask("Покажи тарифы на 90 дней до 200000")
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        first = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert first.response and first.response.asked_question
        answer = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="UZS",
            reply_to_question_id=first.response.asked_question.question_id,
        )
        await lab.touch.admit_message(answer)
        assert await lab.touch.process_upsell()
        final = await lab.touch.message_state(LAB_PARENT, answer.request_id)
        assert final.response and "162 000.00 UZS" in final.response.answer
        assert (await lab.state()).history.quota.used_tokens == 150
        assert (await lab.state()).safety_budget.server_used_tokens == 0
        assert lab.catalog.calls == 1
        before = snapshot(lab.store)
        assert await lab.touch.admit_message(request) == first
        assert await lab.touch.admit_message(answer) == final
        assert snapshot(lab.store) == before
    finally:
        await lab.close()


async def test_reminder_is_an_unexecuted_draft_under_its_owning_scope(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "reminder")
    try:
        request = ask("Напомни завтра в 9 купить тетради")
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_reviewed_message()
        history = (await lab.state()).history
        assert history.active_confirmation is not None
        assert history.quota.used_tokens == 300
        assert (await lab.state()).safety_budget.server_used_tokens == 0
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM assistant_reminders").fetchone()[0] == "draft"
    finally:
        await lab.close()


async def test_bound_help_reply_keeps_one_question_and_original_unverified_device_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "help")
    original = lab.touch._model.respond
    bound = []

    async def observe(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        data = json.loads(prompt.messages[0][1])
        if "answered_parent_question" in data:
            assert prompt.manager_scope
            assert prompt.instructions == compact_manager_route(
                prompt.manager_scope, bound_support=True
            )
            bound.append(data["answered_parent_question"])
        return await original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(lab.touch._model, "respond", observe)
    try:
        request = ask("Как настроить MANA?")
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        first = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert first.response and first.response.asked_question
        answer = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Android",
            reply_to_question_id=first.response.asked_question.question_id,
        )
        await lab.touch.admit_message(answer)
        assert await lab.touch.process_reviewed_message()
        final = await lab.touch.message_state(LAB_PARENT, answer.request_id)
        assert final.response and bound
        assert (await lab.state()).safety_budget.server_used_tokens == 0
        assert lab.battery.calls == lab.catalog.calls == 0
    finally:
        await lab.close()


@pytest.mark.parametrize("late", [False, True])
async def test_disable_fences_work_and_retains_verified_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, late: bool
) -> None:
    lab, _ = await setup(tmp_path / str(late))
    original = lab.touch._model.respond
    assert isinstance(lab.store, SqliteCompactParentPublicationStore)
    store = lab.store

    async def disable(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        result = await original(prompt, max_output_tokens=max_output_tokens)
        store._compact_manager_enabled = False
        return result

    try:
        request = ask()
        await lab.touch.admit_message(request)
        if late:
            monkeypatch.setattr(lab.touch._model, "respond", disable)
        else:
            store._compact_manager_enabled = False
        assert await lab.touch.process_reviewed_message()
        final = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert final.phase == "failed" and final.response is None
        assert (await lab.state()).history.quota.used_tokens == (150 if late else 0)
        assert lab.battery.calls == 0
        assert await lab.safety.process_one() is None
    finally:
        await lab.close()


async def test_old_v4_admission_does_not_gain_compact_routing_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "old", compact=False)
    assert isinstance(lab.store, SqliteCompactParentPublicationStore)
    original = lab.touch._model.respond
    observed = []
    baseline = {}
    original_builder = manager_prompt

    def build(
        scope: ParentTouchManagerScope,
        data: dict[str, object],
        messages: tuple[tuple[str, str], ...],
        *,
        template: ChatPrompt,
    ) -> ChatPrompt:
        result = original_builder(scope, data, messages, template=template)
        baseline[scope.stage] = result.instructions
        return result

    async def observe(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        assert prompt.manager_scope
        if prompt.manager_scope.stage == "route":
            assert prompt.instructions == baseline["route"]
            observed.append(True)
        return await original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(lab.touch._model, "respond", observe)
    monkeypatch.setattr(touch_module, "manager_prompt", build)
    try:
        await lab.touch.admit_message(ask())
        lab.store._compact_manager_enabled = True
        assert await lab.touch.process_reviewed_message() and observed
        with lab.store._connect() as db:
            assert (
                json.loads(db.execute("SELECT profile FROM source_tool_turns").fetchone()[0])[
                    "parent_publication"
                ]
                == 4
            )
    finally:
        await lab.close()


async def test_native_late_disable_keeps_usage_without_source_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "late-native")
    store, workflow = lab.store, lab.safety._native_sources
    assert isinstance(store, SqliteCompactParentPublicationStore)
    assert isinstance(workflow, SourceToolWorkflow)
    original = workflow._model.respond_source

    async def disable(prompt: SourceToolPrompt, *, max_output_tokens: int) -> SourceModelReceipt:
        result = await original(prompt, max_output_tokens=max_output_tokens)
        store._compact_manager_enabled = False
        return result

    monkeypatch.setattr(workflow._model, "respond_source", disable)
    try:
        await lab.touch.admit_message(ask())
        assert await lab.touch.process_reviewed_message()
        result = await lab.safety.process_one()
        assert result and result.status == "failed"
        assert (await lab.state()).safety_budget.server_used_tokens == 150
        assert lab.battery.calls == 0
    finally:
        await lab.close()


async def test_unknown_initial_generation_keeps_capture_and_hold_across_closed_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "unknown")
    entered = asyncio.Event()

    async def lost(prompt: ChatPrompt, *, max_output_tokens: int) -> Any:
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(lab.touch._model, "respond", lost)
    try:
        await lab.touch.admit_message(ask())
        task = asyncio.create_task(lab.touch.process_reviewed_message())
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        quota = (await lab.state()).history.quota
        assert quota.blocked_by_unresolved_request and quota.reserved_tokens > 0
        before = snapshot(lab.store)
        await SqliteClosedCompactParentPublicationStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
        assert snapshot(lab.store) == before
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        assert not await lab.touch.process_reviewed_message()
        assert (
            await lab.store.quota(LAB_PARENT, clock.now() + timedelta(days=1))
        ).blocked_by_unresolved_request
        assert snapshot(lab.store) == before and lab.battery.calls == 0
    finally:
        await lab.close()
