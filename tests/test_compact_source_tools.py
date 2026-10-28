"""New v5 source frames keep all words/facts, exact pairing and old v4 behavior."""

import asyncio
import copy
import json
from contextlib import suppress
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.mana_ai.application.compact_source_tools import (
    BODY_KEYS,
    RESULT_QUALIFICATIONS,
    compact_source_final_instructions,
    compact_source_frame_hash,
    compact_source_messages,
    compact_source_result,
)
from app.mana_ai.application.source_tool_ports import SourceModelReceipt, SourceToolPrompt
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.family_day_usage import DayUsageTarget
from app.mana_ai.domain.source_tools import (
    SavedObservationCall,
    SourceToolChild,
    SourceToolContinuation,
    SourceToolScope,
    UnifiedObservationCall,
    source_call_access,
)
from app.services.child_source_model import OpenAIChildSourceModel
from app.services.compact_source_tool_store import (
    SqliteClosedCompactSourceToolStore,
    SqliteCompactSourceToolStore,
)
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import LAB_CHILD, LAB_PARENT, ChatLab
from tests.test_mana_chat_lab import Clock
from tests.test_saved_observations import seed, snapshot


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
            compact_source_tools=enabled,
        )
    )
    await lab.start()
    if enabled:
        assert isinstance(lab.store, SqliteCompactSourceToolStore)
    return lab, clock


@pytest.mark.parametrize("saved", [True, False])
async def test_unified_access_finishes_one_chat_and_preserves_original_receipt(
    tmp_path: Path, saved: bool
) -> None:
    lab, clock = await setup(tmp_path / str(saved))
    model = lab._models[1]
    assert isinstance(model, OpenAIChildSourceModel)
    calls: list[dict[str, Any]] = []
    prompts: list[SourceToolPrompt] = []
    original = model.respond_source

    async def observe(prompt: SourceToolPrompt, *, max_output_tokens: int) -> SourceModelReceipt:
        prompts.append(prompt)
        return await original(prompt, max_output_tokens=max_output_tokens)

    model.respond_source = observe  # type: ignore[method-assign]

    async def request(req: httpx.Request) -> None:
        calls.append(json.loads(req.content))

    model._client._client.event_hooks["request"].append(request)
    try:
        if saved:
            await seed(lab)
        source_before = snapshot(lab.source_store._path)
        message = "Проверь сохранённый заряд ребёнка" if saved else "Проверь заряд ребёнка"
        req = ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=message)
        await lab.touch.admit_message(req)
        await lab.touch.process_reviewed_message()
        result = await lab.safety.process_one()
        assert result and result.status == "completed", result
        await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, req.request_id)
        assert done.response and done.phase == "completed"
        assert len(prompts) == 2 and prompts[0].input == prompts[1].input
        assert prompts[0].input.minimum_output_tokens == 128
        assert (
            prompts[0].scope.protocol == 5
            and prompts[0].scope.request_projection_hash == compact_source_frame_hash()
        )
        assert prompts[1].continuation
        assert isinstance(prompts[1].continuation.call, UnifiedObservationCall)
        assert source_call_access(prompts[1].continuation.call) == (
            "saved_only" if saved else "live"
        )
        assert (
            len(calls[0]["tools"]) == 1 and calls[0]["tools"][0]["name"] == "read_child_observation"
        )
        assert calls[0]["tools"][0]["parameters"]["properties"]["access"]["enum"] == [
            "saved_only",
            "live",
        ]
        assert calls[-1]["tools"] == [] and calls[-1]["tool_choice"] == "none"
        assert prompts[-1].scope.calendar_today is not None
        assert (
            calls[-1]["instructions"]
            == compact_source_final_instructions("battery")
            + "\nquery-calendar today "
            + prompts[-1].scope.calendar_today.isoformat()
            + "."
        )
        assert calls[0]["instructions"] != calls[-1]["instructions"]
        body = json.loads(calls[0]["input"][0]["content"])
        assert body["chat"][-1]["content"] == message
        assert "reports" in body and "saved_assessments" not in body
        output = json.loads(
            next(v for v in calls[-1]["input"] if v.get("type") == "function_call_output")["output"]
        )
        assert "qualification" not in output and output["facts"]
        assert "saved_observation" not in output
        if saved:
            assert (
                output["provider_refreshed"] is False
                and output["inspection_scope"] == "saved_sql_only"
            )
            assert snapshot(lab.source_store._path) == source_before
        assert lab.battery.calls == 1
        state = await lab.state()
        assert state.history.quota.used_tokens == state.safety_budget.server_used_tokens == 300
        with lab.store._connect() as db:
            original_receipt = json.loads(
                db.execute("SELECT source_result FROM source_tool_jobs").fetchone()[0]
            )
            assert original_receipt["facts"]["child_id"] == LAB_CHILD
            assert original_receipt["snapshot_id"]
            assert (
                db.execute("SELECT frame_hash FROM compact_source_tool_turns LIMIT 1").fetchone()[0]
                == compact_source_frame_hash()
            )
        family = snapshot(lab.store._path)
        assert await lab.touch.admit_message(req) == done
        assert snapshot(lab.store._path) == family
        closed = SqliteClosedCompactSourceToolStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        assert (
            await closed.touch_history(LAB_PARENT, before=None, limit=20, now=clock.now())
        ).messages == state.history.messages
        assert snapshot(lab.store._path) == family
    finally:
        await lab.close()


