"""Coalesced source snapshots join the existing metered Child-Safety job queue."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from app.mana_ai.application.chat_ports import ParentChatError, ParentChildrenSource
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.child_safety import SafetyJobView
from app.mana_ai.domain.source_reviews import SourceReviewWork


class SourceReviewCache(Protocol):
    async def claim_next_review(self, now: datetime) -> SourceReviewWork | None: ...
    async def update_review(
        self, work: SourceReviewWork, *, expected_phase: str
    ) -> SourceReviewWork: ...


class SourceReviewJobs(Protocol):
    async def admit_source_review(
        self, work: SourceReviewWork, now: datetime, *, allow_new: bool
    ) -> SafetyJobView: ...
    async def observe_source_review(self, work: SourceReviewWork) -> SafetyJobView | None: ...


class SourceReviewService:
    def __init__(
        self,
        cache: SourceReviewCache,
        jobs: SourceReviewJobs,
        children: ParentChildrenSource,
        *,
        clock: Callable[[], datetime],
        available: Callable[[], bool],
    ) -> None:
        self._cache, self._jobs, self._children = cache, jobs, children
        self._clock, self._available = clock, available

    async def process_one(self) -> SourceReviewWork | None:
        work = await self._cache.claim_next_review(self._clock())
        if work is None:
            return None
        if work.phase == "preparing":
            try:
                raw = await self._children.read(work.bundle.parent_id)
                context = ParentChildContext.model_validate(raw.model_dump())
                child = next(
                    (
                        c
                        for c in context.children
                        if c.child_id == work.bundle.child_id and c.connected
                    ),
                    None,
                )
                if (
                    context.parent_id != work.bundle.parent_id
                    or child is None
                    or child.age is None
                    or not 1 <= child.age <= 17
                    or len({c.child_id for c in context.children}) != len(context.children)
                    or not self._clock() - timedelta(seconds=180)
                    <= context.collected_at
                    <= self._clock()
                ):
                    return await self._cache.update_review(
                        work.model_copy(
                            update={
                                "phase": "skipped",
                                "reason": "ownership_or_age_unknown",
                            }
                        ),
                        expected_phase="preparing",
                    )
                return await self._cache.update_review(
                    work.model_copy(
                        update={
                            "phase": "prepared",
                            "profile_collected_at": context.collected_at,
                            "child_age": child.age,
                        }
                    ),
                    expected_phase="preparing",
                )
            except asyncio.CancelledError:
                await asyncio.shield(self._unknown(work, "preparation_unknown"))
                raise
            except Exception:
                return await self._unknown(work, "preparation_unknown")
        if work.dispatch_now:
            try:
                await self._jobs.admit_source_review(
                    work, self._clock(), allow_new=self._available()
                )
            except asyncio.CancelledError:
                await asyncio.shield(self._unknown(work, "admission_unknown"))
                raise
            except ParentChatError as error:
                if error.code in {
                    "safety_queue_full",
                    "safety_context_too_large",
                    "source_review_ownership_denied",
                }:
                    known = await self._jobs.observe_source_review(work)
                    if known is None:
                        return await self._cache.update_review(
                            work.model_copy(
                                update={
                                    "phase": "skipped",
                                    "reason": "admission_refused",
                                    "dispatch_now": False,
                                }
                            ),
                            expected_phase="dispatching",
                        )
            except Exception:
                pass  # Observe the exact SQL admission before classifying a lost acknowledgement.
        known = await self._jobs.observe_source_review(work)
        return await self._cache.update_review(
            work.model_copy(
                update={
                    "phase": "admitted" if known else "unknown",
                    "reason": None if known else "admission_unknown",
                    "job_id": known.job_id if known else None,
                    "dispatch_now": False,
                }
            ),
            expected_phase="dispatching",
        )

    async def _unknown(self, work: SourceReviewWork, reason: str) -> SourceReviewWork:
        return await self._cache.update_review(
            work.model_copy(
                update={
                    "phase": "unknown",
                    "reason": reason,
                    "dispatch_now": False,
                }
            ),
            expected_phase=work.phase,
        )
