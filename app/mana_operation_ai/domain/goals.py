"""Durable, private administrative analysis goals; no provider write authority."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.mana_operation_ai.domain.chat import ChatModel, ProductScope
from app.mana_operation_ai.domain.inference import ModelChoice, ReasoningChoice

GoalStatus = Literal["queued", "running", "paused", "waiting", "completed", "cancelled"]
GoalPhase = Literal["plan", "investigate", "review"]
GoalCapability = Literal["retention.engagement.analyze", "growth.funnel.analyze"]


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


class GoalCommand(ChatModel):
    request_id: UUID
    command: Literal["pause", "resume", "cancel", "steer", "approve_read"]
    message: str = Field(default="", max_length=6000)
    expected_revision: int = Field(ge=0)


class GoalTask(ChatModel):
    title: str = Field(min_length=1, max_length=300)
    status: Literal["pending", "active", "done", "blocked"]


class GoalEvent(ChatModel):
    at: datetime
    kind: Literal["created", "progress", "control", "waiting", "result", "recovery"]
    message: str = Field(max_length=16000)


class GoalEvidence(ChatModel):
    report_id: str
    capability_key: str
    product: ProductScope
    collected_at: datetime | None
    fresh_until: datetime | None
    refresh_status: Literal["live", "cached", "stale", "unknown"]
    summary: str = Field(max_length=5000)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    shortened: bool = False


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


class GoalDecision(ChatModel):
    """Model proposals. Only the runtime decides state transitions and completion."""

    update: str = Field(min_length=1, max_length=2000)
    plan: list[GoalTask] = Field(max_length=8)
    draft: str = Field(max_length=16000)
    evidence_ids: list[str] = Field(max_length=4)
    disposition: Literal["continue", "accepted", "revise", "waiting"]
    missing_information: str = Field(max_length=2000)
    requested_capability: GoalCapability | None


class GoalAvailability(ChatModel):
    enabled: bool
    model: str
    max_steps: int
    budget_microusd: int
    read_capabilities: list[GoalCapability]
    read_product: ProductScope | None = None
    model_selection_enabled: bool = False