def test_lossless_host_projection_keeps_every_nested_value_word_and_whitespace() -> None:
    data = {
        "profile_collected_at": "2026-10-28T09:00:00Z",
        "profile_limitations": [" exact  words\n"],
        "chat_is_bounded_history": True,
        "saved_assessments": [{"summary": " a\n b ", "title": "Keep me"}],
        "saved_assessment_total": 21,
        "saved_assessment_page_limit": 20,
        "conversation_needs": [{"reason": " every original word "}],
        "conversation_needs_scope": "authorized_children_pending_and_recent_answers",
        "children": [{"alias": "child-1", "name": " Exact Name "}],
        "chat": [{"role": "user", "content": "Точно все слова:  a\n b"}],
    }
    projected = json.loads(compact_source_messages((("user", json.dumps(data)),))[0][1])
    inverse = {v: k for k, v in BODY_KEYS.items()}
    assert {inverse.get(k, k): v for k, v in projected.items()} == data
    with pytest.raises(ValueError, match="shadow"):
        compact_source_messages((("user", json.dumps(data | {"reports": []})),))


def test_result_projection_requires_actual_duplicate_dates_and_keeps_all_source_values() -> None:
    facts = {
        "collected_at": "2026-10-28T09:00:00Z",
        "observed_at": None,
        "percent": 12,
        "status": "available",
        "quality": "unknown_measurement_time",
    }
    payload: dict[str, Any] = {
        "source": "firebase.child_battery.v1",
        "facts": facts,
        "qualification": RESULT_QUALIFICATIONS["saved"],
        "status": "completed",
        "reason": None,
        "query_calendar_day": None,
        "saved_observation": {
            "source": "firebase.child_battery.v1",
            "snapshot_collected_at": facts["collected_at"],
            "provider_checked_at": "2026-10-28T09:01:00Z",
            "inspected_at": "2026-10-28T09:02:00Z",
            "provider_refreshed": False,
            "inspection_scope": "saved_sql_only",
        },
    }
    result = compact_source_result(payload)
    assert result["facts"] == facts and result["provider_checked_at"] != result["inspected_at"]
    corrupted = copy.deepcopy(payload)
    corrupted["saved_observation"]["snapshot_collected_at"] = "2026-10-28T08:00:00Z"
    with pytest.raises(ValueError, match="duplicates"):
        compact_source_result(corrupted)


def test_native5_has_one_strict_access_choice_and_old_calls_cannot_upgrade() -> None:
    scope = SourceToolScope(
        parent_id=LAB_PARENT,
        invocation_id=uuid4(),
        children=(SourceToolChild(alias="child-1", child_id=LAB_CHILD),),
        protocol=5,
        calendar_today=Clock.value.date(),
        saved_observations_enabled=True,
        request_projection_hash=compact_source_frame_hash(),
    )
    call = UnifiedObservationCall(
        id="fc",
        call_id="call",
        arguments=json.dumps(
            {
                "child_alias": "child-1",
                "kind": "battery",
                "calendar_day": None,
                "access": "saved_only",
            }
        ),
    )
    scope.validate_call(call)
    assert source_call_access(call) == "saved_only"
    with pytest.raises(ValidationError):
        UnifiedObservationCall.model_validate(
            call.model_dump()
            | {
                "arguments": json.dumps(
                    {"child_alias": "child-1", "kind": "battery", "calendar_day": None}
                )
            }
        )
    old = scope.model_copy(update={"protocol": 4, "request_projection_hash": None})
    with pytest.raises(ValueError, match="not captured"):
        old.validate_call(call)
    legacy = SavedObservationCall(
        id="fc",
        call_id="call",
        arguments=json.dumps({"child_alias": "child-1", "kind": "battery", "calendar_day": None}),
    )
    with pytest.raises(ValidationError):
        SourceToolContinuation(version=5, input_digest="a" * 64, items=(legacy,))


@pytest.mark.parametrize("qualification", [None, "", "unqualified", "Ordinary lookalike"])
def test_unproven_qualification_is_never_discarded(qualification: str | None) -> None:
    with pytest.raises(ValueError, match="qualification"):
        compact_source_result(
            {"source": "firebase.child_battery.v1", "qualification": qualification}
        )


