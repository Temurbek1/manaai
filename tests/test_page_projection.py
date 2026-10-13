"""Exact duplicate-page references, full source retention and fail-closed v13/v4 state."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch
from sqlalchemy import update

from app.core.config import Settings, get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.page_projection import page_reference
from app.mana_operation_ai.domain.agent_tools import AgentToolCall, AgentToolRecord
from app.mana_operation_ai.domain.goals import OperationGoal
from app.mana_operation_ai.domain.model_continuation import ModelContinuation
from app.mana_operation_ai.infrastructure.goal_continuation import finish_continuation
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import GoalRow
from tests.legacy_goal_contract import LegacyGoal
from tests.test_goal_continuation import MODEL, decision, raw_reply
from tests.test_native_report_discovery import TEXT as CATALOG_TEXT
from tests.test_native_report_discovery import CatalogModel, configure, new_goal
from tests.test_operation_goals import command
from tests.test_runtime_snapshots import evidence, finish, native_goal, prepare
from tests.test_saved_report_catalog import catalog_report

TEXT = "\n " + "я" * 3995 + " \t\n" + "x" * 4000 + " EXACT QUALIFIED FOOTER \t\n"


def page_goal(*, offset: int = 0) -> OperationGoal:
    goal = native_goal()
    goal.page_projection_enabled = True
    goal.evidence = [evidence(goal, TEXT)]
    text = TEXT[offset : offset + 4000]
    goal.tools = [
        AgentToolRecord(
            call_id="exact-sql-page",
            call=AgentToolCall(
                name="read_saved_report_page", report_id="exact-source", offset=offset
            ),
            status="completed",
            started_at=goal.created_at,
            result=json.dumps(
                {
                    "report_id": "exact-source",
                    "offset": offset,
                    "text": text,
                    "total_characters": len(TEXT),
                    "next_offset": offset + len(text) if offset + len(text) < len(TEXT) else None,
                    "loaded_into_evidence": True,
                    "reading_not_population_coverage": True,
                },
                ensure_ascii=False,
            ),
        )
    ]
    return goal


def pending_page_state(goal: OperationGoal) -> ModelContinuation:
    before = goal.model_copy(deep=True)
    before.tools = []
    call = goal.tools[0].call
    output = raw_reply(decision(), compact=False, tool=True).http_response.json()["output"]
    output[0].update(
        name=call.name,
        arguments=json.dumps({"report_id": call.report_id, "offset": call.offset}),
    )
    return finish_continuation(
        prepare(before), output, model=MODEL, call=call, maximum_bytes=192000
    )


@pytest.mark.parametrize("offset", [0, 4000, 8000])
def test_exact_unicode_whitespace_page_reference_keeps_all_other_fields(offset: int) -> None:
    goal = page_goal(offset=offset)
    record = goal.tools[0]
    raw = record.result
    reference = page_reference(goal, record)
    if offset == 8000:
        assert reference is None  # A tiny tail is not made larger by metadata.
        return
    assert reference is not None
    original = json.loads(raw)
    assert reference.model_dump(exclude={"text_reference"}) == {
        key: value for key, value in original.items() if key != "text"
    }
    span = goal.evidence[0].summary[offset : offset + reference.text_reference.characters]
    assert span == original["text"]
    assert hashlib.sha256(span.encode()).hexdigest() == reference.text_reference.text_sha256
    assert reference.text_reference.location == "goal.evidence.summary"
    assert record.result == raw and goal.evidence[0].summary == TEXT
    projected = record.model_copy(update={"result": reference.model_dump_json()})
    assert page_reference(goal, projected) == reference


@pytest.mark.parametrize(
    "failure",
    [
        "gate",
        "denied",
        "shortened",
        "extra",
        "false",
        "integer",
        "offset",
        "id",
        "total",
        "next",
        "text",
        "product",
        "receipt",
        "duplicate",
    ],
)
def test_unproven_or_altered_receipt_is_never_replaced(failure: str) -> None:
    goal = page_goal()
    record = goal.tools[0]
    value = json.loads(record.result)
    if failure == "gate":
        goal.page_projection_enabled = False
    elif failure == "denied":
        record.status = "denied"
    elif failure == "shortened":
        record.result_shortened = True
    elif failure == "extra":
        value["unexpected_source_note"] = "Never discard an unknown field"
    elif failure == "false":
        value["loaded_into_evidence"] = False
    elif failure == "integer":
        value["loaded_into_evidence"] = 1
    elif failure == "offset":
        record.call.offset = 1
    elif failure == "id":
        value["report_id"] = "other-report"
    elif failure == "total":
        value["total_characters"] += 1
    elif failure == "next":
        value["next_offset"] += 1
    elif failure == "text":
        value["text"] = value["text"][:-1] + "z"
    elif failure == "product":
        goal.evidence[0].product = "360rec"
    elif failure == "receipt":
        assert goal.evidence[0].report_read_progress is not None
        goal.evidence[0].report_read_progress.loaded_text_sha256 = "b" * 64
    else:
        goal.evidence.append(goal.evidence[0])
    record.result = json.dumps(value, ensure_ascii=False)
    original = record.result
    assert page_reference(goal, record) is None
    assert record.result == original


def test_v4_pending_page_pairing_provenance_rebind_and_independent_review() -> None:
    goal = page_goal()
    pending = pending_page_state(goal)
    resumed = prepare(goal, pending)
    assert resumed.page_outputs[0].tool_position == 0
    assert resumed.page_outputs[0].position == 1
    assert resumed.items[0].get("call_id") == resumed.items[1].get("call_id")
    assert '"text_reference"' in json.loads(str(resumed.items[1].get("output")))["result"]
    assert goal.evidence[0].summary == TEXT
    state = finish(resumed)
    assert state.protocol == "goal-model-continuation-v4"
    repeated = prepare(goal, state)
    assert repeated.items[0:2] == resumed.items[0:2]
    assert len(repeated.page_outputs) == 1 and len(repeated.runtime_snapshots) == 1
    assert "Keep every quoted word" in str(repeated.items[-1])
    compacted = finish(repeated, compact=True)
    assert compacted.page_outputs == [] and compacted.runtime_snapshots == []
    goal.phase = "review"
    reviewed = prepare(goal, state)
    assert len(reviewed.items) == 1 and reviewed.page_outputs == ()
    assert reviewed.goal.evidence[0].summary == TEXT


@pytest.mark.parametrize(
    "failure", ["source", "body", "identity", "position", "digest", "protocol"]
)
def test_lost_or_corrupt_projected_text_stops_without_model_or_source_retry(failure: str) -> None:
    goal = page_goal()
    state = finish(prepare(goal, pending_page_state(goal)))
    changed = goal.model_copy(deep=True)
    if failure == "source":
        assert changed.evidence[0].report_read_progress is not None
        changed.evidence[0].report_read_progress.source_fingerprint = "b" * 64
    elif failure == "identity":
        changed.tools[0].call_id = "different-sql-observation"
    elif failure == "body":
        value = json.loads(changed.tools[0].result)
        value["text"] = "Altered full receipt"
        changed.tools[0].result = json.dumps(value)
    else:
        values = state.model_dump(mode="json")
        if failure == "position":
            values["page_outputs"][0]["position"] = 127
        elif failure == "digest":
            values["page_outputs"][0]["item_digest"] = "0" * 64
        else:
            values["protocol"] = "goal-model-continuation-v3"
        with pytest.raises(ValidationError):
            ModelContinuation.model_validate(values)
        return
    with pytest.raises(ChatError, match="Точный текст"):
        prepare(changed, state)


async def test_context_projection_keeps_sql_receipt_and_full_source_across_restart(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure(monkeypatch, tmp_path / "projection.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_SNAPSHOT_REPLACEMENT_ENABLED", "true")
    monkeypatch.setenv("OPERATION_WORKSPACE_PAGE_PROJECTION_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        initial = await new_goal(service)
        assert initial.page_projection_enabled
        fixture = page_goal()
        changed = initial.model_copy(update={"tools": fixture.tools, "evidence": fixture.evidence})
        raw = changed.tools[0].result
        projected = OperationGoal.model_validate(json.loads(service._context(changed))["goal"])
        assert '"text_reference"' in projected.tools[0].result
        assert projected.tools[0].result_shortened is False
        assert projected.evidence[0].summary == TEXT and changed.tools[0].result == raw
        changed.model_continuation = finish(prepare(projected, pending_page_state(projected)))
        assert await service.repository.save("alice", initial, changed)
        restored = await SqlAlchemyGoalRepository(app.state.operation_database, service._clock).get(
            "alice", initial.goal_id
        )
        assert restored.tools[0].result == raw and restored.evidence[0].summary == TEXT
        assert (
            restored.model_continuation is not None
            and len(restored.model_continuation.page_outputs) == 1
        )
        storage = service.repository._storage(restored)
        assert (
            storage["workspace_payload"] is not None
            and storage["workspace_payload"]["version"] == 13
        )
        assert "page_projection_enabled" not in storage["payload"]
        assert LegacyGoal.model_validate(storage["payload"]).status == "cancelled"
        with pytest.raises(ChatError, match="Договор ссылок"):
            await service.repository.save(
                "alice", restored, restored.model_copy(update={"page_projection_enabled": False})
            )
        service._page_projection_enabled = False
        source = AsyncMock()
        model = AsyncMock()
        monkeypatch.setattr(service._admin, "run_now", source)
        monkeypatch.setattr(service._continuing_model, "continue_decide", model)
        assert await service.tick()
        source.assert_not_called()
        model.assert_not_called()
    get_settings.cache_clear()


@pytest.mark.parametrize("mutation", ["version", "capture", "scope"])
async def test_v13_rejects_tampered_capture_version_or_scope(
    monkeypatch: MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    configure(monkeypatch, tmp_path / f"projection-{mutation}.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_SNAPSHOT_REPLACEMENT_ENABLED", "true")
    monkeypatch.setenv("OPERATION_WORKSPACE_PAGE_PROJECTION_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        goal = await new_goal(service)
        async with app.state.operation_database.session_factory.begin() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row is not None and row.workspace_payload is not None
            value = json.loads(json.dumps(row.workspace_payload))
            if mutation == "version":
                value["version"] = 12
            elif mutation == "capture":
                value["goal"]["page_projection_enabled"] = False
            else:
                value["analysis_scope"] = "saved_snapshot"
            await session.execute(
                update(GoalRow)
                .where(GoalRow.goal_id == goal.goal_id)
                .values(workspace_payload=value)
            )
        with pytest.raises(ChatError):
            await service.repository.get("alice", goal.goal_id)
    get_settings.cache_clear()


def test_projection_is_default_disabled_and_old_capture_is_not_upgraded() -> None:
    assert not Settings(
        _env_file=None, openai_api_key="fixture"
    ).operation_workspace_page_projection_enabled
    goal = native_goal()
    before = SqlAlchemyGoalRepository._storage(goal)
    assert "page_projection_enabled" not in json.dumps(before["workspace_payload"])
    state = finish(prepare(goal))
    saved = goal.model_copy(update={"model_continuation": state})
    assert "page_outputs" not in json.dumps(
        SqlAlchemyGoalRepository._storage(saved)["workspace_payload"]
    )
    upgraded = saved.model_copy(update={"page_projection_enabled": True})
    with pytest.raises(ChatError):
        prepare(upgraded, state)


async def test_native_projection_full_report_review_and_old_goal_capture(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure(monkeypatch, tmp_path / "native-projection.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_SNAPSHOT_REPLACEMENT_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        old = await new_goal(service)
        before = service.repository._storage(old)
        service.repository._page_projection_enabled = True
        service._page_projection_enabled = True
        assert await service.create("alice", old.topic_id, old.request) == old
        assert service.repository._storage(old) == before
        await service.command("alice", old.goal_id, command(old, "cancel"))
        original = await new_goal(service)
        assert original.page_projection_enabled
        for index in range(23):
            await catalog_report(
                service._admin.repository,
                "catalog-target" if index == 0 else f"z-catalog-{index:03}",
                created_at=original.created_at - timedelta(seconds=1),
                text=CATALOG_TEXT if index == 0 else "Unverified fixture",
                verified=index == 0,
            )
        source = AsyncMock()
        monkeypatch.setattr(service._admin, "run_now", source)
        model = CatalogModel()
        service._continuing_model = model
        for _ in range(10):
            assert await service.tick()
        final = await service.repository.get("alice", original.goal_id)
        assert final.status == "completed" and final.request == original.request
        assert final.evidence[0].summary == CATALOG_TEXT and not final.evidence[0].shortened
        assert final.model_continuation is not None
        assert final.model_continuation.protocol == "goal-model-continuation-v4"
        assert not final.read_attempted and not final.approved_capability and not final.limit_grants
        assert any('"text_reference"' in str(item) for item in model.contexts)
        assert any(
            '"text"' in record.result
            for record in final.tools
            if record.call.name == "read_saved_report_page"
        )
        source.assert_not_called()
    get_settings.cache_clear()
