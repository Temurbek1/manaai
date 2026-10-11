"""Real SQL and authenticated SSE; no paid models or external source reads."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.api.workspace_stream import BoundedWorkspaceStream
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.workspace_events import WorkspaceEventService
from app.mana_operation_ai.domain.chat import TopicCreate
from app.mana_operation_ai.domain.goals import GoalCommand, GoalCreate
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.workspace_events import (
    SqlAlchemyWorkspaceEvents,
)
from tests.test_operation_agent_workspace import ToolModel, configure_workspace
from tests.test_operation_api import headers
from tests.test_operation_goals import seed

BASE = "/api/v1/admin/operation/workspace"


async def test_journal_pagination_and_idempotent_control(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "pages.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        goals = app.state.operation_goal_service
        topic = await goals._chats.create(
            "owner", TopicCreate(agent_id="retention-agent", product="mana", title="Pages")
        )
        goal = await goals.create(
            "owner", topic.topic_id, GoalCreate(request_id=uuid4(), objective="Never execute.")
        )
        for index in range(52):
            command = GoalCommand(
                request_id=uuid4(),
                command="pause" if index % 2 == 0 else "resume",
                expected_revision=goal.revision,
            )
            goal = await goals.command("owner", goal.goal_id, command)
            assert await goals.command("owner", goal.goal_id, command) == goal
        events = app.state.operation_workspace_events
        first = await events.page("owner", topic.topic_id)
        assert len(first.items) == 50 and first.has_more
        second = await events.page("owner", topic.topic_id, first.next_cursor)
        assert len(second.items) == 3 and not second.has_more
        assert [event.revision for event in first.items + second.items] == list(range(53))
        assert (await goals.repository.get("owner", goal.goal_id)).steps_used == 0
    get_settings.cache_clear()


async def test_stream_slots_expire_and_backpressure_releases_lease(
    monkeypatch: MonkeyPatch,
) -> None:
    repository = AsyncMock()
    service = WorkspaceEventService(repository, enabled=True, max_connections=2)
    now = 100.0
    monkeypatch.setattr("app.mana_operation_ai.application.workspace_events.monotonic", lambda: now)
    first = await service.acquire("alice", 15)
    await service.acquire("bob", 15)
    with pytest.raises(ChatError) as full:
        await service.acquire("charlie", 15)
    assert full.value.status == 429
    now += 21
    lease = await service.acquire("charlie", 15)
    await service.release(first)
    assert len(service._connections) == 1

    async def content() -> AsyncIterator[str]:
        yield ": connected\n\n"

    async def blocked_send(message: object) -> None:
        await anyio.sleep_forever()

    # Shorten only this synthetic transport deadline, not validated application settings.
    response = BoundedWorkspaceStream(content(), service, lease, -4.98)
    await response({"type": "http", "asgi": {"spec_version": "2.4"}}, AsyncMock(), blocked_send)
    assert not service._connections
    repository.page.assert_not_called()


async def test_journal_replay_scope_revision_fence_and_restart(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "events.db"
    configure_workspace(monkeypatch, path)
    app = create_app()
    async with app.router.lifespan_context(app):
        goals = app.state.operation_goal_service
        goals._model = ToolModel()
        await seed(goals)
        topic = await goals._chats.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Progress"),
        )
        request = GoalCreate(
            request_id=uuid4(), objective="Inspect synthetic sources.", execution_mode="agent"
        )
        goal = await goals.create("alice", topic.topic_id, request)
        events = app.state.operation_workspace_events
        initial = await events.page("alice", topic.topic_id)
        assert len(initial.items) == 1 and initial.items[0].revision == 0
        assert (await goals.create("alice", topic.topic_id, request)).goal_id == goal.goal_id
        assert await events.page("alice", topic.topic_id) == initial
        for _ in range(5):
            assert await goals.tick()
        page = await events.page("alice", topic.topic_id)
        assert page.items[-1].status == "completed" and page.items[-1].phase == "review"
        assert any(tool.status == "started" for event in page.items for tool in event.tools)
        assert any(tool.status == "completed" for event in page.items for tool in event.tools)
        assert [event.revision for event in page.items] == sorted(
            {event.revision for event in page.items}
        )
        assert all(
            event.goal_id == goal.goal_id and event.topic_id == topic.topic_id
            for event in page.items
        )
        assert all("session_memory" not in event.model_dump() for event in page.items)
        assert all(
            "result" not in tool.model_dump() for event in page.items for tool in event.tools
        )
        assert (
            await events.page("alice", topic.topic_id, initial.next_cursor)
        ).items == page.items[1:]
        assert (await events.page("alice", topic.topic_id, page.next_cursor)).items == []
        with pytest.raises(ChatError) as forbidden:
            await events.page("bob", topic.topic_id)
        assert forbidden.value.status == 404
        other = await goals._chats.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="360rec", title="Other"),
        )
        assert (await events.page("alice", other.topic_id)).items == []
        with pytest.raises(ChatError) as invalid:
            await events.page("alice", topic.topic_id, page.next_cursor + 1)
        assert invalid.value.status == 409
        saved = await goals.repository.get("alice", goal.goal_id)
        assert not await goals.repository.save("alice", goal, saved)
        assert await events.page("alice", topic.topic_id) == page
        tip = page.next_cursor
    restarted = OperationDatabase(f"sqlite+aiosqlite:///{path}")
    try:
        recovered = await SqlAlchemyWorkspaceEvents(restarted).page("alice", topic.topic_id, tip)
        assert recovered.items == [] and recovered.next_cursor == tip
    finally:
        await restarted.dispose()
        get_settings.cache_clear()


async def test_event_failure_rolls_back_state(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    configure_workspace(monkeypatch, tmp_path / "atomic.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        goals = app.state.operation_goal_service
        topic = await goals._chats.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Atomic")
        )
        goal = await goals.create(
            "alice",
            topic.topic_id,
            GoalCreate(request_id=uuid4(), objective="Preserve atomic state."),
        )
        before = await app.state.operation_workspace_events.page("alice", topic.topic_id)

        def fail(*args: object) -> None:
            raise RuntimeError("Synthetic journal fault")

        monkeypatch.setattr(
            "app.mana_operation_ai.infrastructure.persistence.goal_repository.append_goal_event",
            fail,
        )
        with pytest.raises(RuntimeError, match="Synthetic"):
            await goals.repository.save(
                "alice", goal, goal.model_copy(update={"status": "completed"})
            )
        assert await goals.repository.get("alice", goal.goal_id) == goal
        assert await app.state.operation_workspace_events.page("alice", topic.topic_id) == before
    get_settings.cache_clear()


async def test_sse_resume_limits_and_no_execution(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    configure_workspace(monkeypatch, tmp_path / "http.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        goals = app.state.operation_goal_service
        fake = ToolModel()
        goals._model = fake
        topic = await goals._chats.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Stream")
        )
        goal = await goals.create(
            "alice",
            topic.topic_id,
            GoalCreate(request_id=uuid4(), objective="A task not yet executed."),
        )
        await goals.command(
            "alice",
            goal.goal_id,
            GoalCommand(request_id=uuid4(), command="pause", expected_revision=goal.revision),
        )
        app.state.settings = app.state.settings.model_copy(
            update={
                "operation_workspace_stream_seconds": 0.02,
                "operation_workspace_event_poll_seconds": 0.001,
            }
        )
        h = headers("alice", "viewer")
        url = f"{BASE}/topics/{topic.topic_id}"
        page = (await client.get(f"{url}/events", headers=h)).json()
        response = await client.get(f"{url}/stream", headers=h)
        assert response.status_code == 200 and response.headers["X-Accel-Buffering"] == "no"
        assert response.headers["Cache-Control"] == "no-store, no-transform"
        frames = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and line != "data: {}"
        ]
        assert frames == page["items"]
        resume = await client.get(
            f"{url}/stream", headers={**h, "Last-Event-ID": str(page["items"][0]["event_id"])}
        )
        assert f"id: {page['items'][0]['event_id']}\n" not in resume.text
        assert "event: reconnect" in resume.text
        for bad in ("-1", "nonsense", "9007199254740992"):
            assert (
                await client.get(f"{url}/stream", headers={**h, "Last-Event-ID": bad})
            ).status_code == 400
        assert (await client.get(f"{url}/events?after=-1", headers=h)).status_code == 422
        assert (
            await client.get(f"{url}/stream", headers=headers("bob", "admin"))
        ).status_code == 404
        service = app.state.operation_workspace_events
        leases = [await service.acquire("alice", 30) for _ in range(3)]
        assert (await client.get(f"{url}/stream", headers=h)).status_code == 429
        for lease in leases:
            await service.release(lease)
        assert fake.contexts == []
        assert (await goals.repository.get("alice", goal.goal_id)).status == "paused"
        service.enabled = False
        assert (await client.get(f"{url}/stream", headers=h)).status_code == 404
    get_settings.cache_clear()


async def test_auth_rechecked_before_batch(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    configure_workspace(monkeypatch, tmp_path / "revoked.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        topic = await app.state.operation_chat_service.repository.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Revoked")
        )
        from fastapi import HTTPException

        revoked = AsyncMock(side_effect=HTTPException(401, "Synthetic revoked identity"))
        monkeypatch.setattr("app.mana_operation_ai.api.workspace_stream.recheck_actor", revoked)
        response = await client.get(
            f"{BASE}/topics/{topic.topic_id}/stream", headers=headers("alice", "viewer")
        )
        assert "event: access_revoked" in response.text and "Synthetic revoked" not in response.text
        assert app.state.operation_workspace_events._connections == {}
    get_settings.cache_clear()
