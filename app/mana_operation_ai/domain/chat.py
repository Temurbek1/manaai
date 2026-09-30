"""Private operational conversations; not a new operational agent registry."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ChatAgent = Literal["operations-orchestrator", "growth-agent", "retention-agent", "technical-agent"]
ProductScope = Literal["mana", "360rec"]
TurnStatus = Literal["reading", "thinking", "completed", "failed", "cancelled"]
ChatNextAction = Literal["none", "analyze", "approvals"]


class ChatModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TopicCreate(ChatModel):
    agent_id: ChatAgent
    product: ProductScope
    title: str = Field(min_length=1, max_length=100)


class ChatTopic(TopicCreate):
    topic_id: str
    created_at: datetime
    updated_at: datetime


class MessageCreate(ChatModel):
    request_id: UUID
    message: str = Field(min_length=1, max_length=6000)


class ChatSource(ChatModel):
    report_id: str
    run_id: str
    created_at: datetime
    title: str
    scope_verified: Literal[False] = False


class ChatTurn(ChatModel):
    turn_id: str
    topic_id: str
    request_id: UUID
    message: str
    status: TurnStatus
    created_at: datetime
    answer: str = ""
    sources: list[ChatSource] = Field(default_factory=list)
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    analysis_requested: bool = False
    plan: list[str] = Field(default_factory=list)
    next_action: ChatNextAction = "none"


class TopicDetail(ChatModel):
    topic: ChatTopic
    turns: list[ChatTurn]


class ChatReply(ChatModel):
    answer: str
    plan: list[str]
    next_action: ChatNextAction


class ChatAvailability(ChatModel):
    enabled: bool
    hourly_limit: int
    daily_limit: int


class AnalysisRequest(ChatModel):
    request_id: UUID
    confirmed: Literal[True]


class ChatAnalysisState(ChatModel):
    state: str
    run_id: str | None = None
    summary: str
