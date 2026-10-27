"""Lossless schema/host formatting under the existing family/source budgets."""

import asyncio
import copy
import json
import sqlite3
from contextlib import suppress
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.input_presentation import (
    compact_native_host_messages,
    without_schema_titles,
)
from app.mana_ai.application.source_tool_ports import SourceModelReceipt, SourceToolPrompt
from app.mana_ai.application.source_tool_workflow import SourceToolWorkflow
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.parent_touch_manager import ParentTouchManagerScope
from app.mana_ai.domain.source_tools import SourceToolPreparedInput
from app.services import mana_chat_lab as lab_module
from app.services.compact_family_input_store import (
    SqliteClosedCompactFamilyInputStore,
    SqliteCompactFamilyInputStore,
)
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.parent_chat_model import OpenAIParentChatModel
from app.services.tariff_handoff_store import SqliteTariffHandoffStore
from tests.test_child_source_model import Provider, message, model, prompt, receipt
from tests.test_mana_chat_lab import Clock
from tests.test_parent_chat_adapters import settings as model_settings
from tests.test_trial_action_cards import snapshot


def test_schema_annotations_do_not_remove_literal_title_fields_or_change_constraints() -> None:
    schema: dict[str, Any] = {
        "title": "Root annotation",
        "type": "object",
        "properties": {
            "title": {
                "title": "Property annotation",
                "type": "string",
                "minLength": 1,
                "description": "Keep the exact human task",
                "default": {"title": "literal"},
            },
            "payload": {"const": {"title": "literal constant"}, "examples": [{"title": "example"}]},
        },
        "$defs": {"title": {"type": "object", "title": "Definition annotation"}},
        "required": ["title", "payload"],
        "additionalProperties": False,
        "anyOf": [{"title": "Variant annotation", "$ref": "#/$defs/title"}],
    }
    original = copy.deepcopy(schema)
    actual = without_schema_titles(schema)
    assert "title" not in actual
    assert actual["required"] == ["title", "payload"]
    assert actual["additionalProperties"] is False
    assert actual["properties"]["title"] == {
        "type": "string",
        "minLength": 1,
        "description": "Keep the exact human task",
        "default": {"title": "literal"},
    }
    assert actual["properties"]["payload"] == schema["properties"]["payload"]
    assert actual["anyOf"] == [{"$ref": "#/$defs/title"}]
    assert "title" in actual["$defs"] and schema == original


def test_host_json_retains_every_string_whitespace_date_alias_and_unknown() -> None:
    payload: dict[str, Any] = {
        "chat": [{"content": "  Keep\n EVERY word. Ўзбекча va o‘zbekcha  ", "role": "user"}],
        "children": [
            {"alias": "child-" + str(i), "name": "Ребёнок " + str(i)} for i in range(1, 7)
        ],
        "facts": {"observed_at": None, "quality": "unknown_measurement_time", "percent": 12},
        "saved_assessments": [],
    }
    raw = json.dumps(payload, ensure_ascii=False)
    actual = compact_native_host_messages((("user", raw),))
    assert json.loads(actual[0][1]) == payload and len(actual[0][1]) < len(raw)
    assert json.loads(actual[0][1])["chat"][0]["content"] == payload["chat"][0]["content"]
    with pytest.raises(ParentChatError):
        compact_native_host_messages((("user", raw), ("user", "a literal user message")))


async def test_sdk_preserves_pairing_and_usage_with_final_only_tools_for_new_capture() -> None:
    provider = Provider()
    sdk = model(provider)
    try:
        original = prompt()
        new = replace(original, scope=original.scope.model_copy(update={"input_presentation": 1}))
        first = await sdk.respond_source(new, max_output_tokens=256)
        assert first.continuation
        continued = replace(new, continuation=first.continuation, source_result=receipt(new))
        provider.body["output"] = [
            message(
                '{"analysis":null,"followup_summary":"Unknown measurement time.","question":null}'
            )
        ]
        assert await sdk.count_source_input(continued) == 100
        final = await sdk.respond_source(continued, max_output_tokens=256)
        assert final.completed and final.usage.total == 150
        assert provider.requests[0]["tools"]
        assert provider.requests[1]["tools"] == provider.requests[2]["tools"] == []
        assert provider.requests[1]["tool_choice"] == "none"
        assert provider.requests[0]["text"] == provider.requests[1]["text"]
        assert sdk._source_input(continued)[-1].get("call_id") == first.continuation.call.call_id
        assert sdk._source_input(continued)[0] == sdk._source_input(original)[0]
        before = len(provider.requests)
        with pytest.raises(ValueError, match="input changed"):
            await sdk.count_source_input(replace(continued, scope=original.scope))
        assert len(provider.requests) == before
        old = await sdk.respond_source(original, max_output_tokens=256)
        assert old.completed
    finally:
        await sdk.close()


