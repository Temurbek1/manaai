"""New publication prompts keep original facts, admission floors and unknown costs."""

import asyncio
import hashlib
import json
import sqlite3
from contextlib import suppress
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pytest

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt
from app.mana_ai.application.compact_parent_publication import compact_child_publication
from app.mana_ai.application.parent_touch_manager import manager_prompt
from app.mana_ai.application.source_tool_ports import SourceModelReceipt, SourceToolPrompt
from app.mana_ai.application.source_tool_workflow import SourceToolWorkflow
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.parent_touch_manager import ParentTouchManagerScope
from app.mana_ai.domain.source_tools import SourceToolPreparedInput
from app.services.compact_parent_publication_store import (
    SqliteClosedCompactParentPublicationStore,
    SqliteCompactParentPublicationStore,
)
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from tests.test_compact_family_inputs import setup as setup_prior
from tests.test_mana_chat_lab import Clock
from tests.test_trial_action_cards import snapshot


async def setup(path: Path) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        replace(
            workspace_options(path, clock=clock, worker_enabled=False),
            tariff_handoff=True,
            compact_inputs=True,
            compact_publication=True,
        )
    )
    await lab.start()
    assert isinstance(lab.store, SqliteCompactParentPublicationStore)
    return lab, clock


def request() -> ParentTouchMessageRequest:
    return ParentTouchMessageRequest(
        parent_id=LAB_PARENT, request_id=uuid4(), message="Какой заряд у ребёнка?"
    )


def test_publication_is_typed_versioned_and_preserves_language_contract() -> None:
    scope = ParentTouchManagerScope(language="ru", stage="child_safety")
    actual = compact_child_publication(scope)
    assert "Reply in ru" in actual and "adult parent" in actual
    assert "YYYY-MM-DD" in actual and "isn't observation" in actual
    assert "question=null" in actual and "urgent first" in actual
    assert "unknown/missing isn't zero" in actual
    bound = compact_child_publication(scope.model_copy(update={"language_reference": "UZS"}))
    assert "response_language_reference" in bound and "preceding clear parent dialogue" in bound
    with pytest.raises(ValueError):
        compact_child_publication(scope.model_copy(update={"stage": "route"}))
    assert hashlib.sha256(compact_child_publication(scope, version=1).encode()).hexdigest() == (
        "4b69e9d88fec630f1624ff5516e36cd7ca031c59372592735412189cc2f329e2"
    )


async def test_full_path_keeps_all_messages_schema_floor_and_location_pairing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "full")
    original = lab.touch._model.respond
    final_prompts = []

    async def observe(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        if prompt.manager_scope and prompt.manager_scope.stage == "child_safety":
            previous = manager_prompt(
                prompt.manager_scope,
                json.loads(prompt.messages[0][1]),
                prompt.messages,
                template=prompt,
            )
            assert prompt.messages == previous.messages
            assert prompt.required_observation_dates == previous.required_observation_dates
            assert prompt.minimum_output_tokens == previous.minimum_output_tokens == 128
            assert prompt.instructions == compact_child_publication(
                prompt.manager_scope, battery_source=prompt.battery_source_publication
            )
            assert len(prompt.instructions) < len(previous.instructions)
            assert prompt.messages[-1] == ("user", "Какой заряд у ребёнка?")
            assert prompt.input_presentation == 1
            final_prompts.append(prompt)
        return await original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(lab.touch._model, "respond", observe)
    try:
        ask = request()
        await lab.touch.admit_message(ask)
        assert await lab.touch.process_reviewed_message()
        review = await lab.safety.process_one()
        assert review and review.status == "completed"
        assert await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, ask.request_id)
        assert done.phase == "completed" and done.response and "12%" in done.response.answer
        assert len(final_prompts) == 1
        state = await lab.state()
        assert state.history.quota.used_tokens == state.safety_budget.server_used_tokens == 300
        assert lab.battery.calls == 1
        with lab.store._connect() as db:
            prepared = SourceToolPreparedInput.model_validate_json(
                db.execute("SELECT prepared FROM source_tool_jobs").fetchone()[0]
            )
            assert prepared.scope.protocol == 3 and prepared.scope.location_prompt_version == 2
            assert db.execute("SELECT COUNT(*) FROM parent_publication_captures").fetchone()[0] == 1
        before = snapshot(lab.store)
        assert await lab.touch.admit_message(ask) == done
        assert snapshot(lab.store) == before
    finally:
        await lab.close()


