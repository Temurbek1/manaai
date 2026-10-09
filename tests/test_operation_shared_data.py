import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.mana_operation_ai.application.cost_control import CostBudgetExceeded
from app.mana_operation_ai.application.ports import ProviderPermanentError
from app.mana_operation_ai.application.shared_data import SharedDataReader, SharedDataUnavailable
from app.mana_operation_ai.domain.cost_control import (
    CostAttribution,
    CostLimits,
    ProductScope,
    ResourceUsage,
)
from app.mana_operation_ai.domain.retention import BackendActivityFacts
from app.mana_operation_ai.domain.shared_data import SavedAggregate, SourceBinding
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.shared_data_store import (
    SqlAlchemySharedDataStore,
)
from tests.test_operation_cost_ledger import Clock


def binding(product: ProductScope = ProductScope.MANA) -> SourceBinding:
    return SourceBinding(
        product=product,
        source="manakids",
        fingerprint=hashlib.sha256(b"approved-source-v1").hexdigest(),
    )


def facts(clock: Clock) -> BackendActivityFacts:
    return BackendActivityFacts(
        source="manakids",
        period_start=clock.now() - timedelta(days=7),
        period_end=clock.now(),
        collected_at=clock.now(),
        parent_accounts_joined=3,
        child_accounts_joined=5,
        total_children=10,
        children_with_app_usage=5,
        children_with_realtime_feature_usage=3,
        completeness=1,
    )


@pytest.mark.asyncio
async def test_shared_snapshot_survives_restart_and_separates_apps(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'shared.db'}"
    db = OperationDatabase(url)
    await db.create_schema()
    clock = Clock()
    reader = SharedDataReader(SqlAlchemySharedDataStore(db, clock=clock))
    calls = 0

    async def load() -> BackendActivityFacts:
        nonlocal calls
        calls += 1
        return facts(clock)

    try:
        first = await reader.read(
            binding=binding(),
            parameters={"days": 7},
            model=BackendActivityFacts,
            load=load,
        )
        reopened = OperationDatabase(url)
        try:
            second = await SharedDataReader(SqlAlchemySharedDataStore(reopened, clock=clock)).read(
                binding=binding(),
                parameters={"days": 7},
                model=BackendActivityFacts,
                load=load,
            )
            assert first.model_dump(exclude={"refresh_status"}) == second.model_dump(
                exclude={"refresh_status"}
            )
            assert first.refresh_status == "live" and second.refresh_status == "cached"
            assert calls == 1
        finally:
            await reopened.dispose()
        await reader.read(
            binding=binding(ProductScope.REC360),
            parameters={"days": 7},
            model=BackendActivityFacts,
            load=load,
        )
        assert calls == 2
        with pytest.raises(SharedDataUnavailable, match="ownership"):
            await reader.read(
                binding=binding(ProductScope.UNVERIFIED),
                parameters={"days": 7},
                model=BackendActivityFacts,
                load=load,
            )
        assert calls == 2
        with pytest.raises(SharedDataUnavailable, match="cooldown"):
            await reader.read(
                binding=binding(), parameters={"days": 30}, model=BackendActivityFacts, load=load
            )
        assert calls == 2
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_single_flight_across_connections_and_crash_cooldown(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}"
    db1, db2 = OperationDatabase(url), OperationDatabase(url)
    await db1.create_schema()
    clock = Clock()
    stores = [SqlAlchemySharedDataStore(db, clock=clock) for db in (db1, db2)]
    key = hashlib.sha256(b"query").hexdigest()
    try:
        admissions = await asyncio.gather(
            *[stores[i % 2].admit(binding(), query_key=key) for i in range(20)],
        )
        assert sum(item.token is not None for item in admissions) == 1
        winner = next(item for item in admissions if item.token is not None)
        # Simulate a crashed worker: do not publish/fail its lease.
        clock.value += timedelta(minutes=31)
        assert (await stores[1].admit(binding(), query_key=key)).reason == "cooldown"
        clock.value += timedelta(hours=6)
        next_admission = await stores[1].admit(binding(), query_key=key)
        assert next_admission.token is not None
        with pytest.raises(SharedDataUnavailable, match="lease"):
            await stores[0].publish(
                winner,
                snapshot=SavedAggregate(
                    query_key=key,
                    collected_at=clock.now(),
                    fresh_until=clock.now() + timedelta(hours=6),
                    payload=facts(clock).model_dump(mode="json"),
                ),
            )
        await stores[0].fail(winner, permanent=True)
        # The old worker must not block or clear the replacement worker's lease.
        assert (await stores[1].admit(binding(), query_key=key)).reason == "busy"
    finally:
        await db1.dispose()
        await db2.dispose()