async def test_parent_projection_keeps_raw_messages_and_original_typed_tool_contract() -> None:
    sdk = OpenAIParentChatModel(model_settings())
    try:
        old = ChatPrompt(
            "Original instructions",
            (("user", "  exact\n words  "),),
            structured_reply=True,
            manager_scope=ParentTouchManagerScope(
                language="ru", upsell_enabled=True, tariff_handoff_enabled=True
            ),
        )
        new = replace(old, input_presentation=1)
        assert sdk._input(old) == sdk._input(new)
        old_format = sdk._text(old)["format"]
        new_format = sdk._text(new)["format"]
        assert old_format["type"] == "json_schema"
        assert new_format["type"] == "json_schema"
        assert new_format["schema"] == without_schema_titles(old_format["schema"])
        old_tools = sdk._manager_tools(old)
        expected = copy.deepcopy(old_tools)
        for tool in expected["tools"]:
            tool["parameters"] = without_schema_titles(tool["parameters"])
        assert sdk._manager_tools(new) == expected and sdk._manager_tools(old) == old_tools
    finally:
        await sdk.close()


async def setup(path: Path) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    options = replace(
        workspace_options(path, clock=clock, worker_enabled=False),
        tariff_handoff=True,
        compact_inputs=True,
        day_usage=False,
        dated_reviews=False,
        location=False,
        usage_comparisons=False,
    )
    lab = ChatLab(options)
    await lab.start()
    assert isinstance(lab.store, SqliteCompactFamilyInputStore)
    return lab, clock


async def ask(lab: ChatLab) -> ParentTouchMessageRequest:
    request = ParentTouchMessageRequest(
        parent_id=LAB_PARENT, request_id=uuid4(), message="Какой заряд у ребёнка?"
    )
    await lab.touch.admit_message(request)
    assert await lab.touch.process_reviewed_message()
    return request


async def test_full_native_path_records_new_presentation_with_no_extra_source_or_budget(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "full")
    try:
        request = await ask(lab)
        review = await lab.safety.process_one()
        assert review and review.status == "completed"
        assert await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert done.response and "12%" in done.response.answer
        assert (await lab.state()).history.quota.used_tokens == 300
        assert (await lab.state()).safety_budget.server_used_tokens == 300
        assert lab.battery.calls == 1
        with lab.store._connect() as db:
            saved = SourceToolPreparedInput.model_validate_json(
                db.execute("SELECT prepared FROM source_tool_jobs").fetchone()[0]
            )
            assert saved.scope.input_presentation == 1 and saved.scope.protocol == 2
            assert saved.messages[0][1] == json.dumps(
                json.loads(saved.messages[0][1]), ensure_ascii=False, separators=(",", ":")
            )
            assert db.execute("SELECT COUNT(*) FROM family_input_presentations").fetchone()[0] == 1
        before = snapshot(lab.store)
        assert await lab.touch.admit_message(request) == done
        assert snapshot(lab.store) == before and lab.battery.calls == 1
    finally:
        await lab.close()


@pytest.mark.parametrize("change", ["disabled", "missing_capture", "changed_profile"])
async def test_changed_capture_stops_before_source_and_retains_manager_cost(
    tmp_path: Path, change: str
) -> None:
    lab, _ = await setup(tmp_path / change)
    try:
        request = await ask(lab)
        assert isinstance(lab.store, SqliteCompactFamilyInputStore)
        if change == "disabled":
            lab.store._compact_inputs_enabled = False
        else:
            with lab.store._transaction() as db:
                if change == "missing_capture":
                    db.execute("DELETE FROM family_input_presentations")
                else:
                    db.execute(
                        "UPDATE source_tool_turns SET "
                        "profile=replace(profile,'\"input_presentation\":1,','')"
                    )
        review = await lab.safety.process_one()
        assert review and review.status == "failed" and lab.battery.calls == 0
        assert (await lab.state()).history.quota.used_tokens == 150
        assert (await lab.state()).safety_budget.server_used_tokens == 0
        assert (await lab.touch.message_state(LAB_PARENT, request.request_id)).response is None
    finally:
        await lab.close()


