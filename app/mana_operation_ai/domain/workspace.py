"""A conversation turn and optional durable work handoff, not a new top-level agent."""

from app.mana_operation_ai.domain.chat import ChatModel, ChatTurn
from app.mana_operation_ai.domain.goals import OperationGoal


class WorkspaceTurn(ChatModel):
    turn: ChatTurn
    goal: OperationGoal | None = None
