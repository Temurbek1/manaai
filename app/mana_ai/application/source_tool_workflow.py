"""One captured review, two bounded model calls and one exact shared source read."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Literal, Protocol, cast
from zoneinfo import ZoneInfo

from app.mana_ai.application.chat_ports import (
    ChatModelReceipt,
    ChatModelRejected,
    ParentChatError,
    ParentChildrenSource,
)
from app.mana_ai.application.child_safety_ports import (
    ChildSafetyStore,
    SafetyCompletion,
    SafetyPrompt,
)
from app.mana_ai.application.day_usage_service import FamilyDayUsageService
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.application.ports import Clock
from app.mana_ai.application.source_tool_ports import SourceToolModel, SourceToolPrompt
from app.mana_ai.domain.chat import ChatTokens, ParentChildContext
from app.mana_ai.domain.child_safety import ChildSafetyLimits, SafetyJob, SafetyJobView
from app.mana_ai.domain.family_day_usage import DayUsageReceipt, DayUsageTarget
from app.mana_ai.domain.family_sources import FamilySourceReceipt, FamilySourceTarget
from app.mana_ai.domain.source_reviews import SourceAnalysisOwner
from app.mana_ai.domain.source_tools import (
    SourceToolChild,
    SourceToolContinuation,
    SourceToolModelProfile,
    SourceToolPreparedInput,
    SourceToolScope,
)


class SourceToolSafetyStore(ChildSafetyStore, Protocol):
    async def source_review_owner(self, job: SafetyJob) -> SourceAnalysisOwner | None: ...
    async def native_captured(self, job: SafetyJob) -> bool: ...
    async def native_protocol(self, job: SafetyJob) -> Literal[1, 2, 3]: ...
    async def prepare_native(
        self,
        job: SafetyJob,
        prepared: SourceToolPreparedInput,
        profile: SourceToolModelProfile,
        now: "datetime",
    ) -> None: ...
    async def submit_native(
        self, job: SafetyJob, position: int, count: int, output: int, now: "datetime"
    ) -> None: ...
    async def record_native_usage(
        self, job: SafetyJob, position: int, usage: ChatTokens, model: str, now: "datetime"
    ) -> int | None: ...
    async def claim_native_source(
        self, job: SafetyJob, continuation: SourceToolContinuation, now: "datetime"
    ) -> FamilySourceTarget | DayUsageTarget: ...
    async def record_native_source(
        self, job: SafetyJob, receipt: FamilySourceReceipt | DayUsageReceipt, now: "datetime"
    ) -> bool: ...
    async def finalize_native_without_source(self, job: SafetyJob, now: "datetime") -> None: ...


class NativeSourcePrompts(Protocol):
    def build(
        self,
        job: SafetyJob,
        context: ParentChildContext,
        saved: list[SafetyJobView],
        *,
        protocol: int = 1,
    ) -> SafetyPrompt: ...


class SourceToolWorkflow:
    def __init__(
        self,
        *,
        store: SourceToolSafetyStore,
        children: ParentChildrenSource,
        model: SourceToolModel,
        prompts: NativeSourcePrompts,
        sources: FamilySourceService,
        clock: Clock,
        limits: ChildSafetyLimits,
        max_output_tokens: int,
        day_usage: FamilyDayUsageService | None = None,
    ) -> None:
        if not 32 <= max_output_tokens < limits.job_tokens:
            raise ValueError("Native source output must fit inside the captured job budget")
        self._store, self._children, self._model = store, children, model
        self._prompts, self._sources, self._clock = prompts, sources, clock
        self._limits, self._output = limits, max_output_tokens
        self._day_usage = day_usage

    async def captured(self, job: SafetyJob) -> bool:
        return await self._store.native_captured(job)

    async def _ownership(self, job: SafetyJob) -> ParentChildContext:
        context = await self._children.read(job.view.parent_id)
        context = ParentChildContext.model_validate(context.model_dump())
        now = self._clock.now()
        if context.parent_id != job.view.parent_id or not (
            now - timedelta(seconds=180) <= context.collected_at <= now + timedelta(seconds=5)
        ):
            raise ParentChatError("safety_ownership_context_invalid", 503)
        await self._store.authorize_children(
            job, tuple(sorted(c.child_id for c in context.children if c.connected)), now
        )
        return context

    async def _count(self, prompt: SourceToolPrompt, remaining: int) -> tuple[int, int]:
        size = len(prompt.input.instructions.encode()) + sum(
            len(text.encode()) for _, text in prompt.input.messages
        )
        if prompt.continuation:
            size += len(prompt.continuation.model_dump_json().encode())
        if prompt.source_result:
            size += len(prompt.source_result.model_dump_json().encode())
        if size > self._limits.max_context_bytes:
            raise ParentChatError("safety_context_too_large", 422)
        count = await self._model.count_source_input(prompt)
        if type(count) is not int or count < 0:
            raise ParentChatError("safety_token_count_invalid", 503)
        output = min(self._output, remaining - count)
        if output < 32:
            raise ParentChatError("safety_job_token_budget_exceeded", 429)
        return count, output

    async def run(self, job: SafetyJob, complete: SafetyCompletion) -> SafetyJobView:
        submitted = False
        try:
            context = await self._ownership(job)
            saved = await self._store.saved_assessments(job)
            protocol = await self._store.native_protocol(job)
            safety_prompt = self._prompts.build(job, context, saved, protocol=protocol)
            scope = SourceToolScope(
                parent_id=job.view.parent_id,
                invocation_id=job.view.job_id,
                protocol=protocol,
                calendar_today=context.collected_at.astimezone(ZoneInfo("Asia/Tashkent")).date()
                if protocol == 3
                else None,
                children=tuple(
                    SourceToolChild(alias=c.alias, child_id=c.child_id)
                    for c in safety_prompt.children
                ),
            )
            prompt = SourceToolPrompt(safety_prompt.input, scope)
            prepared = SourceToolPreparedInput(
                scope=scope,
                input_digest=self._model.source_input_digest(prompt),
                instructions=prompt.input.instructions,
                messages=tuple(
                    (cast(Literal["user", "assistant"], role), text)
                    for role, text in prompt.input.messages
                ),
                minimum_output_tokens=prompt.input.minimum_output_tokens,
            )
            await self._store.prepare_native(
                job, prepared, self._model.source_profile, self._clock.now()
            )
            count, output = await self._count(prompt, job.reserved_tokens)
            await self._store.submit_native(job, 0, count, output, self._clock.now())
            submitted = True
            receipt = await self._model.respond_source(prompt, max_output_tokens=output)
            remaining = await self._store.record_native_usage(
                job, 0, receipt.usage, receipt.model, self._clock.now()
            )
            submitted = False
            if remaining is None:
                return await self._store.assessment(job.view.parent_id, job.view.job_id)
            if not receipt.completed:
                raise ValueError("Invalid metered native source decision")
            if receipt.continuation is None:
                if receipt.answer is None:
                    raise ValueError("A final source review requires text")
                await self._store.finalize_native_without_source(job, self._clock.now())
            else:
                if receipt.answer is not None:
                    raise ValueError("A source call cannot publish accompanying prose")
                if remaining < 32:
                    raise ParentChatError("safety_job_token_budget_exceeded", 429)
                target = await self._store.claim_native_source(
                    job, receipt.continuation, self._clock.now()
                )
                owner = await self._store.source_review_owner(job)
                source: FamilySourceReceipt | DayUsageReceipt
                if isinstance(target, DayUsageTarget):
                    if self._day_usage is None:
                        raise ParentChatError("family_day_usage_not_enabled", 503)
                    source = await self._day_usage.read_for_analysis(target, owner)
                else:
                    source = (
                        await self._sources.read_for_analysis(target, owner)
                        if owner is not None
                        else await self._sources.read(target)
                    )
                if not await self._store.record_native_source(job, source, self._clock.now()):
                    raise ParentChatError("native_source_read_unavailable", 503)
                observation = (
                    source.facts.observed_at.isoformat()
                    if source.facts and source.facts.observed_at
                    else "unknown"
                )
                status = source.facts.status if source.facts else "not_returned"
                collected = (
                    source.facts.collected_at.isoformat() if source.facts else "no child facts"
                )
                safety_prompt = replace(
                    safety_prompt,
                    source_qualification=(
                        f"Parent-intent review using an own-child {status} "
                        f"{source.source} record; measurement time {observation}, "
                        f"collected {collected}. "
                        + (
                            f"Query calendar label {source.requested_day.isoformat()}, "
                            "not a verified measurement day/period. "
                            if isinstance(source, DayUsageReceipt)
                            else ""
                        )
                        + "This is source context, not a complete protective assessment."
                    ),
                )
                await self._ownership(job)  # No alias rebinding on ownership change.
                prompt = SourceToolPrompt(prompt.input, scope, receipt.continuation, source)
                count, output = await self._count(prompt, remaining)
                await self._store.submit_native(job, 1, count, output, self._clock.now())
                submitted = True
                receipt = await self._model.respond_source(prompt, max_output_tokens=output)
                eligible = await self._store.record_native_usage(
                    job, 1, receipt.usage, receipt.model, self._clock.now()
                )
                submitted = False
                if eligible is None:
                    return await self._store.assessment(job.view.parent_id, job.view.job_id)
                if (
                    not receipt.completed
                    or receipt.answer is None
                    or receipt.continuation is not None
                ):
                    raise ValueError("Invalid metered native source final")
            return await complete(
                job,
                safety_prompt,
                ChatModelReceipt(
                    usage=receipt.usage,
                    model=receipt.model,
                    answer=receipt.answer,
                    completed=True,
                ),
            )
        except ChatModelRejected:
            await self._store.fail_safety(
                job, "model_request_rejected", self._clock.now(), definite_model_rejection=True
            )
        except (Exception, asyncio.CancelledError) as error:
            code = (
                "safety_model_receipt_unknown" if submitted else "native_source_review_unavailable"
            )
            if (
                isinstance(error, ParentChatError)
                and not submitted
                and error.code
                in {
                    "safety_job_token_budget_exceeded",
                    "safety_context_too_large",
                    "safety_token_count_invalid",
                }
            ):
                code = error.code
            await asyncio.shield(self._store.fail_safety(job, code, self._clock.now()))
            if isinstance(error, asyncio.CancelledError):
                raise
        return await self._store.assessment(job.view.parent_id, job.view.job_id)