@pytest.mark.parametrize("stale", [False, True])
async def test_saved_unavailable_never_falls_back_to_live(tmp_path: Path, stale: bool) -> None:
    lab, clock = await setup(tmp_path / str(stale))
    try:
        if stale:
            await seed(lab)
            clock.value += timedelta(hours=6, seconds=1)
        before = snapshot(lab.source_store._path)
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Проверь сохранённый заряд ребёнка"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        review = await lab.safety.process_one()
        assert review and review.status == "completed"
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "completed" and state.response
        assert lab.battery.calls == int(stale)
        assert snapshot(lab.source_store._path) == before
        with lab.store._connect() as db:
            row = db.execute("SELECT continuation,source_result FROM source_tool_jobs").fetchone()
            assert json.loads(row[0])["version"] == 5
            assert json.loads(row[1])["status"] == "unavailable"
            assert json.loads(row[1])["facts"] is None
            assert (
                db.execute("SELECT COUNT(*) FROM saved_observation_inspections").fetchone()[0] == 1
            )
    finally:
        await lab.close()


@pytest.mark.parametrize("when", ["before_first", "after_first", "after_second", "changed_frame"])
async def test_compact_capture_fences_keep_verified_costs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    lab, _ = await setup(tmp_path / when)
    store = lab.store
    assert isinstance(store, SqliteCompactSourceToolStore)
    model = lab._models[1]
    assert isinstance(model, OpenAIChildSourceModel)
    try:
        await seed(lab)
        before = snapshot(lab.source_store._path)
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Проверь сохранённый заряд ребёнка"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        original_count, original_respond = model.count_source_input, model.respond_source
        calls = 0
        if when == "before_first":

            async def count(prompt: SourceToolPrompt) -> int:
                value = await original_count(prompt)
                store._compact_source_tools_enabled = False
                return value

            monkeypatch.setattr(model, "count_source_input", count)
        else:

            async def respond(
                prompt: SourceToolPrompt, *, max_output_tokens: int
            ) -> SourceModelReceipt:
                nonlocal calls
                value = await original_respond(prompt, max_output_tokens=max_output_tokens)
                calls += 1
                if calls == 1 and when == "changed_frame":
                    with store._transaction() as db:
                        db.execute("UPDATE compact_source_tool_turns SET frame_hash=?", ("f" * 64,))
                elif calls == (2 if when == "after_second" else 1):
                    store._compact_source_tools_enabled = False
                return value

            monkeypatch.setattr(model, "respond_source", respond)
        review = await lab.safety.process_one()
        assert review and review.status == "failed"
        state = await lab.state()
        assert (
            state.safety_budget.server_used_tokens
            == {
                "before_first": 0,
                "after_first": 150,
                "changed_frame": 150,
                "after_second": 300,
            }[when]
        )
        assert state.safety_budget.server_reserved_tokens == 0
        assert lab.battery.calls == 1 and snapshot(lab.source_store._path) == before
        assert await lab.safety.process_one() is None
    finally:
        await lab.close()


async def test_unknown_final_model_receipt_survives_closed_reader_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "unknown")
    model = lab._models[1]
    assert isinstance(model, OpenAIChildSourceModel)
    original = model.respond_source
    entered = asyncio.Event()

    async def lost(prompt: SourceToolPrompt, *, max_output_tokens: int) -> SourceModelReceipt:
        if prompt.continuation is not None:
            entered.set()
            await asyncio.Event().wait()
        return await original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(model, "respond_source", lost)
    try:
        await seed(lab)
        source_before = snapshot(lab.source_store._path)
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Проверь сохранённый заряд ребёнка"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        task = asyncio.create_task(lab.safety.process_one())
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        budget = (await lab.state()).safety_budget
        assert budget.server_used_tokens == 150 and budget.server_reserved_tokens > 0
        assert budget.parent_blocked_by_unknown
        before = snapshot(lab.store._path)
        await SqliteClosedCompactSourceToolStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
        assert snapshot(lab.store._path) == before
        options = lab.options
        await lab.close()
        lab = ChatLab(options)
        await lab.start()
        assert await lab.safety.process_one() is None
        assert snapshot(lab.store._path) == before
        later = await lab.store.safety_budget(LAB_PARENT, clock.now() + timedelta(days=1))
        assert later.parent_blocked_by_unknown and later.server_reserved_tokens > 0
        assert lab.battery.calls == 0 and snapshot(lab.source_store._path) == source_before
    finally:
        await lab.close()


