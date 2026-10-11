"""Private SQL continuation tests; no paid model or external data reads."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import JsonValue
from pytest import MonkeyPatch
from sqlalchemy import select

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError, SessionContextTooLarge
from app.mana_operation_ai.application.chat_service import _bounded_context
from app.mana_operation_ai.application.session_context import (
    OperationSessionContext,
    session_memory_payload,
)
from app.mana_operation_ai.domain.chat import MessageCreate, TopicCreate
from app.mana_operation_ai.domain.goals import GoalCreate, GoalEvidence
from app.mana_operation_ai.domain.session import (
    SessionCheckpoint,
    SessionEvidenceReference,
    SessionMemory,
    SessionUserContext,
)
from app.mana_operation_ai.infrastructure.persistence.chat_repository import (
    SqlAlchemyChatRepository,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import GoalRow
from tests.test_operation_agent_workspace import (
    BASE,
    ToolModel,
    WorkspaceConversation,
    configure_workspace,
)
from tests.test_operation_api import headers
from tests.test_operation_chat import BASE as CHAT
from tests.test_operation_chat import FakeConversation
from tests.test_operation_cost_ledger import Clock
from tests.test_operation_goals import seed


async def test_completed_analysis_continues_in_chat_and_next_goal_survives_restart(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "continuation.db"
    configure_workspace(monkeypatch, path)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        chats = app.state.operation_chat_service
        goals = app.state.operation_goal_service
        router = WorkspaceConversation()
        chats._model = router
        goals._model = ToolModel()
        await seed(goals)
        topic = await chats.repository.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Удержание"),
        )
        h = headers("alice", "operator")
        first = await client.post(
            f"{BASE}/topics/{topic.topic_id}/messages",
            headers=h,
            json={
                "request_id": str(uuid4()),
                "message": "Проанализируй удержание родителей MANA. Не контактируй с клиентами.",
                "execution_mode": "agent",
            },
        )
        assert first.status_code == 200, first.text
        first_id = first.json()["goal"]["goal_id"]
        assert first.json()["turn"]["session_memory"] is None
        assert first.json()["goal"]["session_memory"] is None
        for _ in range(5):
            assert await goals.tick()
        prior = await goals.repository.get("alice", first_id)
        assert prior.status == "completed"

        discussion = FakeConversation()
        chats._model = discussion
        followup_request = {
            "request_id": str(uuid4()),
            "message": "Объясни подробнее второй вывод.",
        }
        followup = await client.post(
            f"{CHAT}/topics/{topic.topic_id}/messages", headers=h, json=followup_request
        )
        assert followup.status_code == 200, followup.text
        memory = SessionMemory.model_validate(discussion.contexts[0]["session_memory"])
        assert memory.topic_id == topic.topic_id and memory.product == "mana"
        assert memory.checkpoints[0].goal_id == first_id
        assert memory.checkpoints[0].result == prior.result
        assert memory.checkpoints[0].sources[0].report_id == "report-mana"
        assert any("Не контактируй" in record.text for record in memory.user_context)
        assert len(await goals.list_goals("alice", topic.topic_id)) == 1
        assert not await goals.tick()
        assert followup.json()["analysis_requested"] is False

        chats._model = router
        request = {
            "request_id": str(uuid4()),
            "message": "Составь следующий анализ по тем же ограничениям.",
            "execution_mode": "agent",
        }
        next_response = await client.post(
            f"{BASE}/topics/{topic.topic_id}/messages", headers=h, json=request
        )
        assert next_response.status_code == 200, next_response.text
        next_goal = await goals.repository.get("alice", next_response.json()["goal"]["goal_id"])
        assert next_goal.session_memory is not None
        assert next_goal.session_memory.checkpoints[0].goal_id == first_id
        assert next_goal.evidence == [] and next_goal.tools == []
        assert next_goal.approved_capability is None and not next_goal.read_attempted
        assert next_goal.accounted_microusd == 0 and next_goal.steps_used == 0
        frozen = next_goal.session_memory.model_dump(mode="json")
        assert next_response.json()["turn"]["session_memory"] == frozen
        replay = await client.post(
            f"{BASE}/topics/{topic.topic_id}/messages", headers=h, json=request
        )
        assert replay.json() == next_response.json()
        assert len(router.contexts) == 2
        assert (
            await client.post(
                f"{CHAT}/topics/{topic.topic_id}/messages",
                headers=headers("bob", "admin"),
                json={"request_id": str(uuid4()), "message": "Чужая история"},
            )
        ).status_code == 404
        next_id = next_goal.goal_id

    restarted = OperationDatabase(f"sqlite+aiosqlite:///{path}")
    try:
        restored = await SqlAlchemyGoalRepository(restarted, Clock()).get("alice", next_id)
        assert restored.session_memory is not None
        assert restored.session_memory.model_dump(mode="json") == frozen
    finally:
        await restarted.dispose()
        get_settings.cache_clear()


async def test_context_is_owner_topic_product_and_time_scoped(tmp_path: Path) -> None:
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'scope.db'}")
    await database.create_schema()
    clock = Clock(datetime.now(UTC) + timedelta(days=1))
    chats = SqlAlchemyChatRepository(database, hourly_limit=50, daily_limit=200)
    await chats.initialize()
    goals = SqlAlchemyGoalRepository(database, clock)
    reader = OperationSessionContext(chats, goals)
    try:
        topic = await chats.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="MANA")
        )
        other = await chats.create(
            "alice", TopicCreate(agent_id="retention-agent", product="360rec", title="360REC")
        )
        turn, _ = await chats.reserve(
            "alice",
            topic.topic_id,
            MessageCreate(request_id=uuid4(), message="Keep all constraints."),
        )
        assert await chats.update(turn.model_copy(update={"status": "failed"}))
        goal = await goals.create(
            "alice",
            topic,
            GoalCreate(
                request_id=uuid4(), objective="Prior task", constraints="No client contact."
            ),
        )
        changed = goal.model_copy(
            update={
                "status": "cancelled",
                "result": "Partial draft " + "x" * 2100,
                "instructions": ["Keep all constraints.", "No payment claims."],
                "evidence": [
                    GoalEvidence(
                        report_id="mana-report",
                        capability_key="retention.engagement.analyze",
                        product="mana",
                        collected_at=None,
                        fresh_until=None,
                        refresh_status="unknown",
                        summary="Minimized synthetic evidence",
                        limitations=["Synthetic only; payments unavailable."],
                        shortened=True,
                    )
                ],
            }
        )
        assert await goals.save("alice", goal, changed)
        earlier = await reader.read("alice", topic.topic_id, before=clock.now())
        assert earlier is not None and earlier.checkpoints == []
        # A completion exactly at/after this turn's snapshot cannot leak backwards.
        before = clock.now() + timedelta(seconds=1)
        memory = await reader.read("alice", topic.topic_id, before=before)
        assert memory is not None
        assert memory.checkpoints[0].status == "cancelled"
        assert memory.checkpoints[0].sources[0].limitations == [
            "Synthetic only; payments unavailable."
        ]
        assert memory.checkpoints[0].sources[0].shortened
        assert memory.checkpoints[0].result_shortened and len(memory.checkpoints[0].result) == 2000
        assert any(item.text == "No client contact." for item in memory.user_context)
        assert any(
            item.kind == "user_message" and item.text == turn.message
            for item in memory.user_context
        )
        assert await reader.read("alice", other.topic_id, before=before) is None
        with pytest.raises(ChatError, match="Тема не найдена"):
            await reader.read("bob", topic.topic_id, before=before)
        # Defensive rejection of corrupted cross-product history in the same SQL topic.
        latest = await goals.get("alice", goal.goal_id)
        assert await goals.save("alice", latest, latest.model_copy(update={"product": "360rec"}))
        filtered = await reader.read("alice", topic.topic_id, before=before)
        assert filtered is not None and filtered.checkpoints == []
        assert [item.text for item in filtered.user_context] == [turn.message]
    finally:
        await database.dispose()


@pytest.mark.parametrize("state", ["fresh", "expired", "missing", "naive", "future", "reversed"])
def test_history_freshness_is_recomputed_without_mutating_checkpoint(state: str) -> None:
    now = datetime.now(UTC)
    collected: datetime | None = now - timedelta(hours=1)
    expires: datetime | None = now + timedelta(hours=5)
    if state == "expired":
        expires = now - timedelta(minutes=10)
    elif state == "missing":
        collected = None
    elif state == "naive":
        expires = now.replace(tzinfo=None)
    elif state == "future":
        collected = now + timedelta(hours=1)
    elif state == "reversed":
        expires = now - timedelta(hours=2)
    memory = SessionMemory(
        topic_id="topic",
        product="mana",
        captured_at=now,
        checkpoints=[
            SessionCheckpoint(
                goal_id="goal",
                status="completed",
                updated_at=now,
                result="Prior analysis",
                sources=[
                    SessionEvidenceReference(
                        report_id="report",
                        capability_key="retention.engagement.analyze",
                        product="mana",
                        collected_at=collected,
                        fresh_until=expires,
                        refresh_status="live",
                    )
                ],
            )
        ],
    )
    rendered = SessionMemory.model_validate(session_memory_payload(memory, now=now))
    assert rendered.checkpoints[0].sources[0].refresh_status == (
        "live" if state == "fresh" else "stale" if state == "expired" else "unknown"
    )
    assert memory.checkpoints[0].sources[0].refresh_status == "live"


def test_context_bound_shortens_only_labelled_results_not_user_constraints() -> None:
    now = datetime.now(UTC)
    text = "Never contact clients or treat tariffs as payments."
    memory = SessionMemory(
        topic_id="topic",
        product="mana",
        captured_at=now,
        user_context=[SessionUserContext(kind="constraint", text=text, origin_id="original")],
        checkpoints=[
            SessionCheckpoint(
                goal_id="goal",
                status="completed",
                updated_at=now,
                result="x" * 2000,
            )
        ],
    )
    payload = cast(
        dict[str, JsonValue],
        {
            "history": [],
            "saved_reports": [],
            "message": "Explain the previous analysis",
            "session_memory": memory.model_dump(mode="json"),
        },
    )
    bounded = json.loads(_bounded_context(payload, maximum_bytes=1200))
    assert bounded["session_memory"]["user_context"][0]["text"] == text
    assert bounded["session_memory"]["checkpoints"][0]["result_shortened"] is True
    assert memory.checkpoints[0].result_shortened is False
    oversized = memory.model_copy(deep=True)
    oversized.user_context = [
        SessionUserContext(kind="constraint", text="я" * 6000, origin_id="original")
    ]
    payload["session_memory"] = cast(JsonValue, oversized.model_dump(mode="json"))
    with pytest.raises(SessionContextTooLarge):
        _bounded_context(payload, maximum_bytes=8192)


async def test_oversized_context_preserves_messages_and_calls_no_model(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "oversized.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_chat_service
        model = FakeConversation()
        service._model = model
        topic = await service.repository.create(
            "alice", TopicCreate(agent_id="growth-agent", product="mana", title="Full context")
        )
        for index in range(5):
            turn, _ = await service.repository.reserve(
                "alice",
                topic.topic_id,
                MessageCreate(request_id=uuid4(), message=f"{index}: " + "я" * 4000),
            )
            assert await service.repository.update(turn.model_copy(update={"status": "completed"}))
        result = await service.send(
            "alice", topic.topic_id, MessageCreate(request_id=uuid4(), message="Continue")
        )
        assert result.status == "failed" and "Ограничения не сокращались" in result.answer
        assert model.contexts == []
        history = await service.repository.turns("alice", topic.topic_id)
        assert len(history) == 6 and all(len(item.message) > 4000 for item in history[:5])
    get_settings.cache_clear()


async def test_old_request_replay_bypasses_context_rebuild_beyond_history_page(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "long-history.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        topic = await service._chats.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Old request")
        )
        original = GoalCreate(request_id=uuid4(), objective="The original user objective.")
        first = await service.create("alice", topic.topic_id, original)
        assert await service.repository.save(
            "alice", first, first.model_copy(update={"status": "completed"})
        )
        for index in range(100):
            goal = await service.repository.create(
                "alice", topic, GoalCreate(request_id=uuid4(), objective=f"Later task {index:03d}.")
            )
            assert await service.repository.save(
                "alice", goal, goal.model_copy(update={"status": "completed"})
            )
        assert first.goal_id not in {
            item.goal_id for item in await service.repository.list("alice", topic.topic_id)
        }
        assert service._session_context is not None
        from unittest.mock import AsyncMock

        forbidden_read = AsyncMock(side_effect=AssertionError("Replay must not rebuild context"))
        monkeypatch.setattr(service._session_context, "read", forbidden_read)
        replay = await service.create("alice", topic.topic_id, original)
        assert replay.goal_id == first.goal_id and replay.session_memory is None
        forbidden_read.assert_not_called()
        assert await service.repository.find_request("bob", str(original.request_id)) is None
    get_settings.cache_clear()


@pytest.mark.parametrize("corruption", ["version", "topic", "product"])
async def test_corrupt_memory_protocol_or_scope_fails_closed(
    tmp_path: Path, corruption: str
) -> None:
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'protocol.db'}")
    await database.create_schema()
    clock = Clock()
    chats = SqlAlchemyChatRepository(database, hourly_limit=20, daily_limit=200)
    await chats.initialize()
    repository = SqlAlchemyGoalRepository(database, clock)
    try:
        topic = await chats.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Protocol")
        )
        memory = SessionMemory(topic_id=topic.topic_id, product="mana", captured_at=clock.now())
        goal = await repository.create(
            "alice",
            topic,
            GoalCreate(request_id=uuid4(), objective="Private synthetic objective."),
            session_memory=memory,
        )
        async with database.session_factory() as session, session.begin():
            row = await session.scalar(select(GoalRow).where(GoalRow.goal_id == goal.goal_id))
            assert row is not None and row.workspace_payload is not None
            payload = json.loads(json.dumps(row.workspace_payload))
            if corruption == "version":
                payload["version"] = 1
            else:
                payload["goal"]["session_memory"][
                    "topic_id" if corruption == "topic" else "product"
                ] = "foreign-topic" if corruption == "topic" else "360rec"
            row.workspace_payload = payload
        with pytest.raises(ChatError) as failure:
            await repository.get("alice", goal.goal_id)
        assert failure.value.status == 503 and "Private" not in str(failure.value)
    finally:
        await database.dispose()