async def test_prior_v34_admission_never_acquires_presentation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = SqliteCompactFamilyInputStore

    class Prior(SqliteTariffHandoffStore):
        def __init__(self, path: Path, *, compact_inputs_enabled: bool, **family: Any) -> None:
            super().__init__(path, **family)

        async def input_presentation(self, parent_id: str, turn_id: int) -> None:
            return None

    clock = Clock()
    clock.value = Clock.value
    options = replace(
        workspace_options(tmp_path / "upgrade", clock=clock, worker_enabled=False),
        tariff_handoff=True,
        compact_inputs=True,
    )
    with monkeypatch.context() as prior:
        prior.setattr(lab_module, "SqliteCompactFamilyInputStore", Prior)
        lab = ChatLab(options)
        await lab.start()
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Какой заряд?"
        )
        await lab.touch.admit_message(request)
        with lab.store._connect() as db:
            old = db.execute("SELECT profile FROM source_tool_turns").fetchone()[0]
        await lab.close()
    lab = ChatLab(options)
    await lab.start()
    try:
        assert isinstance(lab.store, original)
        with lab.store._connect() as db:
            assert db.execute("SELECT profile FROM source_tool_turns").fetchone()[0] == old
            assert not db.execute("SELECT 1 FROM family_input_presentations").fetchone()
        assert await lab.touch.process_reviewed_message()
        review = await lab.safety.process_one()
        assert review and review.status == "completed"
        with lab.store._connect() as db:
            saved = SourceToolPreparedInput.model_validate_json(
                db.execute("SELECT prepared FROM source_tool_jobs").fetchone()[0]
            )
            assert saved.scope.input_presentation is None
    finally:
        await lab.close()


async def test_unknown_parent_submission_survives_closed_restart_and_midnight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "unknown")
    entered = asyncio.Event()

    async def lost(prompt: ChatPrompt, *, max_output_tokens: int) -> Any:
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(lab.touch._model, "respond", lost)
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Здравствуйте"
        )
        await lab.touch.admit_message(request)
        task = asyncio.create_task(lab.touch.process_reviewed_message())
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        assert (await lab.state()).history.quota.blocked_by_unresolved_request
        before = snapshot(lab.store)
        await SqliteClosedCompactFamilyInputStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
        assert snapshot(lab.store) == before
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        assert snapshot(lab.store) == before
        assert not await lab.touch.process_reviewed_message()
        assert (
            await lab.store.quota(LAB_PARENT, clock.now() + timedelta(days=1))
        ).blocked_by_unresolved_request
        assert snapshot(lab.store) == before
    finally:
        await lab.close()


@pytest.mark.parametrize("kind", ["child", "tariff"])
async def test_late_parent_disable_discards_decision_after_accounting_verified_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    lab, _ = await setup(tmp_path / kind)
    store = lab.store
    assert isinstance(store, SqliteCompactFamilyInputStore)
    original = lab.touch._model.respond

    async def late(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        result = await original(prompt, max_output_tokens=max_output_tokens)
        store._compact_inputs_enabled = False
        return result

    monkeypatch.setattr(lab.touch._model, "respond", late)
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Какой заряд?" if kind == "child" else "Тариф на 90 дней UZS",
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed" and state.response is None
        assert (await lab.state()).history.quota.used_tokens == 150
        assert lab.battery.calls == lab.catalog.calls == 0
        assert await lab.safety.process_one() is None
    finally:
        await lab.close()


async def test_native_late_disable_charges_usage_before_refusing_source_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "native-disable")
    store, workflow = lab.store, lab.safety._native_sources
    assert isinstance(store, SqliteCompactFamilyInputStore)
    assert isinstance(workflow, SourceToolWorkflow)
    original = workflow._model.respond_source

    async def late(prompt: SourceToolPrompt, *, max_output_tokens: int) -> SourceModelReceipt:
        result = await original(prompt, max_output_tokens=max_output_tokens)
        store._compact_inputs_enabled = False
        return result

    monkeypatch.setattr(workflow._model, "respond_source", late)
    try:
        await ask(lab)
        result = await lab.safety.process_one()
        assert result and result.status == "failed"
        assert (await lab.state()).safety_budget.server_used_tokens == 150
        assert lab.battery.calls == 0
        with store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM source_tool_receipts").fetchone()[0] == 1
    finally:
        await lab.close()