async def test_old_native4_turn_keeps_original_two_tools_after_enable(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "old", enabled=True)
    store = lab.store
    assert isinstance(store, SqliteCompactSourceToolStore)
    model = lab._models[1]
    assert isinstance(model, OpenAIChildSourceModel)
    calls: list[dict[str, Any]] = []

    async def observe(req: httpx.Request) -> None:
        calls.append(json.loads(req.content))

    model._client._client.event_hooks["request"].append(observe)
    try:
        store._compact_source_tools_enabled = False
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Проверь сохранённый заряд ребёнка"
        )
        await seed(lab)
        await lab.touch.admit_message(request)
        with store._connect() as db:
            original = db.execute("SELECT profile FROM source_tool_turns").fetchone()[0]
            assert db.execute("SELECT COUNT(*) FROM compact_source_tool_turns").fetchone()[0] == 0
        store._compact_source_tools_enabled = True
        assert await lab.touch.process_reviewed_message()
        review = await lab.safety.process_one()
        assert review and review.status == "completed"
        assert await lab.touch.process_reviewed_message()
        assert [v["name"] for v in calls[0]["tools"]] == [
            "read_child_observation",
            "inspect_saved_child_observation",
        ]
        assert "qualification" in json.loads(
            next(v for v in calls[-1]["input"] if v.get("type") == "function_call_output")["output"]
        )
        with store._connect() as db:
            assert db.execute("SELECT profile FROM source_tool_turns").fetchone()[0] == original
            prepared = json.loads(db.execute("SELECT prepared FROM source_tool_jobs").fetchone()[0])
            assert prepared["scope"]["protocol"] == 4
            assert "request_projection_hash" not in prepared["scope"]
    finally:
        await lab.close()


@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize("kind", ["app_usage", "app_usage_day", "location"])
async def test_each_source_keeps_exact_values_and_selected_final_qualification(
    tmp_path: Path, saved: bool, kind: str
) -> None:
    lab, clock = await setup(tmp_path / f"{kind}-{saved}")
    model = lab._models[1]
    assert isinstance(model, OpenAIChildSourceModel)
    calls: list[dict[str, Any]] = []

    async def observe(req: httpx.Request) -> None:
        calls.append(json.loads(req.content))

    model._client._client.event_hooks["request"].append(observe)
    day = clock.now().date() - timedelta(days=1)
    try:
        if saved:
            if kind == "app_usage_day":
                assert lab.day_usage
                lab.source_store._dispatch_enabled = False
                await lab.day_usage.read_for_analysis(
                    DayUsageTarget(
                        parent_id=LAB_PARENT,
                        child_id=LAB_CHILD,
                        request_id=uuid4(),
                        requested_day=day,
                    ),
                    None,
                )
                lab.source_store._dispatch_enabled = True
            else:
                await seed(
                    lab,
                    "firebase.child_location.v1"
                    if kind == "location"
                    else "manakids.child_app_usage.v1",
                )
        source_before = snapshot(lab.source_store._path)
        label = (
            "местоположение ребёнка"
            if kind == "location"
            else f"приложения ребёнка за {day.isoformat()}"
            if kind == "app_usage_day"
            else "приложения ребёнка"
        )
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message=("Проверь сохранённые " if saved else "Проверь ") + label,
        )
        # The simulated provider accepts "приложения" as a dated request. This
        # case selects the exact advertised kind without introducing a parser
        # into production; all other source dispatch and SDK checks stay real.
        provider = model._client._client._transport
        assert isinstance(provider, httpx.MockTransport)
        original_handler = provider.handler

        async def reply(req: httpx.Request) -> httpx.Response:
            response = original_handler(req)
            if not isinstance(response, httpx.Response):
                response = await response
            data = json.loads(response.content)
            if kind == "app_usage" and data.get("output", [{}])[0].get("type") == "function_call":
                args = json.loads(data["output"][0]["arguments"])
                args["kind"], args["calendar_day"] = "app_usage", None
                data["output"][0]["arguments"] = json.dumps(args)
                return httpx.Response(200, json=data)
            return response

        provider.handler = reply
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        result = await lab.safety.process_one()
        assert result and result.status == "completed", result
        assert await lab.touch.process_reviewed_message()
        assert calls[-1]["instructions"].startswith(compact_source_final_instructions(kind))
        final = json.loads(
            next(v for v in calls[-1]["input"] if v.get("type") == "function_call_output")["output"]
        )
        with lab.store._connect() as db:
            original = json.loads(
                db.execute("SELECT source_result FROM source_tool_jobs").fetchone()[0]
            )
        facts = original["facts"]
        facts.pop("child_id")
        facts.pop("position_fingerprint", None)
        assert final["facts"] == facts
        assert "qualification" not in final
        if kind == "app_usage_day":
            assert final["query_calendar_day"] == day.isoformat()
        if saved:
            assert snapshot(lab.source_store._path) == source_before
            assert final["provider_refreshed"] is False
    finally:
        await lab.close()
