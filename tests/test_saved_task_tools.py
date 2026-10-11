"""Private paged SQL recall, exact constraints and zero external source dispatch."""

import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.goal_ports import GoalModelOutput
from app.mana_operation_ai.domain.agent_tools import AgentToolCall
from app.mana_operation_ai.domain.chat import MessageCreate, TopicCreate
from app.mana_operation_ai.domain.goals import GoalCreate, OperationGoal
from app.mana_operation_ai.infrastructure.agent_tool_schema import parse_agent_function
from app.mana_operation_ai.infrastructure.persistence.chat_repository import (
    SqlAlchemyChatRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import GoalRow
from tests.legacy_goal_contract import LegacyGoal
from tests.test_operation_agent_workspace import configure_workspace
from tests.test_operation_cost_ledger import Clock
from tests.test_operation_goals import GoalFake, seed


class RecallModel(GoalFake):
    def __init__(self, task_id: str) -> None:
        super().__init__()
        self.task_id = task_id

    async def decide(self, *, context: str, owner: str) -> GoalModelOutput:
        goal = OperationGoal.model_validate(json.loads(context)["goal"])
        calls = [
            AgentToolCall(name="find_saved_tasks", query="Older report", cursor=None),
            AgentToolCall(name="read_saved_task", task_id=self.task_id, offset=0),
            AgentToolCall(name="read_saved_task", task_id=self.task_id, offset=4000),
            AgentToolCall(name="read_saved_report", report_id="report-mana"),
        ]
        if len(goal.tools) >= len(calls):
            return await super().decide(context=context, owner=owner)
        from app.mana_operation_ai.domain.goals import GoalDecision

        return GoalModelOutput(
            GoalDecision(
                update="Read private saved context",
                plan=goal.plan,
                draft=goal.result,
                evidence_ids=[],
                disposition="continue",
                missing_information="",
                requested_capability=None,
                tool_call=calls[len(goal.tools)],
            ),
            "fake",
            5000,
        )


async def test_paged_tool_recall_revalidates_report_and_keeps_legacy_projection(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "recall.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        service.availability.max_steps = 8
        topic = await service._chats.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="History"),
        )
        old = await service.repository.create(
            "alice",
            topic,
            GoalCreate(request_id=uuid4(), objective="Older report: historical parent analysis."),
        )
        await service.repository.save(
            "alice",
            old,
            old.model_copy(
                update={"status": "completed", "result": "HEAD " + "x" * 4200 + " EXACT TAIL"}
            ),
        )
        await seed(service)
        for index in range(21):
            await seed(service, product=f"unverified-{index:02d}")
        # Bounded discovery can omit an older valid report; an exact known ID still
        # gets its product/agent checked without collecting a provider or paging it.
        assert await service._tools.reports(old) == []
        goal = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(),
                objective="Explain the older result and revalidate its source.",
                execution_mode="agent",
                max_steps=8,
            ),
        )
        service._model = RecallModel(old.goal_id)
        for _ in range(7):
            assert await service.tick()
        saved = await service.repository.get("alice", goal.goal_id)
        assert saved.status == "completed" and saved.steps_used == 7
        assert not saved.read_attempted and saved.approved_capability is None
        assert json.loads(saved.tools[0].result)["tasks"][0]["task_id"] == old.goal_id
        assert json.loads(saved.tools[1].result)["next_offset"] == 4000
        assert json.loads(saved.tools[2].result)["result"].endswith("EXACT TAIL")
        assert json.loads(saved.tools[2].result)["historical_context_only"]
        assert [item.report_id for item in saved.evidence] == ["report-mana"]
        assert json.loads(saved.tools[0].result)["historical_context_only"]
        rendered = json.loads(service._context(saved))
        assert not rendered["goal"]["tools"][1]["result_shortened"]
        async with app.state.operation_database.session_factory() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row is not None and row.workspace_payload is not None
            assert row.workspace_payload["version"] == 5
            assert row.workspace_payload["analysis_scope"] == "current"
            assert LegacyGoal.model_validate(row.payload).status == "completed"
        assert not await service.tick()
    get_settings.cache_clear()


