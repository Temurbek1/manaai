"""Frozen persistence contracts from supported operation image 2ea7b9a.

Keep the legacy fields explicit: inheriting the new Goal would miss JSON incompatibility.
Task/event/evidence shapes and shared chat/inference types have not changed in this release.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.mana_operation_ai.domain.chat import ChatModel, ProductScope
from app.mana_operation_ai.domain.goals import GoalEvent, GoalEvidence, GoalTask
from app.mana_operation_ai.domain.inference import ModelChoice, ReasoningChoice


class LegacyGoalCreate(ChatModel):
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


class LegacyGoal(ChatModel):
    goal_id: str
    topic_id: str
    agent_id: str
    product: ProductScope
    request: LegacyGoalCreate
    status: Literal["queued", "running", "paused", "waiting", "completed", "cancelled"] = "queued"
    phase: Literal["plan", "investigate", "review"] = "plan"
    revision: int = 0
    created_at: datetime
    updated_at: datetime
    steps_used: int = 0
    accounted_microusd: int = 0
    plan: list[GoalTask] = Field(default_factory=list, max_length=8)
    events: list[GoalEvent] = Field(default_factory=list, max_length=100)
    evidence: list[GoalEvidence] = Field(default_factory=list, max_length=4)
    instructions: list[str] = Field(default_factory=list, max_length=20)
    result: str = Field(default="", max_length=16000)
    waiting_reason: str = Field(default="", max_length=2000)
    requested_capability: (
        Literal["retention.engagement.analyze", "growth.funnel.analyze"] | None
    ) = None
    approved_capability: Literal["retention.engagement.analyze", "growth.funnel.analyze"] | None = (
        None
    )
    read_attempted: bool = False
    model: str | None = None
    lease_until: datetime | None = None