async def test_unknown_native_continuation_keeps_pairing_and_costs_after_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "native-unknown")
    workflow = lab.safety._native_sources
    assert isinstance(workflow, SourceToolWorkflow)
    original = workflow._model.respond_source
    entered = asyncio.Event()

    async def lost(prompt: SourceToolPrompt, *, max_output_tokens: int) -> SourceModelReceipt:
        if prompt.continuation is not None:
            entered.set()
            await asyncio.Event().wait()
        return await original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(workflow._model, "respond_source", lost)
    try:
        await ask(lab)
        task = asyncio.create_task(lab.safety.process_one())
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        budget = (await lab.state()).safety_budget
        assert budget.parent_blocked_by_unknown and budget.server_reserved_tokens > 0
        assert budget.server_used_tokens == 150 and lab.battery.calls == 1
        before = snapshot(lab.store)
        await SqliteClosedCompactFamilyInputStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
        assert snapshot(lab.store) == before
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        assert snapshot(lab.store) == before
        assert await lab.safety.process_one() is None
        assert lab.battery.calls == 0
        next_day = await lab.store.safety_budget(LAB_PARENT, clock.now() + timedelta(days=1))
        assert next_day.parent_blocked_by_unknown
        assert snapshot(lab.store) == before
    finally:
        await lab.close()


async def test_admission_capture_failure_rolls_back_the_profile_marker_and_turn(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "capture-atomic")
    try:
        with lab.store._transaction() as db:
            db.execute(
                "CREATE TRIGGER refuse_capture BEFORE INSERT ON family_input_presentations "
                "BEGIN SELECT RAISE(ABORT,'Synthetic capture refusal'); END"
            )
        before = snapshot(lab.store)
        with pytest.raises(sqlite3.IntegrityError):
            await lab.touch.admit_message(
                ParentTouchMessageRequest(
                    parent_id=LAB_PARENT, request_id=uuid4(), message="Какой заряд?"
                )
            )
        assert snapshot(lab.store) == before
        assert lab.battery.calls == 0
    finally:
        await lab.close()


@pytest.mark.parametrize(
    "compact_publication,compact_manager", [(False, False), (True, False), (True, True)]
)
async def test_actual_runtime_and_closed_configuration_keep_new_schema_without_idle_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    compact_publication: bool,
    compact_manager: bool,
) -> None:
    import httpx

    from app.core.config import Settings
    from app.mana_ai.domain.child_safety import ChildSafetyLimits
    from app.services import parent_chat_runtime as runtime
    from tests.test_family_source_runtime import config, make_credential_file

    attempted: list[str] = []

    def denied(request: httpx.Request) -> httpx.Response:
        attempted.append(request.url.host)
        raise AssertionError("No idle source/model call belongs to configuration acceptance")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_: httpx.MockTransport(denied))
    active = config(
        tmp_path,
        make_credential_file(tmp_path),
        mana_parent_touch_review_first_enabled=True,
        mana_child_safety_enabled=True,
        mana_child_safety_source_tools_enabled=True,
        mana_family_source_safety_enabled=True,
        mana_family_app_usage_enabled=True,
        mana_family_source_reviews_enabled=True,
        mana_parent_reminders_enabled=True,
        mana_client_retention_enabled=True,
        mana_client_upsell_enabled=True,
        mana_retention_expiry_enabled=True,
        mana_parent_touch_manager_enabled=True,
        mana_client_upsell_currency_enabled=True,
        mana_upsell_inline_results_enabled=True,
        mana_parent_touch_tariff_handoff_enabled=True,
        mana_family_compact_inputs_enabled=True,
        mana_parent_touch_compact_publication_enabled=compact_publication,
        mana_parent_touch_compact_manager_enabled=compact_manager,
        mana_child_safety_limits=ChildSafetyLimits(
            job_tokens=2000,
            server_daily_tokens=2000,
            parent_daily_tokens=2000,
            lease_seconds=360,
        ),
    )
    values = active.model_dump()
    for key, value in tuple(values.items()):
        if key.startswith("mana_") and type(value) is bool:
            values[key] = False
    values.update(mana_parent_chat_enabled=True, mana_parent_touch_enabled=True)
    closed = Settings(_env_file=None, **values)
    for selected in (active, closed):
        async with runtime.parent_chat_runtime(selected):
            with sqlite3.connect(active.mana_parent_chat_database_path) as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == (
                    36 if compact_publication else 35
                )
                assert not db.execute("SELECT 1 FROM family_input_presentations").fetchone()
    assert attempted == []
