"""Public work notifications, not model deltas, evidence or execution authority."""

from datetime import datetime

from pydantic import Field

from app.mana_operation_ai.domain.agent_tools import AgentToolName, AgentToolStatus
from app.mana_operation_ai.domain.goals import GoalPhase, GoalStatus, GoalTask
from app.mana_operation_ai.domain.models import DomainModel


class WorkspaceToolState(DomainModel):
    call_id: str
    name: AgentToolName
    status: AgentToolStatus


class WorkspaceEvent(DomainModel):
    event_id: int = Field(ge=0)
    topic_id: str
    goal_id: str
    revision: int = Field(ge=0)
    at: datetime
    status: GoalStatus
    phase: GoalPhase
    message: str = Field(max_length=2000)
    message_shortened: bool = False
    plan: list[GoalTask] = Field(default_factory=list, max_length=8)
    tools: list[WorkspaceToolState] = Field(default_factory=list, max_length=12)


class WorkspaceEventPage(DomainModel):
    items: list[WorkspaceEvent] = Field(default_factory=list, max_length=50)
    next_cursor: int = Field(ge=0)
    has_more: bool
