"""Durable, private administrative analysis goals; no provider write authority."""

import hashlib
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.mana_operation_ai.domain.agent_tools import (
    AgentToolCall,
    AgentToolRecord,
    SourceReadCapability,
)
from app.mana_operation_ai.domain.chat import ChatModel, ProductScope
from app.mana_operation_ai.domain.goal_review import GoalReviewVerdictBody
from app.mana_operation_ai.domain.inference import ModelChoice, ReasoningChoice
from app.mana_operation_ai.domain.model_continuation import ModelContinuation
from app.mana_operation_ai.domain.session import SessionMemory

GoalStatus = Literal["queued", "running", "paused", "waiting", "completed", "cancelled"]
GoalPhase = Literal["plan", "investigate", "review"]
GoalCapability = SourceReadCapability


class GoalConversationTurn(ChatModel):
    user: str = Field(max_length=6000)
    assistant: str = Field(max_length=1000)
    assistant_shortened: bool = False


class GoalCreate(ChatModel):
    request_id: UUID
    objective: str = Field(min_length=10, max_length=6000)
    success_criteria: str = Field(
        default="Подготовить проверенный анализ и план следующих шагов.", max_length=2000
    )
    constraints: str = Field(
        default="Не изменять данные и не связываться с клиентами.", max_length=2000
    )
    max_steps: int = Field(default=6, ge=3, le=12)
    budget_microusd: int = Field(default=500_000, ge=50_000, le=10_000_000)
    model_choice: ModelChoice = "auto"
    reasoning: ReasoningChoice = "auto"
    execution_mode: Literal["analysis", "agent"] = "analysis"
    analysis_scope: Literal["current", "saved_snapshot"] = "current"
    conversation_history: list[GoalConversationTurn] = Field(default_factory=list, max_length=6)
    older_turns_omitted: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_analysis_scope(self) -> "GoalCreate":
        if self.analysis_scope == "saved_snapshot" and self.execution_mode != "agent":
            raise ValueError("Saved-snapshot analysis requires the native agent workspace")
        return self


class GoalCommand(ChatModel):
    request_id: UUID
    command: Literal["pause", "resume", "cancel", "steer", "approve_read", "extend_limits"]
    message: str = Field(default="", max_length=6000)
    expected_revision: int = Field(ge=0)
    max_steps: int | None = Field(default=None, ge=3, le=120, strict=True)
    budget_microusd: int | None = Field(default=None, ge=50_000, le=10_000_000, strict=True)

    @model_validator(mode="after")
    def validate_limit_command(self) -> "GoalCommand":
        if self.command == "extend_limits":
            if self.max_steps is None or self.budget_microusd is None or self.message:
                raise ValueError("Limit extensions require exact limits, not a new instruction")
        elif self.max_steps is not None or self.budget_microusd is not None:
            raise ValueError("Only explicit limit extension commands can change limits")
        return self


class GoalExecutionLimits(ChatModel):
    max_steps: int = Field(ge=3, le=120, strict=True)
    budget_microusd: int = Field(ge=50_000, le=10_000_000, strict=True)


class GoalLimitGrant(GoalExecutionLimits):
    request_id: UUID
    at: datetime

    @model_validator(mode="after")
    def validate_time(self) -> "GoalLimitGrant":
        if self.at.utcoffset() is None:
            raise ValueError("Limit grants require an aware timestamp")
        return self


class GoalTask(ChatModel):
    title: str = Field(min_length=1, max_length=300)
    status: Literal["pending", "active", "done", "blocked"]


class GoalEvent(ChatModel):
    at: datetime
    kind: Literal["created", "progress", "control", "waiting", "result", "recovery"]
    message: str = Field(max_length=16000)


class ReportReadProgress(ChatModel):
    """Runtime-owned contiguous receipt; it proves reading, not source completeness."""

    source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    full_text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    loaded_text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    total_characters: int = Field(ge=0, le=32000)
    next_offset: int = Field(ge=0, le=32000)
    quality_notes_complete: bool


