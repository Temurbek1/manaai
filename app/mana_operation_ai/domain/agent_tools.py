"""Scoped analysis tools. No SDK, provider payloads or arbitrary execution."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.mana_operation_ai.domain.chat import ChatModel

SourceReadCapability = Literal[
    "retention.engagement.analyze", "growth.funnel.analyze", "retention.parents.analyze"
]
AgentToolName = Literal["inspect_sources", "read_saved_report", "request_source_read", "ask_user"]
AgentToolStatus = Literal[
    "started", "completed", "awaiting_approval", "waiting_for_user", "denied", "unknown"
]


class AgentToolCall(ChatModel):
    name: AgentToolName
    report_id: str | None = Field(default=None, min_length=1, max_length=120)
    capability: SourceReadCapability | None = None
    question: str | None = Field(default=None, min_length=1, max_length=1000)
    options: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def validate_arguments(self) -> "AgentToolCall":
        expected = {
            "inspect_sources": (False, False, False),
            "read_saved_report": (True, False, False),
            "request_source_read": (False, True, False),
            "ask_user": (False, False, True),
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
