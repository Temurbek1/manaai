"""No paid models or live sources: exercise the actual HTTP/SQL/tool control path."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput
from app.mana_operation_ai.application.goal_ports import GoalModelOutput, GoalModelResponseError
from app.mana_operation_ai.domain.agent_tools import AgentToolCall, AgentToolRecord
from app.mana_operation_ai.domain.chat import MessageCreate, TopicCreate
from app.mana_operation_ai.domain.enums import AgentRunStatus
from app.mana_operation_ai.domain.goals import GoalCreate, GoalDecision, OperationGoal
from app.mana_operation_ai.domain.models import AgentRunResult
from app.mana_operation_ai.infrastructure.agent_tool_schema import parse_agent_function
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from tests.test_operation_api import configure_operation_env, headers
from tests.test_operation_chat import BASE as CHAT
from tests.test_operation_goal_model import fake_raw_goal_response
from tests.test_operation_goals import GoalFake, command, seed

BASE = "/api/v1/admin/operation/workspace"


def configure_workspace(monkeypatch: MonkeyPatch, database: Path) -> None:
    configure_operation_env(monkeypatch, database)
    monkeypatch.setenv("OPERATION_CHAT_ENABLED", "true")
    monkeypatch.setenv("OPERATION_GOALS_ENABLED", "true")
    monkeypatch.setenv("OPERATION_AGENT_WORKSPACE_ENABLED", "true")
    monkeypatch.setenv("OPERATION_MODEL_SELECTION_ENABLED", "false")
    get_settings.cache_clear()


class WorkspaceConversation:
    def __init__(self) -> None:
        self.contexts: list[dict[str, object]] = []
        self.start_goal = True

    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        assert "start_goal" in instructions
        self.contexts.append(json.loads(context))
        return ChatTurnOutput(
            "Проверю доступные источники." if self.start_goal else "Привет!",
            "fake-router",
            10,
            10,
            next_action="start_goal" if self.start_goal else "none",
        )


class ToolModel(GoalFake):
    def __init__(self, second_call: AgentToolCall | None = None) -> None:
        super().__init__()
        self.second_call = second_call or AgentToolCall(
            name="read_saved_report", report_id="report-mana"
        )

    async def decide(self, *, context: str, owner: str) -> GoalModelOutput:
        payload = json.loads(context)
        goal = OperationGoal.model_validate(payload["goal"])
        if len(goal.tools) >= 2:
            return await super().decide(context=context, owner=owner)
        self.contexts.append(payload)
        self.started.set()
        await self.release.wait()
        return GoalModelOutput(
            GoalDecision(
                update="Выбираю следующий инструмент",
                plan=goal.plan,
                draft=goal.result,
                evidence_ids=[],
                disposition="continue",
                missing_information="",
                requested_capability=None,
                tool_call=AgentToolCall(name="inspect_sources")
                if not goal.tools
                else self.second_call,
            ),
            "fake-strong",
            5000,
        )


async def test_http_handoff_discovery_analysis_review_and_idempotency(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "workspace.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        chats = app.state.operation_chat_service
        service = app.state.operation_goal_service
        router = WorkspaceConversation()
        chats._model = router
        service._model = ToolModel()
        await seed(service)
        await seed(service, product="360rec")
        topic = await chats.repository.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Конверсия"),
        )
        payload = {
            "request_id": str(uuid4()),
            "message": "Как поднять конверсию? Изучи текущие данные MANA.",
            "execution_mode": "agent",
        }
        url = f"{BASE}/topics/{topic.topic_id}/messages"
        h = headers("alice", "operator")
        first = await client.post(url, headers=h, json=payload)
        assert first.status_code == 200, first.text
        goal_id = first.json()["goal"]["goal_id"]
        assert first.json()["turn"]["next_action"] == "start_goal"
        assert len(router.contexts) == 1
        replay = await client.post(url, headers=h, json=payload)
        assert replay.json()["goal"]["goal_id"] == goal_id
        assert len(router.contexts) == 1
        for _ in range(5):
            assert await service.tick()
        goal = await service.repository.get("alice", goal_id)
        assert goal.status == "completed" and goal.phase == "review"
        assert goal.steps_used == 5 and goal.accounted_microusd == 25000
        assert [item.call.name for item in goal.tools] == ["inspect_sources", "read_saved_report"]
        assert all(item.status == "completed" for item in goal.tools)
        catalog = json.loads(goal.tools[0].result)
        assert [item["report_id"] for item in catalog["saved_reports"]] == ["report-mana"]
        assert [item.report_id for item in goal.evidence] == ["report-mana"]
        assert not await service.tick()
        assert (
            await client.post(url, headers=headers("bob", "admin"), json=payload)
        ).status_code == 404
        assert (
            await client.post(url, headers=headers("alice", "viewer"), json=payload)
        ).status_code == 403
        assert (
            await client.post(f"{CHAT}/topics/{topic.topic_id}/messages", headers=h, json=payload)
        ).status_code == 403
    get_settings.cache_clear()


async def test_greeting_stays_a_conversation_and_missing_goal_availability_spends_nothing(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "greeting.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        chats = app.state.operation_chat_service
        goals = app.state.operation_goal_service
        router = WorkspaceConversation()
        router.start_goal = False
        chats._model = router
        topic = await chats.repository.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Обсуждение"),
        )
        result = await app.state.operation_workspace_service.send(
            "alice",
            topic.topic_id,
            MessageCreate(request_id=uuid4(), message="Привет", execution_mode="agent"),
        )
        assert result.goal is None and result.turn.answer == "Привет!"
        assert not await goals.list_goals("alice", topic.topic_id)
        goals.availability.enabled = False
        from app.mana_operation_ai.application.chat_ports import ChatError

        with pytest.raises(ChatError, match="отключён"):
            await app.state.operation_workspace_service.send(
                "alice",
                topic.topic_id,
                MessageCreate(
                    request_id=uuid4(), message="Изучи данные MANA", execution_mode="agent"
                ),
            )
        assert len(router.contexts) == 1
    get_settings.cache_clear()


async def test_handoff_preserves_user_constraints_and_rejects_another_active_task_before_model(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "history.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        chats = app.state.operation_chat_service
        router = WorkspaceConversation()
        chats._model = router
        topic = await chats.repository.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Контекст")
        )
        router.start_goal = False
        await app.state.operation_workspace_service.send(
            "alice",
            topic.topic_id,
            MessageCreate(
                request_id=uuid4(),
                message="Не трогай 360REC. Только родители MANA.",
                execution_mode="agent",
            ),
        )
        router.start_goal = True
        result = await app.state.operation_workspace_service.send(
            "alice",
            topic.topic_id,
            MessageCreate(
                request_id=uuid4(), message="Проанализируй удержание", execution_mode="agent"
            ),
        )
        assert result.goal is not None
        assert (
            result.goal.request.conversation_history[0].user
            == "Не трогай 360REC. Только родители MANA."
        )
        from app.mana_operation_ai.application.chat_ports import ChatError

        with pytest.raises(ChatError, match="уже есть задача"):
            await app.state.operation_workspace_service.send(
                "alice",
                topic.topic_id,
                MessageCreate(
                    request_id=uuid4(), message="И ещё другую задачу", execution_mode="agent"
                ),
            )
        assert len(router.contexts) == 2
    get_settings.cache_clear()


@pytest.mark.parametrize("kind", ["foreign_report", "unbound_read", "ask_user", "parent_read"])
async def test_tool_scope_approval_and_clarification_are_not_source_execution(
    monkeypatch: MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    configure_workspace(monkeypatch, tmp_path / f"{kind}.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        calls = {
            "foreign_report": AgentToolCall(name="read_saved_report", report_id="report-360rec"),
            "unbound_read": AgentToolCall(
                name="request_source_read", capability="retention.engagement.analyze"
            ),
            "ask_user": AgentToolCall(
                name="ask_user", question="Какой период?", options=["7 дней", "30 дней"]
            ),
            "parent_read": AgentToolCall(
                name="request_source_read", capability="retention.parents.analyze"
            ),
        }
        service._model = ToolModel(calls[kind])
        service.availability.read_capabilities = ["retention.parents.analyze"]
        service.availability.read_products = {"retention.parents.analyze": "mana"}
        run_now = AsyncMock(side_effect=AssertionError("No approval; no source call"))
        monkeypatch.setattr(service._admin, "run_now", run_now)
        await seed(service, product="360rec")
        topic = await service._chats.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Область MANA"),
        )
        created = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(), objective="Изучи доступные данные MANA", execution_mode="agent"
            ),
        )
        assert await service.tick() and await service.tick()
        goal = await service.repository.get("alice", created.goal_id)
        assert goal.status == "waiting" and not goal.evidence
        assert not run_now.called and not goal.read_attempted
        assert not await service.tick()
        if kind == "parent_read":
            assert goal.requested_capability == "retention.parents.analyze"
            assert goal.tools[-1].status == "awaiting_approval"
        elif kind == "ask_user":
            assert goal.waiting_reason == "Какой период?"
            assert goal.tools[-1].status == "waiting_for_user"
            assert (
                await service.command("alice", goal.goal_id, command(goal, "steer", "30 дней"))
            ).status == "queued"
        else:
            assert goal.tools[-1].status == "denied"
            assert goal.requested_capability is None
    get_settings.cache_clear()


@pytest.mark.parametrize("paused", [False, True])
async def test_inflight_steering_fences_old_result_without_duplicate_call(
    monkeypatch: MonkeyPatch, tmp_path: Path, paused: bool
) -> None:
    configure_workspace(monkeypatch, tmp_path / "steer.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        model = ToolModel()
        model.release.clear()
        service._model = model
        topic = await service._chats.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Уточнение"),
        )
        created = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(), objective="Изучи текущие данные MANA", execution_mode="agent"
            ),
        )
        work = asyncio.create_task(service.tick())
        await asyncio.wait_for(model.started.wait(), timeout=5)
        goal = await service.repository.get("alice", created.goal_id)
        if paused:
            goal = await service.command("alice", goal.goal_id, command(goal, "pause"))
        goal = await service.command(
            "alice",
            goal.goal_id,
            command(goal, "steer", "Только родители; платежи не подменять тарифами."),
        )
        assert goal.status == ("paused" if paused else "running")
        assert goal.lease_until is not None and not await service.tick()
        model.release.set()
        assert await asyncio.wait_for(work, timeout=5)
        goal = await service.repository.get("alice", goal.goal_id)
        assert goal.status == ("paused" if paused else "queued")
        assert goal.lease_until is None and not goal.tools
        # The lost, fenced result does not refund the goal-local conservative hold.
        assert goal.accounted_microusd == 20000 and len(model.contexts) == 1
        if paused:
            goal = await service.command("alice", goal.goal_id, command(goal, "resume"))
        assert await service.tick()
        assert OperationGoal.model_validate(model.contexts[-1]["goal"]).instructions == [
            "Только родители; платежи не подменять тарифами."
        ]
    get_settings.cache_clear()


@pytest.mark.parametrize("bad_call", [None, "unknown", "extra_argument", "multiple", "commentary"])
async def test_native_function_request_is_strict_and_usage_is_accounted(
    monkeypatch: MonkeyPatch, tmp_path: Path, bad_call: str | None
) -> None:
    configure_workspace(monkeypatch, tmp_path / "native.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        model = OpenAIGoalModel(get_settings(), app.state.operation_cost_ledger)
        call = SimpleNamespace(type="function_call", name="inspect_sources", arguments="{}")
        if bad_call == "unknown":
            call.name = "query_entire_database"
        if bad_call == "extra_argument":
            call.arguments = '{"permission":"admin"}'
        response = SimpleNamespace(
            status="completed",
            model="gpt-6.1-sol",
            service_tier="default",
            output=[call, call] if bad_call == "multiple" else [call],
            output_parsed=None,
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=50,
                input_tokens_details=SimpleNamespace(cached_tokens=10),
            ),
            model_dump_json=lambda **kwargs: "{}",
        )
        if bad_call == "commentary":
            response.output.append(
                SimpleNamespace(
                    type="message", content=[{"type": "output_text", "text": "Проверю источники."}]
                )
            )
        raw_response = fake_raw_goal_response(response)
        if bad_call == "commentary":
            raw_response.parse = Mock(side_effect=ValueError("NOT JSON; must not parse commentary"))
        parse = AsyncMock(return_value=raw_response)
        monkeypatch.setattr(model._client.responses.with_raw_response, "parse", parse)
        context = json.dumps(
            {
                "goal": {
                    "product": "mana",
                    "agent_id": "operations-orchestrator",
                    "phase": "plan",
                    "request": {"execution_mode": "agent"},
                }
            }
        )
        try:
            if bad_call and bad_call != "commentary":
                with pytest.raises((ValueError, RuntimeError)):
                    await model.decide(context=context, owner="alice")
            else:
                output = await model.decide(context=context, owner="alice")
                assert output.decision.tool_call == AgentToolCall(name="inspect_sources")
                if bad_call == "commentary":
                    assert not raw_response.parse.called
            kwargs = parse.call_args.kwargs
            assert kwargs["parallel_tool_calls"] is False and kwargs["store"] is False
            assert {tool["name"] for tool in kwargs["tools"]} == {
                "inspect_sources",
                "read_saved_report",
                "request_source_read",
                "ask_user",
            }
            assert all(
                tool["strict"] and not tool["parameters"]["additionalProperties"]
                for tool in kwargs["tools"]
            )
            assert parse.call_count == 1 and model._client.max_retries == 0
            assert all(
                period.usage.llm_microusd == 681
                for period in await app.state.operation_cost_ledger.periods()
            )
        finally:
            await model.close()
    get_settings.cache_clear()


def test_function_arguments_cannot_smuggle_payloads_or_mutations() -> None:
    with pytest.raises(ValueError):
        parse_agent_function("request_source_read", '{"capability":"delete_users"}')
    with pytest.raises(ValueError):
        parse_agent_function("read_saved_report", '{"report_id":"known","sql":"SELECT *"}')


def test_unused_workspace_preserves_the_previous_ordinary_goal_json_contract() -> None:
    now = datetime.now(UTC)
    request = GoalCreate(request_id=uuid4(), objective="Проанализируй удержание")
    goal = OperationGoal(
        goal_id="goal",
        topic_id="topic",
        agent_id="retention-agent",
        product="mana",
        request=request,
        created_at=now,
        updated_at=now,
    )
    payload = SqlAlchemyGoalRepository._payload(goal)
    assert "tools" not in payload
    assert payload["request"] == request.model_dump(
        mode="json", exclude={"execution_mode", "conversation_history", "older_turns_omitted"}
    )
    assert OperationGoal.model_validate(payload) == goal


@pytest.mark.parametrize("lost", [False, True])
async def test_approved_tool_read_is_single_use_and_records_known_or_unknown_outcome(
    monkeypatch: MonkeyPatch, tmp_path: Path, lost: bool
) -> None:
    configure_workspace(monkeypatch, tmp_path / "approval.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        service.availability.read_capabilities = ["retention.parents.analyze"]
        service.availability.read_products = {"retention.parents.analyze": "mana"}
        service._model = ToolModel(
            AgentToolCall(name="request_source_read", capability="retention.parents.analyze")
        )
        run = AsyncMock(
            side_effect=TimeoutError("PRIVATE provider payload") if lost else None,
            return_value=AgentRunResult(run_id="fake-read", status=AgentRunStatus.COMPLETED),
        )
        monkeypatch.setattr(service._admin, "run_now", run)
        topic = await service._chats.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Подтверждение"),
        )
        goal = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(), objective="Изучи родителей MANA", execution_mode="agent"
            ),
        )
        await service.tick()
        await service.tick()
        goal = await service.repository.get("alice", goal.goal_id)
        assert not run.called
        await service.command("alice", goal.goal_id, command(goal, "approve_read"))
        await service.tick()
        goal = await service.repository.get("alice", goal.goal_id)
        assert goal.read_attempted and goal.approved_capability is None
        assert goal.tools[-1].status == ("unknown" if lost else "completed")
        assert "PRIVATE" not in goal.model_dump_json()
        assert run.call_count == 1
        if lost:
            assert goal.status == "waiting" and not await service.tick()
            await service.command("alice", goal.goal_id, command(goal, "resume"))
            await service.tick()
        assert run.call_count == 1
        kwargs = run.call_args.kwargs
        assert kwargs["agent_id"] == "retention-agent"
        assert kwargs["capability_key"] == "retention.parents.analyze"
        assert kwargs["idempotency_key"] == f"goal-read:{goal.goal_id}:retention.parents.analyze"
    get_settings.cache_clear()


async def test_context_compacts_obsolete_tool_output_not_user_constraints_or_evidence(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "context.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        topic = await service._chats.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Контекст"),
        )
        goal = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(),
                objective="Проанализируй удержание",
                execution_mode="agent",
                constraints="Только родители. Не читать Firebase.",
            ),
        )
        goal.instructions = ["Платежи не подменять тарифами."]
        goal.result = "Сохранённая полезная часть анализа."
        goal.tools = [
            AgentToolRecord(
                call_id=f"call-{index}",
                call=AgentToolCall(name="inspect_sources"),
                status="completed",
                started_at=service._clock.now(),
                result="x" * 4000,
            )
            for index in range(4)
        ]
        context_goal = OperationGoal.model_validate(json.loads(service._context(goal))["goal"])
        assert len(context_goal.tools[0].result) == 320
        assert context_goal.tools[0].result_shortened
        assert not context_goal.tools[-1].result_shortened
        assert len(goal.tools[0].result) == 4000 and not goal.tools[0].result_shortened
        assert context_goal.request.constraints == goal.request.constraints
        assert context_goal.instructions == goal.instructions and context_goal.result == goal.result
    get_settings.cache_clear()


async def test_disabling_workspace_stops_queued_agent_before_cost_or_source_io(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "disabled.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        model = ToolModel()
        service._model = model
        topic = await service._chats.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Выключение"),
        )
        goal = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(), objective="Проанализируй удержание", execution_mode="agent"
            ),
        )
        service.availability.agent_workspace_enabled = False
        assert await service.tick()
        goal = await service.repository.get("alice", goal.goal_id)
        assert goal.status == "waiting" and not model.contexts
        assert goal.steps_used == 0 and goal.accounted_microusd == 0
        assert not await service.tick()
    get_settings.cache_clear()


async def test_invalid_completed_model_output_keeps_verified_cost_not_unknown_hold(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "verified-cost.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        model = ToolModel()
        monkeypatch.setattr(
            model,
            "decide",
            AsyncMock(
                side_effect=GoalModelResponseError("Формат ответа не прошёл проверку.", 5000)
            ),
        )
        service._model = model
        topic = await service._chats.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Расходы"),
        )
        goal = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(), objective="Проанализируй удержание", execution_mode="agent"
            ),
        )
        assert await service.tick()
        goal = await service.repository.get("alice", goal.goal_id)
        assert goal.status == "waiting" and goal.accounted_microusd == 5000
        assert not await service.tick()
    get_settings.cache_clear()


@pytest.mark.parametrize("pause", [False, True])
async def test_source_read_interruption_never_leaves_a_phantom_running_tool_or_reissues_read(
    monkeypatch: MonkeyPatch, tmp_path: Path, pause: bool
) -> None:
    configure_workspace(monkeypatch, tmp_path / "read-control.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        service.availability.read_capabilities = ["retention.parents.analyze"]
        service.availability.read_products = {"retention.parents.analyze": "mana"}
        service._model = ToolModel(
            AgentToolCall(name="request_source_read", capability="retention.parents.analyze")
        )
        started, finish = asyncio.Event(), asyncio.Event()

        async def complete_read(**kwargs: object) -> AgentRunResult:
            started.set()
            await finish.wait()
            return AgentRunResult(run_id="fake-controlled-read", status=AgentRunStatus.COMPLETED)

        run = AsyncMock(side_effect=complete_read)
        monkeypatch.setattr(service._admin, "run_now", run)
        topic = await service._chats.create(
            "alice",
            TopicCreate(
                agent_id="operations-orchestrator", product="mana", title="Управление чтением"
            ),
        )
        goal = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(), objective="Изучи родителей MANA", execution_mode="agent"
            ),
        )
        await service.tick()
        await service.tick()
        goal = await service.repository.get("alice", goal.goal_id)
        await service.command("alice", goal.goal_id, command(goal, "approve_read"))
        reading = asyncio.create_task(service.tick())
        await asyncio.wait_for(started.wait(), timeout=5)
        goal = await service.repository.get("alice", goal.goal_id)
        if pause:
            goal = await service.command("alice", goal.goal_id, command(goal, "pause"))
        goal = await service.command(
            "alice", goal.goal_id, command(goal, "steer", "Не делай новое чтение.")
        )
        assert not await service.tick() and run.call_count == 1
        finish.set()
        await asyncio.wait_for(reading, timeout=5)
        goal = await service.repository.get("alice", goal.goal_id)
        assert goal.status == ("paused" if pause else "queued")
        assert goal.lease_until is None and goal.read_attempted
        assert goal.tools[-1].status == "unknown"
        if pause:
            await service.command("alice", goal.goal_id, command(goal, "resume"))
        await service.tick()
        assert run.call_count == 1
    get_settings.cache_clear()
