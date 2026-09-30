from __future__ import annotations

from typing import Protocol

from app.mana_operation_ai.domain.chat import (
    ChatNextAction,
    ChatTopic,
    ChatTurn,
    MessageCreate,
    TopicCreate,
)


class ChatError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


class ChatRepository(Protocol):
    async def topics(self, owner: str) -> list[ChatTopic]: ...

    async def create(self, owner: str, payload: TopicCreate) -> ChatTopic: ...

    async def topic(self, owner: str, topic_id: str) -> ChatTopic: ...

    async def turns(self, owner: str, topic_id: str) -> list[ChatTurn]: ...

    async def reserve(
        self, owner: str, topic_id: str, payload: MessageCreate
    ) -> tuple[ChatTurn, bool]: ...

    async def update(self, turn: ChatTurn) -> bool: ...

    async def cancel(self, owner: str, topic_id: str, turn_id: str) -> ChatTurn: ...


class ConversationModel(Protocol):
    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput: ...


class ChatTurnOutput:
    def __init__(
        self,
        answer: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
        plan: list[str] | None = None,
        next_action: ChatNextAction = "none",
    ) -> None:
        self.answer = answer
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.plan = plan or []
        self.next_action = next_action
