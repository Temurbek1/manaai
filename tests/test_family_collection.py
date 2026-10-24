"""Real source-cache/occurrence SQL, fictional population and providers only."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.mana_ai.application.family_collection import FamilyCollectionService
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.domain.chat import ChatChild, ParentChildContext
from app.mana_ai.domain.family_collection import (
    FamilyCollectionPolicy,
    FamilyCollectionWindow,
    FamilyInventoryPage,
    InventoryFamily,
    next_family_collection_window,
)
from app.mana_ai.domain.family_sources import (
    ChildAppUsageFacts,
    ChildBatteryFacts,
    FamilySourceLimits,
)
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services.family_collection_store import SqliteFamilyCollectionStore
from app.services.multi_family_source_store import SqliteMultiFamilySourceStore


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 25, 3, 59, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


class Inventory:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.calls: list[int] = []
        self.failure: BaseException | None = None

    async def read(self, offset: int, limit: int) -> FamilyInventoryPage:
        self.calls.append(offset)
        if self.failure:
            raise self.failure
        parents = (501, 502, 503)
        return FamilyInventoryPage(
            offset=offset,
            limit=limit,
            total_parents=3,
            collected_at=self.clock.now(),
            families=tuple(
                InventoryFamily(parent_id=str(p), connected_child_ids=(p + 100,))
                for p in parents[offset : offset + limit]
            ),
        )


class Profiles:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    async def read(self, parent_id: str) -> ParentChildContext:
        return ParentChildContext(
            parent_id=parent_id,
            children=[ChatChild(child_id=int(parent_id) + 100, connected=True, age=9)],
            collected_at=self.clock.now(),
            limitations=[],
        )


class Battery:
    def __init__(self, clock: Clock) -> None:
        self.clock, self.calls = clock, 0
        self.observed = datetime(2026, 10, 25, 3, 58, tzinfo=UTC)
        self.unknown = False

    async def read(self, child_id: int) -> ChildBatteryFacts:
        self.calls += 1
        if self.unknown:
            raise httpx.ReadTimeout("Synthetic collection source receipt lost")
        return ChildBatteryFacts(
            child_id=child_id,
            status="available",
            percent=12,
            observed_at=self.observed,
            source_updated_at=self.observed,
            collected_at=self.clock.now(),
            quality="dated",
        )


class Usage:
    def __init__(self, clock: Clock) -> None:
        self.clock, self.calls = clock, 0

    async def read(self, child_id: int) -> ChildAppUsageFacts:
        self.calls += 1
        return ChildAppUsageFacts(
            child_id=child_id,
            status="missing",
            entries=(),
            returned_apps=0,
            total_apps=0,
            complete=True,
            collected_at=self.clock.now(),
        )


async def setup(
    path: Path,
    clock: Clock,
    policy: FamilyCollectionPolicy | None = None,
    *,
    source_limits: FamilySourceLimits | None = None,
) -> tuple[
    FamilyCollectionService,
    SqliteFamilyCollectionStore,
    Inventory,
    Battery,
    Usage,
    SqliteMultiFamilySourceStore,
]:
    selected = policy or FamilyCollectionPolicy(page_size=2)
    store = SqliteFamilyCollectionStore(
        path / "collection.sqlite3",
        binding="fake-collection-mana",
        policy=selected,
        sources=("firebase.child_battery.v1", "manakids.child_app_usage.v1"),
    )
    await store.initialize(clock.now())
    sources = SqliteMultiFamilySourceStore(
        path / "sources.sqlite3",
        binding="fake-collection-mana",
        limits=source_limits or FamilySourceLimits(),
        policy=SourceSafetyPolicy(),
        enabled=False,
    )
    await sources.initialize()
    inventory, battery, usage = Inventory(clock), Battery(clock), Usage(clock)
    reader = FamilySourceService(
        sources, Profiles(clock), battery, clock=clock.now, app_usage=usage
    )
    service = FamilyCollectionService(store, inventory, reader, sources, clock=clock.now)
    return service, store, inventory, battery, usage, sources


async def drain(service: FamilyCollectionService) -> FamilyCollectionWindow:
    last = None
    for _ in range(100):
        result = await service.process_one()
        if result is None:
            break
        last = result
        if result.status != "collecting":
            return result
    assert last is not None
    return last


async def test_two_windows_shared_acquisition_restart_no_catchup_or_reinference(
    tmp_path: Path,
) -> None:
    clock = Clock()
    service, store, inventory, battery, usage, sources = await setup(tmp_path, clock)
    assert await service.process_one() is None and inventory.calls == []
    clock.value = datetime(2026, 10, 25, 4, tzinfo=UTC)
    first = await drain(service)
    assert (
        first.status == "completed"
        and first.pages == 2
        and first.targets == 6
        and first.parents_seen == 3
    )
    assert first.inventory_exhausted and not first.population_complete
    assert inventory.calls == [0, 2] and battery.calls == usage.calls == 3
    assert await service.process_one() is None
    restarted = await setup(tmp_path, clock)
    assert await restarted[0].process_one() is None and not restarted[2].calls
    assert (await store.latest())[0] == first
    clock.value = datetime(2026, 10, 25, 10, tzinfo=UTC)
    second = await drain(service)
    assert second.status == "completed" and second.window_id != first.window_id
    assert battery.calls == usage.calls == 6
    # Re-reading unchanged remote state does not create another change or analysis.
    with sources._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM source_changes").fetchone()[0] == 6
        assert db.execute("SELECT SUM(units) FROM source_reads").fetchone()[0] == 12
    assert len(await store.latest()) == 2
    assert next_family_collection_window(clock.now()) == datetime(2026, 10, 26, 4, tzinfo=UTC)


async def test_enable_after_slot_and_long_downtime_never_backfill(tmp_path: Path) -> None:
    clock = Clock()
    clock.value = datetime(2026, 10, 25, 4, 1, tzinfo=UTC)
    service, store, inventory, *_ = await setup(tmp_path, clock)
    assert await service.process_one() is None
    clock.value = datetime(2026, 10, 27, 11, tzinfo=UTC)
    skipped = await service.process_one()
    assert skipped and skipped.status == "skipped" and skipped.reason == "missed_window"
    assert inventory.calls == [] and await service.process_one() is None
    assert len(await store.latest()) == 1


async def test_inventory_unknown_survives_restart_and_next_slot_without_read(
    tmp_path: Path,
) -> None:
    clock = Clock()
    service, store, inventory, *_ = await setup(tmp_path, clock)
    clock.value = datetime(2026, 10, 25, 4, tzinfo=UTC)
    inventory.failure = httpx.ReadTimeout("Synthetic inventory receipt lost")
    failed = await service.process_one()
    assert failed and failed.status == "unknown" and inventory.calls == [0]
    clock.value = datetime(2026, 10, 25, 10, tzinfo=UTC)
    restarted = await setup(tmp_path, clock)
    result = await restarted[0].process_one()
    assert result and result.reason == "inventory_unknown" and not restarted[2].calls
    assert len(await store.latest()) == 2


async def test_source_unknown_blocks_only_its_target_not_the_other_provider(tmp_path: Path) -> None:
    clock = Clock()
    service, store, inventory, battery, usage, *_ = await setup(tmp_path, clock)
    clock.value = datetime(2026, 10, 25, 4, tzinfo=UTC)
    battery.unknown = True
    result = await drain(service)
    assert result.status == "unknown"
    assert battery.calls == usage.calls == 3
    assert result.counts[0].unknown == 3 and result.counts[1].completed == 3
    assert await service.process_one() is None


async def test_read_capacity_retains_backlog_for_next_allowed_window(tmp_path: Path) -> None:
    clock = Clock()
    policy = FamilyCollectionPolicy(page_size=2, reads_per_window=2)
    service, store, inventory, battery, usage, *_ = await setup(tmp_path, clock, policy)
    clock.value = datetime(2026, 10, 25, 4, tzinfo=UTC)
    first = await drain(service)
    assert first.status == "partial" and first.reason == "read_capacity" and first.targets == 2
    assert inventory.calls == [0]
    clock.value = datetime(2026, 10, 25, 10, tzinfo=UTC)
    second = await drain(service)
    assert second.targets == 2 and inventory.calls == [0]
    assert battery.calls == usage.calls == 2
    assert await store.manifest(first.window_id) == first


async def test_policy_change_refuses_to_reset_occurrences(tmp_path: Path) -> None:
    clock = Clock()
    await setup(tmp_path, clock)
    with pytest.raises(ValueError, match="policy/binding"):
        await setup(tmp_path, clock, FamilyCollectionPolicy(page_size=3))


async def test_two_connections_claim_one_inventory_and_lost_ack_is_sql_only(
    tmp_path: Path,
) -> None:
    import asyncio

    from app.mana_ai.domain.family_collection import FamilyCollectionWork

    clock = Clock()
    service, store, inventory, battery, usage, sources = await setup(tmp_path, clock)
    other = (await setup(tmp_path, clock))[1]
    clock.value = datetime(2026, 10, 25, 4, tzinfo=UTC)
    claims = await asyncio.gather(store.claim_next(clock.now()), other.claim_next(clock.now()))
    admitted = [c for c in claims if isinstance(c, FamilyCollectionWork)]
    assert len(admitted) == 1 and admitted[0].kind == "inventory"
    page = await inventory.read(0, store.page_size)
    await store.finish_page(admitted[0], page, clock.now())
    # The caller lost only the completion acknowledgement, not the committed page.
    await store.fail_page(admitted[0], "inventory_unknown", clock.now(), unknown=True)
    result = await drain(service)
    assert result.status == "completed" and inventory.calls == [0, 2]
    assert battery.calls == usage.calls == 3


async def test_claim_lost_before_dispatch_is_never_reissued_and_publication_is_immutable(
    tmp_path: Path,
) -> None:
    from datetime import timedelta

    from app.mana_ai.domain.family_collection import FamilyCollectionWork

    clock = Clock()
    service, store, inventory, *_ = await setup(tmp_path, clock)
    clock.value = datetime(2026, 10, 25, 4, tzinfo=UTC)
    work = await store.claim_next(clock.now())
    assert isinstance(work, FamilyCollectionWork) and work.kind == "inventory"
    clock.value += timedelta(hours=1)
    assert await service.process_one() is None
    original = (await store.latest())[0]
    assert original.status == "unknown" and original.published_at is not None
    clock.value = datetime(2026, 10, 25, 10, tzinfo=UTC)
    later = await service.process_one()
    assert later and later.reason == "inventory_unknown" and inventory.calls == []
    assert await store.manifest(original.window_id) == original


async def test_lost_source_ack_observes_existing_receipt_without_another_source_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    service, store, inventory, battery, usage, sources = await setup(tmp_path, clock)
    original = store.finish_source
    lost = False

    from app.mana_ai.domain.family_collection import FamilyCollectionWork
    from app.mana_ai.domain.family_sources import FamilySourceReceipt

    async def lose_ack(
        work: FamilyCollectionWork,
        receipt: FamilySourceReceipt | None,
        now: datetime,
        *,
        refusal: str | None = None,
        stop_window: bool = False,
    ) -> None:
        nonlocal lost
        if not lost:
            lost = True
            raise RuntimeError("Synthetic local completion acknowledgement loss")
        await original(work, receipt, now, refusal=refusal, stop_window=stop_window)

    monkeypatch.setattr(store, "finish_source", lose_ack)
    clock.value = datetime(2026, 10, 25, 4, tzinfo=UTC)
    result = await drain(service)
    assert result.status == "completed" and battery.calls == usage.calls == 3
    assert result.counts[0].completed == result.counts[1].completed == 3


async def test_revoked_membership_cannot_publish_inventory_children_as_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    service, store, inventory, battery, usage, sources = await setup(tmp_path, clock)

    async def revoked(parent_id: str) -> ParentChildContext:
        return ParentChildContext(
            parent_id=parent_id, children=[], collected_at=clock.now(), limitations=[]
        )

    monkeypatch.setattr(service._sources._children, "read", revoked)
    clock.value = datetime(2026, 10, 25, 4, tzinfo=UTC)
    result = await drain(service)
    assert result.status == "partial" and result.reason == "source_refused_or_failed"
    assert battery.calls == usage.calls == 0
    assert all(c.available == 0 and c.failed == 3 for c in result.counts)


async def test_source_capacity_stops_before_more_provider_io(tmp_path: Path) -> None:
    clock = Clock()
    service, store, inventory, battery, usage, sources = await setup(
        tmp_path, clock, source_limits=FamilySourceLimits(requests_per_24h=1)
    )
    clock.value = datetime(2026, 10, 25, 4, tzinfo=UTC)
    result = await drain(service)
    assert result.status == "partial" and result.reason == "family_source_request_limit"
    assert battery.calls + usage.calls == 1 and inventory.calls == [0]