@pytest.mark.parametrize("change", ["disabled", "capture_missing", "marker_changed"])
async def test_capture_fences_before_generation_without_another_source(
    tmp_path: Path, change: str
) -> None:
    lab, _ = await setup(tmp_path / change)
    try:
        ask = request()
        await lab.touch.admit_message(ask)
        assert isinstance(lab.store, SqliteCompactParentPublicationStore)
        if change == "disabled":
            lab.store._compact_publication_enabled = False
        else:
            with lab.store._connect() as db:
                if change == "capture_missing":
                    db.execute("DELETE FROM parent_publication_captures")
                else:
                    db.execute(
                        "UPDATE source_tool_turns SET profile="
                        "replace(profile,'\"parent_publication\":4','\"parent_publication\":5')"
                    )
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, ask.request_id)
        assert state.phase == "failed" and state.response is None
        assert (await lab.state()).history.quota.used_tokens == 0
        assert lab.battery.calls == 0
    finally:
        await lab.close()


@pytest.mark.parametrize("stage", ["route", "child_safety"])
async def test_late_disable_fences_decision_but_keeps_verified_raw_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    lab, _ = await setup(tmp_path / stage)
    original = lab.touch._model.respond

    async def disable(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        receipt = await original(prompt, max_output_tokens=max_output_tokens)
        if prompt.manager_scope and prompt.manager_scope.stage == stage:
            assert isinstance(lab.store, SqliteCompactParentPublicationStore)
            lab.store._compact_publication_enabled = False
        return receipt

    monkeypatch.setattr(lab.touch._model, "respond", disable)
    try:
        ask = request()
        await lab.touch.admit_message(ask)
        assert await lab.touch.process_reviewed_message()
        if stage == "child_safety":
            review = await lab.safety.process_one()
            assert review and review.status == "completed"
            assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, ask.request_id)
        assert state.phase == "failed" and state.response is None
        current = await lab.state()
        assert current.history.quota.used_tokens == (150 if stage == "route" else 300)
        assert current.history.quota.reserved_tokens == 0
        assert len(current.history.messages) == 1
        assert lab.battery.calls == (0 if stage == "route" else 1)
    finally:
        await lab.close()


async def test_unknown_final_publication_survives_closed_reader_restart_and_next_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "unknown")
    try:
        ask = request()
        await lab.touch.admit_message(ask)
        assert await lab.touch.process_reviewed_message()
        review = await lab.safety.process_one()
        assert review and review.status == "completed"
        entered = asyncio.Event()

        async def lost(prompt: ChatPrompt, *, max_output_tokens: int) -> Any:
            assert prompt.manager_scope and prompt.manager_scope.stage == "child_safety"
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(lab.touch._model, "respond", lost)
        task = asyncio.create_task(lab.touch.process_reviewed_message())
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        quota = (await lab.state()).history.quota
        assert quota.used_tokens == 150 and quota.reserved_tokens > 0
        assert quota.blocked_by_unresolved_request
        before = snapshot(lab.store)
        await SqliteClosedCompactParentPublicationStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
        assert snapshot(lab.store) == before
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        assert not await lab.touch.process_reviewed_message()
        later = await lab.store.quota(LAB_PARENT, clock.now() + timedelta(days=1))
        assert later.blocked_by_unresolved_request
        assert snapshot(lab.store) == before and lab.battery.calls == 0
    finally:
        await lab.close()


