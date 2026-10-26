"""Captured native GPS -> minimized tool result -> same-chat response, all fake providers."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.source_tools import DatedObservationCall, SourceToolChild, SourceToolScope
from app.services.child_source_model import OpenAIChildSourceModel
from app.services.location_safety_store import (
    SqliteClosedLocationSafetyStore,
    SqliteLocationSafetyStore,
)
from app.services.mana_chat_lab import LAB_PARENT, ChatLab, LabOptions
from tests.test_dated_source_workflow import options
from tests.test_mana_chat_lab import Clock


async def start(path: Path) -> ChatLab:
    lab = ChatLab(replace(options(path, Clock()), manager=True, location=True))
    await lab.start()
    return lab


async def test_location_lab_factory_has_a_running_clock_and_no_unrelated_expiry_or_io(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from app.services import mana_chat_lab as runtime
    from scripts import mana_chat_lab as script

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("The fictional GPS lab cannot initialize live credentials/models")

    create_app = script.create_app

    def isolated(*, options: LabOptions | None = None) -> FastAPI:
        assert options
        return create_app(options=replace(options, directory=tmp_path / "lab"))

    monkeypatch.setattr(runtime, "get_settings", forbidden)
    monkeypatch.setattr(script, "create_app", isolated)
    app = script.create_location_app()
    async with app.router.lifespan_context(app):
        lab = app.state.chat_lab
        first = lab.options.clock.now()
        await asyncio.sleep(0.01)
        assert lab.options.clock.now() > first
        context = await lab._profiles.read(LAB_PARENT)
        assert context.tariff and context.tariff.valid_until
        assert (context.tariff.valid_until - first).days >= 29
        assert lab.bootstrap().mode == "simulation"
        assert any(s.key == "source-location" for s in lab.bootstrap().scenarios)
        assert not (await lab.state()).history.messages
        assert lab.location.calls == lab.battery.calls == 0


async def test_native_location_is_dated_minimized_owned_and_exactly_replayed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "location"
    lab = await start(path)
    calls: list[dict[str, Any]] = []

    async def observe(req: httpx.Request) -> None:
        calls.append(json.loads(req.content))

    model = lab._models[1]
    assert isinstance(model, OpenAIChildSourceModel)
    model._client._client.event_hooks["request"].append(observe)
    request = ParentTouchMessageRequest(
        parent_id=LAB_PARENT, request_id=uuid4(), message="Где сейчас ребёнок?"
    )
    try:
        assert isinstance(lab.store, SqliteLocationSafetyStore)
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()  # Parent-Touch chooses Child-Safety.
        review = await lab.safety.process_one()
        assert review and review.status == "completed", review
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "completed" and state.response
        assert "2026-10-14" in state.response.answer
        assert "Текущее местоположение неизвестно" in state.response.answer
        assert lab.location.calls == 1 and lab.battery.calls == lab.app_usage.calls == 0
        assert len(calls) == 4
        assert "location" in calls[0]["tools"][0]["parameters"]["properties"]["kind"]["enum"]
        assert calls[-1]["tools"] == [] and calls[-1]["tool_choice"] == "none"
        result = next(i for i in calls[-1]["input"] if i.get("type") == "function_call_output")
        facts = json.loads(result["output"])["facts"]
        assert "child_id" not in facts and "position_fingerprint" not in facts
        assert "latitude" not in json.dumps(calls) and "longitude" not in json.dumps(calls)
        assert "2026-10-14" in facts["observed_at"] and facts["mock"] is False
        saved = await lab.state()
        assert len(saved.history.messages) == 2
        assert saved.history.quota.used_tokens == saved.safety_budget.server_used_tokens == 300
        assert (
            saved.history.quota.reserved_tokens == saved.safety_budget.server_reserved_tokens == 0
        )
        with lab.store._connect() as db:
            assert (
                json.loads(db.execute("SELECT prepared FROM source_tool_jobs").fetchone()[0])[
                    "scope"
                ]["location_enabled"]
                is True
            )
            assert (
                json.loads(db.execute("SELECT prepared FROM source_tool_jobs").fetchone()[0])[
                    "scope"
                ]["location_prompt_version"]
                == 2
            )
            before = list(db.iterdump())
        await lab.close()
        lab = await start(path)
        assert await lab.touch.admit_message(request) == state
        assert await lab.safety.process_one() is None
        assert lab.location.calls == 0
        with lab.store._connect() as db:
            assert list(db.iterdump()) == before
        closed = SqliteClosedLocationSafetyStore(
            path / "family.sqlite3", history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        assert (
            await closed.touch_history(
                LAB_PARENT, before=None, limit=10, now=lab.options.clock.now()
            )
        ).messages == saved.history.messages
    finally:
        await lab.close()


async def test_disabled_capture_does_not_gain_gps_tools_when_rearmed(tmp_path: Path) -> None:
    lab = await start(tmp_path / "old-scope")
    assert isinstance(lab.store, SqliteLocationSafetyStore)
    lab.store._location_enabled = False
    try:
        await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT, request_id=uuid4(), message="Где сейчас ребёнок?"
            )
        )
        lab.store._location_enabled = True
        assert await lab.touch.process_reviewed_message()
        review = await lab.safety.process_one()
        assert review and review.status == "completed", review
        assert lab.location.calls == 0
        with lab.store._connect() as db:
            assert (
                "location_enabled"
                not in json.loads(
                    db.execute("SELECT prepared FROM source_tool_jobs").fetchone()[0]
                )["scope"]
            )
    finally:
        await lab.close()


async def test_original_location_profile_keeps_its_exact_prompt_without_upgrade(
    tmp_path: Path,
) -> None:
    lab = await start(tmp_path / "original-location-profile")
    assert isinstance(lab.store, SqliteLocationSafetyStore)
    model = lab._models[1]
    assert isinstance(model, OpenAIChildSourceModel)
    calls: list[dict[str, Any]] = []

    async def observe(request: httpx.Request) -> None:
        calls.append(json.loads(request.content))

    model._client._client.event_hooks["request"].append(observe)
    message = "Где сейчас ребёнок? Сохрани все мои слова: сначала проверь дату записи."
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message=message
        )
        await lab.touch.admit_message(request)
        # This fixture represents the actual original, unversioned v23 capture.
        with lab.store._transaction() as db:
            db.execute("UPDATE source_tool_turns SET profile=?", (lab.store._native_policy,))
        assert await lab.touch.process_reviewed_message()
        result = await lab.safety.process_one()
        assert result and result.status == "completed", result
        assert len(calls) == 4
        assert "The captured location kind is available" in calls[0]["instructions"]
        assert message in json.dumps(calls[0], ensure_ascii=False)
        with lab.store._connect() as db:
            prepared = json.loads(db.execute("SELECT prepared FROM source_tool_jobs").fetchone()[0])
        assert prepared["scope"]["location_enabled"] is True
        assert "location_prompt_version" not in prepared["scope"]
        assert prepared["minimum_output_tokens"] == 32
    finally:
        await lab.close()


async def test_disable_after_submitted_model_keeps_cost_and_prevents_source_dispatch(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    lab = await start(tmp_path / "stopped")
    assert isinstance(lab.store, SqliteLocationSafetyStore)
    store = lab.store
    model = lab._models[1]
    assert isinstance(model, OpenAIChildSourceModel)
    original = model.respond_source

    async def stop(*args: Any, **kwargs: Any) -> Any:
        receipt = await original(*args, **kwargs)
        store._location_enabled = False
        return receipt

    monkeypatch.setattr(model, "respond_source", stop)
    try:
        await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT, request_id=uuid4(), message="Где сейчас ребёнок?"
            )
        )
        assert await lab.touch.process_reviewed_message()
        result = await lab.safety.process_one()
        assert result and result.status == "failed", result
        assert lab.location.calls == 0
        assert (await lab.state()).safety_budget.server_used_tokens == 150
    finally:
        await lab.close()


def test_old_scope_rejects_a_location_call_and_new_scope_requires_null_calendar_day() -> None:
    scope = SourceToolScope(
        parent_id="4",
        invocation_id=uuid4(),
        children=(SourceToolChild(alias="child-1", child_id=900002),),
        protocol=3,
        calendar_today=Clock.value.date(),
    )
    call = DatedObservationCall(
        id="fc",
        call_id="call",
        arguments=json.dumps({"child_alias": "child-1", "kind": "location", "calendar_day": None}),
    )
    with pytest.raises(ValueError, match="Location was not captured"):
        scope.validate_call(call)
    with pytest.raises(ValidationError):
        DatedObservationCall(
            id="fc",
            call_id="call",
            arguments=json.dumps(
                {"child_alias": "child-1", "kind": "location", "calendar_day": "2026-10-23"}
            ),
        )
