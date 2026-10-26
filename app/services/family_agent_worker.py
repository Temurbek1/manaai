import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.application.source_reviews import SourceReviewService
from app.mana_ai.application.source_safety import SourceSafetyService


class FamilyAgentWorker:
    """Poll private SQL only; new admitted events alone authorize source/model work."""

    def __init__(
        self,
        safety: ChildSafetyService,
        touch: ParentTouchService,
        *,
        clock: Callable[[], datetime],
        interval: float = 1,
        source_safety: SourceSafetyService | None = None,
        source_reviews: SourceReviewService | None = None,
        parallel_enabled: bool = False,
    ) -> None:
        self._safety, self._touch, self._clock, self._interval = safety, touch, clock, interval
        self._source_safety = source_safety
        self._source_reviews = source_reviews
        self._parallel_enabled = parallel_enabled
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._logger = logging.getLogger(__name__)

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("The family worker is already started")
        self._task = asyncio.create_task(self._run())

    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            # Cancellation records an unknown hold if inference was submitted.
            with suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._task, timeout=5)

    async def _run(self) -> None:
        try:
            if self._parallel_enabled:
                async with asyncio.TaskGroup() as group:
                    for name, step in self._lanes():
                        group.create_task(self._poll(name, step), name="mana-family-" + name)
            else:
                await self._run_serial()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._stop.set()
            self._safety.worker_available = False
            self._logger.error("family_worker_stopped; inspect durable state before restarting")
            # No automatic restart or redispatch after an unclassified storage failure.

    def _lanes(self) -> tuple[tuple[str, Callable[[], Awaitable[object]]], ...]:
        return (
            ("sources", self._process_sources),
            ("safety", self._safety.process_one),
            ("conversation", self._touch.process_reviewed_message),
            ("delivery", self._process_delivery),
            ("reminders", self._touch.process_reminders),
            ("upsell", self._touch.process_upsell),
            ("retention", self._touch.process_retention),
            ("conversion", self._touch.process_conversion),
            ("push", self._touch.process_push),
        )

    async def _poll(self, name: str, step: Callable[[], Awaitable[object]]) -> None:
        try:
            while not self._stop.is_set():
                await step()
                # One in-flight call per lane; a busy lane cannot fan out its queue.
                await self._pause()
        except asyncio.CancelledError:
            if not self._stop.is_set():
                self._safety.worker_available = False
                self._stop.set()
                # TaskGroup treats a cancelled child as a normal termination.
                # An independently lost lane must instead fence all new work.
                raise RuntimeError("family_worker_lane_cancelled") from None
            raise
        except Exception:
            self._safety.worker_available = False
            self._stop.set()
            self._logger.error("family_worker_lane_stopped; lane=%s", name)
            raise  # TaskGroup cancels siblings and awaits their durable cleanup.

    async def _process_sources(self) -> None:
        if self._source_safety is not None:
            await self._source_safety.process_one()
        if self._source_reviews is not None and not self._stop.is_set():
            await self._source_reviews.process_one()

    async def _process_delivery(self) -> None:
        delivery = await self._safety.store.next_delivery(self._clock())
        if delivery is not None and not self._stop.is_set():
            # State is durable; never retry using a new nonce. SQL still owns
            # per-parent pending-turn exclusion and current priority checks.
            with suppress(ParentChatError):
                await self._touch.deliver(delivery)

    async def _pause(self) -> None:
        with suppress(TimeoutError):
            await asyncio.wait_for(self._stop.wait(), timeout=self._interval)

    async def _run_serial(self) -> None:
        while not self._stop.is_set():
            await self._process_sources()
            processed = await self._safety.process_one()
            await self._touch.process_reviewed_message()
            await self._process_delivery()
            if not self._stop.is_set():
                await self._touch.process_reminders()
                await self._touch.process_upsell()
                await self._touch.process_retention()
                await self._touch.process_conversion()
                await self._touch.process_push()
            if processed is None:
                await self._pause()
