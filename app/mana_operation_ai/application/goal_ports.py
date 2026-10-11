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
from app.mana_operation_ai.domain.session import SessionMemory


@dataclass(frozen=True)
class GoalHistory:
    goals: list[OperationGoal]
    older_goals_omitted: int


@dataclass(frozen=True)
class SavedTaskPage:
    goals: list[OperationGoal]
    next_cursor: str | None


class GoalModelOutput:
    def __init__(self, decision: GoalDecision, model: str, actual_microusd: int) -> None:
        self.decision = decision
        self.model = model
        self.actual_microusd = actual_microusd


class GoalModelResponseError(RuntimeError):
    """Controlled output failure after verified provider usage was accounted."""

    def __init__(self, reason: str, actual_microusd: int) -> None:
        super().__init__(reason)
        self.actual_microusd = actual_microusd


class GoalModel(Protocol):
    def reservation(self, context: str) -> int: ...

    async def decide(self, *, context: str, owner: str) -> GoalModelOutput: ...


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

    async def closed_history(
        self, owner: str, topic_id: str, *, before: datetime
    ) -> GoalHistory: ...

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
