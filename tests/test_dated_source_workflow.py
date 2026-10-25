"""Captured v3 tools, real SDK and same-chat delivery; all providers are fictional."""

import json
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.mana_ai.application.chat_ports import ChatPrompt
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.family_day_usage import FamilyDayUsagePage, ParentUsageLookup
from app.mana_ai.domain.source_tools import (
    DatedObservationCall,
    ObservationSourceCall,
    SourceToolContinuation,
)
from app.services.child_source_model import OpenAIChildSourceModel
from app.services.dated_source_safety_store import (
    SqliteClosedDatedSourceSafetyStore,
    SqliteDatedSourceSafetyStore,
)
from app.services.mana_chat_lab import LAB_PARENT, ChatLab, LabOptions
from app.services.retention_expiry_store import SqliteRetentionExpiryStore
from tests.test_child_source_model import Provider, call, model, prompt
from tests.test_mana_chat_lab import Clock


def options(path: Path, clock: Clock) -> LabOptions:
    return LabOptions(
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
        day_usage=True,
    )


@pytest.mark.parametrize(
    "language,message",
    [
        ("ru", "Какие приложения использовал ребёнок за 2026-10-23?"),
        ("uz-Latn", "Farzandim 2026-10-23 kuni qaysi ilovalardan foydalangan?"),
    ],
)
async def test_same_chat_loop_has_original_day_qualifications_and_restart_replay(
    tmp_path: Path, language: str, message: str, monkeypatch: MonkeyPatch
) -> None:
    clock = Clock()
    lab = ChatLab(options(tmp_path / language, clock))
    await lab.start()
    native_http: list[dict[str, Any]] = []

    async def observe(request: httpx.Request) -> None:
        native_http.append(json.loads(request.content))

    native_model = lab._models[1]
    assert isinstance(native_model, OpenAIChildSourceModel)
    native_model._client._client.event_hooks["request"].append(observe)
    speaker_prompts: list[ChatPrompt] = []

    async def capture(prompt: ChatPrompt) -> int:
        speaker_prompts.append(prompt)
        return 100

    monkeypatch.setattr(lab._models[0], "count_input", capture)
    req = ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=message)
    try:
        assert isinstance(lab.store, SqliteDatedSourceSafetyStore)
        await lab.touch.admit_message(req)
        reviewed = await lab.safety.process_one()
        assert reviewed and reviewed.status == "completed", reviewed
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, req.request_id)
        assert state.phase == "completed" and state.response
        assert "2026-10-23" in state.response.answer
        assert len(speaker_prompts) == 1
        assert speaker_prompts[0].reminder_scope is not None
        assert speaker_prompts[0].upsell_scope is not None
        assert any(role == "user" and text == message for role, text in speaker_prompts[0].messages)
        assert ("noma’lum" if language == "uz-Latn" else "неизвестны") in state.response.answer
        assert lab.day_provider.calls == 1 and lab.battery.calls == lab.app_usage.calls == 0
        assert len(native_http) == 4
        assert native_http[0]["tools"] and native_http[1]["tools"]
        schema = native_http[0]["tools"][0]["parameters"]
        assert set(schema["required"]) == set(schema["properties"])
        assert schema["properties"]["calendar_day"]["type"] == ["string", "null"]
        assert native_http[2]["tools"] == native_http[3]["tools"] == []
        assert native_http[2]["tool_choice"] == native_http[3]["tool_choice"] == "none"
        assert any(i.get("type") == "function_call_output" for i in native_http[3]["input"])
        before = await lab.state()
        assert before.safety_budget.server_used_tokens == 300
        assert before.safety_budget.server_reserved_tokens == 0
        assert before.history.quota.used_tokens == 150
        assert len(before.history.messages) == 2
        with lab.store._connect() as db:
            native = db.execute("SELECT * FROM source_tool_jobs").fetchone()
            result = json.loads(native["source_result"])
            assert result["requested_day"] == "2026-10-23"
            assert json.loads(native["continuation"])["version"] == 3
            assert json.loads(native["prepared"])["scope"]["calendar_today"] == "2026-10-24"
            saved = list(db.iterdump())
        await lab.close()
        lab = ChatLab(options(tmp_path / language, clock))
        await lab.start()
        assert await lab.touch.admit_message(req) == state
        assert await lab.safety.process_one() is None
        assert not await lab.touch.process_reviewed_message()
        assert lab.day_provider.calls == 0
        with lab.store._connect() as db:
            assert list(db.iterdump()) == saved
    finally:
        await lab.close()


async def test_unknown_day_read_stops_before_second_model_call_and_keeps_hold(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    lab = ChatLab(options(tmp_path / "lost", Clock()))
    await lab.start()

    async def lost(*args: object) -> object:
        raise TimeoutError("fictional lost day response")

    monkeypatch.setattr(lab.day_provider, "read_verified", lost)
    try:
        await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT,
                request_id=uuid4(),
                message="Какие приложения использовал ребёнок за 2026-10-23?",
            )
        )
        result = await lab.safety.process_one()
        assert result and result.status == "failed"
        state = await lab.state()
        assert state.safety_budget.server_used_tokens == 150
        with lab.source_store._connection() as db:
            assert db.execute("SELECT status FROM day_usage_ownership").fetchone()[0] == "unknown"
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM source_tool_receipts").fetchone()[0] == 1
        assert len(state.history.messages) == 1
    finally:
        await lab.close()


