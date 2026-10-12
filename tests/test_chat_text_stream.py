"""Actual HTTP/SQL and SDK SSE decoding; no paid model or external source calls."""

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from openai import AsyncOpenAI
from pydantic import SecretStr
from pytest import MonkeyPatch
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError, ChatTurnOutput
from app.mana_operation_ai.domain.chat import ChatReply, MessageCreate, TopicCreate
from app.mana_operation_ai.domain.workspace_events import ChatTextEvent
from app.mana_operation_ai.infrastructure.chat_model import OpenAIConversationModel
from app.mana_operation_ai.infrastructure.persistence.chat_repository import (
    SqlAlchemyChatRepository,
)
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import ChatTurnRow, WorkspaceEventRow
from app.mana_operation_ai.infrastructure.persistence.workspace_events import (
    SqlAlchemyWorkspaceEvents,
)
from tests.test_operation_agent_workspace import BASE, configure_workspace
from tests.test_operation_api import headers
from tests.test_operation_chat_costs import CONTEXT, policy
from tests.test_operation_cost_ledger import Clock


class SlowStream:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = asyncio.Event()
        self.calls = 0

    async def stream_reply(
        self, *, instructions: str, context: str, owner: str
    ) -> AsyncGenerator[str | ChatTurnOutput, None]:
        self.calls += 1
        try:
            yield "Черновик 🧒"
            self.started.set()
            await self.release.wait()
            yield "Черновик 🧒 готов"
            yield ChatTurnOutput("Черновик 🧒 готов", "fake-stream", 10, 20, next_action="none")
        finally:
            self.closed.set()


async def assert_stream_atomicity(url: str) -> None:
    """Independent SQL connections, stop/preview races, recovery and bounded storage."""
    databases = [OperationDatabase(url), OperationDatabase(url)]
    repos = [
        SqlAlchemyChatRepository(db, hourly_limit=100, daily_limit=1000, stream_events_enabled=True)
        for db in databases
    ]
    await repos[0].initialize()
    owner = f"stream-{uuid4()}"
    topic = await repos[0].create(
        owner, TopicCreate(agent_id="operations-orchestrator", product="mana", title="Atomic")
    )
    events = SqlAlchemyWorkspaceEvents(databases[0])
    try:
        for _ in range(3):
            turn, _ = await repos[0].reserve(
                owner, topic.topic_id, MessageCreate(request_id=uuid4(), message="Race")
            )
            await repos[0].preview(owner, topic.topic_id, turn.turn_id, "First 🧒")
            await asyncio.gather(
                repos[0].cancel(owner, topic.topic_id, turn.turn_id),
                repos[1].preview(owner, topic.topic_id, turn.turn_id, "First 🧒 second"),
            )
            saved = await repos[1].turn(owner, topic.topic_id, turn.turn_id)
            assert saved.status == "cancelled"
            assert saved.preview in ("First 🧒", "First 🧒 second")
            assert not await repos[1].preview(
                owner, topic.topic_id, turn.turn_id, saved.preview + "!"
            )
            page = await events.notifications(owner, topic.topic_id, 0)
            journal = [
                item
                for item in page.items
                if isinstance(item, ChatTextEvent) and item.turn_id == turn.turn_id
            ]
            assert [item.revision for item in journal] == list(range(1, saved.preview_revision + 1))
            assert journal[-1].status == "cancelled" and journal[-1].final_answer == saved.answer
            assert "".join(item.delta for item in journal) == saved.preview

        turn, _ = await repos[0].reserve(
            owner, topic.topic_id, MessageCreate(request_id=uuid4(), message="Lost producer")
        )
        await repos[0].preview(owner, topic.topic_id, turn.turn_id, "Lost draft")
        async with databases[0].session_factory() as session, session.begin():
            await session.execute(
                update(ChatTurnRow)
                .where(ChatTurnRow.turn_id == turn.turn_id)
                .values(created_at=datetime.now(UTC) - timedelta(minutes=4))
            )
        next_turn, _ = await repos[1].reserve(
            owner, topic.topic_id, MessageCreate(request_id=uuid4(), message="New question")
        )
        recovered = await repos[0].turn(owner, topic.topic_id, turn.turn_id)
        assert recovered.status == "failed" and recovered.preview == "Lost draft"
        assert recovered.preview_revision == 2
        assert not await repos[0].update(
            turn.model_copy(update={"status": "completed", "answer": "Late"})
        )
        page = await events.notifications(owner, topic.topic_id, 0)
        assert page.items[-1].status == "failed"
        assert await repos[0].cancel(owner, topic.topic_id, next_turn.turn_id)

        bounded, _ = await repos[0].reserve(
            owner, topic.topic_id, MessageCreate(request_id=uuid4(), message="Bound")
        )
        for revision in range(1, 132):
            assert await repos[0].preview(owner, topic.topic_id, bounded.turn_id, "x" * revision)
        saved = await repos[0].turn(owner, topic.topic_id, bounded.turn_id)
        assert saved.preview_revision == 128 and len(saved.preview) == 128
        with pytest.raises(ChatError):
            await repos[0].preview(owner, topic.topic_id, bounded.turn_id, "y")
        with pytest.raises(ChatError):
            await repos[0].preview(owner, topic.topic_id, bounded.turn_id, "x" * 16001)
        with pytest.raises(ChatError):
            await repos[0].preview("foreign-owner", topic.topic_id, bounded.turn_id, "x")
        assert await repos[0].update(
            bounded.model_copy(update={"status": "completed", "answer": "Final"})
        )
        final = await repos[1].turn(owner, topic.topic_id, bounded.turn_id)
        assert final.preview_revision == 129 and final.answer == "Final"
    finally:
        await asyncio.gather(*(db.dispose() for db in databases))


