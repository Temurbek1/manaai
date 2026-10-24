"""Independent SQL polling; only durably admitted windows permit provider I/O."""

import asyncio
import logging
from contextlib import suppress

from app.mana_ai.application.family_collection import FamilyCollectionService


class FamilyCollectionWorker:
    def __init__(self, service: FamilyCollectionService, *, interval: float = 30) -> None:
        if not 0.05 <= interval <= 60:
            raise ValueError("A bounded collection poll interval is required")
        self._service, self._interval = service, interval
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.available = True

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Collection worker already started")
        self._task = asyncio.create_task(self._run(), name="mana-family-collection")

    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                result = await self._service.process_one()
                if result is None or result.status != "collecting":
                    with suppress(TimeoutError):
                        await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.available = False
            logging.getLogger(__name__).error(
                "family_collection_worker_stopped; inspect durable state"
            )
            # No automatic restart; personal chat/safety workers remain independent.