async def test_stopping_day_tools_blocks_captured_v3_before_inference(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    lab = ChatLab(options(tmp_path / "stopped", Clock()))
    await lab.start()
    try:
        await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT,
                request_id=uuid4(),
                message="Какие приложения использовал ребёнок за вчера?",
            )
        )
        monkeypatch.setattr(lab.store, "_day_tools_enabled", False)
        result = await lab.safety.process_one()
        assert result and result.status == "failed"
        assert (await lab.state()).safety_budget.server_used_tokens == 0
        assert lab.day_provider.calls == 0
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM source_tool_receipts").fetchone()
        assert (
            not await lab.touch.process_reviewed_message()
        )  # Close the failed review, no inference.
        await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT, request_id=uuid4(), message="Какой заряд батареи?"
            )
        )
        with lab.store._connect() as db:
            profiles = [
                json.loads(r[0])["source_contract"]
                for r in db.execute("SELECT profile FROM source_tool_turns ORDER BY turn_id")
            ]
            assert profiles == [3, 2]
        monkeypatch.setattr(lab.store, "_day_tools_enabled", True)
        ordinary = await lab.safety.process_one()
        assert ordinary and ordinary.status == "completed"
        assert lab.day_provider.calls == 0 and lab.battery.calls == 1
    finally:
        await lab.close()


async def test_absent_child_receipt_continues_to_a_qualified_chat_answer(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    lab = ChatLab(options(tmp_path / "absent", Clock()))
    await lab.start()
    original = lab.day_provider.read_verified

    async def absent(lookup: ParentUsageLookup, day: date) -> FamilyDayUsagePage:
        page = await original(lookup, day)
        return FamilyDayUsagePage.model_validate(
            page.model_dump()
            | {"children": (), "provider_children_count": 0, "complete_family": False}
        )

    monkeypatch.setattr(lab.day_provider, "read_verified", absent)
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Какие приложения использовал ребёнок за 2026-10-23?",
        )
        await lab.touch.admit_message(request)
        result = await lab.safety.process_one()
        assert result and result.status == "completed", result
        assert await lab.touch.process_reviewed_message()
        answer = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert answer.response and "использование неизвестно" in answer.response.answer
        assert "2026-10-23" in answer.response.answer
    finally:
        await lab.close()


@pytest.mark.parametrize("day", ["2026-10-24", "2026-09-22", "2026-02-30"])
async def test_invalid_model_date_keeps_verified_usage_without_a_read(day: str) -> None:
    provider = Provider()
    item = call() | {
        "name": "read_child_observation",
        "arguments": json.dumps(
            {"child_alias": "child-1", "kind": "app_usage_day", "calendar_day": day}
        ),
    }
    provider.body["output"] = [item]
    adapter = model(provider)
    value = prompt()
    value = replace(
        value,
        scope=value.scope.model_copy(update={"protocol": 3, "calendar_today": date(2026, 10, 24)}),
    )
    try:
        receipt = await adapter.respond_source(value, max_output_tokens=512)
        assert not receipt.completed and receipt.continuation is None
        assert receipt.usage.total == 150
    finally:
        await adapter.close()


def test_old_protocols_cannot_acquire_dated_arguments_or_call() -> None:
    args = json.dumps(
        {"child_alias": "child-1", "kind": "app_usage_day", "calendar_day": "2026-10-23"}
    )
    with pytest.raises(ValidationError):
        ObservationSourceCall(id="fc_x", call_id="call_x", arguments=args)
    dated = DatedObservationCall(id="fc_x", call_id="call_x", arguments=args)
    with pytest.raises(ValidationError):
        SourceToolContinuation(version=2, input_digest="a" * 64, items=(dated,))
    assert "calendar_today" not in prompt().scope.model_dump()


async def test_closed_v18_retains_history_unknown_holds_and_older_reader_refuses(
    tmp_path: Path,
) -> None:
    path = tmp_path / "compat"
    lab = ChatLab(options(path, Clock()))
    await lab.start()
    try:
        with lab.store._connect() as db:
            expected = list(db.iterdump())
        closed = SqliteClosedDatedSourceSafetyStore(
            path / "family.sqlite3", daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        with sqlite3.connect(path / "family.sqlite3") as db:
            assert list(db.iterdump()) == expected
        # An actual v17 class must not silently downgrade the new private protocol.
        old = SqliteRetentionExpiryStore.__new__(SqliteRetentionExpiryStore)
        old.__dict__.update(lab.store.__dict__)
        with pytest.raises((ValueError, RuntimeError)):
            await old.initialize()
        with lab.store._connect() as db:
            assert list(db.iterdump()) == expected
    finally:
        await lab.close()
