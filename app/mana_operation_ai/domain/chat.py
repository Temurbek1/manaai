"""Private operational conversations; not a new operational agent registry."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.mana_operation_ai.domain.inference import ModelChoice, ReasoningChoice

ChatAgent = Literal["operations-orchestrator", "growth-agent", "retention-agent", "technical-agent"]
ProductScope = Literal["mana", "360rec"]
TurnStatus = Literal["reading", "thinking", "completed", "failed", "cancelled"]
ChatNextAction = Literal["none", "analyze", "approvals", "mana_parents"]


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
    model_choice: ModelChoice = "auto"
    reasoning: ReasoningChoice = "auto"


class ChatSource(ChatModel):
    report_id: str
    run_id: str
    created_at: datetime
    title: str
    scope_verified: bool = False
    product: ProductScope | None = None
    collected_at: datetime | None = None
    fresh_until: datetime | None = None
    refresh_status: Literal["live", "cached", "stale", "unknown"] = "unknown"


class ChatReadConfirmation(ChatModel):
    """Server-owned read conditions, not model-issued consent or an admission receipt."""

    kind: Literal["default", "mana_parents"]
    product: ProductScope
    capability_key: str = Field(min_length=1, max_length=120)
    confirmation_required: Literal[True] = True
    admission_checks: tuple[
        Literal["access"], Literal["product_scope"], Literal["cooldown"], Literal["budget"]
    ] = ("access", "product_scope", "cooldown", "budget")
    minimum_interval_seconds: int | None = Field(default=None, ge=21600, le=86400)


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
    model_choice: ModelChoice = "auto"
    reasoning: ReasoningChoice = "auto"
    input_tokens: int | None = None
    output_tokens: int | None = None
    analysis_requested: bool = False
    analysis_kind: Literal["default", "mana_parents"] = "default"
    plan: list[str] = Field(default_factory=list)
    next_action: ChatNextAction = "none"
    read_confirmation: ChatReadConfirmation | None = None


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
    parent_summary_enabled: bool = False
    model_selection_enabled: bool = False


class AnalysisRequest(ChatModel):
    request_id: UUID
    confirmed: Literal[True]
    kind: Literal["default", "mana_parents"] = "default"


class ChatAnalysisState(ChatModel):
    state: str
    run_id: str | None = None
    summary: str
