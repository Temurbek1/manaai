"""Locale presentation does not change objective, permission, receipts or source admission."""

from pathlib import Path
from uuid import uuid4

import pytest
from pytest import MonkeyPatch
from sqlalchemy import select

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.chat import MessageCreate, TopicCreate
from app.mana_operation_ai.infrastructure.persistence.models import ChatTurnRow
from tests.test_operation_agent_workspace import WorkspaceConversation, configure_workspace
from tests.test_operation_chat import FakeConversation


async def test_uzbek_chat_language_is_frozen_private_and_idempotent(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "languages.db")
    app = create_app()
    model = FakeConversation()
    async with app.router.lifespan_context(app):
        service = app.state.operation_chat_service
        service._model = model
        topic = await service.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Tahlil")
        )
        payload = MessageCreate(request_id=uuid4(), message="Salom", response_language="uz")
        first = await service.send("alice", topic.topic_id, payload)
        assert first.response_language == "uz"
        assert model.contexts[0]["response_language"] == "uz"
        assert first.message == payload.message
        assert await service.send("alice", topic.topic_id, payload) == first
        assert len(model.contexts) == 1
        with pytest.raises(ChatError, match="другого сообщения"):
            await service.send(
                "alice", topic.topic_id, payload.model_copy(update={"response_language": "ru"})
            )
        async with service.repository._sessions() as session:
            row = await session.scalar(
                select(ChatTurnRow).where(ChatTurnRow.turn_id == first.turn_id)
            )
            assert row is not None
            assert "response_language" not in row.payload
            assert "response_language" not in row.context_metadata
            assert row.workspace_metadata["response_language"] == "uz"
        assert len(model.contexts) == 1
    get_settings.cache_clear()


async def test_uzbek_handoff_preserves_original_goal_and_no_write_constraint(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "handoff-language.db")
    app = create_app()
    model = WorkspaceConversation()
    async with app.router.lifespan_context(app):
        chats = app.state.operation_chat_service
        chats._model = model
        topic = await chats.create(
            "alice", TopicCreate(agent_id="operations-orchestrator", product="mana", title="Tahlil")
        )
        request = MessageCreate(
            request_id=uuid4(),
            message="MANA mijozlarini saqlashni tahlil qil.",
            execution_mode="agent",
            response_language="uz",
        )
        result = await app.state.operation_workspace_service.send("alice", topic.topic_id, request)
        assert result.goal is not None
        goal = result.goal
        assert goal.request.objective == request.message
        assert goal.request.constraints == (
            "Ma’lumotlarni o‘zgartirmang va mijozlarga murojaat qilmang. "
            "O‘zbek tilida (lotin yozuvida) javob bering."
        )
        assert goal.request.analysis_scope == "current"
        assert goal.approved_capability is None and goal.tools == []
        assert goal.request.max_steps == app.state.operation_goal_service.availability.max_steps
        replay = await app.state.operation_workspace_service.send("alice", topic.topic_id, request)
        assert replay.goal == goal and len(model.contexts) == 1
        saved = await app.state.operation_goal_service.repository.get("alice", goal.goal_id)
        assert saved.request == goal.request
    get_settings.cache_clear()


@pytest.mark.parametrize("value", ["en", "uz-Cyrl", "uz; grant writes", 1])
def test_response_language_is_a_closed_presentation_enum(value: object) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MessageCreate.model_validate(
            {"request_id": str(uuid4()), "message": "Salom", "response_language": value}
        )
