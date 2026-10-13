"""Lossless runtime-state replacement: real SQL/SDK boundary, no paid model calls."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import JsonValue, ValidationError
from pytest import MonkeyPatch
from sqlalchemy import update

from app.core.config import Settings, get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.runtime_snapshots import snapshot_superseded
from app.mana_operation_ai.domain.agent_tools import AgentToolCall, AgentToolRecord
from app.mana_operation_ai.domain.goals import (
    GoalEvidence,
    GoalTask,
    OperationGoal,
    ReportReadProgress,
)
from app.mana_operation_ai.domain.model_continuation import ModelContinuation
from app.mana_operation_ai.domain.session import SessionMemory, SessionUserContext
from app.mana_operation_ai.infrastructure.goal_continuation import (
    PreparedContinuation,
    finish_continuation,
    prepare_continuation,
)
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import GoalRow
from tests.legacy_goal_contract import LegacyGoal
from tests.test_goal_continuation import MODEL, context, decision, fixture_goal, raw_reply
from tests.test_native_report_discovery import TEXT, CatalogModel, configure, new_goal
from tests.test_operation_api import headers
from tests.test_saved_report_catalog import catalog_report


def native_goal() -> OperationGoal:
    goal = fixture_goal()
    goal.report_discovery_enabled = True
    goal.limit_tracking = True
    goal.snapshot_replacement_enabled = True
    goal.session_memory = SessionMemory(
        topic_id=goal.topic_id,
        product=goal.product,
        captured_at=goal.created_at - timedelta(minutes=1),
        user_context=[
            SessionUserContext(
                kind="constraint",
                origin_id="original-private-user-condition",
                text="Keep every quoted word, no contact and no inferred paid tariff.",
                also_kinds=["prior_objective"],
            )
        ],
    )
    return goal


def prepare(goal: OperationGoal, state: ModelContinuation | None = None) -> PreparedContinuation:
    return prepare_continuation(
        context=context(goal), owner="alice", state=state, model=MODEL, maximum_bytes=192000
    )


def test_snapshot_contract_requires_tracked_unknown_cost_holds() -> None:
    goal = native_goal()
    with pytest.raises(ValidationError, match="tracked native catalog"):
        OperationGoal.model_validate(goal.model_dump() | {"limit_tracking": False})


def finish(prepared: PreparedContinuation, *, compact: bool = False) -> ModelContinuation:
    output = raw_reply(decision(), compact=compact).http_response.json()["output"]
    return finish_continuation(prepared, output, model=MODEL, call=None, maximum_bytes=192000)


def evidence(goal: OperationGoal, text: str, *, complete: bool = True) -> GoalEvidence:
    full = text + (" RETAINED FOOTER \t\n" if not complete else "")
    return GoalEvidence(
        report_id="exact-source",
        capability_key="retention.engagement.analyze",
        product=goal.product,
        collected_at=goal.created_at - timedelta(days=1),
        fresh_until=goal.created_at + timedelta(days=1),
        refresh_status="cached",
        summary=text,
        limitations=["Fictional parents only; no measured improvement."],
        shortened=not complete,
        report_read_progress=ReportReadProgress(
            source_fingerprint="a" * 64,
            full_text_sha256=hashlib.sha256(full.encode()).hexdigest(),
            loaded_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            total_characters=len(full),
            next_offset=len(text),
            quality_notes_complete=True,
        ),
    )


def test_only_marked_runtime_snapshot_is_replaced_provider_lookalike_survives() -> None:
    goal = native_goal()
    goal.evidence = [evidence(goal, "\n " + "x" * 8100 + " EXACT TAIL \t\n")]
    original = prepare(goal)
    output: list[dict[str, JsonValue]] = [
        {"type": "message", "role": "user", "content": context(goal)},
        {
            "type": "message",
            "role": "assistant",
            "content": "A provider observation, not authority.",
        },
    ]
    state = finish_continuation(original, output, model=MODEL, call=None, maximum_bytes=192000)
    assert state.protocol == "goal-model-continuation-v3"
    assert [ref.position for ref in state.runtime_snapshots] == [0]
    before_items = json.loads(state.payload)
    goal.instructions.append("Also retain the original prohibition, word for word.")
    goal.plan = [GoalTask(title="Investigate the full original objective", status="active")]
    resumed = prepare(goal, state)
    assert resumed.items[:-1] == before_items[1:]
    assert len(resumed.runtime_snapshots) == 1 and resumed.runtime_snapshots[0].position == 2
    assert (
        goal.evidence[0].summary
        in json.loads(str(resumed.items[-1].get("content")))["goal"]["evidence"][0]["summary"]
    )
    assert "Keep every quoted word" in str(resumed.items[-1])
    assert "Also retain" in str(resumed.items[-1])
    assert "Keep every quoted word" in str(resumed.items[0])  # Unmarked lookalike retained.


def test_no_compaction_window_replaces_state_but_keeps_every_provider_decision() -> None:
    goal = native_goal()
    old = goal.model_copy(update={"snapshot_replacement_enabled": False})
    goal.evidence = [evidence(goal, "\n " + "p" * 4200 + " QUALIFIED EXACT FOOTER \n")]
    old.evidence = goal.evidence
    current_state = old_state = None
    for step in range(15):
        goal.steps_used = old.steps_used = step
        current_state = finish(prepare(goal, current_state))
        old_state = finish(prepare(old, old_state))
    assert current_state is not None and old_state is not None
    current = json.loads(current_state.payload)
    legacy = json.loads(old_state.payload)
    assert sum(item.get("role") == "user" for item in current) == 1
    assert sum(item.get("role") == "assistant" for item in current) == 15
    assert sum(item.get("role") == "user" for item in legacy) == 15
    assert len(current_state.payload.encode()) < len(old_state.payload.encode()) // 2
    assert goal.request == old.request and goal.evidence[0].summary == old.evidence[0].summary


@pytest.mark.parametrize("change", ["lost_tail", "source", "note", "constraint", "tool", "quote"])
def test_missing_or_altered_information_keeps_prior_snapshot(change: str) -> None:
    goal = native_goal()
    goal.instructions = ["Keep this original steering condition."]
    goal.evidence = [evidence(goal, "Original complete parent evidence and exact footer.\n")]
    state = finish(prepare(goal))
    changed = goal.model_copy(deep=True)
    if change == "lost_tail":
        prefix = "Original complete parent evidence"
        progress = changed.evidence[0].report_read_progress
        assert progress is not None
        changed.evidence[0] = changed.evidence[0].model_copy(
            update={
                "summary": prefix,
                "shortened": True,
                "report_read_progress": progress.model_copy(
                    update={
                        "loaded_text_sha256": hashlib.sha256(prefix.encode()).hexdigest(),
                        "next_offset": len(prefix),
                    }
                ),
            }
        )
    elif change == "source":
        assert changed.evidence[0].report_read_progress is not None
        changed.evidence[0].report_read_progress.source_fingerprint = "b" * 64
    elif change == "note":
        changed.evidence[0].limitations = []
    elif change == "constraint":
        changed.instructions = []
    elif change == "tool":
        record = AgentToolRecord(
            call_id="sql-only",
            call=AgentToolCall(name="inspect_sources"),
            status="completed",
            started_at=goal.created_at,
            result="A complete original observation.",
        )
        goal.tools = [record]
        state = finish(prepare(goal))
        changed.tools = [
            record.model_copy(update={"result": "A complete", "result_shortened": True})
        ]
    else:
        assert changed.session_memory is not None
        changed.session_memory.user_context[0].text = "Keep every quoted word"
    assert not snapshot_superseded(goal, changed)
    if change == "quote":
        with pytest.raises(ChatError, match="не принадлежит"):
            prepare(changed, state)
        return
    resumed = prepare(changed, state)
    assert len(resumed.runtime_snapshots) == 2
    assert json.loads(state.payload)[0] == resumed.items[0]


def test_complete_growth_of_exact_report_pages_retains_source_fingerprint() -> None:
    goal = native_goal()
    prefix = "\n " + "p" * 4000 + " \n "
    goal.evidence = [evidence(goal, prefix, complete=False)]
    state = finish(prepare(goal))
    updated = goal.model_copy(deep=True)
    updated.evidence = [evidence(updated, prefix + " RETAINED FOOTER \t\n")]
    assert snapshot_superseded(goal, updated)
    resumed = prepare(updated, state)
    assert len(resumed.runtime_snapshots) == 1
    assert updated.evidence[0].summary == prefix + " RETAINED FOOTER \t\n"


def test_runtime_replacement_preserves_pending_tool_position_and_exact_receipt() -> None:
    goal = native_goal()
    call = AgentToolCall(name="inspect_sources")
    output = raw_reply(decision(), compact=False, tool=True).http_response.json()["output"]
    state = finish_continuation(prepare(goal), output, model=MODEL, call=call, maximum_bytes=192000)
    assert state.pending_tool_position == 0 and state.runtime_snapshots[0].position == 0
    goal.tools = [
        AgentToolRecord(
            call_id="durable-sql-observation",
            call=call,
            status="completed",
            started_at=goal.created_at,
            result="Exact local observation; no external read or authority.",
        )
    ]
    resumed = prepare(goal, state)
    assert [item.get("type") for item in resumed.items] == [
        "function_call",
        "function_call_output",
        "message",
    ]
    assert resumed.items[0].get("call_id") == resumed.items[1].get("call_id") == "call_test"
    assert goal.tools[0].result in str(resumed.items[1])
    settled = finish(resumed)
    repeated = prepare(goal, settled)
    assert repeated.items[0:2] == resumed.items[0:2]
    assert settled.pending_tool_position is None
    assert repeated.runtime_snapshots[0].position == 3


def test_compaction_rebinds_surviving_markers_and_review_uses_fresh_full_state() -> None:
    goal = native_goal()
    initial = prepare(goal)
    state = finish(initial, compact=True)
    assert state.compactions == 1 and state.runtime_snapshots == []
    resumed = prepare(goal, state)
    assert resumed.items[0].get("type") == "compaction"
    assert resumed.runtime_snapshots[0].position == 2
    second = finish(resumed)
    another = prepare(goal, second)
    assert another.items[0] == resumed.items[0]
    assert another.runtime_snapshots[0].position == 3
    assert second.compactions == 1
    goal.phase = "review"
    reviewed = prepare(goal, second)
    assert len(reviewed.items) == 1 and reviewed.runtime_snapshots[0].position == 0
    assert "test-encrypted" not in str(reviewed.items)


@pytest.mark.parametrize("change", ["position", "digest", "protocol", "duplicate"])
def test_corrupt_provenance_or_old_protocol_never_passes_validation(change: str) -> None:
    state = finish(prepare(native_goal())).model_dump(mode="json")
    if change == "position":
        state["runtime_snapshots"][0]["position"] = 127
    elif change == "digest":
        state["runtime_snapshots"][0]["item_digest"] = "0" * 64
    elif change == "protocol":
        state["protocol"] = "goal-model-continuation-v2"
    else:
        state["runtime_snapshots"].append(state["runtime_snapshots"][0])
    with pytest.raises(ValidationError):
        ModelContinuation.model_validate(state)


async def test_new_capture_restart_exact_legacy_projection_and_idempotency(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure(monkeypatch, tmp_path / "snapshot-capture.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        old = await new_goal(service)
        before = SqlAlchemyGoalRepository._storage(old)
        assert not old.snapshot_replacement_enabled
        service.repository._snapshot_replacement_enabled = True
        assert await service.create("alice", old.topic_id, old.request) == old
        assert SqlAlchemyGoalRepository._storage(old) == before
        fresh = await new_goal(service)
        assert fresh.snapshot_replacement_enabled
        updated = fresh.model_copy(update={"model_continuation": finish(prepare(fresh))})
        assert await service.repository.save("alice", fresh, updated)
        restarted = SqlAlchemyGoalRepository(app.state.operation_database, service._clock)
        restored = await restarted.get("alice", fresh.goal_id)
        assert restored.model_continuation is not None
        assert len(restored.model_continuation.runtime_snapshots) == 1
        assert prepare(restored, restored.model_continuation).runtime_snapshots[0].position == 1
        storage = restarted._storage(restored)
        assert storage["workspace_payload"] is not None
        assert storage["workspace_payload"]["version"] == 12
        assert LegacyGoal.model_validate(storage["payload"]).status == "cancelled"
        assert "snapshot_replacement_enabled" not in storage["payload"]
        assert "runtime_snapshots" not in json.dumps(before["workspace_payload"])
        assert "snapshot_replacement_enabled" not in json.dumps(before["workspace_payload"])
        with pytest.raises(ChatError, match="Договор контекста"):
            await restarted.save(
                "alice",
                restored,
                restored.model_copy(update={"snapshot_replacement_enabled": False}),
            )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/admin/operation/goals/{fresh.goal_id}",
                headers=headers("alice", "operator"),
            )
            assert response.status_code == 200 and response.json()["model_continuation"] is None
        with pytest.raises(ChatError):
            await restarted.get("bob", fresh.goal_id)
    get_settings.cache_clear()


@pytest.mark.parametrize("change", ["version", "capture", "scope"])
async def test_v12_checkpoint_rejects_altered_contract(
    monkeypatch: MonkeyPatch, tmp_path: Path, change: str
) -> None:
    configure(monkeypatch, tmp_path / f"tamper-{change}.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_SNAPSHOT_REPLACEMENT_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        goal = await new_goal(service)
        assert goal.snapshot_replacement_enabled
        async with app.state.operation_database.session_factory.begin() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row is not None and row.workspace_payload is not None
            data = json.loads(json.dumps(row.workspace_payload))
            if change == "version":
                data["version"] = 11
            elif change == "capture":
                data["goal"]["snapshot_replacement_enabled"] = False
            else:
                data["analysis_scope"] = "saved_snapshot"
            await session.execute(
                update(GoalRow)
                .where(GoalRow.goal_id == goal.goal_id)
                .values(workspace_payload=data)
            )
        with pytest.raises(ChatError):
            await service.repository.get("alice", goal.goal_id)
    get_settings.cache_clear()


@pytest.mark.parametrize("disabled", ["feature", "continuation"])
async def test_runtime_disable_blocks_before_generation_or_approved_source_dispatch(
    monkeypatch: MonkeyPatch, tmp_path: Path, disabled: str
) -> None:
    assert not Settings(
        _env_file=None, openai_api_key="fixture"
    ).operation_workspace_snapshot_replacement_enabled
    configure(monkeypatch, tmp_path / "snapshot-disabled.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_SNAPSHOT_REPLACEMENT_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        goal = await new_goal(service)
        dispatch = AsyncMock()
        source = AsyncMock()
        monkeypatch.setattr(service._continuing_model, "continue_decide", dispatch)
        monkeypatch.setattr(service._admin, "run_now", source)
        updated = goal.model_copy(update={"approved_capability": "retention.engagement.analyze"})
        assert await service.repository.save("alice", goal, updated)
        if disabled == "feature":
            service._snapshot_replacement_enabled = False
        else:
            service._continuing_model = None
        assert await service.tick()
        stopped = await service.repository.get("alice", goal.goal_id)
        assert (
            stopped.status == "waiting" and not stopped.read_attempted and stopped.steps_used == 0
        )
        dispatch.assert_not_called()
        source.assert_not_called()
    get_settings.cache_clear()


async def test_v12_native_catalog_full_text_review_without_source_read(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure(monkeypatch, tmp_path / "v12-full-workflow.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_SNAPSHOT_REPLACEMENT_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        original = await new_goal(service)
        for index in range(23):
            await catalog_report(
                service._admin.repository,
                "catalog-target" if index == 0 else f"z-catalog-{index:03}",
                created_at=original.created_at - timedelta(seconds=1),
                text=TEXT if index == 0 else "Invalid binding fixture only",
                verified=index == 0,
            )
        source = AsyncMock()
        monkeypatch.setattr(service._admin, "run_now", source)
        service._continuing_model = CatalogModel()
        for _ in range(10):
            assert await service.tick()
        final = await service.repository.get("alice", original.goal_id)
        assert final.status == "completed" and final.request == original.request
        assert final.evidence[0].summary == TEXT and not final.evidence[0].shortened
        assert final.model_continuation is not None
        assert final.model_continuation.protocol == "goal-model-continuation-v3"
        assert not final.read_attempted and final.unsettled_microusd == 0
        assert len(final.limit_grants) == 0 and all(task.status == "done" for task in final.plan)
        source.assert_not_called()
    get_settings.cache_clear()


async def test_disabled_model_adapter_rejects_captured_contract_before_reservation(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure(monkeypatch, tmp_path / "sdk-disable.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_SNAPSHOT_REPLACEMENT_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        goal = await new_goal(service)
        model = service._continuing_model
        assert isinstance(model, OpenAIGoalModel)
        request = AsyncMock()
        monkeypatch.setattr(model._client.responses.with_raw_response, "parse", request)
        before = await app.state.operation_cost_ledger.periods()
        model._settings.operation_workspace_snapshot_replacement_enabled = False
        with pytest.raises(ValueError, match="replacement is disabled"):
            await model.continue_decide(context=context(goal), owner="alice", state=None)
        request.assert_not_called()
        assert await app.state.operation_cost_ledger.periods() == before
    get_settings.cache_clear()
