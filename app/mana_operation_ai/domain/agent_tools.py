"""Scoped analysis tools. No SDK, provider payloads or arbitrary execution."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.mana_operation_ai.domain.chat import ChatModel

SourceReadCapability = Literal[
    "retention.engagement.analyze", "growth.funnel.analyze", "retention.parents.analyze"
]
AgentToolName = Literal[
    "inspect_sources",
    "read_saved_report",
    "find_saved_tasks",
    "read_saved_task",
    "request_source_read",
    "ask_user",
]
TASK_HISTORY_TOOLS = ("find_saved_tasks", "read_saved_task")
AgentToolStatus = Literal[
    "started", "completed", "awaiting_approval", "waiting_for_user", "denied", "unknown"
]


class AgentToolCall(ChatModel):
    name: AgentToolName
    report_id: str | None = Field(default=None, min_length=1, max_length=120)
    capability: SourceReadCapability | None = None
    question: str | None = Field(default=None, min_length=1, max_length=1000)
    options: list[str] = Field(default_factory=list, max_length=3)
    task_id: str | None = Field(default=None, min_length=1, max_length=36)
    query: str | None = Field(default=None, max_length=120)
    cursor: str | None = Field(default=None, min_length=1, max_length=36)
    offset: int | None = Field(default=None, ge=0, le=16000, strict=True)

    @model_validator(mode="after")
    def validate_arguments(self) -> "AgentToolCall":
        expected = {
            "inspect_sources": (False, False, False),
            "read_saved_report": (True, False, False),
            "request_source_read": (False, True, False),
            "ask_user": (False, False, True),
            "find_saved_tasks": (False, False, False),
            "read_saved_task": (False, False, False),
        }[self.name]
        if (
            tuple(value is not None for value in (self.report_id, self.capability, self.question))
            != expected
        ):
            raise ValueError("Arguments do not match the selected analysis tool")
        if self.options and self.name != "ask_user":
            raise ValueError("Options are only allowed for user questions")
        if any(not item.strip() or len(item) > 200 for item in self.options):
            raise ValueError("Question options must be nonempty and bounded")
        if (self.task_id is not None) != (self.name == "read_saved_task") or (
            (self.offset is not None) != (self.name == "read_saved_task")
        ):
            raise ValueError("Saved-task reads require an exact task and text offset")
        if (self.query is not None) != (self.name == "find_saved_tasks") or (
            self.cursor is not None and self.name != "find_saved_tasks"
        ):
            raise ValueError("Search and cursor arguments belong only to saved-task lookup")
        return self


class AgentToolRecord(ChatModel):
    call_id: str
    call: AgentToolCall
    status: AgentToolStatus
    started_at: datetime
    completed_at: datetime | None = None
    # Bounded minimized results, never raw upstream bodies or hidden reasoning.
    result: str = Field(default="", max_length=8000)
    result_shortened: bool = False
