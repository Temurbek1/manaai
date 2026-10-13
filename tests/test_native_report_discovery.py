"""Captured native SQL discovery with real persistence and fake provider receipts."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import JsonValue, ValidationError
from pytest import MonkeyPatch
from sqlalchemy import update

from app.core.config import Settings, get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.goal_ports import GoalModelOutput, GoalModelResponseError
from app.mana_operation_ai.application.model_continuation import continuation_scope_digest
from app.mana_operation_ai.domain.agent_tools import AgentToolCall
from app.mana_operation_ai.domain.chat import TopicCreate
from app.mana_operation_ai.domain.goals import GoalCreate, GoalTask, OperationGoal
from app.mana_operation_ai.infrastructure.agent_tool_schema import (
    agent_function_tools,
    parse_agent_function,
)
from app.mana_operation_ai.infrastructure.goal_continuation import (
    finish_continuation,
    prepare_continuation,
)
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import GoalRow
from tests.legacy_goal_contract import LegacyGoal
from tests.test_goal_continuation import context, decision, fixture_goal, raw_reply
from tests.test_operation_agent_workspace import configure_workspace
from tests.test_operation_api import headers
from tests.test_operation_goals import GoalFake, command
from tests.test_saved_report_catalog import catalog_report

TAIL = "EXACT DISCOVERY FOOTER: parents only; tariffs are not payments."
TEXT = "Synthetic supplied MANA parent evidence only. " + "x" * 8100 + " " + TAIL
OBJECTIVE = (
    "Find the older saved report, read its complete text including the exact footer, "
    "and analyze it."
)


def configure(monkeypatch: MonkeyPatch, path: Path, *, enabled: bool = True) -> None:
    configure_workspace(monkeypatch, path)
    monkeypatch.setenv("OPERATION_WORKSPACE_REPORT_DISCOVERY_ENABLED", str(enabled).lower())
    monkeypatch.setenv("OPERATION_GOAL_LIMIT_EXTENSIONS_ENABLED", "true")
    monkeypatch.setenv("OPERATION_GOALS_MAX_STEPS", "12")
    monkeypatch.setenv("OPERATION_GOALS_BUDGET_MICROUSD", "500000")
    monkeypatch.setenv("OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED", "true")
    get_settings.cache_clear()


async def new_goal(service: object) -> OperationGoal:
    # Callers supply the assembled application service, not a fabricated goal repository.
    from app.mana_operation_ai.application.goal_service import OperationGoalService

    assert isinstance(service, OperationGoalService)
    topic = await service._chats.create(
        "alice", TopicCreate(agent_id="operations-orchestrator", product="mana", title="Discovery")
    )
    return await service.create(
        "alice",
        topic.topic_id,
        GoalCreate(
            request_id=uuid4(),
            objective=OBJECTIVE,
            constraints=(
                "Do not collect sources or contact clients. Preserve parents/children separation."
            ),
            execution_mode="agent",
            max_steps=12,
        ),
    )


class CatalogModel(GoalFake):
    async def continue_decide(self, *, context: str, owner: str, state: object) -> GoalModelOutput:
        from app.mana_operation_ai.domain.model_continuation import ModelContinuation

        assert state is None or isinstance(state, ModelContinuation)
        prepared = prepare_continuation(
            context=context, owner=owner, state=state, model="catalog-fake", maximum_bytes=192000
        )
        goal = prepared.goal
        call = None
        if not goal.tools:
            call = AgentToolCall(name="inspect_sources")
        elif not goal.evidence:
            receipt = json.loads(goal.tools[-1].result)
            if receipt["saved_reports"]:
                call = AgentToolCall(
                    name="read_saved_report", report_id=receipt["saved_reports"][0]["report_id"]
                )
            else:
                assert receipt["next_cursor"] is not None
                call = AgentToolCall(
                    name="find_saved_reports", query="", cursor=receipt["next_cursor"]
                )
        elif goal.evidence[0].shortened:
            progress = goal.evidence[0].report_read_progress
            call = AgentToolCall(
                name="read_saved_report_page",
                report_id=goal.evidence[0].report_id,
                offset=progress.next_offset if progress else 0,
            )
        output = await super().decide(context=context, owner=owner)
        output.model = "catalog-fake"
        output.decision.tool_call = call
        if call is None:
            assert goal.evidence[0].summary == TEXT
            output.decision.plan = [
                GoalTask(title=title, status="done" if goal.phase == "review" else "active")
                for title in [
                    "Find the scoped report",
                    "Read all saved text",
                    "Review full evidence",
                ]
            ]
            output.decision.draft = "Synthetic saved report catalog-target: " + TAIL
        schema = next(
            (
                tool
                for tool in agent_function_tools(report_discovery_enabled=True)
                if call and tool["name"] == call.name
            ),
            None,
        )
        items: list[dict[str, JsonValue]] = [
            {
                "type": "compaction",
                "id": "fixture-compaction",
                "encrypted_content": "fixture-private-window",
            }
        ]
        if call:
            assert schema is not None and schema["parameters"] is not None
            properties = schema["parameters"]["properties"]
            assert isinstance(properties, dict)
            items.append(
                {
                    "type": "function_call",
                    "id": "fixture-function",
                    "call_id": f"call-{goal.steps_used}",
                    "name": call.name,
                    "arguments": json.dumps({key: call.model_dump()[key] for key in properties}),
                }
            )
        else:
            items.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "id": "fixture-message",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": output.decision.model_dump_json(exclude={"tool_call"}),
                            "annotations": [],
                        }
                    ],
                }
            )
        output.continuation = finish_continuation(
            prepared, items, model="catalog-fake", call=call, maximum_bytes=192000
        )
        return output

    def continuation_reservation(self, *, context: str, owner: str, state: object) -> int:
        return 20000


async def test_native_discovery_pages_full_text_review_restart_and_owner_scope(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure(monkeypatch, tmp_path / "native.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        goal = await new_goal(service)
        assert goal.report_discovery_enabled and goal.limit_tracking
        for index in range(23):
            await catalog_report(
                service._admin.repository,
                "catalog-target" if index == 0 else f"z-catalog-{index:03}",
                created_at=goal.created_at - timedelta(seconds=1),
                text=TEXT if index == 0 else "Invalid binding fixture",
                verified=index == 0,
            )
        source = AsyncMock()
        monkeypatch.setattr(service._admin, "run_now", source)
        model = CatalogModel()
        service._continuing_model = model
        for _ in range(10):
            assert await service.tick()
        restored = SqlAlchemyGoalRepository(
            app.state.operation_database,
            service._clock,
            report_discovery_enabled=True,
            limit_extensions_enabled=True,
        )
        final = await restored.get("alice", goal.goal_id)
        assert final.status == "completed" and final.steps_used == 10
        assert final.request == goal.request and final.evidence[0].summary == TEXT
        assert not final.evidence[0].shortened and TAIL in final.result
        assert final.unsettled_microusd == 0 and not final.read_attempted
        assert final.approved_capability is None and final.requested_capability is None
        assert [record.call.name for record in final.tools].count("find_saved_reports") == 2
        assert all(task.status == "done" for task in final.plan)
        assert OperationGoal.model_validate(model.contexts[-1]["goal"]).phase == "review"
        source.assert_not_called()
        assert not await service.tick()
        with pytest.raises(ChatError):
            await restored.get("bob", goal.goal_id)
        async with app.state.operation_database.session_factory() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row is not None and row.workspace_payload is not None
            assert row.workspace_payload["version"] == 11
            assert row.workspace_payload["analysis_scope"] == "current"
            assert "report_discovery_enabled" not in row.payload
            assert LegacyGoal.model_validate(row.payload).status == "completed"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                f"/api/v1/admin/operation/goals/{goal.goal_id}",
                headers=headers("alice", "operator"),
            )
            assert response.status_code == 200 and response.json()["status"] == "completed"
    get_settings.cache_clear()


async def test_existing_goal_tool_contract_and_checkpoint_are_not_upgraded(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "capture.db"
    configure(monkeypatch, path, enabled=False)
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        original = await new_goal(service)
        before = SqlAlchemyGoalRepository._storage(original)
        scope = continuation_scope_digest("alice", original)
    configure(monkeypatch, path)
    reopened = create_app()
    async with reopened.router.lifespan_context(reopened):
        service = reopened.state.operation_goal_service
        restored = await service.repository.get("alice", original.goal_id)
        assert not restored.report_discovery_enabled
        assert SqlAlchemyGoalRepository._storage(restored) == before
        assert continuation_scope_digest("alice", restored) == scope
        assert await service.create("alice", restored.topic_id, restored.request) == restored
        fresh = await new_goal(service)
        assert fresh.report_discovery_enabled
        for captured in (restored, fresh):
            with pytest.raises(ChatError, match="Набор инструментов"):
                await service.repository.save(
                    "alice",
                    captured,
                    captured.model_copy(
                        update={"report_discovery_enabled": not captured.report_discovery_enabled}
                    ),
                )
    get_settings.cache_clear()


@pytest.mark.parametrize("mutation", ["version", "flag", "scope"])
async def test_v11_rejects_tampered_capture_or_analysis_scope(
    monkeypatch: MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    configure(monkeypatch, tmp_path / f"tamper-{mutation}.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        goal = await new_goal(service)
        async with app.state.operation_database.session_factory.begin() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row is not None and row.workspace_payload is not None
            payload = json.loads(json.dumps(row.workspace_payload))
            if mutation == "version":
                payload["version"] = 10
            elif mutation == "flag":
                payload["goal"]["report_discovery_enabled"] = False
            else:
                payload["analysis_scope"] = "saved_snapshot"
            await session.execute(
                update(GoalRow)
                .where(GoalRow.goal_id == goal.goal_id)
                .values(workspace_payload=payload)
            )
        with pytest.raises(ChatError):
            await service.repository.get("alice", goal.goal_id)
    get_settings.cache_clear()


def test_discovery_schema_gate_arguments_and_old_task_cursor_limits() -> None:
    assert not Settings(
        _env_file=None, openai_api_key="fixture"
    ).operation_workspace_report_discovery_enabled
    assert "find_saved_reports" not in {tool["name"] for tool in agent_function_tools()}
    tools = agent_function_tools(report_discovery_enabled=True)
    assert "find_saved_reports" in {tool["name"] for tool in tools}
    arguments = json.dumps({"query": "", "cursor": None, "catalog_capability": None})
    with pytest.raises(ValueError):
        parse_agent_function("find_saved_reports", arguments)
    parsed = parse_agent_function("find_saved_reports", arguments, report_discovery_enabled=True)
    assert parsed.capability is None and parsed.catalog_capability is None
    with pytest.raises(ValueError):
        parse_agent_function(
            "find_saved_reports", '{"query":"","cursor":null}', report_discovery_enabled=True
        )
    with pytest.raises(ValidationError):
        AgentToolCall(name="find_saved_tasks", query="", cursor="x" * 37)
    with pytest.raises(ValidationError):
        AgentToolCall(
            name="request_source_read",
            capability="retention.parents.analyze",
            catalog_capability="retention.parents.analyze",
        )


@pytest.mark.parametrize("captured", [False, True])
async def test_sdk_advertises_and_accepts_only_the_captured_catalog_tool(
    monkeypatch: MonkeyPatch, tmp_path: Path, captured: bool
) -> None:
    configure(monkeypatch, tmp_path / f"sdk-{captured}.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        model = OpenAIGoalModel(get_settings(), app.state.operation_cost_ledger)
        goal = fixture_goal().model_copy(update={"report_discovery_enabled": captured})
        response = raw_reply(decision(), tool=True)
        payload = response.http_response.json()
        payload["output"][-1].update(
            name="find_saved_reports",
            arguments=json.dumps({"query": "", "cursor": None, "catalog_capability": None}),
        )
        response.http_response.json = lambda: payload
        parse = AsyncMock(return_value=response)
        monkeypatch.setattr(model._client.responses.with_raw_response, "parse", parse)
        try:
            if captured:
                output = await model.continue_decide(
                    context=context(goal), owner="alice", state=None
                )
                assert (
                    output.decision.tool_call is not None
                    and output.decision.tool_call.name == "find_saved_reports"
                )
                assert output.continuation is not None
            else:
                with pytest.raises(GoalModelResponseError) as failure:
                    await model.continue_decide(context=context(goal), owner="alice", state=None)
                assert failure.value.actual_microusd == 700
            assert parse.call_count == 1
            names = {tool["name"] for tool in parse.call_args.kwargs["tools"]}
            assert ("find_saved_reports" in names) == captured
        finally:
            await model.close()
    get_settings.cache_clear()


async def test_runtime_disable_and_unknown_costs_stop_before_generation(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure(monkeypatch, tmp_path / "disabled.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        goal = await new_goal(service)
        model = CatalogModel()
        service._continuing_model = model
        service._report_discovery_enabled = False
        assert await service.tick()
        paused = await service.repository.get("alice", goal.goal_id)
        assert paused.status == "waiting" and paused.steps_used == 0 and model.contexts == []
        service._report_discovery_enabled = True
        paused = await service.command("alice", goal.goal_id, command(paused, "resume"))
        held = paused.model_copy(update={"accounted_microusd": 50000, "unsettled_microusd": 50000})
        assert await service.repository.save("alice", paused, held)
        assert await service.tick()
        waiting = await service.repository.get("alice", goal.goal_id)
        assert (
            waiting.unsettled_microusd == 50000 and waiting.steps_used == 0 and model.contexts == []
        )
    get_settings.cache_clear()


async def test_catalog_beyond_twelve_tools_requires_exact_same_goal_limit_grant(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    from app.mana_operation_ai.domain.goals import GoalCommand

    configure(monkeypatch, tmp_path / "extended-catalog.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        original = await new_goal(service)
        for index in range(103):
            await catalog_report(
                service._admin.repository,
                "catalog-target" if index == 0 else f"z-catalog-{index:03}",
                created_at=original.created_at - timedelta(seconds=1),
                text=TEXT if index == 0 else "Invalid binding fixture",
                verified=index == 0,
            )
        service._continuing_model = CatalogModel()
        for _ in range(13):
            assert await service.tick()
        stopped = await service.repository.get("alice", original.goal_id)
        assert (
            stopped.status == "waiting"
            and stopped.limit_stop == "steps"
            and stopped.steps_used == 12
        )
        assert len(stopped.tools) == 12 and stopped.unsettled_microusd == 0
        assert (
            stopped.model_continuation is not None
            and stopped.model_continuation.protocol == "goal-model-continuation-v2"
        )
        assert not await service.tick()
        await service.command(
            "alice",
            original.goal_id,
            GoalCommand(
                request_id=uuid4(),
                expected_revision=stopped.revision,
                command="extend_limits",
                max_steps=24,
                budget_microusd=original.request.budget_microusd,
            ),
        )
        for _ in range(6):
            assert await service.tick()
        final = await service.repository.get("alice", original.goal_id)
        assert final.status == "completed" and final.steps_used == 18
        assert final.request == original.request and final.evidence[0].summary == TEXT
        assert len(final.tools) == 15 and len(final.limit_grants) == 1
        assert (
            not final.read_attempted
            and final.requested_capability is None
            and final.approved_capability is None
        )
        assert final.unsettled_microusd == 0
    get_settings.cache_clear()


def test_extended_continuation_requires_new_captured_protocol_and_preserves_v1_bound() -> None:
    from app.mana_operation_ai.domain.model_continuation import ModelContinuation

    goal = fixture_goal()
    values = {
        "model": "catalog-fake",
        "scope_digest": continuation_scope_digest("alice", goal),
        "payload": "[]",
        "payload_digest": hashlib.sha256(b"[]").hexdigest(),
        "pending_tool_position": 12,
        "pending_tool_call": AgentToolCall(name="inspect_sources"),
    }
    with pytest.raises(ValidationError):
        ModelContinuation.model_validate(values)
    extended = ModelContinuation.model_validate(
        {**values, "protocol": "goal-model-continuation-v2"}
    )
    with pytest.raises(ChatError, match="Протокол"):
        prepare_continuation(
            context=context(goal),
            owner="alice",
            state=extended,
            model="catalog-fake",
            maximum_bytes=192000,
        )
    with pytest.raises(ValidationError):
        ModelContinuation.model_validate(
            {**values, "protocol": "goal-model-continuation-v2", "pending_tool_position": 120}
        )