class GoalEvidence(ChatModel):
    report_id: str
    capability_key: str
    product: ProductScope
    collected_at: datetime | None
    fresh_until: datetime | None
    refresh_status: Literal["live", "cached", "stale", "unknown"]
    # Saved-text receipts hash exact source characters, including whitespace boundaries.
    summary: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(max_length=32000)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    shortened: bool = False
    report_read_progress: ReportReadProgress | None = None

    @model_validator(mode="after")
    def validate_report_read_progress(self) -> "GoalEvidence":
        progress = self.report_read_progress
        if progress is None:
            return self
        digest = hashlib.sha256(self.summary.encode()).hexdigest()
        complete = progress.next_offset == progress.total_characters
        if (
            progress.next_offset != len(self.summary)
            or progress.next_offset > progress.total_characters
            or digest != progress.loaded_text_sha256
            or (complete and digest != progress.full_text_sha256)
            or self.shortened != (not complete or not progress.quality_notes_complete)
        ):
            raise ValueError("Saved-report reading receipt does not match its exact text")
        return self


class GoalModelFeedback(ChatModel):
    code: Literal["unloaded_evidence", "invalid_decision"]
    message: str = Field(max_length=1000)


class OperationGoal(ChatModel):
    goal_id: str
    topic_id: str
    agent_id: str
    product: ProductScope
    request: GoalCreate
    status: GoalStatus = "queued"
    phase: GoalPhase = "plan"
    revision: int = 0
    created_at: datetime
    updated_at: datetime
    steps_used: int = 0
    accounted_microusd: int = 0
    # Includes unsettled worst-case reservations; not an invoice.
    plan: list[GoalTask] = Field(default_factory=list, max_length=8)
    events: list[GoalEvent] = Field(default_factory=list, max_length=100)
    evidence: list[GoalEvidence] = Field(default_factory=list, max_length=4)
    instructions: list[str] = Field(default_factory=list, max_length=20)
    result: str = Field(default="", max_length=16000)
    waiting_reason: str = Field(default="", max_length=2000)
    requested_capability: GoalCapability | None = None
    approved_capability: GoalCapability | None = None
    read_attempted: bool = False
    model: str | None = None
    lease_until: datetime | None = None
    tools: list[AgentToolRecord] = Field(default_factory=list, max_length=120)
    session_memory: SessionMemory | None = None
    model_continuation: ModelContinuation | None = None
    model_feedback: GoalModelFeedback | None = None
    model_recoveries: int = Field(default=0, ge=0, le=2)
    limit_stop: Literal["steps", "budget"] | None = None
    limit_grants: list[GoalLimitGrant] = Field(default_factory=list, max_length=20)
    limit_tracking: bool = False
    unsettled_microusd: int = Field(default=0, ge=0)
    # Captured by the server on creation; never a source permission or public create option.
    report_discovery_enabled: bool = Field(default=False, strict=True)
    snapshot_replacement_enabled: bool = Field(default=False, strict=True)
    page_projection_enabled: bool = Field(default=False, strict=True)
    review_verdict_enabled: bool = Field(default=False, strict=True)
    # Latest private review; historical on revision, never fresh evidence or authority.
    review_receipt: GoalReviewVerdictBody | None = None

    @property
    def execution_limits(self) -> GoalExecutionLimits:
        if self.limit_grants:
            grant = self.limit_grants[-1]
            return GoalExecutionLimits(
                max_steps=grant.max_steps, budget_microusd=grant.budget_microusd
            )
        return GoalExecutionLimits(
            max_steps=self.request.max_steps, budget_microusd=self.request.budget_microusd
        )

    @model_validator(mode="after")
    def validate_limit_grants(self) -> "OperationGoal":
        if self.review_verdict_enabled and not self.page_projection_enabled:
            raise ValueError("Review verdicts require the tracked native paged-catalog contract")
        if self.review_receipt is not None and not self.review_verdict_enabled:
            raise ValueError("A review receipt requires the captured verdict contract")
        if self.review_receipt is not None:
            for target in ("objective", "success_criteria"):
                quotes = "".join(
                    check.quote for check in self.review_receipt.checks if check.target == target
                )
                if quotes != getattr(self.request, target):
                    raise ValueError(
                        "Saved review must retain every original objective/criterion word"
                    )
            if self.review_receipt.disposition == "accepted" and (
                not self.review_receipt.conditions_checked
                or not self.review_receipt.evidence_checked
                or not self.review_receipt.evidence_ids
                or any(check.status != "passed" for check in self.review_receipt.checks)
            ):
                raise ValueError("Saved acceptance requires complete conditions/evidence/checks")
        if self.page_projection_enabled and not self.snapshot_replacement_enabled:
            raise ValueError("Saved-page projection requires captured runtime snapshot replacement")
        if self.snapshot_replacement_enabled and (
            self.request.execution_mode != "agent"
            or not self.report_discovery_enabled
            or not self.limit_tracking
        ):
            raise ValueError("Runtime snapshot replacement requires a tracked native catalog Goal")
        if self.report_discovery_enabled and self.request.execution_mode != "agent":
            raise ValueError("Saved-report discovery requires the native workspace")
        if not self.limit_tracking and len(self.tools) > 12:
            raise ValueError("Legacy and untracked Goal tool journals remain limited to twelve")
        if (
            self.limit_tracking or self.limit_grants or self.limit_stop or self.unsettled_microusd
        ) and self.request.execution_mode != "agent":
            raise ValueError("Extended limits require the native workspace")
        if (
            self.limit_grants or self.limit_stop or self.unsettled_microusd
        ) and not self.limit_tracking:
            raise ValueError("Extended limits require tracked model reservations")
        if self.unsettled_microusd > self.accounted_microusd:
            raise ValueError("Unsettled costs cannot exceed accounted costs")
        steps, budget, at = self.request.max_steps, self.request.budget_microusd, self.created_at
        seen: set[UUID] = set()
        for grant in self.limit_grants:
            if (
                grant.max_steps < steps
                or grant.budget_microusd < budget
                or (grant.max_steps == steps and grant.budget_microusd == budget)
                or at.utcoffset() is None
                or grant.at < at
                or grant.request_id in seen
            ):
                raise ValueError("Limit grants must be unique, dated, monotonic increases")
            seen.add(grant.request_id)
            steps, budget, at = grant.max_steps, grant.budget_microusd, grant.at
        if self.limit_stop and self.status not in {"waiting", "paused", "cancelled"}:
            raise ValueError("A limit stop cannot execute or complete a Goal")
        if self.limit_stop == "steps" and self.steps_used < steps:
            raise ValueError("Step exhaustion must match the effective step limit")
        return self

    def validate_private_review(self) -> None:
        """Persistence requires the proof; authenticated HTTP projections omit it."""
        if (
            self.review_verdict_enabled
            and self.status == "completed"
            and (
                self.review_receipt is None
                or self.review_receipt.disposition != "accepted"
                or self.review_receipt.checked_plan_positions != list(range(len(self.plan)))
                or self.review_receipt.draft_sha256
                != hashlib.sha256(self.result.encode()).hexdigest()
            )
        ):
            raise ValueError("Completed verdict Goals require their exact accepted review receipt")


