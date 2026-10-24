import asyncio
import logging
from collections.abc import Callable
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
    ) -> None:
        self._safety, self._touch, self._clock, self._interval = safety, touch, clock, interval
        self._source_safety = source_safety
        self._source_reviews = source_reviews
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
            while not self._stop.is_set():
                if self._source_safety is not None:
                    await self._source_safety.process_one()
                if self._source_reviews is not None:
                    await self._source_reviews.process_one()
                processed = await self._safety.process_one()
                await self._touch.process_reviewed_message()
                delivery = await self._safety.store.next_delivery(self._clock())
                if delivery is not None and not self._stop.is_set():
                    # State is durable; never retry using a new nonce.
                    with suppress(ParentChatError):
                        await self._touch.deliver(delivery)
                if not self._stop.is_set():
                    await self._touch.process_conversion()
                    await self._touch.process_push()
                if processed is None:
                    with suppress(TimeoutError):
                        await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._safety.worker_available = False
            self._logger.error("family_worker_stopped; inspect durable state before restarting")
            # No automatic restart or redispatch after an unclassified storage failure.