async def test_sql_lookup_pagination_literal_query_owner_product_and_time_fences(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "pages.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        clock = Clock()
        service.repository._clock = clock
        topic = await service._chats.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Private")
        )
        ids = []
        for index in range(12):
            goal = await service.repository.create(
                "alice",
                topic,
                GoalCreate(
                    request_id=uuid4(), objective=f"Saved task {index:02d} literal % _ data."
                ),
            )
            assert await service.repository.save(
                "alice", goal, goal.model_copy(update={"status": "completed"})
            )
            ids.append(goal.goal_id)
        cutoff = clock.now() + timedelta(seconds=1)
        cursor = None
        loaded: list[str] = []
        for _ in range(3):
            page = await service.repository.find_saved_tasks(
                "alice", topic.topic_id, "mana", before=cutoff, query="", cursor=cursor
            )
            assert len(page.goals) <= 5
            loaded.extend(item.goal_id for item in page.goals)
            cursor = page.next_cursor
        assert cursor is None and len(loaded) == len(set(loaded)) == 12
        assert set(loaded) == set(ids)
        exact = await service.repository.find_saved_tasks(
            "alice", topic.topic_id, "mana", before=cutoff, query="literal % _", cursor=None
        )
        assert len(exact.goals) == 5
        assert not (
            await service.repository.find_saved_tasks(
                "alice", topic.topic_id, "mana", before=cutoff, query="SAVED", cursor=None
            )
        ).goals
        for owner, product, before in [
            ("bob", "mana", cutoff),
            ("alice", "360rec", cutoff),
            ("alice", "mana", clock.now()),
        ]:
            with pytest.raises(ChatError) as denied:
                await service.repository.saved_task(
                    owner, topic.topic_id, product, ids[0], before=before
                )
            assert denied.value.status == 404
        with pytest.raises(ChatError):
            await service.repository.find_saved_tasks(
                "bob", topic.topic_id, "mana", before=cutoff, query="", cursor=ids[0]
            )
    get_settings.cache_clear()


async def test_exact_cross_role_dedup_keeps_every_word_and_all_constraint_roles(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "exact-context.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        chats = SqlAlchemyChatRepository(
            app.state.operation_database, hourly_limit=200, daily_limit=200
        )
        await chats.initialize()
        topic = await chats.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Long")
        )
        expected = []
        for index in range(100):
            text = f"Historical task {index:03d}: never contact clients in cohort {index:03d}."
            expected.append(text)
            turn, _ = await chats.reserve(
                "alice", topic.topic_id, MessageCreate(request_id=uuid4(), message=text)
            )
            await chats.update(turn.model_copy(update={"status": "completed"}))
            task = await service.repository.create(
                "alice",
                topic,
                GoalCreate(
                    request_id=uuid4(), objective=text, success_criteria=text, constraints=text
                ),
            )
            await service.repository.save(
                "alice",
                task,
                task.model_copy(update={"status": "completed", "instructions": [text]}),
            )
        memory = await service._session_context.read(
            "alice", topic.topic_id, before=service._clock.now() + timedelta(seconds=1)
        )
        assert memory is not None and len(memory.user_context) == 100
        assert [item.text for item in memory.user_context] == expected
        assert all(item.kind == "user_message" for item in memory.user_context)
        assert sum("constraint" in item.also_kinds for item in memory.user_context) == 100
        assert all(
            set(item.also_kinds)
            == {"prior_objective", "prior_criteria", "constraint", "instruction"}
            for item in memory.user_context
        )
        request = GoalCreate(
            request_id=uuid4(),
            objective="Continue with all exact constraints.",
            execution_mode="agent",
        )
        new = await service.create(
            "alice", topic.topic_id, request, session_memory=memory, capture_session_context=False
        )
        stored = await service.repository.get("alice", new.goal_id)
        assert stored.session_memory == memory
        async with app.state.operation_database.session_factory() as session:
            row = await session.get(GoalRow, new.goal_id)
            assert row is not None and row.workspace_payload["version"] == 5
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "name,args",
    [
        ("find_saved_tasks", '{"query":"","cursor":null,"owner":"bob"}'),
        ("read_saved_task", '{"task_id":"known","offset":true}'),
        ("read_saved_task", '{"task_id":"known","offset":-1}'),
        ("read_saved_task", '{"task_id":"known","offset":16001}'),
    ],
)
def test_native_task_arguments_cannot_expand_scope(name: str, args: str) -> None:
    with pytest.raises(ValueError):
        parse_agent_function(name, args)
