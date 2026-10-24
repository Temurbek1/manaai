"""One source-change -> existing Child-Safety admission, never another speaker."""

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid5

from app.mana_ai.application.chat_ports import ParentChatError, ParentChildrenSource
from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.child_safety import SafetyTarget
from app.mana_ai.domain.enums import AgeBand
from app.mana_ai.domain.requests import SafetyMonitorInput, SafetyMonitorRequest
from app.mana_ai.domain.signals import BatterySignal, SubjectContext
from app.mana_ai.domain.source_safety import (
    SourceSafetyIntent,
    SourceSafetyPolicy,
    SourceSafetyReason,
    SourceSafetyReceipt,
    SourceSafetyWork,
)


def battery_semantics(percent: int, observed_at: datetime) -> str:
    stamp = observed_at.astimezone(UTC).isoformat()
    return hashlib.sha256(f"{percent}:{stamp}".encode()).hexdigest()


def source_age_band(age: int) -> AgeBand:
    if age < 7:
        return AgeBand.UNDER_7
    if age <= 12:
        return AgeBand.AGE_7_12
    return AgeBand.AGE_13_15 if age <= 15 else AgeBand.AGE_16_17


def battery_safety_intent(
    work: SourceSafetyWork,
    policy: SourceSafetyPolicy,
    *,
    age: int,
    profile_collected_at: datetime,
) -> SourceSafetyIntent:
    facts = work.facts
    assert facts.percent is not None and facts.observed_at is not None
    identity = uuid5(work.event.event_id, "source-battery-safety-v1")
    revision = battery_semantics(facts.percent, facts.observed_at)
    return SourceSafetyIntent(
        target=SafetyTarget(
            parent_id=work.receipt.parent_id,
            child_id=facts.child_id,
            request_id=identity,
            source_revision=revision,
        ),
        child_age=age,
        profile_collected_at=profile_collected_at,
        analysis=SafetyMonitorRequest(
            request_id=str(identity),
            occurred_at=facts.observed_at,
            locale="en",  # Internal analysis presentation, never recipient authority.
            data_minimized=True,
            subject=SubjectContext(
                subject_id=str(facts.child_id),
                age_band=source_age_band(age),
                timezone=policy.timezone,
                policy_version="source-battery-safety-v1",
            ),
            input=SafetyMonitorInput(
                battery=[
                    BatterySignal(
                        evidence_id="battery-" + revision,
                        observed_at=facts.observed_at,
                        percent=facts.percent,
                        online=None,
                    )
                ]
            ),
        ),
    )


class SourceSafetyStore(Protocol):
    async def claim_next_dispatch(self, now: datetime) -> SourceSafetyWork | None: ...

    async def prepare_dispatch(
        self, event_id: UUID, intent: SourceSafetyIntent, now: datetime
    ) -> SourceSafetyReceipt: ...

    async def finish_dispatch(
        self,
        event_id: UUID,
        now: datetime,
        *,
        reason: SourceSafetyReason | None = None,
        unknown: bool = False,
        job_id: UUID | None = None,
    ) -> SourceSafetyReceipt: ...

    async def dispatch_work(self, parent_id: str, event_id: UUID) -> SourceSafetyWork: ...


class SourceSafetyService:
    def __init__(
        self,
        store: SourceSafetyStore,
        safety: ChildSafetyService,
        children: ParentChildrenSource,
        *,
        policy: SourceSafetyPolicy,
        clock: Callable[[], datetime],
    ) -> None:
        self._store, self._safety, self._children = store, safety, children
        self._policy, self._clock = policy, clock

    async def process_one(self) -> SourceSafetyReceipt | None:
        work = await self._store.claim_next_dispatch(self._clock())
        if work is None:
            return None
        if work.receipt.phase == "skipped":
            return work.receipt
        if work.receipt.phase == "preparing":
            return await self._prepare(work)
        if work.dispatch_now:
            return await self._admit(work)
        return await self._reconcile(work)

    async def _prepare(self, work: SourceSafetyWork) -> SourceSafetyReceipt:
        try:
            raw = await self._children.read(work.receipt.parent_id)
            context = ParentChildContext.model_validate(raw.model_dump())
            now = self._clock()
            children = [
                child
                for child in context.children
                if child.child_id == work.receipt.child_id and child.connected
            ]
            if (
                context.parent_id != work.receipt.parent_id
                or not now - timedelta(seconds=180) <= context.collected_at <= now
                or len({child.child_id for child in context.children}) != len(context.children)
                or len(children) != 1
            ):
                return await self._store.finish_dispatch(
                    work.receipt.event_id, now, reason="ownership_denied"
                )
            age = children[0].age
            if age is None:
                return await self._store.finish_dispatch(
                    work.receipt.event_id, now, reason="age_unknown"
                )
            intent = battery_safety_intent(
                work, self._policy, age=age, profile_collected_at=context.collected_at
            )
            return await self._store.prepare_dispatch(work.event.event_id, intent, self._clock())
        except asyncio.CancelledError:
            await asyncio.shield(
                self._store.finish_dispatch(
                    work.receipt.event_id, self._clock(), reason="preparation_unknown", unknown=True
                )
            )
            raise
        except Exception:
            return await self._store.finish_dispatch(
                work.receipt.event_id, self._clock(), reason="preparation_unknown", unknown=True
            )

    async def _admit(self, work: SourceSafetyWork) -> SourceSafetyReceipt:
        assert work.intent is not None
        try:
            await self._safety.admit(work.intent.target, work.intent.analysis)
        except asyncio.CancelledError:
            await asyncio.shield(
                self._store.finish_dispatch(
                    work.event.event_id, self._clock(), reason="admission_unknown", unknown=True
                )
            )
            raise
        except ParentChatError as exc:
            # Even a refusal is first reconciled against the exact local SQL ID.
            reason: SourceSafetyReason = (
                "admission_refused"
                if exc.code
                in {
                    "child_safety_worker_unavailable",
                    "safety_queue_full",
                    "safety_context_too_large",
                    "safety_observation_in_future",
                    "safety_subject_mismatch",
                    "safety_capability_not_owned",
                }
                else "admission_unknown"
            )
            return await self._reconcile(work, reason=reason)
        except Exception:
            return await self._reconcile(work)
        return await self._reconcile(work)

    async def _reconcile(
        self, work: SourceSafetyWork, *, reason: SourceSafetyReason = "admission_unknown"
    ) -> SourceSafetyReceipt:
        assert work.intent is not None
        known = await self._safety.store.observe_analysis_request(
            work.intent.target, work.intent.analysis
        )
        return await self._store.finish_dispatch(
            work.event.event_id,
            self._clock(),
            job_id=known.job_id if known is not None else None,
            reason=None if known is not None else reason,
            unknown=known is None and reason != "admission_refused",
        )

    async def observe(self, parent_id: str, event_id: UUID) -> SourceSafetyReceipt:
        work = await self._store.dispatch_work(parent_id, event_id)
        if (
            work.receipt.phase in {"dispatching", "unknown"}
            and work.intent is not None
            and work.receipt.reason != "preparation_unknown"
        ):
            return await self._reconcile(work)  # SQL observation only, never an admission retry.
        return work.receipt