@pytest.mark.asyncio
async def test_permanent_failure_blocks_refresh_but_returns_dated_saved_facts(
    tmp_path: Path,
) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'failure.db'}")
    await db.create_schema()
    clock = Clock()
    reader = SharedDataReader(SqlAlchemySharedDataStore(db, clock=clock))
    calls = 0
    fail = False

    async def load() -> BackendActivityFacts:
        nonlocal calls
        calls += 1
        if fail:
            raise ProviderPermanentError("Provider denied access: HTTP 403")
        return facts(clock)

    try:
        first = await reader.read(
            binding=binding(), parameters={}, model=BackendActivityFacts, load=load
        )
        clock.value += timedelta(hours=6)
        fail = True
        stale = await reader.read(
            binding=binding(), parameters={}, model=BackendActivityFacts, load=load
        )
        assert stale.collected_at == first.collected_at
        assert "refresh is unavailable" in str(stale.limitations)
        clock.value += timedelta(days=2)
        await reader.read(binding=binding(), parameters={}, model=BackendActivityFacts, load=load)
        assert calls == 2
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_budget_exhaustion_does_not_permanently_block_source(tmp_path: Path) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'budget.db'}")
    await db.create_schema()
    clock = Clock()
    reader = SharedDataReader(SqlAlchemySharedDataStore(db, clock=clock))
    fail = True

    async def load() -> BackendActivityFacts:
        if fail:
            raise CostBudgetExceeded("Local quota exhausted")
        return facts(clock)

    try:
        with pytest.raises(CostBudgetExceeded):
            await reader.read(
                binding=binding(), parameters={}, model=BackendActivityFacts, load=load
            )
        clock.value += timedelta(hours=6)
        fail = False
        result = await reader.read(
            binding=binding(), parameters={}, model=BackendActivityFacts, load=load
        )
        assert result.completeness == 1
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_four_daily_cycles_are_shared_across_consumers_and_restart(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'day-cycles.db'}"
    databases = [OperationDatabase(url) for _ in range(3)]
    await databases[0].create_schema()
    start = datetime(2026, 10, 8, tzinfo=UTC)
    clock = Clock(start)
    readers = [SharedDataReader(SqlAlchemySharedDataStore(db, clock=clock)) for db in databases]
    usage = ResourceUsage(provider_requests=8, document_reads=400, response_bytes=400_000)
    ledger = SqlAlchemyCostLedger(
        databases[0], clock=clock, limits=CostLimits(daily=usage, monthly=usage)
    )
    calls = {ProductScope.MANA: 0, ProductScope.REC360: 0}

    async def load(product: ProductScope) -> BackendActivityFacts:
        reserved = await ledger.reserve(
            ResourceUsage(provider_requests=1, document_reads=50, response_bytes=50_000),
            attribution=CostAttribution(
                product=product,
                source="manakids",
                agent_id="retention-agent",
                capability_key="retention.engagement.analyze",
            ),
        )
        calls[product] += 1
        await ledger.settle(reserved.reservation_id, actual=reserved.usage)
        return facts(clock).model_copy(update={"product_scope": product})

    try:
        for hour in range(24):
            clock.value = start + timedelta(hours=hour)
            for product in (ProductScope.MANA, ProductScope.REC360):
                # Separate fixture bindings stand for owner-confirmed source
                # ownership, not inference that a live backend serves both apps.
                async def collect(product: ProductScope = product) -> BackendActivityFacts:
                    return await load(product)

                for consumer in range(4):
                    saved = await readers[(hour + consumer) % 3].read(
                        binding=binding(product),
                        parameters={"days": 7},
                        model=BackendActivityFacts,
                        load=collect,
                    )
                    assert saved.product_scope is product
                    assert saved.collected_at == start + timedelta(hours=(hour // 6) * 6)
                    assert calls[product] == hour // 6 + 1
            if hour == 11:
                # New application objects/DB connection do not reset admission.
                await databases[2].dispose()
                databases[2] = OperationDatabase(url)
                readers[2] = SharedDataReader(SqlAlchemySharedDataStore(databases[2], clock=clock))
        assert calls == {ProductScope.MANA: 4, ProductScope.REC360: 4}
        assert (await ledger.periods())[0].usage == usage
    finally:
        for database in databases:
            await database.dispose()
