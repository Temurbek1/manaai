"""Public work state and display-only answer drafts; never execution authority."""

from datetime import datetime
from typing import Literal

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


class ChatTextEvent(DomainModel):
    kind: Literal["chat_text"] = "chat_text"
    event_id: int = Field(ge=0)
    topic_id: str
    turn_id: str
    revision: int = Field(ge=1, le=130)
    at: datetime
    status: Literal["thinking", "completed", "failed", "cancelled"]
    offset: int = Field(ge=0, le=16000)
    delta: str = Field(default="", max_length=16000)
    final_answer: str | None = Field(default=None, max_length=16000)


class WorkspaceNotificationPage(DomainModel):
    items: list[WorkspaceEvent | ChatTextEvent] = Field(default_factory=list, max_length=50)
    next_cursor: int = Field(ge=0)
    has_more: bool
