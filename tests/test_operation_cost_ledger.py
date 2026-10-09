import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.mana_operation_ai.application.cost_control import CostBudgetExceeded
from app.mana_operation_ai.domain.cost_control import (
    CostAttribution,
    CostLimits,
    ProductScope,
    ResourceUsage,
)
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase


@dataclass
class Clock:
    value: datetime = datetime(2026, 10, 7, 23, 59, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


def attribution(product: ProductScope = ProductScope.MANA) -> CostAttribution:
    return CostAttribution(
        product=product,
        source="ga4",
        agent_id="retention-agent",
        capability_key="retention.engagement.analyze",
    )


def limits(*, daily: int = 10, monthly: int = 20) -> CostLimits:
    return CostLimits(
        daily=ResourceUsage(provider_requests=daily, input_tokens=100, output_tokens=100),
        monthly=ResourceUsage(provider_requests=monthly, input_tokens=200, output_tokens=200),
    )


@pytest.mark.asyncio
async def test_independent_connections_share_atomic_global_admission(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'budget.db'}"
    databases = [OperationDatabase(url), OperationDatabase(url)]
    await databases[0].create_schema()
    clock = Clock()
    ledgers = [SqlAlchemyCostLedger(db, clock=clock, limits=limits()) for db in databases]
    try:
        results = await asyncio.gather(
            *[
                ledgers[index % 2].reserve(
                    ResourceUsage(provider_requests=1),
                    attribution=attribution(
                        ProductScope.MANA if index % 2 else ProductScope.REC360
                    ),
                )
                for index in range(40)
            ],
            return_exceptions=True,
        )
        assert sum(not isinstance(item, BaseException) for item in results) == 10
        assert sum(isinstance(item, CostBudgetExceeded) for item in results) == 30
        assert [item.usage.provider_requests for item in await ledgers[0].periods()] == [10, 10]
        # Reopening a third engine cannot bypass the budget.
        reopened = OperationDatabase(url)
        try:
            with pytest.raises(CostBudgetExceeded):
                await SqlAlchemyCostLedger(reopened, clock=clock, limits=limits()).reserve(
                    ResourceUsage(provider_requests=1),
                    attribution=attribution(),
                )
        finally:
            await reopened.dispose()
    finally:
        for db in databases:
            await db.dispose()


@pytest.mark.asyncio
async def test_monthly_rejection_rolls_back_daily_admission(tmp_path: Path) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'month.db'}")
    await db.create_schema()
    clock = Clock()
    ledger = SqlAlchemyCostLedger(db, clock=clock, limits=limits(daily=10, monthly=1))
    try:
        await ledger.reserve(ResourceUsage(provider_requests=1), attribution=attribution())
        clock.value += timedelta(days=1)
        with pytest.raises(CostBudgetExceeded, match="month"):
            await ledger.reserve(ResourceUsage(provider_requests=1), attribution=attribution())
        assert [item.usage.provider_requests for item in await ledger.periods()] == [0, 1]
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_uncertain_attempt_stays_reserved_and_settlement_uses_original_periods(
    tmp_path: Path,
) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'settle.db'}")
    await db.create_schema()
    clock = Clock(datetime(2026, 10, 31, 23, 59, tzinfo=UTC))
    ledger = SqlAlchemyCostLedger(db, clock=clock, limits=limits())
    try:
        receipt = await ledger.reserve(
            ResourceUsage(provider_requests=1, input_tokens=100),
            attribution=attribution(),
        )
        with pytest.raises(CostBudgetExceeded, match="input_tokens"):
            await ledger.reserve(ResourceUsage(input_tokens=1), attribution=attribution())
        clock.value += timedelta(minutes=2)
        actual = ResourceUsage(provider_requests=1, input_tokens=20)
        await asyncio.gather(
            *[ledger.settle(receipt.reservation_id, actual=actual) for _ in range(5)]
        )
        assert [item.usage.input_tokens for item in await ledger.periods()] == [0, 0]
        clock.value -= timedelta(minutes=2)
        assert [item.usage.input_tokens for item in await ledger.periods()] == [20, 20]
        with pytest.raises(ValueError, match="differently"):
            await ledger.settle(receipt.reservation_id, actual=ResourceUsage(input_tokens=0))
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_observed_overrun_is_recorded_and_blocks_future_admission(tmp_path: Path) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'overrun.db'}")
    await db.create_schema()
    ledger = SqlAlchemyCostLedger(db, clock=Clock(), limits=limits())
    try:
        receipt = await ledger.reserve(ResourceUsage(output_tokens=1), attribution=attribution())
        await ledger.settle(receipt.reservation_id, actual=ResourceUsage(output_tokens=101))
        with pytest.raises(CostBudgetExceeded, match="output_tokens"):
            await ledger.reserve(ResourceUsage(provider_requests=1), attribution=attribution())
        assert (await ledger.periods())[0].usage.output_tokens == 101
    finally:
        await db.dispose()


@pytest.mark.asyncio
async def test_rejected_tighter_policy_is_durable_for_stale_worker(tmp_path: Path) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'policies.db'}")
    await db.create_schema()
    clock = Clock()
    old = SqlAlchemyCostLedger(db, clock=clock, limits=limits(daily=10, monthly=20))
    new = SqlAlchemyCostLedger(db, clock=clock, limits=limits(daily=1, monthly=20))
    try:
        await old.reserve(ResourceUsage(provider_requests=1), attribution=attribution())
        with pytest.raises(CostBudgetExceeded):
            await new.reserve(ResourceUsage(provider_requests=1), attribution=attribution())
        with pytest.raises(CostBudgetExceeded):
            await old.reserve(ResourceUsage(provider_requests=1), attribution=attribution())
        assert (await old.periods())[0].usage.provider_requests == 1
    finally:
        await db.dispose()
