"""Historical completion is explicit, source-free and never weakens current Goals."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pytest import MonkeyPatch
from sqlalchemy import select

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.agent_tools import AgentToolCall
from app.mana_operation_ai.domain.chat import TopicCreate
from app.mana_operation_ai.domain.goals import GoalCreate, GoalDecision, GoalTask
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import GoalRow
from tests.legacy_goal_contract import LegacyGoal
from tests.test_operation_agent_workspace import ToolModel, configure_workspace
from tests.test_operation_goals import seed


@pytest.mark.parametrize("scope", ["current", "saved_snapshot"])
async def test_explicit_historical_scope_completes_dated_stale_analysis_without_reads(
    monkeypatch: MonkeyPatch, tmp_path: Path, scope: str
) -> None:
    configure_workspace(monkeypatch, tmp_path / f"{scope}.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        model = ToolModel()
        service._model = model
        await seed(service, stale=True)
        topic = await service._chats.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Saved slice"),
        )
        request = GoalCreate(
            request_id=uuid4(),
            objective="Analyze only the dated saved snapshot, not today's retention.",
            analysis_scope=scope,
            execution_mode="agent",
        )
        goal = await service.create("alice", topic.topic_id, request)
        assert service._allowed_reads(goal) == []
        for _ in range(5):
            assert await service.tick()
        saved = await service.repository.get("alice", goal.goal_id)
        assert saved.status == ("completed" if scope == "saved_snapshot" else "waiting")
        assert saved.request.analysis_scope == scope
        assert [record.call.name for record in saved.tools] == [
            "inspect_sources",
            "read_saved_report",
        ]
        assert not saved.read_attempted
        assert not await service.tick()
        async with app.state.operation_database.session_factory() as session:
            row = await session.scalar(select(GoalRow).where(GoalRow.goal_id == goal.goal_id))
            assert row is not None and row.workspace_payload is not None
            assert row.workspace_payload["version"] == (4 if scope == "saved_snapshot" else 1)
            legacy = LegacyGoal.model_validate(row.payload)
            assert legacy.status in ("completed", "cancelled")
            assert "analysis_scope" not in row.payload["request"]
        restored = await SqlAlchemyGoalRepository(app.state.operation_database, service._clock).get(
            "alice", goal.goal_id
        )
        assert restored == saved
        assert (await service.create("alice", topic.topic_id, request)) == saved
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "failure", ["future", "undated", "shortened", "wrong_product", "unused", "empty"]
)
async def test_historical_scope_still_rejects_incompatible_evidence(
    monkeypatch: MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    configure_workspace(monkeypatch, tmp_path / f"{failure}.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        service._model = ToolModel()
        await seed(service, stale=True)
        topic = await service._chats.create(
            "alice",
            TopicCreate(
                agent_id="operations-orchestrator", product="mana", title="Invalid evidence"
            ),
        )
        goal = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(),
                objective="Analyze the saved historical snapshot.",
                execution_mode="agent",
                analysis_scope="saved_snapshot",
            ),
        )
        await service.tick()
        await service.tick()
        goal = await service.repository.get("alice", goal.goal_id)
        goal.phase = "review"
        item = goal.evidence[0]
        if failure == "future":
            item.collected_at = service._clock.now() + timedelta(days=1)
        elif failure == "undated":
            item.collected_at = None
        elif failure == "shortened":
            item.shortened = True
        elif failure == "wrong_product":
            item.product = "360rec"
        elif failure == "empty":
            item.summary = " "
        decision = GoalDecision(
            update="Review finished",
            draft="Historical findings only.",
            plan=[GoalTask(title="Check evidence", status="done")],
            evidence_ids=[] if failure == "unused" else [item.report_id],
            disposition="accepted",
            missing_information="",
            requested_capability=None,
        )
        with pytest.raises(ChatError, match="цель не закрыта"):
            service._apply(goal, decision)
        assert goal.status != "completed"
    get_settings.cache_clear()


async def test_saved_snapshot_does_not_offer_or_approve_a_live_read(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "read-refused.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        service.availability.read_capabilities = ["retention.parents.analyze"]
        service.availability.read_products = {"retention.parents.analyze": "mana"}
        service._model = ToolModel(
            AgentToolCall(name="request_source_read", capability="retention.parents.analyze")
        )
        topic = await service._chats.create(
            "alice",
            TopicCreate(
                agent_id="operations-orchestrator", product="mana", title="No source reads"
            ),
        )
        goal = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(),
                objective="Analyze only the saved summary.",
                execution_mode="agent",
                analysis_scope="saved_snapshot",
            ),
        )
        assert not service._allowed_reads(goal)
        assert '"allowed_read_capabilities":[]' in service._context(goal).replace(" ", "")
        await service.tick()
        await service.tick()
        denied = await service.repository.get("alice", goal.goal_id)
        assert denied.status == "waiting" and not denied.read_attempted
        assert denied.tools[-1].status == "denied"
        assert denied.requested_capability is None and denied.approved_capability is None
        service.availability.agent_workspace_enabled = False
        with pytest.raises(ChatError):
            await service.create(
                "alice", topic.topic_id, goal.request.model_copy(update={"request_id": uuid4()})
            )
    get_settings.cache_clear()


@pytest.mark.parametrize("scope,version", [("saved_snapshot", 3), ("current", 4)])
async def test_checkpoint_protocol_cannot_silently_change_analysis_scope(
    monkeypatch: MonkeyPatch, tmp_path: Path, scope: str, version: int
) -> None:
    configure_workspace(monkeypatch, tmp_path / "wrong-scope-protocol.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        topic = await service._chats.create(
            "alice",
            TopicCreate(
                agent_id="operations-orchestrator", product="mana", title="PRIVATE protocol"
            ),
        )
        goal = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(),
                objective="PRIVATE protocol compatibility check.",
                execution_mode="agent",
                analysis_scope=scope,
            ),
        )
        async with app.state.operation_database.session_factory() as session, session.begin():
            row = await session.get(GoalRow, goal.goal_id)
            assert row is not None and row.workspace_payload is not None
            row.workspace_payload = {**row.workspace_payload, "version": version}
        with pytest.raises(ChatError) as error:
            await service.repository.get("alice", goal.goal_id)
        assert error.value.status == 503
        assert "PRIVATE" not in str(error.value)
    get_settings.cache_clear()
