"""Owner-scoped long-topic history; no paid model or external source reads."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import event, select, update

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.chat import ChatTopic, ChatTurn, MessageCreate, TopicCreate
from app.mana_operation_ai.infrastructure.persistence.chat_repository import _storage
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import ChatTurnRow
from tests.test_operation_agent_workspace import BASE, configure_workspace
from tests.test_operation_api import headers
from tests.test_operation_chat import BASE as CHAT
from tests.test_operation_chat import FakeConversation

FIRST = "Only parent activity; never use child inventories as retention denominators."


async def seed_transcript(
    database: OperationDatabase, topic: ChatTopic, *, count: int = 110, owner: str = "alice"
) -> list[ChatTurn]:
    # Tie timestamps exercise the UUID tiebreaker at page boundaries.
    start = datetime(2020, 1, 1, tzinfo=UTC)
    turns = [
        ChatTurn(
            turn_id=str(UUID(int=index + 1)),
            topic_id=topic.topic_id,
            request_id=uuid4(),
            message=FIRST if index == 0 else "Continue under the original conditions.",
            answer=f"Saved answer {index + 1}",
            status="completed",
            created_at=start + timedelta(seconds=index // 7),
        )
        for index in range(count)
    ]
    async with database.session_factory() as session, session.begin():
        session.add_all(
            [
                ChatTurnRow(
                    turn_id=turn.turn_id,
                    topic_id=topic.topic_id,
                    owner=owner,
                    request_id=str(turn.request_id),
                    status=turn.status,
                    created_at=turn.created_at,
                    **_storage(turn),
                )
                for turn in turns
            ]
        )
    return turns


async def set_saved_turn(database: OperationDatabase, turn: ChatTurn) -> None:
    async with database.session_factory() as session, session.begin():
        await session.execute(
            update(ChatTurnRow)
            .where(ChatTurnRow.turn_id == turn.turn_id)
            .values(status=turn.status, **_storage(turn))
        )


async def test_pages_are_complete_private_projected_and_read_only(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "pages.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        chats = app.state.operation_chat_service
        database = app.state.operation_database
        topic = await chats.create(
            "alice", TopicCreate(agent_id="operations-orchestrator", product="mana", title="Long")
        )
        turns = await seed_transcript(database, topic)
        # An expired active record must not be rewritten by a transcript GET.
        await set_saved_turn(database, turns[0].model_copy(update={"status": "reading"}))
        statements: list[str] = []

        def observe(*args: object) -> None:
            statements.append(str(args[2]))

        event.listen(database.engine.sync_engine, "before_cursor_execute", observe)
        try:
            result: list[str] = []
            cursor = None
            while True:
                response = await client.get(
                    f"{BASE}/topics/{topic.topic_id}/messages",
                    params={"limit": 17, **({"before": cursor} if cursor else {})},
                    headers=headers("alice", "viewer"),
                )
                assert response.status_code == 200, response.text
                page = response.json()
                assert all(turn["session_memory"] is None for turn in page["turns"])
                result[0:0] = [turn["turn_id"] for turn in page["turns"]]
                cursor = page["next_cursor"]
                if not page["has_more"]:
                    assert cursor is None
                    break
            assert result == [turn.turn_id for turn in turns]
            assert len(set(result)) == 110
            assert not any(
                statement.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))
                for statement in statements
            )
            turn_queries = [s for s in statements if "FROM operation_chat_turns" in s]
            assert turn_queries and all("session_memory" not in s for s in turn_queries)
            projected = [s for s in turn_queries if "SELECT operation_chat_turns.payload" in s]
            assert projected and all(
                "JSON_EXTRACT(operation_chat_turns.workspace_metadata" in s for s in projected
            )
        finally:
            event.remove(database.engine.sync_engine, "before_cursor_execute", observe)
        assert (await chats.repository.turn("alice", topic.topic_id, turns[0].turn_id)).status == (
            "reading"
        )
        assert (
            await client.get(
                f"{BASE}/topics/{topic.topic_id}/messages", headers=headers("bob", "viewer")
            )
        ).status_code == 404
        other = await chats.create(
            "alice", TopicCreate(agent_id="retention-agent", product="360rec", title="Other")
        )
        other_turn, _ = await chats.repository.reserve(
            "alice", other.topic_id, MessageCreate(request_id=uuid4(), message="Other")
        )
        assert (
            await client.get(
                f"{BASE}/topics/{topic.topic_id}/messages",
                params={"before": other_turn.turn_id},
                headers=headers("alice", "viewer"),
            )
        ).status_code == 404
        for limit in (0, 31):
            assert (
                await client.get(
                    f"{BASE}/topics/{topic.topic_id}/messages",
                    params={"limit": limit},
                    headers=headers("alice", "viewer"),
                )
            ).status_code == 422
    get_settings.cache_clear()


@pytest.mark.parametrize("native,paged", [(True, True), (True, False), (False, True)])
async def test_capacity_is_native_opt_in_and_complete_constraints_survive(
    monkeypatch: MonkeyPatch, tmp_path: Path, native: bool, paged: bool
) -> None:
    configure_workspace(monkeypatch, tmp_path / "capacity.db")
    monkeypatch.setenv("OPERATION_AGENT_WORKSPACE_ENABLED", str(native).lower())
    monkeypatch.setenv("OPERATION_WORKSPACE_TRANSCRIPT_ENABLED", str(paged).lower())
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        chats = app.state.operation_chat_service
        model = FakeConversation()
        chats._model = model
        topic = await chats.create(
            "alice", TopicCreate(agent_id="growth-agent", product="mana", title="Capacity")
        )
        turns = await seed_transcript(app.state.operation_database, topic, count=100)
        payload = MessageCreate(request_id=uuid4(), message="Keep the original restrictions.")
        if native and paged:
            answer = await chats.send("alice", topic.topic_id, payload)
            assert answer.status == "completed" and len(model.contexts) == 1
            memory = model.contexts[0]["session_memory"]
            assert isinstance(memory, dict)
            assert memory["user_context"][0]["text"] == FIRST
            assert model.contexts[0]["older_turns_omitted"] == 94
            recent = model.contexts[0]["history"]
            assert isinstance(recent, list) and len(recent) == 6
            assert await chats.send("alice", topic.topic_id, payload) == answer
            assert len(model.contexts) == 1
            latest = await chats.repository.turns("alice", topic.topic_id)
            assert len(latest) == 100 and latest[-1].turn_id == answer.turn_id
            assert turns[0].turn_id not in {item.turn_id for item in latest}
        else:
            with pytest.raises(ChatError, match="100 сообщений") as error:
                await chats.send("alice", topic.topic_id, payload)
            assert error.value.status == 429 and not model.contexts
            with pytest.raises(ChatError) as disabled:
                await chats.transcript("alice", topic.topic_id, before=None)
            assert disabled.value.status == 503
    get_settings.cache_clear()


async def test_addressed_reads_stop_and_analysis_work_outside_display_window(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "addressed.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        chats = app.state.operation_chat_service
        topic = await chats.create(
            "alice", TopicCreate(agent_id="growth-agent", product="mana", title="Addressed")
        )
        turns = await seed_transcript(app.state.operation_database, topic)
        first = turns[0].model_copy(update={"analysis_requested": True})
        await set_saved_turn(app.state.operation_database, first)
        state = await chats.analysis_state("alice", topic.topic_id, first.turn_id)
        assert state.state == "unconfirmed"
        await set_saved_turn(
            app.state.operation_database,
            first.model_copy(update={"execution_mode": "agent", "next_action": "approvals"}),
        )
        actions = await client.get(
            f"{BASE}/topics/{topic.topic_id}/messages/{first.turn_id}/actions",
            headers=headers("alice", "viewer"),
        )
        assert actions.status_code == 200 and actions.json()["items"] == []
        await set_saved_turn(app.state.operation_database, first)
        chats._model = FakeConversation()
        replay = await chats.send(
            "alice",
            topic.topic_id,
            MessageCreate(request_id=first.request_id, message=first.message),
        )
        assert replay.turn_id == first.turn_id and not chats._model.contexts
        # Stop is an explicit owner mutation, independent of the public page size.
        await set_saved_turn(
            app.state.operation_database, first.model_copy(update={"status": "thinking"})
        )
        stop = await client.post(
            f"{CHAT}/topics/{topic.topic_id}/messages/{first.turn_id}/stop",
            headers=headers("alice", "operator"),
            json={},
        )
        assert stop.status_code == 200 and stop.json()["status"] == "cancelled"
        async with app.state.operation_database.session_factory() as session:
            rows = (await session.scalars(select(ChatTurnRow))).all()
            assert len(rows) == 110
    get_settings.cache_clear()
