"""Two explicit fictional time windows; never permits paid models or real sources."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.family_collection import FamilyCollectionService
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.domain.family_collection import (
    FamilyCollectionPolicy,
    FamilyCollectionWindow,
    FamilyInventoryPage,
    InventoryFamily,
)
from app.services.family_collection_store import SqliteFamilyCollectionStore
from app.services.multi_family_source_store import SqliteMultiFamilySourceStore


class LabCollectionClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 10, 25, 3, 59, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def restore(self, value: datetime) -> None:
        if value not in {
            datetime(2026, 10, 25, 4, tzinfo=UTC),
            datetime(2026, 10, 25, 10, tzinfo=UTC),
        }:
            raise ValueError("Unsupported fictional collection clock")
        self._now = max(self._now, value)

    def advance(self, hour: Literal[9, 15]) -> None:
        target = datetime(2026, 10, 25, hour - 5, tzinfo=UTC)
        if target > self._now and hour == 15 and self._now.hour != 4:
            raise ParentChatError("lab_collect_morning_first", 409)
        self._now = max(self._now, target)


async def lab_collection_store(
    directory: Path, clock: LabCollectionClock
) -> SqliteFamilyCollectionStore:
    store = SqliteFamilyCollectionStore(
        directory / "collection.sqlite3",
        binding="fake-lab-mana",
        policy=FamilyCollectionPolicy(page_size=1, reads_per_window=4),
        sources=("firebase.child_battery.v1", "manakids.child_app_usage.v1"),
    )
    await store.initialize(clock.now())
    latest = await store.latest(1)
    if latest:
        clock.restore(latest[0].scheduled_at)
    return store


class LabInventory:
    def __init__(self, clock: LabCollectionClock, parent_id: str, child_id: int) -> None:
        self._clock, self._parent, self._child = clock, parent_id, child_id
        self.calls = 0

    async def read(self, offset: int, limit: int) -> FamilyInventoryPage:
        self.calls += 1
        return FamilyInventoryPage(
            offset=offset,
            limit=limit,
            total_parents=1,
            families=(InventoryFamily(parent_id=self._parent, connected_child_ids=(self._child,)),)
            if offset == 0
            else (),
            collected_at=self._clock.now(),
        )


class LabCollection:
    def __init__(
        self,
        store: SqliteFamilyCollectionStore,
        clock: LabCollectionClock,
        reads: FamilySourceService,
        observations: SqliteMultiFamilySourceStore,
        *,
        parent_id: str,
        child_id: int,
    ) -> None:
        self.store, self.clock = store, clock
        self.inventory = LabInventory(clock, parent_id, child_id)
        self.service = FamilyCollectionService(
            store, self.inventory, reads, observations, clock=clock.now
        )

    async def collect(self, hour: Literal[9, 15]) -> FamilyCollectionWindow:
        for window in await self.store.latest():
            if window.scheduled_at.hour == hour - 5:
                return window  # Including a lost/unknown outcome: observation never redispatches.
        self.clock.advance(hour)
        last = None
        for _ in range(12):
            result = await self.service.process_one()
            if result is None:
                break
            last = result
            if result.status != "collecting":
                return result
        if last is not None:
            return last
        raise ParentChatError("lab_collection_not_admitted", 409)
