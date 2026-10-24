"""One separately metered specialist analysis, never a parent-visible sender."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid5

from app.mana_ai.application.chat_ports import (
    ChatModelReceipt,
    ChatModelRejected,
    ParentChatError,
    ParentChatModel,
    ParentChildrenSource,
)
from app.mana_ai.application.child_safety_ports import (
    ChildSafetyPrompts,
    ChildSafetyStore,
    NativeSafetyWorkflow,
    SafetyPrompt,
)
from app.mana_ai.application.ports import Clock
from app.mana_ai.application.service import ManaAIAnalysisService
from app.mana_ai.domain.child_safety import (
    ChildSafetyLimits,
    SafetyAssessmentPage,
    SafetyBudget,
    SafetyJob,
    SafetyJobView,
    SafetyModelDecision,
    SafetyStoredResult,
    SafetyTarget,
)
from app.mana_ai.domain.family_agents import AgentQuestionRequest
from app.mana_ai.domain.requests import ManaAIRequest
from app.mana_ai.domain.responses import CheckResult, FindingDraft, ModelAnalysis


class CapturedSafetyAnalysis:
    """Feed one paid, metered decision through existing validation without reinference."""

    def __init__(self, analysis: ModelAnalysis, model: str) -> None:
        self._analysis, self._model = analysis, model

    @property
    def model_name(self) -> str:
        return self._model

    async def analyze(
        self,
        request: ManaAIRequest,
        *,
        deterministic_findings: list[FindingDraft],
        required_checks: list[CheckResult],
    ) -> ModelAnalysis:
        return self._analysis


class ChildSafetyService:
    def __init__(
        self,
        *,
        store: ChildSafetyStore,
        children: ParentChildrenSource,
        model: ParentChatModel,
        prompts: ChildSafetyPrompts,
        clock: Clock,
        limits: ChildSafetyLimits,
        max_output_tokens: int,
        native_sources: NativeSafetyWorkflow | None = None,
    ) -> None:
        if not 32 <= max_output_tokens < limits.job_tokens:
            raise ValueError("Safety output cap must fit inside the explicit job allowance")
        self.store, self._children, self._model, self._prompts = store, children, model, prompts
        self._clock, self._limits, self._output = clock, limits, max_output_tokens
        self.worker_available = True
        self._native_sources = native_sources

    async def admit(self, target: SafetyTarget, analysis: ManaAIRequest) -> SafetyJobView:
        return await self.store.admit_analysis(
            target=target,
            analysis=analysis,
            now=self._clock.now(),
            allow_new=self.worker_available,
        )

    async def assessment(self, parent_id: str, job_id: UUID) -> SafetyJobView:
        return await self.store.assessment(parent_id, job_id)

    async def assessments(self, parent_id: str, *, after: int, limit: int) -> SafetyAssessmentPage:
        return await self.store.assessments(parent_id, after=after, limit=limit)

    async def budget(self, parent_id: str) -> SafetyBudget:
        return await self.store.safety_budget(parent_id, self._clock.now())

    async def process_one(self) -> SafetyJobView | None:
        await self.store.materialize_parent_event(self._clock.now())
        job = await self.store.claim_next(self._clock.now())
        if job is None:
            return None
        return await self._run(job)

    async def _run(self, job: SafetyJob) -> SafetyJobView:
        if self._native_sources is not None and await self._native_sources.captured(job):
            return await self._native_sources.run(job, self._complete)
        submitted = False
        metered = False
        try:
            context = await self._children.read(job.view.parent_id)
            now = self._clock.now()
            if context.parent_id != job.view.parent_id or not (
                now - timedelta(seconds=180) <= context.collected_at <= now + timedelta(seconds=5)
            ):
                raise ParentChatError("safety_ownership_context_invalid", 503)
            connected = tuple(sorted(c.child_id for c in context.children if c.connected))
            await self.store.authorize_children(job, connected, now)
            saved = await self.store.saved_assessments(job)
            prompt = self._prompts.build(job, context, saved)
            size = len(prompt.input.instructions.encode()) + sum(
                len(text.encode()) for _, text in prompt.input.messages
            )
            if size > self._limits.max_context_bytes:
                raise ParentChatError("safety_context_too_large", 422)
            count = await self._model.count_input(prompt.input)
            if type(count) is not int or count < 0:
                raise ParentChatError("safety_token_count_invalid", 503)
            output = min(self._output, job.reserved_tokens - count)
            if output < 32:
                raise ParentChatError("safety_job_token_budget_exceeded", 429)
            await self.store.submit_safety(job, count + output, self._clock.now())
            submitted = True
            receipt = await self._model.respond(prompt.input, max_output_tokens=output)
            eligible = await self.store.record_usage(
                job, receipt.usage, receipt.model, self._clock.now()
            )
            metered = True
            if not eligible:
                return await self.assessment(job.view.parent_id, job.view.job_id)
            if (
                not receipt.completed
                or receipt.answer is None
                or receipt.question_id is not None
                or receipt.notice_id is not None
            ):
                raise ValueError("Invalid safety decision receipt")
            return await self._complete(job, prompt, receipt)
        except ChatModelRejected:
            await self.store.fail_safety(
                job, "model_request_rejected", self._clock.now(), definite_model_rejection=True
            )
        except (Exception, asyncio.CancelledError) as exc:
            code = (
                "safety_invalid_decision"
                if metered
                else (
                    "safety_model_receipt_unknown"
                    if submitted
                    else "safety_source_or_context_unavailable"
                )
            )
            if isinstance(exc, ParentChatError) and not submitted:
                code = (
                    exc.code
                    if exc.code
                    in {
                        "safety_ownership_context_invalid",
                        "safety_child_not_authorized",
                        "safety_context_too_large",
                        "safety_token_count_invalid",
                        "safety_job_token_budget_exceeded",
                        "safety_saved_evidence_unavailable",
                    }
                    else "safety_source_or_context_unavailable"
                )
            await asyncio.shield(self.store.fail_safety(job, code, self._clock.now()))
            if isinstance(exc, asyncio.CancelledError):
                raise
        return await self.assessment(job.view.parent_id, job.view.job_id)

    async def _complete(
        self, job: SafetyJob, prompt: SafetyPrompt, receipt: ChatModelReceipt
    ) -> SafetyJobView:
        if receipt.answer is None:
            raise ValueError("A metered specialist decision is required")
        decision = SafetyModelDecision.model_validate_json(receipt.answer)
        result = await self._validate_result(job, decision, receipt.model)
        question = self._question(job, prompt, decision)
        return await self.store.finish_safety(job, result, self._clock.now(), question=question)

    async def _validate_result(
        self,
        job: SafetyJob,
        decision: SafetyModelDecision,
        model: str,
    ) -> SafetyStoredResult:
        if job.analysis is not None:
            if decision.analysis is None or decision.followup_summary is not None:
                raise ValueError("An observation job requires its actual protective analysis")
            result = await ManaAIAnalysisService(
                gateway=CapturedSafetyAnalysis(decision.analysis, model),
                clock=self._clock,
            ).analyze(job.analysis)
            return SafetyStoredResult(analysis=result)
        if decision.analysis is not None or decision.followup_summary is None:
            raise ValueError("A chat review cannot pretend to be a fresh sensor analysis")
        return SafetyStoredResult(followup_summary=decision.followup_summary)

    def _question(
        self,
        job: SafetyJob,
        prompt: SafetyPrompt,
        decision: SafetyModelDecision,
    ) -> AgentQuestionRequest | None:
        need = decision.question
        if need is None:
            return None
        child = next((c for c in prompt.children if c.alias == need.child_alias), None)
        if child is None or (job.view.child_id is not None and child.child_id != job.view.child_id):
            raise ValueError("An information need selected an unauthorized child")
        now = self._clock.now()
        qualification = (
            f"Dated observation report evaluated at {job.analysis.occurred_at.isoformat()}. "
            if job.analysis
            else prompt.source_qualification + " "
            if prompt.source_qualification
            else "Historical chat review; no new sensor measurement. "
        )
        return AgentQuestionRequest(
            parent_id=job.view.parent_id,
            child_id=child.child_id,
            agent_id="child-safety",
            request_id=uuid5(job.view.job_id, need.information_key),
            information_key=need.information_key,
            source_revision=child.revision,
            question=need.question,
            reason=qualification + need.reason,
            priority=need.priority,
            observed_at=now,
            expires_at=now + timedelta(days=1),
        )
