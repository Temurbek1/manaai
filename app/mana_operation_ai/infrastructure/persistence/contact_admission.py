"""One short SQL admission transaction, no source call or expiring pending reservation."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import AwareDatetime, TypeAdapter, ValidationError
from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.retention.preparation_errors import ContactPreparationError
from app.mana_operation_ai.domain.contact_admission import (
    ContactPreparationBinding,
    ContactPreparationClaim,
    ContactPreparationLimits,
    preparation_binding,
)
from app.mana_operation_ai.domain.retention_contact import RetentionContactAction
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    ChatTopicRow,
    ChatTurnRow,
    ContactPreparationGateRow,
    ContactPreparationRow,
    RetentionContactRow,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _claim(row: ContactPreparationRow) -> ContactPreparationClaim:
    try:
        if row.status not in {"pending", "recorded"} or (row.status == "recorded") != (
            row.action_id is not None
        ):
            raise ValueError("Preparation lifecycle is inconsistent")
        return ContactPreparationClaim(
            claim_id=UUID(row.claim_id),
            binding=ContactPreparationBinding(
                owner=row.owner,
                topic_id=row.topic_id,
                turn_id=row.turn_id,
                request_id=UUID(row.request_id),
                request_sha256=row.request_sha256,
                target_sha256=row.target_sha256,
            ),
            admitted_at=_utc(row.admitted_at),
            limits=ContactPreparationLimits.model_validate(row.limits),
        )
    except (ValidationError, ValueError):
        raise ContactPreparationError("contact_preparation_history_unavailable") from None


class SqlAlchemyContactPreparations:
    def __init__(self, database: OperationDatabase) -> None:
        self._sessions = database.session_factory
        self._dialect = database.engine.dialect.name
        self._date = TypeAdapter(AwareDatetime)

    async def _lock(
        self, session: AsyncSession, limits: ContactPreparationLimits
    ) -> ContactPreparationLimits:
        insert: Any = sqlite_insert if self._dialect == "sqlite" else pg_insert
        key = "retention.contact.sandbox"
        await session.execute(
            insert(ContactPreparationGateRow)
            .values(gate_id=key, revision=0, limits=limits.model_dump())
            .on_conflict_do_nothing(index_elements=["gate_id"])
        )
        # SQLite obtains its write lock before any count; PostgreSQL locks this
        # same row. No contact/action/grant lock is held while acquiring it.
        await session.execute(
            update(ContactPreparationGateRow)
            .where(ContactPreparationGateRow.gate_id == key)
            .values(revision=ContactPreparationGateRow.revision + 1)
        )
        row = await session.scalar(
            select(ContactPreparationGateRow)
            .where(ContactPreparationGateRow.gate_id == key)
            .with_for_update()
        )
        assert row is not None
        try:
            previous = ContactPreparationLimits.model_validate(row.limits)
        except ValidationError:
            raise ContactPreparationError("contact_preparation_history_unavailable") from None
        # A stale runtime cannot loosen the persisted ceiling. Raising it needs
        # a separately reviewed policy migration, never a timer or another nonce.
        values = {
            key: min(value, getattr(previous, key)) for key, value in limits.model_dump().items()
        }
        row.limits = values
        return ContactPreparationLimits.model_validate(values)

    async def _owned(self, session: AsyncSession, binding: ContactPreparationBinding) -> None:
        topic = await session.scalar(
            select(ChatTopicRow).where(
                ChatTopicRow.topic_id == binding.topic_id, ChatTopicRow.owner == binding.owner
            )
        )
        if (
            topic is None
            or topic.payload.get("product") != "mana"
            or topic.payload.get("agent_id") not in {"retention-agent", "operations-orchestrator"}
        ):
            raise ChatError("Тема не найдена.", 404)
        if binding.turn_id is not None:
            turn = await session.scalar(
                select(ChatTurnRow).where(
                    ChatTurnRow.owner == binding.owner,
                    ChatTurnRow.topic_id == binding.topic_id,
                    ChatTurnRow.turn_id == binding.turn_id,
                )
            )
            if (
                turn is None
                or turn.status != "completed"
                or (turn.workspace_metadata or {}).get("execution_mode") != "agent"
                or (turn.workspace_metadata or {}).get("next_action") != "retention_contacts"
            ):
                raise ChatError("Контактная подготовка не связана с этим сообщением.", 403)

    async def _legacy_counts(
        self,
        session: AsyncSession,
        binding: ContactPreparationBinding,
        limits: ContactPreparationLimits,
        now: datetime,
    ) -> tuple[int, int, int]:
        tracked = exists().where(ContactPreparationRow.action_id == RetentionContactRow.action_id)
        # Never load bodies/targets or interpret a bounded prefix as all history.
        rows = (
            await session.execute(
                select(
                    RetentionContactRow.owner,
                    RetentionContactRow.topic_id,
                    RetentionContactRow.payload["turn_id"].as_string(),
                    RetentionContactRow.payload["prepared_at"].as_string(),
                )
                .where(~tracked)
                .limit(limits.legacy_scan_limit + 1)
            )
        ).all()
        if len(rows) > limits.legacy_scan_limit:
            raise ContactPreparationError("contact_preparation_history_unavailable")
        turn_count = owner_count = day_count = 0
        for owner, topic_id, turn_id, at in rows:
            try:
                if not isinstance(at, str):
                    raise ValueError("An untracked preparation needs its exact aware date")
                prepared = self._date.validate_python(at)
                if prepared > now:
                    raise ValueError("Future preparation history cannot renew admission")
            except (ValidationError, ValueError):
                raise ContactPreparationError("contact_preparation_history_unavailable") from None
            day_count += int(prepared >= now - timedelta(days=1))
            owner_count += int(owner == binding.owner and prepared >= now - timedelta(hours=1))
            turn_count += int(
                (owner, topic_id, turn_id) == (binding.owner, binding.topic_id, binding.turn_id)
            )
        return turn_count, owner_count, day_count

    async def admit(
        self, binding: ContactPreparationBinding, *, limits: ContactPreparationLimits, now: datetime
    ) -> ContactPreparationClaim | None:
        if now.utcoffset() is None:
            raise ValueError("Preparation admission requires an aware clock")
        failure: ContactPreparationError | None = None
        claim: ContactPreparationClaim | None = None
        async with self._sessions() as session, session.begin():
            limits = await self._lock(session, limits)
            await self._owned(session, binding)
            try:
                claim = await self._admit_locked(session, binding, limits, now)
            except ContactPreparationError as exc:
                # Persist a tighter policy even when this request is refused.
                # No admission/source attempt has been added on these paths.
                failure = exc
        if failure is not None:
            raise failure
        return claim

    async def _admit_locked(
        self,
        session: AsyncSession,
        binding: ContactPreparationBinding,
        limits: ContactPreparationLimits,
        now: datetime,
    ) -> ContactPreparationClaim | None:
        row = await session.scalar(
            select(ContactPreparationRow).where(
                ContactPreparationRow.owner == binding.owner,
                ContactPreparationRow.request_id == str(binding.request_id),
            )
        )
        if row is not None:
            if _claim(row).binding != binding:
                raise ContactPreparationError("contact_preparation_conflict")
            return None
        pending = await session.scalar(
            select(ContactPreparationRow.claim_id)
            .where(
                ContactPreparationRow.target_sha256 == binding.target_sha256,
                ContactPreparationRow.status == "pending",
            )
            .limit(1)
        )
        if pending is not None:
            raise ContactPreparationError("contact_preparation_pending")
        counts = await self._legacy_counts(session, binding, limits, now)
        predicates = [
            (ContactPreparationRow.owner == binding.owner)
            & (ContactPreparationRow.topic_id == binding.topic_id)
            & (ContactPreparationRow.turn_id == binding.turn_id),
            (ContactPreparationRow.owner == binding.owner)
            & (ContactPreparationRow.admitted_at >= now - timedelta(hours=1)),
            ContactPreparationRow.admitted_at >= now - timedelta(days=1),
        ]
        for predicate, legacy_count, ceiling in zip(
            predicates,
            counts,
            [limits.per_turn, limits.per_owner_hour, limits.per_day],
            strict=True,
        ):
            current = await session.scalar(
                select(func.count()).select_from(ContactPreparationRow).where(predicate)
            )
            if int(current or 0) + legacy_count >= ceiling:
                raise ContactPreparationError("contact_preparation_limit")
        claim = ContactPreparationClaim(
            claim_id=uuid4(), binding=binding, admitted_at=now, limits=limits
        )
        session.add(
            ContactPreparationRow(
                claim_id=str(claim.claim_id),
                owner=binding.owner,
                topic_id=binding.topic_id,
                turn_id=binding.turn_id,
                request_id=str(binding.request_id),
                request_sha256=binding.request_sha256,
                target_sha256=binding.target_sha256,
                admitted_at=now,
                limits=limits.model_dump(),
                status="pending",
                action_id=None,
            )
        )
        return claim

    async def pending(self, owner: str, topic_id: str, turn_id: str) -> bool:
        async with self._sessions() as session:
            return (
                await session.scalar(
                    select(ContactPreparationRow.claim_id)
                    .where(
                        ContactPreparationRow.owner == owner,
                        ContactPreparationRow.topic_id == topic_id,
                        ContactPreparationRow.turn_id == turn_id,
                        ContactPreparationRow.status == "pending",
                    )
                    .limit(1)
                )
            ) is not None

    async def request_pending(self, owner: str, request_id: str) -> bool:
        async with self._sessions() as session:
            return (
                await session.scalar(
                    select(ContactPreparationRow.claim_id).where(
                        ContactPreparationRow.owner == owner,
                        ContactPreparationRow.request_id == request_id,
                        ContactPreparationRow.status == "pending",
                    )
                )
            ) is not None

    async def complete(
        self, session: AsyncSession, claim: ContactPreparationClaim, action: RetentionContactAction
    ) -> None:
        row = await session.scalar(
            select(ContactPreparationRow)
            .where(ContactPreparationRow.claim_id == str(claim.claim_id))
            .with_for_update()
        )
        if (
            row is None
            or _claim(row) != claim
            or row.status != "pending"
            or preparation_binding(action.owner, action.topic_id, action.turn_id, action.request)
            != claim.binding
            or action.prepared_at < claim.admitted_at
        ):
            raise ContactPreparationError("contact_preparation_conflict")
        row.status, row.action_id = "recorded", action.action_id
