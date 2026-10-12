"""Contiguous minimized SQL evidence with fake models; never a provider scan."""

import json
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from pytest import MonkeyPatch
from sqlalchemy import update

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.goal_ports import GoalModelOutput
from app.mana_operation_ai.application.goal_service import OperationGoalService
from app.mana_operation_ai.application.model_continuation import public_goal
from app.mana_operation_ai.domain.agent_tools import AgentToolCall
from app.mana_operation_ai.domain.chat import TopicCreate
from app.mana_operation_ai.domain.goals import GoalCreate, GoalDecision, OperationGoal
from app.mana_operation_ai.infrastructure.agent_tool_schema import parse_agent_function
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import GoalRow
from tests.legacy_goal_contract import LegacyGoal
from tests.test_operation_agent_workspace import configure_workspace
from tests.test_operation_goals import GoalFake, seed

REPORT_ID = "paged-synthetic-report"
TEXT = "Synthetic minimized source. " + "р" * 8100 + " EXACT FOOTER: fixture only, not payments."


class PageModel(GoalFake):
    async def decide(self, *, context: str, owner: str) -> GoalModelOutput:
        goal = OperationGoal.model_validate(json.loads(context)["goal"])
        if not goal.tools:
            call = AgentToolCall(name="inspect_sources")
        elif len(goal.tools) == 1:
            call = AgentToolCall(name="read_saved_report", report_id=REPORT_ID)
        else:
            item = goal.evidence[0]
            progress = item.report_read_progress
            if progress is not None and progress.next_offset == progress.total_characters:
                output = await super().decide(context=context, owner=owner)
                output.decision.draft = "Read complete synthetic report, including EXACT FOOTER."
                return output
            call = AgentToolCall(
                name="read_saved_report_page",
                report_id=REPORT_ID,
                offset=progress.next_offset if progress is not None else 0,
            )
        return GoalModelOutput(
            GoalDecision(
                update="Read the next saved page",
                plan=goal.plan,
                draft=goal.result,
                evidence_ids=[],
                disposition="continue",
                missing_information="",
                requested_capability=None,
                tool_call=call,
            ),
            "fake",
            5000,
        )


async def setup_goal(app: FastAPI, *, text: str = TEXT, max_steps: int = 12) -> OperationGoal:
    # Tests use the real application state, but no provider request is dispatched.
    service: OperationGoalService = app.state.operation_goal_service
    service.availability.max_steps = 12
    await seed(service)
    original = await service._admin.get_report("report-mana")
    assert original is not None
    run = await service._admin.repository.get_run(original.run_id)
    assert run is not None
    await service._admin.repository.create_run(
        run.model_copy(update={"run_id": "paged-fixture-run", "idempotency_key": "paged-fixture"})
    )
    await service._admin.repository.save_report(
        original.model_copy(
            update={
                "report_id": REPORT_ID,
                "run_id": "paged-fixture-run",
                "human_readable": text,
            }
        )
    )
    topic = await service._chats.create(
        "alice", TopicCreate(agent_id="operations-orchestrator", product="mana", title="Pages")
    )
    return await service.create(
        "alice",
        topic.topic_id,
        GoalCreate(
            request_id=uuid4(),
            objective="Read the full saved synthetic report, including its exact footer.",
            execution_mode="agent",
            max_steps=max_steps,
        ),
    )


