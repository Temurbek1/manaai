"""Known page -> durable batch -> shared cache -> sole speaker; fake providers only."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pytest import MonkeyPatch

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.inventory_tariffs import TariffCollectionService
from app.mana_ai.domain.family_collection import (
    FamilyCollectionPolicy,
    FamilyCollectionWork,
    FamilyInventoryPage,
    InventoryFamily,
)
from app.mana_ai.domain.inventory_tariffs import InventoryTariffPolicy, TariffInventoryPage
from app.mana_ai.domain.retention_expiry import RetentionExpiryPolicy, RetentionTariffFact
from app.services.family_collection_store import SqliteFamilyCollectionStore
from app.services.inventory_tariff_store import SqliteInventoryTariffStore
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.manakids_family_inventory import ManakidsFamilyInventory
from app.services.retention_expiry_store import SqliteRetentionExpiryStore
from tests.test_family_collection_adapters import NOW, Auth, page
from tests.test_mana_chat_lab import Clock
from tests.test_retention_expiry import setup


class Inventory:
    def __init__(self, clock: Clock) -> None:
        self.clock, self.calls = clock, 0
        self.deadline = clock.now() + timedelta(days=2)
        self.failure: Exception | None = None
        self.delay = 0
        self.children: tuple[int, ...] = ()

    async def read(self, offset: int, limit: int) -> TariffInventoryPage:
        self.calls += 1
        if self.failure:
            raise self.failure
        result = TariffInventoryPage(
            offset=offset,
            limit=limit,
            total_parents=1,
            collected_at=self.clock.now(),
            families=(InventoryFamily(parent_id=LAB_PARENT, connected_child_ids=self.children),),
            tariff_facts=(
                RetentionTariffFact(
                    parent_id=LAB_PARENT,
                    collected_at=self.clock.now(),
                    is_paid=True,
                    valid_until=self.deadline,
                ),
            ),
        )
        self.clock.value += timedelta(seconds=self.delay)
        return result


def store(path: Path, *, enabled: bool = True) -> SqliteInventoryTariffStore:
    return SqliteInventoryTariffStore(
        path,
        binding="fake-mana",
        policy=FamilyCollectionPolicy(page_size=1),
        sources=("firebase.child_battery.v1",),
        tariff_policy=InventoryTariffPolicy(),
        recipient_binding="fictional-family-v17",
        tariffs_enabled=enabled,
    )


async def scenario(
    path: Path,
) -> tuple[ChatLab, Clock, SqliteInventoryTariffStore, Inventory, TariffCollectionService]:
    lab, clock = await setup(path / "family")
    ledger = store(path / "collection.sqlite3")
    await ledger.initialize(clock.now())
    inventory = Inventory(clock)
    assert isinstance(lab.store, SqliteRetentionExpiryStore)
    service = TariffCollectionService(
        ledger, inventory, lab.sources, lab.source_store, receiver=lab.store, clock=clock.now
    )
    clock.value += timedelta(hours=1)  # The next named 15:00 Tashkent window.
    return lab, clock, ledger, inventory, service


async def test_bulk_page_starts_parent_chat_without_targeted_profile_or_child_reads(
    tmp_path: Path,
) -> None:
    lab, clock, ledger, inventory, service = await scenario(tmp_path)
    try:
        assert isinstance(lab.store, SqliteRetentionExpiryStore)
        await service.process_one()
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM retention_tariff_heads").fetchone()
        with ledger._connection() as db:
            assert db.execute("SELECT phase FROM collection_pages").fetchone()[0] == "recorded"
            assert (
                db.execute("SELECT phase FROM collection_tariff_batches").fetchone()[0] == "waiting"
            )
        await service.process_one()
        assert await lab.touch.process_retention()
        for _ in range(4):
            await service.process_one()
        assert not await lab.touch.process_retention()
        state = await lab.state()
        assert len(state.history.messages) == 1 and state.history.messages[0].role == "assistant"
        assert state.history.quota.used_tokens == state.safety_budget.server_used_tokens == 0
        assert (
            inventory.calls == 1
            and lab.battery.calls == lab.app_usage.calls == lab.catalog.calls == 0
        )
        assert (await ledger.latest())[0].parents_seen == 1
        assert (await ledger.latest())[0].targets == 0
        # This also works for a discovered parent with no queued child source target.
        assert (await ledger.latest())[0].population_complete is False
    finally:
        await lab.close()


@pytest.mark.parametrize("lost", ["page", "cache", "completion"])
async def test_lost_local_ack_never_repeats_page_or_batch(
    tmp_path: Path, monkeypatch: MonkeyPatch, lost: str
) -> None:
    lab, clock, ledger, inventory, service = await scenario(tmp_path)
    calls = 0
    assert isinstance(lab.store, SqliteRetentionExpiryStore)
    original = lab.store.observe_inventory_tariffs

    async def receive(facts: tuple[RetentionTariffFact, ...], now: datetime) -> bool:
        nonlocal calls
        calls += 1
        result = await original(facts, now)
        if lost == "cache":
            raise OSError("fictional lost cache acknowledgement")
        return result

    monkeypatch.setattr(lab.store, "observe_inventory_tariffs", receive)
    if lost in {"page", "completion"}:
        target = "finish_page" if lost == "page" else "finish_tariffs"
        method = getattr(ledger, target)

        async def lose(*args: Any, **kwargs: Any) -> None:
            await method(*args, **kwargs)
            raise OSError("fictional lost committed acknowledgement")

        monkeypatch.setattr(ledger, target, lose)
    try:
        await service.process_one()
        if lost == "completion":
            with pytest.raises(OSError):
                await service.process_one()
            monkeypatch.setattr(ledger, target, method)
        else:
            await service.process_one()
        for _ in range(3):
            await service.process_one()
        assert calls == inventory.calls == 1
        with ledger._connection() as db:
            assert db.execute("SELECT phase FROM collection_tariff_batches").fetchone()[0] == (
                "unknown" if lost == "cache" else "applied"
            )
        # The external page itself is known; a local acknowledgement loss is not a lost source read.
        assert await lab.touch.process_retention()
        assert not await lab.touch.process_retention()
        assert len((await lab.state()).history.messages) == 1
    finally:
        await lab.close()


@pytest.mark.parametrize("case", ["unknown", "late", "stale"])
async def test_unknown_late_and_stale_pages_never_fan_out(tmp_path: Path, case: str) -> None:
    lab, clock, ledger, inventory, service = await scenario(tmp_path)
    try:
        if case == "unknown":
            inventory.failure = TimeoutError("fictional lost HTTP result")
        if case == "late":
            inventory.delay = 121  # Past its page claim, but within the window.
        await service.process_one()
        if case == "stale":
            clock.value += timedelta(seconds=181)
        for _ in range(3):
            await service.process_one()
        assert not await lab.touch.process_retention()
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM retention_tariff_heads").fetchone()
        with ledger._connection() as db:
            if case == "stale":
                assert (
                    db.execute("SELECT phase FROM collection_tariff_batches").fetchone()[0]
                    == "stale"
                )
            else:
                assert not db.execute("SELECT 1 FROM collection_tariff_batches").fetchone()
        assert inventory.calls == 1
    finally:
        await lab.close()


@pytest.mark.parametrize("field", ["page_hash", "facts_hash", "window_id"])
async def test_consumer_refuses_changed_page_pairing(tmp_path: Path, field: str) -> None:
    lab, clock, ledger, inventory, service = await scenario(tmp_path)
    try:
        await service.process_one()
        with ledger._connection() as db:
            db.execute(f"UPDATE collection_tariff_batches SET {field}=?", ("0" * 64,))
        await service.process_one()
        with ledger._connection() as db:
            assert (
                db.execute("SELECT blocked FROM collection_tariff_policy").fetchone()[0]
                == "integrity"
            )
        assert not await lab.touch.process_retention()
        assert inventory.calls == 1
    finally:
        await lab.close()


async def test_unknown_claim_and_disabled_capture_survive_reconstruction(tmp_path: Path) -> None:
    lab, clock, ledger, inventory, service = await scenario(tmp_path)
    try:
        await service.process_one()
        parallel = await asyncio.gather(*(ledger.claim_tariffs(clock.now()) for _ in range(8)))
        claimed = [w for w in parallel if w is not None]
        assert len(claimed) == 1
        work = claimed[0]
        clock.value += timedelta(seconds=31)
        rebuilt = store(tmp_path / "collection.sqlite3")
        await rebuilt.initialize(clock.now())
        assert await rebuilt.claim_tariffs(clock.now()) is None
        with rebuilt._connection() as db:
            assert (
                db.execute("SELECT phase FROM collection_tariff_batches").fetchone()[0] == "unknown"
            )
        with pytest.raises(ValueError):
            await rebuilt.finish_tariffs(
                work.model_copy(update={"claim_id": uuid4()}), clock.now(), accepted=True
            )
        await rebuilt.finish_tariffs(work, clock.now(), accepted=True)
        with rebuilt._connection() as db:
            assert (
                db.execute("SELECT phase FROM collection_tariff_batches").fetchone()[0] == "unknown"
            )
    finally:
        await lab.close()


async def test_old_and_disabled_page_claims_never_gain_tariff_consumer(tmp_path: Path) -> None:
    lab, clock, ledger, inventory, service = await scenario(tmp_path)
    try:
        legacy = SqliteFamilyCollectionStore(
            tmp_path / "old.sqlite3",
            binding="fake-mana",
            policy=FamilyCollectionPolicy(page_size=1),
            sources=("firebase.child_battery.v1",),
        )
        await legacy.initialize(clock.now() - timedelta(minutes=1))
        work = await legacy.claim_next(clock.now())
        assert isinstance(work, FamilyCollectionWork)
        upgraded = store(tmp_path / "old.sqlite3")
        await upgraded.initialize(clock.now())
        result = await inventory.read(0, 1)
        old_page = FamilyInventoryPage.model_validate(result.model_dump(exclude={"tariff_facts"}))
        await upgraded.finish_page(work, old_page, clock.now())
        assert await upgraded.claim_tariffs(clock.now()) is None
        stopped = store(tmp_path / "off.sqlite3", enabled=False)
        await stopped.initialize(clock.now() - timedelta(minutes=1))
        new = await stopped.claim_next(clock.now())
        assert isinstance(new, FamilyCollectionWork)
        await stopped.finish_page(new, result, clock.now())
        armed = store(tmp_path / "off.sqlite3")
        await armed.initialize(clock.now())
        assert await armed.claim_tariffs(clock.now()) is None
    finally:
        await lab.close()


async def test_batch_capacity_refuses_all_facts_and_keeps_closed_circuit(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.mana_chat_lab.RetentionExpiryPolicy",
        lambda: RetentionExpiryPolicy(maximum_profiles=1),
    )
    lab, clock = await setup(tmp_path / "capacity")
    try:
        assert isinstance(lab.store, SqliteRetentionExpiryStore)
        facts = tuple(
            RetentionTariffFact(
                parent_id=p,
                collected_at=clock.now(),
                is_paid=True,
                valid_until=clock.now() + timedelta(days=1),
            )
            for p in (LAB_PARENT, "123")
        )
        assert not await lab.store.observe_inventory_tariffs(facts, clock.now())
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM retention_tariff_heads").fetchone()
            assert db.execute("SELECT circuit_open FROM retention_expiry_policy").fetchone()[0] == 1
        assert not await lab.touch.process_retention()
    finally:
        await lab.close()


async def test_known_inventory_auth_denial_durably_stops_expiry(tmp_path: Path) -> None:
    lab, clock, ledger, inventory, service = await scenario(tmp_path)
    try:
        inventory.failure = ParentChatError("family_inventory_auth_denied", 503)
        await service.process_one()
        with lab.store._connect() as db:
            assert db.execute("SELECT circuit_open FROM retention_expiry_policy").fetchone()[0] == 1
        clock.value += timedelta(hours=18)
        await service.process_one()
        await service.process_one()
        assert inventory.calls == 1
    finally:
        await lab.close()


async def test_child_queue_capacity_does_not_discard_known_tariff_facts(tmp_path: Path) -> None:
    lab, clock, _, inventory, _ = await scenario(tmp_path)
    try:
        assert isinstance(lab.store, SqliteRetentionExpiryStore)
        ledger = SqliteInventoryTariffStore(
            tmp_path / "small.sqlite3",
            binding="fake-mana",
            policy=FamilyCollectionPolicy(page_size=1, maximum_queued_targets=1),
            sources=("firebase.child_battery.v1",),
            tariff_policy=InventoryTariffPolicy(),
            recipient_binding="fictional-family-v17",
            tariffs_enabled=True,
        )
        await ledger.initialize(clock.now() - timedelta(minutes=1))
        inventory.children = (101, 102)
        service = TariffCollectionService(
            ledger, inventory, lab.sources, lab.source_store, receiver=lab.store, clock=clock.now
        )
        result = await service.process_one()
        assert result and result.status == "partial" and result.reason == "target_capacity"
        await service.process_one()
        assert await lab.touch.process_retention()
        assert lab.battery.calls == 0 and inventory.calls == 1
        with ledger._connection() as db:
            assert (
                db.execute("SELECT phase FROM collection_tariff_batches").fetchone()[0] == "applied"
            )
    finally:
        await lab.close()


async def test_adapter_reuses_one_get_and_keeps_malformed_optional_tariffs_unknown() -> None:
    payload = page()
    rows = payload["results"]
    assert isinstance(rows, list)
    rows[0].update(is_paid=True, valid_until=(NOW + timedelta(days=2)).isoformat())
    rows[1].update(is_paid="false", valid_until="invalid-date")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = ManakidsFamilyInventory(
            client,
            Auth(),
            base_url="https://api.manakids.uz",
            clock=lambda: NOW,
            include_tariffs=True,
        )
        result = await source.read(0, 2)
    assert isinstance(result, TariffInventoryPage)
    assert len(requests) == 1 and result.tariff_facts[0].is_paid is True
    assert result.tariff_facts[1].is_paid is None
    assert result.tariff_facts[1].valid_until is None
    assert "phone" not in result.model_dump_json() and "Fictional" not in result.model_dump_json()
