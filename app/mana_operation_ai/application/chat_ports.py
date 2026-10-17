from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Protocol

from app.mana_operation_ai.domain.chat import (
    ChatNextAction,
    ChatTopic,
    ChatTurn,
    MessageCreate,
    RecentConversation,
    TopicCreate,
    TranscriptPage,
)
from app.mana_operation_ai.domain.contact_continuation import (
    ContactModelWindow,
    ContactPreparationResult,
)
from app.mana_operation_ai.domain.contact_loop import ContactLoopState
from app.mana_operation_ai.domain.contact_preparation import ContactToolSelection
from app.mana_operation_ai.domain.session import SessionMemory, SessionUserContext


class ChatError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


class SessionContextTooLarge(ChatError):
    def __init__(self) -> None:
        super().__init__(
            "История достигла лимита контекста. Ограничения не сокращались, запрос к AI "
            "не отправлен. Создайте новую тему с нужными условиями; старая история сохранена.",
            422,
        )


class SessionContextReader(Protocol):
    async def read(
        self, owner: str, topic_id: str, *, before: datetime
    ) -> SessionMemory | None: ...


class ChatRepository(Protocol):
    async def topics(self, owner: str) -> list[ChatTopic]: ...

    async def create(self, owner: str, payload: TopicCreate) -> ChatTopic: ...

    async def topic(self, owner: str, topic_id: str) -> ChatTopic: ...

    async def turns(self, owner: str, topic_id: str) -> list[ChatTurn]: ...

    async def turn(self, owner: str, topic_id: str, turn_id: str) -> ChatTurn: ...

    async def transcript_page(
        self, owner: str, topic_id: str, *, before: str | None, limit: int = 20
    ) -> TranscriptPage: ...

    async def recent_conversation(
        self, owner: str, topic_id: str, *, before: datetime
    ) -> RecentConversation: ...

    def user_context(
        self, owner: str, topic_id: str, *, before: datetime
    ) -> AsyncGenerator[SessionUserContext, None]: ...

    async def reserve(
        self,
        owner: str,
        topic_id: str,
        payload: MessageCreate,
        *,
        contact_result: ContactPreparationResult | None = None,
    ) -> tuple[ChatTurn, bool]: ...

    async def update(self, turn: ChatTurn) -> bool: ...

    async def cancel(self, owner: str, topic_id: str, turn_id: str) -> ChatTurn: ...

    async def preview(self, owner: str, topic_id: str, turn_id: str, text: str) -> bool: ...


class ConversationModel(Protocol):
    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput: ...


class ContactContinuationModel(Protocol):
    async def continue_contact(
        self,
        *,
        window: ContactModelWindow,
        result: ContactPreparationResult,
        call_sha256: str,
        owner: str,
        memory: SessionMemory | None = None,
    ) -> ChatTurnOutput: ...


class ContactLoopModel(Protocol):
    async def continue_contact_loop(
        self,
        *,
        window: ContactModelWindow,
        result: ContactPreparationResult,
        call_sha256: str,
        owner: str,
        memory: SessionMemory | None,
        loop: ContactLoopState,
    ) -> ChatTurnOutput: ...


class StreamingConversationModel(Protocol):
    def stream_reply(
        self, *, instructions: str, context: str, owner: str
    ) -> AsyncGenerator[str | ChatTurnOutput, None]: ...


class ChatTurnOutput:
    def __init__(
        self,
        answer: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        plan: list[str] | None = None,
        next_action: ChatNextAction = "none",
        contact_selection: ContactToolSelection | None = None,
        contact_call_sha256: str | None = None,
        contact_model_window: ContactModelWindow | None = None,
    ) -> None:
        self.answer = answer
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.plan = plan or []
        self.next_action = next_action
        self.contact_selection = contact_selection
        self.contact_call_sha256 = contact_call_sha256
        self.contact_model_window = contact_model_window