async def test_actual_v35_pending_turn_never_gains_new_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prior, clock = await setup_prior(tmp_path / "prior")
    ask = request()
    await prior.touch.admit_message(ask)
    before = snapshot(prior.store)
    family_path, source_path = prior.store._path, prior.source_store._path
    options = replace(prior.options, directory=tmp_path / "current", compact_publication=True)
    await prior.close()
    current = ChatLab(options)
    current._directory()
    for old, name in ((family_path, "family.sqlite3"), (source_path, "sources.sqlite3")):
        with sqlite3.connect(old) as src, sqlite3.connect(options.directory / name) as dst:
            src.backup(dst)
    await current.start()
    original = current.touch._model.respond

    async def observe(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        if prompt.manager_scope and prompt.manager_scope.stage == "child_safety":
            assert "Collection/write time is not observation time" in prompt.instructions
        return await original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(current.touch._model, "respond", observe)
    try:
        after = snapshot(current.store)
        assert {key: after[key] for key in before} == before
        assert isinstance(current.store, SqliteCompactParentPublicationStore)
        assert await current.store.parent_publication_version(LAB_PARENT, 1) is None
        assert await current.touch.process_reviewed_message()
        review = await current.safety.process_one()
        assert review and review.status == "completed"
        assert await current.touch.process_reviewed_message()
        with current.store._connect() as db:
            assert not db.execute("SELECT 1 FROM parent_publication_captures").fetchone()
    finally:
        await current.close()


@pytest.mark.parametrize("previous_protocol", [1, 2, 3])
async def test_captured_previous_turn_keeps_exact_instructions_after_new_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    previous_protocol: Literal[1, 2, 3],
) -> None:
    lab, _ = await setup(tmp_path / "captured-v1")
    assert isinstance(lab.store, SqliteCompactParentPublicationStore)
    original = lab.touch._model.respond
    versions = []

    async def observe(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        if prompt.manager_scope and prompt.manager_scope.stage == "child_safety":
            versions.append((prompt.instructions, prompt.battery_source_publication))
        return await original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(lab.touch._model, "respond", observe)
    try:
        lab.store._publication_protocol = previous_protocol
        first = request()
        await lab.touch.admit_message(first)
        lab.store._publication_protocol = 4
        assert await lab.store.parent_publication_version(LAB_PARENT, 1) == previous_protocol
        assert await lab.touch.process_reviewed_message()
        assert await lab.safety.process_one()
        assert await lab.touch.process_reviewed_message()
        scope = ParentTouchManagerScope(language="ru", stage="child_safety")
        assert versions[0][0] == compact_child_publication(
            scope, version=previous_protocol, battery_source=versions[0][1]
        )
        second = request()
        await lab.touch.admit_message(second)
        assert await lab.touch.process_reviewed_message()
        assert await lab.safety.process_one()
        assert await lab.touch.process_reviewed_message()
        assert len(versions) == 2
        assert versions[1][0] == compact_child_publication(
            scope, version=4, battery_source=versions[1][1]
        )
        with lab.store._connect() as db:
            protocols = [
                json.loads(row[0])["parent_publication"]
                for row in db.execute("SELECT profile FROM source_tool_turns ORDER BY turn_id")
            ]
            assert protocols == [previous_protocol, 4]
    finally:
        await lab.close()


async def test_native_late_disable_keeps_raw_receipt_without_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "late-native")
    store, workflow = lab.store, lab.safety._native_sources
    assert isinstance(store, SqliteCompactParentPublicationStore)
    assert isinstance(workflow, SourceToolWorkflow)
    original = workflow._model.respond_source

    async def disable(prompt: SourceToolPrompt, *, max_output_tokens: int) -> SourceModelReceipt:
        result = await original(prompt, max_output_tokens=max_output_tokens)
        store._compact_publication_enabled = False
        return result

    monkeypatch.setattr(workflow._model, "respond_source", disable)
    try:
        await lab.touch.admit_message(request())
        assert await lab.touch.process_reviewed_message()
        result = await lab.safety.process_one()
        assert result and result.status == "failed"
        assert (await lab.state()).safety_budget.server_used_tokens == 150
        assert lab.battery.calls == 0
    finally:
        await lab.close()


async def test_failed_capture_rolls_back_all_admission_rows(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "atomic")
    try:
        with lab.store._connect() as db:
            db.execute(
                "CREATE TRIGGER reject_publication BEFORE INSERT ON parent_publication_captures "
                "BEGIN SELECT RAISE(ABORT,'synthetic rejection'); END;"
            )
        before = snapshot(lab.store)
        with pytest.raises(sqlite3.IntegrityError):
            await lab.touch.admit_message(request())
        assert snapshot(lab.store) == before and lab.battery.calls == 0
    finally:
        await lab.close()
