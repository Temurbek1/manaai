from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.mana_operation_ai.domain.chat import ChatTopic, ProductScope
from app.mana_operation_ai.domain.goals import (
    GoalCommand,
    GoalCreate,
    GoalDecision,
    OperationGoal,
)
from app.mana_operation_ai.domain.model_continuation import ModelContinuation
from app.mana_operation_ai.domain.session import SessionMemory


@dataclass(frozen=True)
class SavedTaskPage:
    goals: list[OperationGoal]
    next_cursor: str | None


class GoalModelOutput:
    def __init__(
        self,
        decision: GoalDecision,
        model: str,
        actual_microusd: int,
        continuation: ModelContinuation | None = None,
    ) -> None:
        self.decision = decision
        self.model = model
        self.actual_microusd = actual_microusd
        self.continuation = continuation


class GoalModelResponseError(RuntimeError):
    """Controlled output failure after verified provider usage was accounted."""

    def __init__(
        self,
        reason: str,
        actual_microusd: int,
        *,
        provider_status: str | None = None,
        incomplete_reason: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.actual_microusd = actual_microusd
        self.provider_status = provider_status
        self.incomplete_reason = incomplete_reason


class GoalModel(Protocol):
    def reservation(self, context: str) -> int: ...

    async def decide(self, *, context: str, owner: str) -> GoalModelOutput: ...


class ContinuingGoalModel(Protocol):
    def continuation_reservation(
        self, *, context: str, owner: str, state: ModelContinuation | None
    ) -> int: ...

    async def continue_decide(
        self, *, context: str, owner: str, state: ModelContinuation | None
    ) -> GoalModelOutput: ...


class GoalRepository(Protocol):
    async def create(
        self,
        owner: str,
        topic: ChatTopic,
        request: GoalCreate,
        *,
        session_memory: SessionMemory | None = None,
    ) -> OperationGoal: ...

    async def list(self, owner: str, topic_id: str) -> list[OperationGoal]: ...

    async def find_request(self, owner: str, request_id: str) -> OperationGoal | None: ...

    def closed_context(
        self, owner: str, topic_id: str, *, product: ProductScope, before: datetime
    ) -> AsyncGenerator[OperationGoal, None]: ...

    async def get(self, owner: str, goal_id: str) -> OperationGoal: ...

    async def saved_task(
        self,
        owner: str,
        topic_id: str,
        product: ProductScope,
        task_id: str,
        *,
        before: datetime,
    ) -> OperationGoal: ...

    async def find_saved_tasks(
        self,
        owner: str,
        topic_id: str,
        product: ProductScope,
        *,
        before: datetime,
        query: str,
        cursor: str | None,
    ) -> SavedTaskPage: ...

    async def command(self, owner: str, goal_id: str, payload: GoalCommand) -> OperationGoal: ...

    async def claim(self) -> tuple[str, OperationGoal] | None: ...

    async def save(self, owner: str, before: OperationGoal, after: OperationGoal) -> bool: ...
