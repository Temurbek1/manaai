"""Actual v2/v3 queues, captured window policy and one shared source-read ceiling."""

import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.mana_ai.domain.family_collection import (
    FamilyCollectionPolicy,
    FamilyCollectionWindow,
    FamilyCollectionWork,
)
from app.mana_ai.domain.family_day_usage import DAY_USAGE_SOURCE, DayUsageTarget
from app.mana_ai.domain.inventory_tariffs import InventoryTariffPolicy
from app.services.dated_collection_store import SqliteDatedCollectionStore
from app.services.inventory_tariff_store import SqliteInventoryTariffStore
from app.services.lab_collection import LabCollectionClock, LabInventory


def store(
    path: Path, *, dated: bool = False, legacy: bool = False, limit: int = 50
) -> SqliteInventoryTariffStore:
    cls = SqliteInventoryTariffStore if legacy else SqliteDatedCollectionStore
    extra: dict[str, Any] = (
        {} if legacy else {"dated_enabled": dated, "source_binding": "fictional-dated-source-v1"}
    )
    return cls(
        path,
        binding="fictional-collection",
        policy=FamilyCollectionPolicy(page_size=1, reads_per_window=limit),
        sources=("firebase.child_battery.v1", "manakids.child_app_usage.v1"),
        tariff_policy=InventoryTariffPolicy(),
        recipient_binding="fictional-family",
        tariffs_enabled=False,
        **extra,
    )


async def page(
    current: SqliteInventoryTariffStore, clock: LabCollectionClock
) -> FamilyCollectionWork:
    work = await current.claim_next(clock.now())
    assert isinstance(work, FamilyCollectionWork) and work.kind == "inventory"
    data = await LabInventory(clock, "900001", 900002).read(work.offset, 1)
    await current.finish_page(work, data, clock.now())
    return work


async def close(
    current: SqliteInventoryTariffStore, clock: LabCollectionClock
) -> FamilyCollectionWindow:
    for _ in range(5):
        work = await current.claim_next(clock.now())
        if isinstance(work, FamilyCollectionWindow):
            return work
        assert isinstance(work, FamilyCollectionWork) and work.kind == "source"
        await current.finish_source(work, None, clock.now(), refusal="family_source_not_enabled")
    raise AssertionError("Fixture window must close without external I/O")


async def test_pre_upgrade_page_and_window_never_gain_a_new_source(tmp_path: Path) -> None:
    path = tmp_path / "collection.sqlite3"
    clock = LabCollectionClock()
    old = store(path, legacy=True)
    await old.initialize(clock.now())
    clock.advance(9)
    work = await old.claim_next(clock.now())
    assert isinstance(work, FamilyCollectionWork)
    current = store(path, dated=True)
    await current.initialize(clock.now())
    data = await LabInventory(clock, "900001", 900002).read(0, 1)
    await current.finish_page(work, data, clock.now())
    morning = await close(current, clock)
    assert DAY_USAGE_SOURCE not in {c.source for c in morning.counts}
    clock.advance(15)
    await page(current, clock)
    dated = await current.claim_next(clock.now())
    assert isinstance(dated, FamilyCollectionWork) and isinstance(dated.target, DayUsageTarget)
    assert dated.target.requested_day.isoformat() == "2026-10-24"


async def test_disabled_new_window_does_not_upgrade_when_flag_reenabled(tmp_path: Path) -> None:
    path = tmp_path / "collection.sqlite3"
    clock = LabCollectionClock()
    current = store(path)
    await current.initialize(clock.now())
    clock.advance(9)
    work = await current.claim_next(clock.now())
    assert isinstance(work, FamilyCollectionWork)
    assert isinstance(current, SqliteDatedCollectionStore)
    current._dated_enabled = True
    data = await LabInventory(clock, "900001", 900002).read(0, 1)
    await current.finish_page(work, data, clock.now())
    result = await close(current, clock)
    assert DAY_USAGE_SOURCE not in {c.source for c in result.counts}


async def test_day_work_shares_the_existing_window_read_limit(tmp_path: Path) -> None:
    clock = LabCollectionClock()
    current = store(tmp_path / "collection.sqlite3", dated=True, limit=1)
    await current.initialize(clock.now())
    clock.advance(9)
    await page(current, clock)
    work = await current.claim_next(clock.now())
    assert isinstance(work, FamilyCollectionWork) and isinstance(work.target, DayUsageTarget)
    await current.finish_source(work, None, clock.now(), refusal="family_source_not_enabled")
    result = await current.claim_next(clock.now())
    assert isinstance(result, FamilyCollectionWindow) and result.status == "partial"
    assert result.reason == "read_capacity" and result.targets == 1


async def test_stopping_new_dated_window_preserves_original_pending_claim(tmp_path: Path) -> None:
    clock = LabCollectionClock()
    path = tmp_path / "collection.sqlite3"
    current = store(path, dated=True)
    await current.initialize(clock.now())
    clock.advance(9)
    await page(current, clock)
    original = await current.claim_next(clock.now())
    assert isinstance(original, FamilyCollectionWork) and isinstance(
        original.target, DayUsageTarget
    )
    stopped = store(path, dated=False)
    await stopped.initialize(clock.now())
    result = await stopped.claim_next(clock.now())
    assert (
        isinstance(result, FamilyCollectionWindow) and result.reason == "dated_collection_disabled"
    )
    observed = await stopped.claim_next(clock.now())
    # Stopping/expiring the claim permits SQL observation only, never redispatch.
    if observed is None:
        observed = await stopped.claim_next(clock.now() + timedelta(seconds=121))
    assert isinstance(observed, FamilyCollectionWork) and observed.kind == "observe_source"
    assert observed.target == original.target and observed.claim_id == original.claim_id


async def test_old_v2_refuses_v3_without_changing_bytes(tmp_path: Path) -> None:
    clock = LabCollectionClock()
    path = tmp_path / "collection.sqlite3"
    current = store(path, dated=True)
    await current.initialize(clock.now())
    clock.advance(9)
    await page(current, clock)
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        await store(path, legacy=True).initialize(clock.now())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original
