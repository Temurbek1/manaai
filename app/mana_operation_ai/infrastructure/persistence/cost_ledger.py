import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.mana_operation_ai.application.cost_control import CostBudgetExceeded
from app.mana_operation_ai.application.ports import Clock
from app.mana_operation_ai.domain.cost_control import (
    CostAttribution,
    CostLimits,
    CostPeriod,
    CostReservation,
    ResourceUsage,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    CostPeriodRow,
    CostReservationRow,
)


class SqlAlchemyCostLedger:
    """Global, durable day/month admission shared by API and worker processes.

    Reserve in one transaction before I/O. Unknown/abandoned charges remain
    reserved; only a validated provider receipt can reconcile them. UTC calendar
    periods belong to the original admission, even if completion crosses midnight.
    SQLite's first statement is a write; PostgreSQL additionally locks each row.
    Both paths serialize admission and settlement without process-local locks.
    """

    def __init__(self, database: OperationDatabase, *, clock: Clock, limits: CostLimits) -> None:
        self._database = database
        self._clock = clock
        self._limits = limits
        self._dialect = database.engine.dialect.name
        if self._dialect not in {"sqlite", "postgresql"}:
            raise ValueError("Cost accounting supports SQLite and PostgreSQL")

    async def reserve(
        self, usage: ResourceUsage, *, attribution: CostAttribution
    ) -> CostReservation:
        if not any(usage.model_dump().values()):
            raise ValueError("A reservation must contain at least one resource")
        now = _aware_utc(self._clock.now())
        keys = _period_keys(now)
        # Commit policy tightening even if the following admission is rejected.
        # Otherwise a stale process could keep using the old, higher limits.
        async with self._database.session_factory() as policy_session, policy_session.begin():
            for key, limit in zip(keys, (self._limits.daily, self._limits.monthly), strict=True):
                await self._lock_period(policy_session, key, limit=limit)
        async with self._database.session_factory() as session, session.begin():
            for key in keys:
                row = await self._lock_period(session, key)
                updated = ResourceUsage.model_validate(row.usage).plus(usage)
                exceeded = updated.exceeds(ResourceUsage.model_validate(row.limits))
                if exceeded:
                    # Raising rolls back BOTH periods; a rejected request spends nothing.
                    raise CostBudgetExceeded(
                        f"Operation budget exhausted ({key}): {', '.join(exceeded)}",
                    )
                row.usage = updated.model_dump()
                await session.flush()
            receipt = CostReservation(
                reservation_id=str(uuid.uuid4()),
                reserved_at=now,
                usage=usage,
                attribution=attribution,
            )
            session.add(
                CostReservationRow(
                    reservation_id=receipt.reservation_id,
                    reserved_at=now,
                    period_keys=list(keys),
                    usage=usage.model_dump(),
                    actual=None,
                    attribution=attribution.model_dump(mode="json"),
                ),
            )
        return receipt

    async def settle(self, reservation_id: str, *, actual: ResourceUsage) -> None:
        # Finish this read-only transaction before SQLite's write transaction starts.
        # Upgrading concurrent SQLite read snapshots into writers is unsafe.
        async with self._database.session_factory() as lookup:
            original = await lookup.get(CostReservationRow, reservation_id)
            if original is None:
                raise LookupError("Cost reservation was not found")
            keys = list(original.period_keys)
        async with self._database.session_factory() as session, session.begin():
            # Lock period rows before the receipt, in the same order as admission.
            # This avoids receipt/period lock inversions across concurrent settlement.
            rows = [await self._lock_period(session, key) for key in keys]
            receipt = await session.scalar(
                select(CostReservationRow)
                .where(CostReservationRow.reservation_id == reservation_id)
                .with_for_update()
                .execution_options(populate_existing=True),
            )
            assert receipt is not None
            if receipt.actual is not None:
                if ResourceUsage.model_validate(receipt.actual) != actual:
                    raise ValueError("A settled reservation cannot be reconciled differently")
                return
            reserved = ResourceUsage.model_validate(receipt.usage)
            # Keep the full observed charge, including an unexpected overrun.
            # Subsequent admission fails if a counter is now above its limit.
            updated_usage = [
                ResourceUsage.model_validate(row.usage).minus(reserved).plus(actual) for row in rows
            ]
            for row, updated in zip(rows, updated_usage, strict=True):
                row.usage = updated.model_dump()
            receipt.actual = actual.model_dump()

    async def periods(self) -> list[CostPeriod]:
        keys = _period_keys(_aware_utc(self._clock.now()))
        async with self._database.session_factory() as session:
            rows = await session.scalars(
                select(CostPeriodRow).where(CostPeriodRow.period_key.in_(keys)),
            )
            usage = {row.period_key: ResourceUsage.model_validate(row.usage) for row in rows}
        return [CostPeriod(period_key=key, usage=usage.get(key, ResourceUsage())) for key in keys]

    async def _lock_period(
        self, session: AsyncSession, key: str, *, limit: ResourceUsage | None = None
    ) -> CostPeriodRow:
        insert: Any = sqlite_insert if self._dialect == "sqlite" else postgres_insert
        await session.execute(
            insert(CostPeriodRow)
            .values(
                period_key=key,
                usage=ResourceUsage().model_dump(),
                limits=limit.model_dump() if limit is not None else {},
            )
            .on_conflict_do_nothing(index_elements=["period_key"]),
        )
        row = await session.scalar(
            select(CostPeriodRow).where(CostPeriodRow.period_key == key).with_for_update(),
        )
        assert row is not None
        if limit is not None:
            # A rolling deployment's stale worker must not loosen a tighter policy.
            # Increases require the next period or an explicit operator migration.
            previous = ResourceUsage.model_validate(row.limits)
            row.limits = {
                name: min(value, getattr(previous, name))
                for name, value in limit.model_dump().items()
            }
        return row


def _aware_utc(now: datetime) -> datetime:
    if now.utcoffset() is None:
        raise ValueError("Cost accounting requires a timezone-aware clock")
    return now.astimezone(UTC)


def _period_keys(now: datetime) -> tuple[str, str]:
    return f"day:{now:%Y-%m-%d}", f"month:{now:%Y-%m}"