class GoalDecisionBody(ChatModel):
    """Structured analysis, separate from native tool arguments."""

    update: str = Field(min_length=1, max_length=2000)
    plan: list[GoalTask] = Field(max_length=8)
    draft: str = Field(max_length=16000)
    evidence_ids: list[str] = Field(max_length=4)
    disposition: Literal["continue", "accepted", "revise", "waiting"]
    missing_information: str = Field(max_length=2000)
    requested_capability: GoalCapability | None


class GoalDecision(GoalDecisionBody):
    """Runtime decisions; only native tools may add an execution request."""

    tool_call: AgentToolCall | None = None


class GoalAvailability(ChatModel):
    enabled: bool
    model: str
    max_steps: int
    budget_microusd: int
    read_capabilities: list[GoalCapability]
    read_product: ProductScope | None = None
    model_selection_enabled: bool = False
    agent_workspace_enabled: bool = False
    event_stream_enabled: bool = False
    read_products: dict[GoalCapability, ProductScope] = Field(default_factory=dict)
    limit_extensions_enabled: bool = False
    extension_max_steps: int = Field(default=0, ge=0, le=120)
    extension_budget_microusd: int = Field(default=0, ge=0, le=10_000_000)
    response_languages: tuple[Literal["ru"], Literal["uz"]] = ("ru", "uz")
