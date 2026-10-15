"""Private operational conversations; not a new operational agent registry."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import SkipJsonSchema

from app.mana_operation_ai.domain.contact_continuation import (
    BoundContactWindow,
    ContactPreparationResult,
)
from app.mana_operation_ai.domain.contact_preparation import ContactToolContract, ContactToolRequest
from app.mana_operation_ai.domain.inference import ModelChoice, ReasoningChoice
from app.mana_operation_ai.domain.session import SessionMemory

ChatAgent = Literal["operations-orchestrator", "growth-agent", "retention-agent", "technical-agent"]
ProductScope = Literal["mana", "360rec"]
TurnStatus = Literal["reading", "thinking", "completed", "failed", "cancelled"]
ChatNextAction = Literal[
    "none", "analyze", "approvals", "mana_parents", "start_goal", "retention_contacts"
]
ResponseLanguage = Literal["ru", "uz"]


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
    execution_mode: Literal["discussion", "agent"] = "discussion"
    response_language: ResponseLanguage | None = None


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
    execution_mode: Literal["discussion", "agent"] = "discussion"
    response_language: ResponseLanguage | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    analysis_requested: bool = False
    analysis_kind: Literal["default", "mana_parents"] = "default"
    plan: list[str] = Field(default_factory=list)
    next_action: ChatNextAction = "none"
    read_confirmation: ChatReadConfirmation | None = None
    session_memory: SessionMemory | None = None
    preview: str = Field(default="", max_length=16000)
    preview_revision: int = Field(default=0, ge=0, le=130)
    contact_tool_contract: ContactToolContract | None = None
    contact_preparation: ContactToolRequest | None = None
    contact_model_window: SkipJsonSchema[BoundContactWindow | None] = Field(
        default=None, exclude=True, repr=False
    )
    contact_result: SkipJsonSchema[ContactPreparationResult | None] = Field(
        default=None, exclude=True
    )
    contact_reply_turn_id: SkipJsonSchema[str | None] = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def contact_contract(self) -> "ChatTurn":
        if self.contact_tool_contract is not None and self.execution_mode != "agent":
            raise ValueError("Native contact selection belongs only to an admitted agent turn")
        if (
            self.contact_tool_contract is not None
            and self.status == "completed"
            and self.next_action == "retention_contacts"
            and self.contact_preparation is None
        ):
            raise ValueError("A completed native contact request cannot fall back to a manual card")
        if self.contact_preparation is not None and (
            self.contact_tool_contract != self.contact_preparation.contract
            or self.status != "completed"
            or self.next_action != "retention_contacts"
        ):
            raise ValueError("Contact selection requires its original completed native tool turn")
        if self.contact_model_window is not None and (
            self.contact_preparation is None
            or self.contact_preparation.contract != "native_contact_preparation_v2"
            or self.contact_model_window.selection_fingerprint
            != self.contact_preparation.selection_fingerprint
        ):
            raise ValueError("A private continuation requires its original v2 preparation request")
        if self.contact_reply_turn_id is not None and self.contact_model_window is None:
            raise ValueError("A consumed contact call requires its retained original model window")
        if self.contact_result is not None and (
            self.execution_mode != "agent" or self.contact_preparation is not None
        ):
            raise ValueError("A contact result belongs to a separate agent continuation turn")
        return self


class TopicDetail(ChatModel):
    topic: ChatTopic
    turns: list[ChatTurn]


class TranscriptPage(ChatModel):
    topic: ChatTopic
    turns: list[ChatTurn] = Field(max_length=30)
    next_cursor: str | None = None
    has_more: bool


class RecentConversation(ChatModel):
    turns: list[ChatTurn] = Field(max_length=6)
    older_turns_omitted: int = Field(ge=0)


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
    agent_workspace_enabled: bool = False
    action_reviews_enabled: bool = False
    retention_contact_reviews_enabled: bool = False
    retention_peer_reviews_enabled: bool = False
    contact_tool_proposals_enabled: bool = False
    contact_tool_continuations_enabled: bool = False
    transcript_pagination_enabled: bool = False
    chat_streaming_enabled: bool = False
    response_languages: tuple[Literal["ru"], Literal["uz"]] = ("ru", "uz")


class AnalysisRequest(ChatModel):
    request_id: UUID
    confirmed: Literal[True]
    kind: Literal["default", "mana_parents"] = "default"


class ChatAnalysisState(ChatModel):
    state: str
    run_id: str | None = None
    summary: str
