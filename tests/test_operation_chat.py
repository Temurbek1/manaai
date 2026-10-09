import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import update

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput
from app.mana_operation_ai.application.chat_service import OperationChatService
from app.mana_operation_ai.domain.chat import ChatReply, MessageCreate, TopicCreate
from app.mana_operation_ai.infrastructure.chat_model import OpenAIConversationModel
from app.mana_operation_ai.infrastructure.persistence.models import ChatTurnRow
from tests.test_operation_api import configure_operation_env, headers

BASE = "/api/v1/admin/operation/chat"


class FakeConversation:
    def __init__(self) -> None:
        self.contexts: list[dict[str, object]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.fail = False
        self.suggest_analysis = False

    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        assert "NO execution tools" in instructions
        assert owner
        self.contexts.append(json.loads(context))
        self.started.set()
        await self.release.wait()
        if self.fail:
            raise RuntimeError("SECRET upstream body")
        return ChatTurnOutput(
            "Проверил контекст. Данных пока недостаточно.",
            "fake-model",
            12,
            8,
            plan=["Проверить отчёт"],
            next_action="analyze" if self.suggest_analysis else "none",
        )


async def test_conversation_provider_is_bounded_and_does_not_store_data(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "chat.db")
    gateway = OpenAIConversationModel(get_settings())
    fake_parse = AsyncMock(
        return_value=SimpleNamespace(
            status="completed",
            model="fake-model",
            output_parsed=ChatReply(answer="Уточните период.", plan=[], next_action="none"),
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )
    )
    monkeypatch.setattr(gateway._client.responses, "parse", fake_parse)
    try:
        output = await gateway.reply(
            instructions="Test", context="No real data", owner="private-owner"
        )
        assert output.answer == "Уточните период."
        assert gateway._client.max_retries == 0
        kwargs = fake_parse.call_args.kwargs
        assert kwargs["store"] is False
        assert kwargs["max_output_tokens"] <= 2048
        assert kwargs["safety_identifier"] != "private-owner"
        assert "tools" not in kwargs
        assert fake_parse.call_count == 1
    finally:
        await gateway.close()
    get_settings.cache_clear()


async def test_private_topics_idempotency_context_and_no_external_reads(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "chat.db")
    app = create_app()
    model = FakeConversation()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        service: OperationChatService = app.state.operation_chat_service
        service._model = model
        h = headers("alice", "viewer")
        created = await client.post(
            f"{BASE}/topics",
            headers=h,
            json={
                "agent_id": "growth-agent",
                "product": "mana",
                "title": "Рост регистраций",
            },
        )
        assert created.status_code == 201
        topic_id = created.json()["topic_id"]
        url = f"{BASE}/topics/{topic_id}"
        assert (await client.get(url, headers=headers("bob", "admin"))).status_code == 404
        assert (await client.get(f"{BASE}/topics", headers=headers("bob", "admin"))).json() == []
        payload = {"request_id": str(uuid4()), "message": "Что известно о MANA?"}
        first = await client.post(f"{url}/messages", headers=h, json=payload)
        assert first.status_code == 200
        assert first.json()["status"] == "completed"
        replay = await client.post(f"{url}/messages", headers=h, json=payload)
        assert replay.json() == first.json()
        assert len(model.contexts) == 1
        conflict = await client.post(
            f"{url}/messages", headers=h, json={**payload, "message": "Другое"}
        )
        assert conflict.status_code == 409
        assert (
            await client.post(
                f"{url}/messages", headers=h, json={"request_id": str(uuid4()), "message": "  "}
            )
        ).status_code == 422
        await client.post(
            f"{url}/messages", headers=h, json={"request_id": str(uuid4()), "message": "Продолжи"}
        )
        assert "scope_verified" not in model.contexts[-1]
        assert json.loads(json.dumps(model.contexts[-1]))["topic"]["product"] == "mana"
        assert "Что известно о MANA?" in str(model.contexts[-1]["history"])
        assert model.contexts[-1]["saved_reports"] == []
        runs = await client.get("/api/v1/admin/operation/runs", headers=h)
        assert runs.json()["total"] == 0
        detail = (await client.get(url, headers=h)).json()
        assert len(detail["turns"]) == 2
        assert detail["topic"]["product"] == "mana"
        # A different product topic never receives the first topic's history.
        other = (
            await client.post(
                f"{BASE}/topics",
                headers=h,
                json={
                    "agent_id": "retention-agent",
                    "product": "360rec",
                    "title": "Другой продукт",
                },
            )
        ).json()
        await client.post(
            f"{BASE}/topics/{other['topic_id']}/messages",
            headers=h,
            json={"request_id": str(uuid4()), "message": "Помоги"},
        )
        assert model.contexts[-1]["history"] == []
    get_settings.cache_clear()


async def test_concurrent_admission_stop_and_provider_failure(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "chat.db")
    app = create_app()
    model = FakeConversation()
    model.release.clear()
    async with app.router.lifespan_context(app):
        service: OperationChatService = app.state.operation_chat_service
        service._model = model
        topic = await service.create(
            "alice", TopicCreate(agent_id="technical-agent", product="mana", title="Тема")
        )
        payload = MessageCreate(request_id=uuid4(), message="Помоги описать проблему")
        task = asyncio.create_task(service.send("alice", topic.topic_id, payload))
        await asyncio.wait_for(model.started.wait(), timeout=5)
        replay = await service.send("alice", topic.topic_id, payload)
        assert replay.status == "thinking"
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            blocked = await client.post(
                f"{BASE}/topics/{topic.topic_id}/messages",
                headers=headers("alice", "viewer"),
                json={"request_id": str(uuid4()), "message": "Второй запрос"},
            )
            assert blocked.status_code == 409
            foreign_stop = await client.post(
                f"{BASE}/topics/{topic.topic_id}/messages/{replay.turn_id}/stop",
                headers=headers("bob", "admin"),
                json={},
            )
            assert foreign_stop.status_code == 404
        await service.repository.cancel("alice", topic.topic_id, replay.turn_id)
        model.release.set()
        assert (await task).status == "cancelled"
        assert len(model.contexts) == 1
        model.fail = True
        failed = await service.send(
            "alice", topic.topic_id, MessageCreate(request_id=uuid4(), message="Попробуем снова")
        )
        assert failed.status == "failed"
        assert "SECRET" not in failed.answer
    get_settings.cache_clear()


async def test_budget_and_interrupted_turn_recovery(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "chat.db")
    monkeypatch.setenv("OPERATION_CHAT_HOURLY_LIMIT", "1")
    monkeypatch.setenv("OPERATION_CHAT_DAILY_LIMIT", "1")
    get_settings.cache_clear()
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        service: OperationChatService = app.state.operation_chat_service
        model = FakeConversation()
        service._model = model
        topic = await service.create(
            "alice", TopicCreate(agent_id="growth-agent", product="mana", title="Тема")
        )
        turn, _ = await service.repository.reserve(
            "alice", topic.topic_id, MessageCreate(request_id=uuid4(), message="Прерванный запрос")
        )
        async with app.state.operation_database.session_factory.begin() as session:
            await session.execute(
                update(ChatTurnRow)
                .where(ChatTurnRow.turn_id == turn.turn_id)
                .values(created_at=datetime.now(UTC) - timedelta(minutes=4))
            )
        detail = await service.detail("alice", topic.topic_id)
        assert detail.turns[0].status == "failed"
        assert model.contexts == []
        denied = await client.post(
            f"{BASE}/topics/{topic.topic_id}/messages",
            headers=headers("alice", "viewer"),
            json={"request_id": str(uuid4()), "message": "Ещё"},
        )
        assert denied.status_code == 429
        other = await service.create(
            "bob", TopicCreate(agent_id="growth-agent", product="mana", title="Тема")
        )
        denied_global = await client.post(
            f"{BASE}/topics/{other.topic_id}/messages",
            headers=headers("bob", "viewer"),
            json={"request_id": str(uuid4()), "message": "Ещё"},
        )
        assert denied_global.status_code == 429
    get_settings.cache_clear()


async def test_explicit_analysis_rbac_confirmation_and_replay(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "chat.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        service: OperationChatService = app.state.operation_chat_service
        topic = await service.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Тема")
        )
        url = f"{BASE}/topics/{topic.topic_id}/analysis"
        payload = {"request_id": str(uuid4()), "confirmed": True}
        assert (
            await client.post(url, headers=headers("alice", "viewer"), json=payload)
        ).status_code == 403
        assert (
            await client.post(
                url, headers=headers("alice", "operator"), json={**payload, "confirmed": False}
            )
        ).status_code == 422
        first = await client.post(url, headers=headers("alice", "operator"), json=payload)
        assert first.status_code == 202, first.text
        again = await client.post(url, headers=headers("alice", "operator"), json=payload)
        assert again.json() == first.json()
        runs = await client.get("/api/v1/admin/operation/runs", headers=headers("alice", "viewer"))
        assert runs.json()["total"] == 1
        result = await client.get(
            f"{url}/{first.json()['turn_id']}", headers=headers("alice", "viewer")
        )
        assert result.status_code == 200
        assert result.json()["state"] == "completed", result.text
        assert result.json()["run_id"]
        planned = await service.create(
            "alice", TopicCreate(agent_id="technical-agent", product="mana", title="Тема")
        )
        assert (
            await client.post(
                f"{BASE}/topics/{planned.topic_id}/analysis",
                headers=headers("alice", "admin"),
                json={"request_id": str(uuid4()), "confirmed": True},
            )
        ).status_code == 409
    get_settings.cache_clear()
