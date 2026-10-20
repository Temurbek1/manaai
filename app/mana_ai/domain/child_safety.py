"""Private family-analysis jobs and a budget separate from Parent-Touch."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ChatTokens, ParentChatId
from app.mana_ai.domain.enums import ManaAICapability
from app.mana_ai.domain.requests import ManaAIRequest
from app.mana_ai.domain.responses import ManaAIAnalysisResult

SafetyJobKind = Literal["child_data", "parent_message"]
SafetyJobStatus = Literal[
    "queued", "preparing", "submitted", "unknown", "metered", "completed", "failed"
]


class ChildSafetyLimits(ChatContract):
    """All paid allowances are explicit; there is no unlimited/default server pool."""

    server_daily_tokens: int = Field(ge=64, le=100_000_000, strict=True)
    parent_daily_tokens: int = Field(ge=64, le=1_000_000, strict=True)
    job_tokens: int = Field(ge=64, le=100_000, strict=True)
    max_pending_jobs: int = Field(default=1000, ge=1, le=100_000, strict=True)
    max_parent_pending_jobs: int = Field(default=20, ge=1, le=1000, strict=True)
    parent_daily_attempts: int = Field(default=50, ge=1, le=1000, strict=True)
    history_turns: int = Field(default=4, ge=1, le=10, strict=True)
    max_context_bytes: int = Field(default=65_536, ge=4096, le=1_048_576, strict=True)
    max_queue_age_seconds: int = Field(default=3600, ge=60, le=86_400, strict=True)
    lease_seconds: int = Field(default=300, ge=300, le=600, strict=True)

    @model_validator(mode="after")
    def ordered_limits(self) -> "ChildSafetyLimits":
        if not self.job_tokens <= self.parent_daily_tokens <= self.server_daily_tokens:
            raise ValueError("Safety limits must satisfy job <= parent <= server")
        if self.max_parent_pending_jobs > self.max_pending_jobs:
            raise ValueError("A parent queue cannot exceed the server queue")
        return self


class SafetyTarget(ChatContract):
    parent_id: ParentChatId
    child_id: int = Field(gt=0, strict=True)
    request_id: UUID
    source_revision: str = Field(min_length=1, max_length=128, pattern=r"\S")


class SafetyChatMessage(ChatContract):
    role: Literal["user", "assistant"]
    content: str
    created_at: AwareDatetime


class SafetyContextSnapshot(ChatContract):
    version: Literal[1] = 1
    chat_turn_cutoff: int = Field(ge=0, strict=True)
    messages: list[SafetyChatMessage] = Field(max_length=20)
    saved_assessment_ids: list[UUID] = Field(max_length=20)
    saved_assessment_total: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def exact_saved_identities(self) -> "SafetyContextSnapshot":
        if len(set(self.saved_assessment_ids)) != len(self.saved_assessment_ids):
            raise ValueError("Frozen assessment identities must be unique")
        if self.saved_assessment_total < len(self.saved_assessment_ids):
            raise ValueError("The saved assessment total cannot be smaller than its page")
        return self


class SafetyStoredResult(ChatContract):
    analysis: ManaAIAnalysisResult | None = None
    followup_summary: str | None = Field(default=None, min_length=1, max_length=1500)
    question_id: UUID | None = None

    @model_validator(mode="after")
    def one_result(self) -> "SafetyStoredResult":
        if (self.analysis is None) == (self.followup_summary is None):
            raise ValueError("Exactly one analysis or historical chat review is required")
        return self


class SafetyJobView(ChatContract):
    job_id: UUID
    parent_id: ParentChatId
    child_id: int | None
    kind: SafetyJobKind
    capability: ManaAICapability | None
    status: SafetyJobStatus
    parent_turn_cutoff: int
    created_at: AwareDatetime
    updated_at: AwareDatetime
    evaluated_at: AwareDatetime | None = None
    signal_first_observed_at: AwareDatetime | None = None
    signal_last_observed_at: AwareDatetime | None = None
    usage: ChatTokens | None = None
    model: str | None = None
    error_code: str | None = None
    result: SafetyStoredResult | None = None


@dataclass(frozen=True)
class SafetyJob:
    """Worker-only frozen input. Public projections must never include this payload."""

    view: SafetyJobView
    source_revision: str
    data_digest: str
    analysis: ManaAIRequest | None
    context: SafetyContextSnapshot
    claim_id: UUID | None = None
    reserved_tokens: int = 0
    lease_expires_at: datetime | None = None


class SafetyBudget(ChatContract):
    server_daily_limit: int
    server_used_tokens: int
    server_reserved_tokens: int
    server_remaining_tokens: int
    parent_daily_limit: int
    parent_used_tokens: int
    parent_reserved_tokens: int
    parent_remaining_tokens: int
    parent_blocked_by_unknown: bool
    resets_at: AwareDatetime
    timezone: str
