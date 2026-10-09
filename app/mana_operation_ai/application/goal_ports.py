from typing import Protocol

from app.mana_operation_ai.domain.chat import ChatTopic
from app.mana_operation_ai.domain.goals import (
    GoalCommand,
    GoalCreate,
    GoalDecision,
    OperationGoal,
)


class GoalModelOutput:
    def __init__(self, decision: GoalDecision, model: str, actual_microusd: int) -> None:
        self.decision = decision
        self.model = model
        self.actual_microusd = actual_microusd


class GoalModel(Protocol):
    def reservation(self, context: str) -> int: ...

    async def decide(self, *, context: str, owner: str) -> GoalModelOutput: ...


class GoalRepository(Protocol):
    async def create(self, owner: str, topic: ChatTopic, request: GoalCreate) -> OperationGoal: ...

    async def list(self, owner: str, topic_id: str) -> list[OperationGoal]: ...

    async def get(self, owner: str, goal_id: str) -> OperationGoal: ...

    async def command(self, owner: str, goal_id: str, payload: GoalCommand) -> OperationGoal: ...

    async def claim(self) -> tuple[str, OperationGoal] | None: ...

    async def save(self, owner: str, before: OperationGoal, after: OperationGoal) -> bool: ...
