"""Durable fan-out reuses one known inventory page, including first-time parents."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.mana_ai.application.setup_collection import SetupCollectionService
from app.mana_ai.domain.family_collection import FamilyCollectionPolicy, FamilyCollectionWork
from app.mana_ai.domain.inventory_tariffs import InventoryTariffPolicy, TariffInventoryPage
from app.mana_ai.domain.parent_setup import ParentSetupFact, ParentSetupPolicy
from app.services.parent_setup_store import SqliteParentSetupStore
from app.services.setup_collection_store import SqliteSetupCollectionStore
from tests.test_inventory_tariffs import Inventory as BaseInventory
from tests.test_parent_setup import contact, setup


class Inventory(BaseInventory):
    async def read(self, offset: int, limit: int) -> TariffInventoryPage:
        result = await super().read(offset, limit)
        return result.model_copy(
            update={
                "families": tuple(
                    f.model_copy(update={"children_complete": True}) for f in result.families
                )
            }
        )


def store(path: Path, *, enabled: bool = True) -> SqliteSetupCollectionStore:
    return SqliteSetupCollectionStore(
        path,
        binding="fake-mana",
        policy=FamilyCollectionPolicy(page_size=1),
        sources=("firebase.child_battery.v1",),
        tariff_policy=InventoryTariffPolicy(),
        recipient_binding="fake-family",
        tariffs_enabled=True,
        source_binding="fake-source",
        dated_enabled=False,
        location_enabled=False,
        setup_enabled=enabled,
        setup_recipient_binding="fake-family",
        setup_policy=ParentSetupPolicy(),
    )


@pytest.mark.parametrize("lost", [False, True])
async def test_one_inventory_page_same_receipt_setup_and_tariffs_no_child_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lost: bool
) -> None:
    lab, clock = await setup(tmp_path / "family")
    ledger = store(tmp_path / "collection.sqlite3")
    await ledger.initialize(clock.now())
    inventory = Inventory(clock)
    assert isinstance(lab.store, SqliteParentSetupStore)
    calls = 0
    original = lab.store.observe_setup_facts

    async def receive(facts: tuple[ParentSetupFact, ...], now: datetime) -> bool:
        nonlocal calls
        calls += 1
        result = await original(facts, now)
        if lost:
            raise OSError("fake lost local acknowledgement")
        return result

    monkeypatch.setattr(lab.store, "observe_setup_facts", receive)
    flow = SetupCollectionService(
        store=ledger,
        setup_receiver=lab.store,
        inventory=inventory,
        sources=lab.sources,
        observations=lab.source_store,
        receiver=lab.store,
        clock=clock.now,
        day_usage=None,
        day_observations=lab.source_store,
    )
    try:
        await contact(lab)
        clock.value += timedelta(hours=1)
        await flow.process_one()  # One physical inventory page, captured before its lookup.
        await flow.process_one()  # Exact local setup receipt fan-out.
        await flow.process_one()  # Existing tariff fan-out shares the original page.
        assert inventory.calls == 1 and calls == 1
        assert await lab.store.publish_setup(clock.now())
        for _ in range(4):
            await flow.process_one()
        assert inventory.calls == calls == 1
        with ledger._connection() as db:
            assert db.execute("SELECT phase FROM collection_setup_batches").fetchone()[0] == (
                "unknown" if lost else "applied"
            )
            assert (
                db.execute("SELECT phase FROM collection_tariff_batches").fetchone()[0] == "applied"
            )
        state = await lab.state()
        assert len(state.history.messages) == 1 and state.history.active_question
        assert state.history.quota.used_tokens == state.safety_budget.server_used_tokens == 0
        assert lab.battery.calls == lab.app_usage.calls == lab.catalog.calls == 0
        reopened = store(tmp_path / "collection.sqlite3")
        await reopened.initialize(clock.now())
        assert await reopened.claim_setup(clock.now()) is None
    finally:
        await lab.close()


async def test_old_page_disable_capture_and_unknown_claim_never_upgrade(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "family")
    ledger = store(tmp_path / "collection.sqlite3", enabled=False)
    await ledger.initialize(clock.now())
    inventory = Inventory(clock)
    try:
        clock.value += timedelta(hours=1)
        work = await ledger.claim_next(clock.now())
        assert isinstance(work, FamilyCollectionWork) and work.kind == "inventory"
        page = await inventory.read(work.offset, ledger.policy.page_size)
        ledger._setup_enabled = True
        await ledger.finish_page(work, page, clock.now())
        assert await ledger.claim_setup(clock.now()) is None
        with ledger._connection() as db:
            assert db.execute("SELECT enabled FROM collection_setup_captures").fetchone()[0] == 0
            assert not db.execute("SELECT 1 FROM collection_setup_batches").fetchone()
    finally:
        await lab.close()


@pytest.mark.parametrize("newer", [False, True])
async def test_incomplete_page_invalidates_only_earlier_empty_head_without_new_read(
    tmp_path: Path,
    newer: bool,
) -> None:
    lab, clock = await setup(tmp_path / "family")
    ledger = store(tmp_path / "collection.sqlite3")
    await ledger.initialize(clock.now())
    inventory = BaseInventory(clock)  # Its legacy page deliberately has no completeness proof.
    assert isinstance(lab.store, SqliteParentSetupStore)
    flow = SetupCollectionService(
        store=ledger,
        setup_receiver=lab.store,
        inventory=inventory,
        sources=lab.sources,
        observations=lab.source_store,
        receiver=lab.store,
        clock=clock.now,
        day_usage=None,
        day_observations=lab.source_store,
    )
    try:
        await contact(lab)
        clock.value += timedelta(hours=1)
        await lab.store.observe_setup_facts(
            (
                ParentSetupFact(
                    parent_id="900001", connected_child_ids=(), collected_at=clock.now()
                ),
            ),
            clock.now(),
        )
        clock.value += timedelta(seconds=1)
        await flow.process_one()
        if newer:
            clock.value += timedelta(seconds=1)
            await lab.store.observe_setup_facts(
                (
                    ParentSetupFact(
                        parent_id="900001", connected_child_ids=(), collected_at=clock.now()
                    ),
                ),
                clock.now(),
            )
        await flow.process_one()
        assert await lab.store.publish_setup(clock.now()) is newer
        assert await ledger.claim_setup(clock.now()) is None
        assert inventory.calls == 1
        with ledger._connection() as db:
            row = db.execute("SELECT phase,payload FROM collection_setup_batches").fetchone()
            assert row[0] == "applied"
            assert '"unknown_parent_ids":["900001"]' in row[1]
        assert len((await lab.state()).history.messages) == int(newer)
    finally:
        await lab.close()


async def test_claim_unknown_across_restart_and_day_change_cannot_be_replayed(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "family")
    ledger = store(tmp_path / "collection.sqlite3")
    await ledger.initialize(clock.now())
    inventory = Inventory(clock)
    try:
        clock.value += timedelta(hours=1)
        work = await ledger.claim_next(clock.now())
        assert isinstance(work, FamilyCollectionWork) and work.kind == "inventory"
        await ledger.finish_page(
            work, await inventory.read(work.offset, ledger.policy.page_size), clock.now()
        )
        claimed = await ledger.claim_setup(clock.now())
        assert claimed
        other = store(tmp_path / "collection.sqlite3")
        await other.initialize(clock.now())
        assert await other.claim_setup(clock.now()) is None
        clock.value += timedelta(days=1)
        assert await other.claim_setup(clock.now()) is None
        with other._connection() as db:
            assert (
                db.execute("SELECT phase FROM collection_setup_batches").fetchone()[0] == "unknown"
            )
        # A matching late known answer still cannot change the terminal unknown.
        await other.finish_setup(claimed, clock.now(), accepted=True)
        with other._connection() as db:
            assert (
                db.execute("SELECT phase FROM collection_setup_batches").fetchone()[0] == "unknown"
            )
        assert inventory.calls == 1
    finally:
        await lab.close()
