"""Declared fictional last-point metadata; no Google client, coordinates or live key."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.mana_ai.domain.child_location import ChildLocationFacts


class LabLocationSource:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self.calls = 0

    async def read(self, child_id: int) -> ChildLocationFacts:
        self.calls += 1
        now = self._clock()
        observed = datetime(2026, 10, 14, 9, tzinfo=UTC)
        return ChildLocationFacts(
            child_id=child_id,
            status="available",
            position_fingerprint="c" * 64,
            observed_at=observed,
            source_updated_at=observed + timedelta(seconds=1),
            collected_at=now,
            quality="dated",
            mock=False,
            sample=False,
            is_moving=False,
            accuracy_reported=True,
        )