async def test_sqlite_atomic_stop_recovery_and_storage_bounds(tmp_path: Path) -> None:
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}")
    await database.create_schema()
    await database.dispose()
    await assert_stream_atomicity(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}")


@pytest.mark.parametrize("terminal", [False, True])
async def test_chat_journal_fault_rolls_back_draft_and_terminal(
    tmp_path: Path, monkeypatch: MonkeyPatch, terminal: bool
) -> None:
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'rollback.db'}")
    await database.create_schema()
    repo = SqlAlchemyChatRepository(
        database, hourly_limit=10, daily_limit=100, stream_events_enabled=True
    )
    await repo.initialize()
    try:
        topic = await repo.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Rollback")
        )
        turn, _ = await repo.reserve(
            "alice", topic.topic_id, MessageCreate(request_id=uuid4(), message="Test")
        )
        await repo.preview("alice", topic.topic_id, turn.turn_id, "Original")
        before = await repo.turn("alice", topic.topic_id, turn.turn_id)
        events = SqlAlchemyWorkspaceEvents(database)
        journal = await events.notifications("alice", topic.topic_id, 0)
        original_add = AsyncSession.add

        def fail(session: AsyncSession, instance: object, *, _warn: bool = True) -> None:
            if isinstance(instance, WorkspaceEventRow):
                raise RuntimeError("Synthetic journal fault")
            original_add(session, instance, _warn=_warn)

        with monkeypatch.context() as patch:
            patch.setattr(AsyncSession, "add", fail)
            with pytest.raises(RuntimeError, match="Synthetic journal"):
                if terminal:
                    await repo.update(
                        before.model_copy(update={"status": "completed", "answer": "Final"})
                    )
                else:
                    await repo.preview("alice", topic.topic_id, turn.turn_id, "Original more")
        assert await repo.turn("alice", topic.topic_id, turn.turn_id) == before
        assert await events.notifications("alice", topic.topic_id, 0) == journal
    finally:
        await database.dispose()


