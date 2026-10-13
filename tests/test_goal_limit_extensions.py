"""Explicit continuation of the original Goal; no provider calls or new read authority."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from pytest import MonkeyPatch
from sqlalchemy import select

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.cost_control import CostBudgetExceeded
from app.mana_operation_ai.application.goal_ports import GoalModelOutput
from app.mana_operation_ai.application.goal_service import OperationGoalService
from app.mana_operation_ai.application.model_continuation import continuation_scope_digest
from app.mana_operation_ai.domain.agent_tools import AgentToolCall
from app.mana_operation_ai.domain.chat import TopicCreate
from app.mana_operation_ai.domain.goals import GoalCommand, GoalCreate, GoalDecision, OperationGoal
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from app.mana_operation_ai.infrastructure.persistence.models import GoalCommandRow, GoalRow
from tests.legacy_goal_contract import LegacyGoal
from tests.test_operation_agent_workspace import ToolModel, configure_workspace
from tests.test_operation_api import headers
from tests.test_operation_goals import GoalFake, command, seed

BASE = "/api/v1/admin/operation/goals"


def configure(monkeypatch: MonkeyPatch, path: Path) -> None:
    configure_workspace(monkeypatch, path)
    monkeypatch.setenv("OPERATION_GOALS_WORKER_ENABLED", "false")
    monkeypatch.setenv("OPERATION_GOAL_LIMIT_EXTENSIONS_ENABLED", "true")
    monkeypatch.setenv("OPERATION_GOALS_EXTENSION_MAX_STEPS", "12")
    monkeypatch.setenv("OPERATION_GOALS_EXTENSION_BUDGET_MICROUSD", "500000")
    get_settings.cache_clear()


async def goal(service: OperationGoalService, *, budget: int = 50000) -> OperationGoal:
    topic = await service._chats.create(
        "alice", TopicCreate(agent_id="operations-orchestrator", product="mana", title="Long work")
    )
    return await service.create(
        "alice",
        topic.topic_id,
        GoalCreate(
            request_id=uuid4(),
            objective="Analyze the supplied saved evidence without narrowing my goal.",
            constraints="Do not collect sources or change data. "
            "Keep parents separate from children.",
            execution_mode="agent",
            max_steps=3,
            budget_microusd=budget,
        ),
    )


async def stopped(service: OperationGoalService) -> OperationGoal:
    await seed(service)
    saved = await goal(service)
    service._model = ToolModel()
    for _ in range(4):
        assert await service.tick()
    result = await service.repository.get("alice", saved.goal_id)
    assert result.status == "waiting" and result.limit_stop == "steps"
    assert result.unsettled_microusd == 0
    return result


def extension(saved: OperationGoal, *, steps: int = 6, budget: int = 50000) -> GoalCommand:
    return GoalCommand(
        request_id=uuid4(),
        command="extend_limits",
        expected_revision=saved.revision,
        max_steps=steps,
        budget_microusd=budget,
    )


async def test_same_goal_continues_across_restart_without_changing_request_or_read_grants(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path / "limits.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        saved = await stopped(service)
        payload = extension(saved)
        expanded = await service.command("alice", saved.goal_id, payload)
        assert expanded.status == "queued" and expanded.limit_stop is None
        assert expanded.request == saved.request and expanded.result == saved.result
        assert expanded.accounted_microusd == saved.accounted_microusd
        assert expanded.evidence == saved.evidence and expanded.tools == saved.tools
        assert not expanded.approved_capability and not expanded.read_attempted
        replay = await service.command("alice", saved.goal_id, payload)
        assert replay.revision == expanded.revision and len(replay.limit_grants) == 1
        async with app.state.operation_database.session_factory() as session:
            row = await session.get(GoalRow, saved.goal_id)
            assert row and row.workspace_payload and row.workspace_payload["version"] == 10
            legacy = LegacyGoal.model_validate(row.payload)
            assert legacy.status == "cancelled"
            receipts = list((await session.scalars(select(GoalCommandRow))).all())
            assert len(receipts) == 1
    restarted = create_app()
    async with restarted.router.lifespan_context(restarted):
        service = restarted.state.operation_goal_service
        service._model = ToolModel()
        restored = await service.repository.get("alice", saved.goal_id)
        assert restored.limit_grants == expanded.limit_grants and restored.request == saved.request
        for _ in range(2):
            assert await service.tick()
        completed = await service.repository.get("alice", saved.goal_id)
        assert completed.status == "completed" and completed.steps_used == 5
        assert completed.request == saved.request and completed.execution_limits.max_steps == 6
        assert completed.unsettled_microusd == 0
        assert completed.accounted_microusd > saved.accounted_microusd
        assert completed.read_attempted is False
        assert len(completed.tools) == 2


@pytest.mark.parametrize("historical", [False, True])
async def test_sdk_continuation_and_review_preserve_scope_and_original_conditions_after_grant(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    historical: bool,
) -> None:
    from tests.test_goal_continuation import decision, raw_reply
    from tests.test_goal_tool_replanning import tool_reply

    configure(monkeypatch, tmp_path / "sdk.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        await seed(service)
        topic = await service._chats.create(
            "alice",
            TopicCreate(
                agent_id="operations-orchestrator", product="mana", title="SDK continuation"
            ),
        )
        saved = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(),
                objective="Finish the original evidence-backed analysis.",
                constraints="Never request another source or silently narrow this objective.",
                execution_mode="agent",
                analysis_scope="saved_snapshot" if historical else "current",
                max_steps=3,
                budget_microusd=500000,
            ),
        )
        digest = continuation_scope_digest("alice", saved)
        model = service._continuing_model
        assert isinstance(model, OpenAIGoalModel)
        parser = AsyncMock(
            side_effect=[
                tool_reply("inspect_sources", {}),
                tool_reply("read_saved_report", {"report_id": "report-mana"}),
                raw_reply(decision()),
                raw_reply(decision()),
                raw_reply(decision(review=True)),
            ]
        )
        monkeypatch.setattr(model._client.responses.with_raw_response, "parse", parser)
        source = AsyncMock(side_effect=AssertionError("A limit grant cannot authorize a source"))
        monkeypatch.setattr(service._admin, "run_now", source)
        for _ in range(4):
            assert await service.tick()
        stopped = await service.repository.get("alice", saved.goal_id)
        assert stopped.limit_stop == "steps" and stopped.model_continuation
        continuation = stopped.model_continuation
        expanded = await service.command(
            "alice", saved.goal_id, extension(stopped, steps=6, budget=500000)
        )
        assert expanded.model_continuation == continuation
        assert continuation_scope_digest("alice", expanded) == digest
        for _ in range(2):
            assert await service.tick()
        final = await service.repository.get("alice", saved.goal_id)
        assert final.status == "completed" and final.steps_used == 5
        assert final.request == saved.request and not final.read_attempted
        assert final.model_continuation and final.model_continuation.scope_digest == digest
        assert final.unsettled_microusd == 0 and parser.call_count == 5
        review_context = str(parser.call_args_list[-1].kwargs["input"])
        assert (
            saved.request.objective in review_context
            and saved.request.constraints in review_context
        )
        assert "test-encrypted-continuation" not in review_context
        source.assert_not_awaited()


async def test_budget_stop_requires_exact_larger_budget_and_keeps_reserved_costs(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path / "budget.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        saved = await goal(service)
        model = GoalFake()
        model.reservation = lambda context: 60000  # type: ignore[method-assign]
        service._model = model
        assert await service.tick()
        saved = await service.repository.get("alice", saved.goal_id)
        assert saved.limit_stop == "budget" and saved.steps_used == 0
        assert saved.accounted_microusd == 0 and model.contexts == []
        with pytest.raises(ChatError):
            await service.command("alice", saved.goal_id, extension(saved, steps=6))
        expanded = await service.command("alice", saved.goal_id, extension(saved, budget=100000))
        assert expanded.accounted_microusd == 0 and expanded.request.budget_microusd == 50000
        assert await service.tick()
        observed = await service.repository.get("alice", saved.goal_id)
        assert observed.accounted_microusd == 5000 and observed.unsettled_microusd == 0


async def test_extended_goal_can_cross_the_original_twelve_tool_bound_without_corrupting_storage(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    import json

    class LongTools(GoalFake):
        async def decide(self, *, context: str, owner: str) -> GoalModelOutput:
            saved = OperationGoal.model_validate(json.loads(context)["goal"])
            if len(saved.tools) < 14:
                return GoalModelOutput(
                    GoalDecision(
                        update="Inspect saved sources within the original objective.",
                        plan=saved.plan,
                        draft=saved.result,
                        evidence_ids=[],
                        disposition="continue",
                        missing_information="",
                        requested_capability=None,
                        tool_call=AgentToolCall(name="inspect_sources")
                        if len(saved.tools) < 13
                        else AgentToolCall(name="read_saved_report", report_id="report-mana"),
                    ),
                    "fake",
                    1000,
                )
            return await super().decide(context=context, owner=owner)

    configure(monkeypatch, tmp_path / "long-tools.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        service.availability.extension_max_steps = 24
        await seed(service)
        saved = await goal(service, budget=500000)
        service._model = LongTools()
        for _ in range(4):
            assert await service.tick()
        stopped = await service.repository.get("alice", saved.goal_id)
        await service.command("alice", saved.goal_id, extension(stopped, steps=18, budget=500000))
        for _ in range(14):
            assert await service.tick()
        completed = await service.repository.get("alice", saved.goal_id)
        assert completed.status == "completed" and len(completed.tools) == 14
        assert completed.steps_used == 17 and completed.request == saved.request
        assert not completed.read_attempted and completed.unsettled_microusd == 0
        assert completed.limit_grants[0].max_steps == 18


@pytest.mark.parametrize(
    "steps,budget", [(3, 50000), (2, 50000), (6, 49000), (13, 50000), (6, 500001)]
)
async def test_non_increase_decrease_and_server_ceiling_fail_closed(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    steps: int,
    budget: int,
) -> None:
    configure(monkeypatch, tmp_path / "denied.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        saved = await stopped(service)
        with pytest.raises((ChatError, ValidationError)):
            await service.command(
                "alice", saved.goal_id, extension(saved, steps=steps, budget=budget)
            )
        assert await service.repository.get("alice", saved.goal_id) == saved


async def test_unknown_model_hold_cannot_resume_extend_or_redispatch_after_restart(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path / "unknown.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        saved = await goal(service)
        model = GoalFake()
        model.fail = True
        service._model = model
        assert await service.tick()
        saved = await service.repository.get("alice", saved.goal_id)
        assert saved.unsettled_microusd == saved.accounted_microusd == 20000
        assert saved.status == "waiting" and saved.limit_stop is None
        with pytest.raises(ChatError):
            await service.command("alice", saved.goal_id, extension(saved, budget=100000))
        with pytest.raises(ChatError):
            await service.command("alice", saved.goal_id, command(saved, "resume"))
        steered = await service.command(
            "alice", saved.goal_id, command(saved, "steer", "Keep my task.")
        )
        assert steered.status == "waiting" and steered.unsettled_microusd == 20000
    restarted = create_app()
    async with restarted.router.lifespan_context(restarted):
        service = restarted.state.operation_goal_service
        service._model = GoalFake()
        assert not await service.tick()
        restored = await service.repository.get("alice", saved.goal_id)
        assert restored.unsettled_microusd == 20000
        assert restored.accounted_microusd == 20000 and restored.instructions == ["Keep my task."]


async def test_pause_accepts_verified_usage_only_and_can_resume_the_same_goal(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path / "pause.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        saved = await goal(service)
        model = GoalFake()
        model.release.clear()
        service._model = model
        work = asyncio.create_task(service.tick())
        await asyncio.wait_for(model.started.wait(), 2)
        current = await service.repository.get("alice", saved.goal_id)
        assert current.unsettled_microusd == 20000
        await service.command("alice", saved.goal_id, command(current, "pause"))
        model.release.set()
        assert await work
        paused = await service.repository.get("alice", saved.goal_id)
        assert paused.status == "paused" and paused.lease_until is None
        assert paused.unsettled_microusd == 0 and paused.accounted_microusd == 5000
        assert not paused.result and not paused.plan and paused.model_continuation is None
        resumed = await service.command("alice", saved.goal_id, command(paused, "resume"))
        assert resumed.status == "queued" and resumed.request == saved.request
        assert await service.tick()
        result = await service.repository.get("alice", saved.goal_id)
        assert result.steps_used == 2 and result.accounted_microusd == 10000


async def test_later_tool_admission_failure_never_refunds_the_priced_model_response(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path / "later-admission.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        saved = await goal(service)
        service._model = ToolModel()
        denied = AsyncMock(side_effect=CostBudgetExceeded("Synthetic later tool admission"))
        monkeypatch.setattr(service, "_execute_tool", denied)
        assert await service.tick()
        result = await service.repository.get("alice", saved.goal_id)
        assert result.status == "waiting" and result.accounted_microusd == 5000
        assert result.unsettled_microusd == 0 and result.limit_stop is None
        assert result.tools[-1].status == "unknown"


async def test_controls_are_owned_fenced_and_disabled_without_activating_sources(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path / "api.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        service = app.state.operation_goal_service
        saved = await stopped(service)
        read = AsyncMock()
        service._admin.run_now = read
        payload = extension(saved).model_dump(mode="json")
        for actor, role, expected in [("bob", "admin", 404), ("alice", "viewer", 403)]:
            reply = await client.post(
                f"{BASE}/{saved.goal_id}/commands", headers=headers(actor, role), json=payload
            )
            assert reply.status_code == expected
        stale = {**payload, "expected_revision": saved.revision - 1}
        assert (
            await client.post(
                f"{BASE}/{saved.goal_id}/commands", headers=headers("alice", "admin"), json=stale
            )
        ).status_code == 409
        service.availability.limit_extensions_enabled = False
        assert (
            await client.post(
                f"{BASE}/{saved.goal_id}/commands", headers=headers("alice", "admin"), json=payload
            )
        ).status_code == 503
        service.availability.limit_extensions_enabled = True
        replies = await asyncio.gather(
            *[
                client.post(
                    f"{BASE}/{saved.goal_id}/commands",
                    headers=headers("alice", "admin"),
                    json=payload,
                )
                for _ in range(2)
            ]
        )
        assert all(reply.status_code == 200 for reply in replies)
        assert replies[0].json()["revision"] == replies[1].json()["revision"]
        assert len(replies[0].json()["limit_grants"]) == 1
        read.assert_not_awaited()
        service.availability.extension_max_steps = 3
        model = GoalFake()
        service._model = model
        assert await service.tick()
        assert not model.contexts


async def test_v10_cannot_be_mislabeled_or_lose_original_scope(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path / "tampered.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        saved = await stopped(service)
        async with app.state.operation_database.session_factory() as session, session.begin():
            row = await session.get(GoalRow, saved.goal_id)
            assert row and row.workspace_payload
            row.workspace_payload = {**row.workspace_payload, "version": 9}
        with pytest.raises(ChatError, match="совместимости"):
            await service.repository.get("alice", saved.goal_id)


@pytest.mark.parametrize(
    "payload",
    [
        {"command": "extend_limits", "max_steps": True, "budget_microusd": 50000},
        {"command": "extend_limits", "max_steps": 6, "budget_microusd": "50000"},
        {"command": "extend_limits", "max_steps": 6},
        {"command": "resume", "max_steps": 6, "budget_microusd": 50000},
    ],
)
def test_exact_typed_limits_only(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GoalCommand.model_validate({"request_id": str(uuid4()), "expected_revision": 0, **payload})


def test_default_configuration_does_not_activate_limit_extensions() -> None:
    from app.core.config import Settings

    settings = Settings(_env_file=None, openai_api_key="test-key")
    assert not settings.operation_goal_limit_extensions_enabled
