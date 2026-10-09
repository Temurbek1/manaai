import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.mana_operation_ai.application.ports import Clock
from app.mana_operation_ai.application.shared_data import SharedDataUnavailable
from app.mana_operation_ai.domain.shared_data import SavedAggregate, SourceAdmission, SourceBinding
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    SharedAggregateRow,
    SharedSourceGateRow,
)


class SqlAlchemySharedDataStore:
    def __init__(self, database: OperationDatabase, *, clock: Clock) -> None:
        self._database = database
        self._clock = clock
        self._dialect = database.engine.dialect.name
        if self._dialect not in {"sqlite", "postgresql"}:
            raise ValueError("Shared aggregates support SQLite and PostgreSQL")

    async def admit(self, binding: SourceBinding, *, query_key: str) -> SourceAdmission:
        now = _utc(self._clock.now())
        binding_key = hashlib.sha256(
            f"{binding.product}:{binding.source}:{binding.fingerprint}".encode(),
        ).hexdigest()
        async with self._database.session_factory() as session, session.begin():
            insert: Any = sqlite_insert if self._dialect == "sqlite" else postgres_insert
            await session.execute(
                insert(SharedSourceGateRow)
                .values(
                    binding_key=binding_key,
                    product=binding.product.value,
                    source=binding.source,
                    next_attempt_at=now,
                    blocked=False,
                    lease_token=None,
                    lease_until=None,
                )
                .on_conflict_do_nothing(index_elements=["binding_key"]),
            )
            gate = await self._gate(session, binding_key)
            saved = await session.get(SharedAggregateRow, query_key)
            if saved is not None and saved.binding_key != binding_key:
                raise SharedDataUnavailable("Saved aggregate belongs to a different source")
            snapshot = _snapshot(saved)
            token = None
            if gate.blocked:
                reason = "blocked"
            elif snapshot is not None and now < snapshot.fresh_until:
                reason = "fresh"
            elif gate.lease_until is not None and now < _utc(gate.lease_until):
                reason = "busy"
            elif now < _utc(gate.next_attempt_at):
                reason = "cooldown"
            else:
                reason = "admitted"
                token = str(uuid.uuid4())
                gate.lease_token = token
                gate.lease_until = now + timedelta(seconds=binding.lease_seconds)
                # Persist BEFORE provider I/O. Failures and restarts consume the slot.
                gate.next_attempt_at = now + timedelta(seconds=binding.minimum_interval_seconds)
            return SourceAdmission(
                binding_key=binding_key,
                query_key=query_key,
                token=token,
                snapshot=snapshot,
                reason=reason,
            )

    async def publish(self, admission: SourceAdmission, *, snapshot: SavedAggregate) -> None:
        if snapshot.query_key != admission.query_key or admission.token is None:
            raise SharedDataUnavailable("Invalid shared aggregate publication")
        now = _utc(self._clock.now())
        if _utc(snapshot.collected_at) > now or snapshot.fresh_until <= snapshot.collected_at:
            raise SharedDataUnavailable("Invalid shared aggregate collection time")
        async with self._database.session_factory() as session, session.begin():
            gate = await self._lock_existing(session, admission.binding_key)
            if (
                gate.lease_token != admission.token
                or gate.lease_until is None
                or now >= _utc(gate.lease_until)
            ):
                raise SharedDataUnavailable("Shared aggregate lease expired or was replaced")
            row = await session.get(SharedAggregateRow, admission.query_key)
            if row is None:
                session.add(
                    SharedAggregateRow(
                        query_key=admission.query_key,
                        binding_key=admission.binding_key,
                        collected_at=snapshot.collected_at,
                        fresh_until=snapshot.fresh_until,
                        payload=snapshot.payload,
                    )
                )
            else:
                row.collected_at = snapshot.collected_at
                row.fresh_until = snapshot.fresh_until
                row.payload = snapshot.payload
            gate.lease_token = None
            gate.lease_until = None

    async def fail(self, admission: SourceAdmission, *, permanent: bool) -> None:
        async with self._database.session_factory() as session, session.begin():
            gate = await self._lock_existing(session, admission.binding_key)
            if gate.lease_token == admission.token and admission.token is not None:
                gate.lease_token = None
                gate.lease_until = None
                gate.blocked = permanent

    async def _lock_existing(self, session: AsyncSession, key: str) -> SharedSourceGateRow:
        # The no-op UPDATE starts SQLite's write transaction before any reads.
        await session.execute(
            update(SharedSourceGateRow)
            .where(SharedSourceGateRow.binding_key == key)
            .values(binding_key=key),
        )
        return await self._gate(session, key)

    @staticmethod
    async def _gate(session: AsyncSession, key: str) -> SharedSourceGateRow:
        row = await session.scalar(
            select(SharedSourceGateRow)
            .where(SharedSourceGateRow.binding_key == key)
            .with_for_update(),
        )
        if row is None:
            raise SharedDataUnavailable("Shared source gate was not found")
        return row


def _snapshot(row: SharedAggregateRow | None) -> SavedAggregate | None:
    if row is None:
        return None
    return SavedAggregate(
        query_key=row.query_key,
        collected_at=_utc(row.collected_at),
        fresh_until=_utc(row.fresh_until),
        payload=row.payload,
    )


def _utc(value: datetime) -> datetime:
    # SQLite returns naive UTC values from timezone-aware DateTime columns.
    return value.replace(tzinfo=UTC) if value.utcoffset() is None else value.astimezone(UTC)
