from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt
from app.mana_ai.domain.chat import ChatTokens, ParentChildContext
from app.mana_ai.domain.child_safety import (
    SafetyAssessmentPage,
    SafetyBudget,
    SafetyJob,
    SafetyJobView,
    SafetyStoredResult,
    SafetyTarget,
)
from app.mana_ai.domain.family_agents import AgentQuestionRequest, ParentTouchDeliveryRequest
from app.mana_ai.domain.requests import ManaAIRequest


@dataclass(frozen=True)
class SafetyChildAlias:
    child_id: int
    alias: str
    revision: str


@dataclass(frozen=True)
class SafetyPrompt:
    input: ChatPrompt
    children: tuple[SafetyChildAlias, ...]
    source_qualification: str | None = None


class ChildSafetyPrompts(Protocol):
    def build(
        self,
        job: SafetyJob,
        context: ParentChildContext,
        saved: list[SafetyJobView],
    ) -> SafetyPrompt: ...


SafetyCompletion = Callable[[SafetyJob, SafetyPrompt, ChatModelReceipt], Awaitable[SafetyJobView]]


class NativeSafetyWorkflow(Protocol):
    async def captured(self, job: SafetyJob) -> bool: ...

    async def run(self, job: SafetyJob, complete: SafetyCompletion) -> SafetyJobView: ...


class ChildSafetyStore(Protocol):
    async def observe_analysis_request(
        self, target: SafetyTarget, analysis: ManaAIRequest
    ) -> SafetyJobView | None: ...

    async def admit_analysis(
        self,
        *,
        target: SafetyTarget,
        analysis: ManaAIRequest,
        now: datetime,
        allow_new: bool = True,
    ) -> SafetyJobView: ...

    async def assessment(self, parent_id: str, job_id: UUID) -> SafetyJobView: ...
    async def assessments(
        self, parent_id: str, *, after: int, limit: int
    ) -> SafetyAssessmentPage: ...
    async def safety_budget(self, parent_id: str, now: datetime) -> SafetyBudget: ...
    async def materialize_parent_event(self, now: datetime) -> SafetyJobView | None: ...
    async def claim_next(self, now: datetime) -> SafetyJob | None: ...
    async def saved_assessments(self, job: SafetyJob) -> list[SafetyJobView]: ...
    async def authorize_children(
        self, job: SafetyJob, child_ids: tuple[int, ...], now: datetime
    ) -> None: ...
    async def submit_safety(self, job: SafetyJob, reserved_tokens: int, now: datetime) -> None: ...
    async def record_usage(
        self, job: SafetyJob, usage: ChatTokens, model: str, now: datetime
    ) -> bool: ...
    async def fail_safety(
        self,
        job: SafetyJob,
        code: str,
        now: datetime,
        *,
        definite_model_rejection: bool = False,
    ) -> None: ...
    async def finish_safety(
        self,
        job: SafetyJob,
        result: SafetyStoredResult,
        now: datetime,
        *,
        question: AgentQuestionRequest | None = None,
    ) -> SafetyJobView: ...
    async def next_delivery(self, now: datetime) -> ParentTouchDeliveryRequest | None: ...