@pytest.mark.parametrize("stop", [False, True])
async def test_durable_preview_terminal_race_replay_and_owner_scope(
    monkeypatch: MonkeyPatch, tmp_path: Path, stop: bool
) -> None:
    configure_workspace(monkeypatch, tmp_path / "stream.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_CHAT_STREAMING_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        service = app.state.operation_chat_service
        model = SlowStream()
        service._streaming_model = model
        topic = await service.create(
            "alice", TopicCreate(agent_id="operations-orchestrator", product="mana", title="Stream")
        )
        payload = MessageCreate(
            request_id=uuid4(), message="Explain the existing context.", execution_mode="agent"
        )
        job = asyncio.create_task(service.send("alice", topic.topic_id, payload, workspace=True))
        await asyncio.wait_for(model.started.wait(), 3)
        path = f"{BASE}/topics/{topic.topic_id}/notifications"
        first = await client.get(path, headers=headers("alice", "viewer"))
        assert first.status_code == 200
        page = first.json()
        assert len(page["items"]) == 1 and page["items"][0]["delta"] == "Черновик 🧒"
        assert page["items"][0]["final_answer"] is None
        turn_id = page["items"][0]["turn_id"]
        saved = await service.repository.turn("alice", topic.topic_id, turn_id)
        assert saved.status == "thinking" and saved.answer == "" and saved.preview == "Черновик 🧒"
        assert saved.next_action == "none" and not saved.analysis_requested
        assert (await client.get(path, headers=headers("bob", "viewer"))).status_code == 404
        assert (
            await app.state.operation_workspace_events.page("alice", topic.topic_id)
        ).items == []
        if stop:
            cancelled = await service.repository.cancel("alice", topic.topic_id, turn_id)
            assert cancelled.preview == "Черновик 🧒"
        model.release.set()
        final = await asyncio.wait_for(job, 3)
        assert final.status == ("cancelled" if stop else "completed")
        assert model.calls == 1 and model.closed.is_set()
        replay = await service.send("alice", topic.topic_id, payload, workspace=True)
        assert replay.turn_id == turn_id and model.calls == 1
        events = await app.state.operation_workspace_events.notifications("alice", topic.topic_id)
        assert all(isinstance(item, ChatTextEvent) for item in events.items)
        assert events.items[-1].status == final.status
        assert events.items[-1].final_answer == final.answer
        assert (
            await client.get(
                f"{BASE}/topics/{topic.topic_id}/messages", headers=headers("alice", "viewer")
            )
        ).json()["turns"][0]["preview"]
        app.state.settings = app.state.settings.model_copy(
            update={
                "operation_workspace_stream_seconds": 0.02,
                "operation_workspace_event_poll_seconds": 0.001,
            }
        )
        stream_path = f"{BASE}/topics/{topic.topic_id}/stream"
        wire = await client.get(stream_path, headers=headers("alice", "viewer"))
        assert "event: chat_text" in wire.text and "event: workspace" not in wire.text
        frames = [
            json.loads(line[6:])
            for line in wire.text.splitlines()
            if line.startswith("data: ") and line != "data: {}"
        ]
        assert frames == [item.model_dump(mode="json") for item in events.items]
        resumed = await client.get(
            stream_path,
            headers={**headers("alice", "viewer"), "Last-Event-ID": str(events.items[-1].event_id)},
        )
        assert "event: chat_text" not in resumed.text and model.calls == 1
        assert (await client.get(stream_path, headers=headers("bob", "viewer"))).status_code == 404
    get_settings.cache_clear()


@pytest.mark.parametrize("failure", [None, "invalid", "incomplete", "unknown_model", "cut"])
async def test_sdk_stream_usage_before_parse_and_unknown_receipts(
    tmp_path: Path, failure: str | None
) -> None:
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'sdk.db'}")
    await database.create_schema()
    ledger = SqlAlchemyCostLedger(database, clock=Clock(), limits=policy())
    settings = Settings(
        _env_file=None, openai_api_key=SecretStr("fake-key"), openai_model="gpt-5.4-nano"
    )
    model = OpenAIConversationModel(settings, ledger=ledger)
    reply = ChatReply(answer="Привет 🧒!", plan=[], next_action="none").model_dump_json()
    text = (
        '{"answer":"Привет 🧒!", "plan":[], "next_action":"invalid"}'
        if failure == "invalid"
        else reply
    )
    final = {
        "id": "resp_fake",
        "object": "response",
        "created_at": 0,
        "status": "incomplete" if failure == "incomplete" else "completed",
        "model": "wrong-model" if failure == "unknown_model" else settings.openai_model,
        "service_tier": "default",
        "output": [],
        "usage": {
            "input_tokens": 200,
            "output_tokens": 100,
            "input_tokens_details": {"cached_tokens": 40, "cache_write_tokens": 30},
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 300,
        },
    }
    events = [
        {
            "type": "response.output_text.delta",
            "sequence_number": 1,
            "content_index": 0,
            "output_index": 0,
            "item_id": "msg_fake",
            "delta": text,
        }
    ]
    if failure != "cut":
        events.append(
            {
                "type": "response.incomplete" if failure == "incomplete" else "response.completed",
                "sequence_number": 2,
                "response": final,
            }
        )
    wire = "".join(f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events)
    requests = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200, headers={"Content-Type": "text/event-stream"}, content=wire.encode()
        )

    await model._client.close()
    model._client = AsyncOpenAI(
        api_key="fake-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    try:
        if failure:
            with pytest.raises((RuntimeError, ValueError)):
                _ = [
                    item
                    async for item in model.stream_reply(
                        instructions="Test", context=CONTEXT, owner="alice"
                    )
                ]
        else:
            output = [
                item
                async for item in model.stream_reply(
                    instructions="Test", context=CONTEXT, owner="alice"
                )
            ]
            assert output[0] == "Привет 🧒!" and isinstance(output[-1], ChatTurnOutput)
            assert output[-1].answer == "Привет 🧒!"
        assert len(requests) == 1 and requests[0]["stream"] and not requests[0]["store"]
        assert requests[0]["text"]["format"]["strict"]
        usage = (await ledger.periods())[0].usage
        assert usage.llm_calls == 1
        assert (
            usage.llm_microusd == 158
            if failure in (None, "invalid", "incomplete")
            else usage.llm_microusd > 158
        )
    finally:
        await model.close()
        await database.dispose()