async def test_complete_report_tail_reaches_independent_review_and_survives_sql_restart(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "full.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        created = await setup_goal(app)
        model = PageModel()
        service._model = model
        source_read = AsyncMock()
        monkeypatch.setattr(service._admin, "run_now", source_read)
        for _ in range(8):
            assert await service.tick()
        restored = SqlAlchemyGoalRepository(app.state.operation_database, service._clock)
        goal = await restored.get("alice", created.goal_id)
        assert goal.status == "completed" and goal.steps_used == 8
        assert goal.request.objective == created.request.objective
        assert goal.evidence[0].summary == TEXT and not goal.evidence[0].shortened
        assert goal.evidence[0].report_read_progress is not None
        assert goal.evidence[0].report_read_progress.next_offset == len(TEXT)
        review = model.contexts[-1]["goal"]
        assert isinstance(review, dict) and review["phase"] == "review"
        assert OperationGoal.model_validate(review).evidence[0].summary.endswith("not payments.")
        assert not goal.read_attempted and goal.approved_capability is None
        source_read.assert_not_called()
        assert public_goal(goal).evidence[0].report_read_progress is None
        async with app.state.operation_database.session_factory() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row is not None and row.workspace_payload is not None
            assert row.workspace_payload["version"] == 8
            assert row.workspace_payload["analysis_scope"] == "current"
            legacy = LegacyGoal.model_validate(row.payload)
            assert legacy.status == "completed"
            assert len(legacy.evidence[0].summary) == 5000 and legacy.evidence[0].shortened
            assert "report_read_progress" not in row.payload["evidence"][0]
        assert not await service.tick()
    get_settings.cache_clear()


@pytest.mark.parametrize("kind", ["gap", "foreign", "changed_text", "changed_metadata"])
async def test_report_pages_require_contiguous_unchanged_scoped_source(
    monkeypatch: MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    configure_workspace(monkeypatch, tmp_path / f"{kind}.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        goal = await setup_goal(app)
        first, _ = await service._tools.read_page(goal, REPORT_ID, 0)
        goal.evidence = [first]
        original = await service._admin.get_report(REPORT_ID)
        assert original is not None
        if kind == "foreign":
            replacement = original.model_copy(
                update={"structured": {**original.structured, "product": "360rec"}}
            )
        elif kind == "changed_text":
            replacement = original.model_copy(update={"human_readable": TEXT + "changed"})
        elif kind == "changed_metadata":
            replacement = original.model_copy(update={"data_quality_notes": ["changed quality"]})
        else:
            replacement = original
        monkeypatch.setattr(service._admin, "get_report", AsyncMock(return_value=replacement))
        with pytest.raises(ChatError):
            await service._tools.read_page(goal, REPORT_ID, 5000 if kind == "gap" else 4000)
        assert goal.evidence[0].summary == TEXT[:4000]
    get_settings.cache_clear()


async def test_small_step_budget_preserves_original_objective_and_never_shortcuts_review(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "step-limit.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        created = await setup_goal(app, max_steps=6)
        service._model = PageModel()
        for _ in range(7):
            assert await service.tick()
        saved = await service.repository.get("alice", created.goal_id)
        assert saved.status == "waiting" and saved.phase != "review"
        assert saved.request == created.request and saved.steps_used == 6
        assert saved.accounted_microusd == 30000 and not saved.read_attempted
        assert not await service.tick()
    get_settings.cache_clear()


async def test_partial_pages_quality_clipping_and_oversized_sources_never_complete(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "bounds.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        goal = await setup_goal(app)
        first, payload = await service._tools.read_page(goal, REPORT_ID, 0)
        assert first.shortened and json.loads(payload)["next_offset"] == 4000
        goal.evidence = [first]
        goal.phase = "review"
        fake = GoalFake()
        output = await fake.decide(context=service._context(goal), owner="alice")
        with pytest.raises(ChatError, match="полные|свежие"):
            service._apply(goal, output.decision)
        original = await service._admin.get_report(REPORT_ID)
        assert original is not None
        monkeypatch.setattr(
            service._admin,
            "get_report",
            AsyncMock(return_value=original.model_copy(update={"human_readable": "x" * 32001})),
        )
        with pytest.raises(ChatError, match="не обрезан"):
            await service._tools.read_page(goal, REPORT_ID, 0)
        short = original.model_copy(
            update={"human_readable": "short", "data_quality_notes": ["q" * 301]}
        )
        monkeypatch.setattr(service._admin, "get_report", AsyncMock(return_value=short))
        item, _ = await service._tools.read_page(goal, REPORT_ID, 0)
        assert item.shortened and item.report_read_progress is not None
        assert not item.report_read_progress.quality_notes_complete
    get_settings.cache_clear()


@pytest.mark.parametrize("kind", ["version", "scope", "text", "receipt"])
async def test_private_v8_rejects_corruption_without_downgrading_or_losing_history(
    monkeypatch: MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    configure_workspace(monkeypatch, tmp_path / f"corrupt-{kind}.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        goal = await setup_goal(app)
        item, _ = await service._tools.read_page(goal, REPORT_ID, 0)
        assert await service.repository.save(
            "alice", goal, goal.model_copy(update={"evidence": [item]})
        )
        async with app.state.operation_database.session_factory.begin() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row is not None and row.workspace_payload is not None
            data = json.loads(json.dumps(row.workspace_payload))
            if kind == "version":
                data["version"] = 2
            elif kind == "scope":
                data["analysis_scope"] = "saved_snapshot"
            elif kind == "text":
                data["goal"]["evidence"][0]["summary"] += "tampered"
            else:
                data["goal"]["evidence"][0]["report_read_progress"]["next_offset"] += 1
            await session.execute(
                update(GoalRow)
                .where(GoalRow.goal_id == goal.goal_id)
                .values(workspace_payload=data)
            )
        with pytest.raises(ChatError, match="совместим"):
            await service.repository.get("alice", goal.goal_id)
    get_settings.cache_clear()


@pytest.mark.parametrize("offset", [-1, 1.5, True, 32001, None])
def test_page_function_has_strict_bounded_offsets_and_no_provider_payload(offset: object) -> None:
    with pytest.raises((ValidationError, ValueError)):
        parse_agent_function(
            "read_saved_report_page", json.dumps({"report_id": REPORT_ID, "offset": offset})
        )


def test_page_function_requires_only_report_id_and_offset() -> None:
    assert parse_agent_function(
        "read_saved_report_page", json.dumps({"report_id": REPORT_ID, "offset": 0})
    ) == AgentToolCall(name="read_saved_report_page", report_id=REPORT_ID, offset=0)
    with pytest.raises(ValueError):
        parse_agent_function(
            "read_saved_report_page",
            json.dumps({"report_id": REPORT_ID, "offset": 0, "permission": "admin"}),
        )
