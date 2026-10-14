from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.contact_reviews import ContactReviewGrant
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    AdminUserRow,
    ContactReviewEventRow,
    ContactReviewGrantRow,
    RetentionContactRow,
)
from app.mana_operation_ai.infrastructure.persistence.retention_contact_state import (
    contact_action as _action,
)


def review_grant(row: ContactReviewGrantRow) -> ContactReviewGrant:
    try:
        grant = ContactReviewGrant.model_validate(row.payload)
        expires = (
            row.expires_at.replace(tzinfo=UTC) if row.expires_at.tzinfo is None else row.expires_at
        )
        revoked = row.revoked_at
        if revoked and revoked.tzinfo is None:
            revoked = revoked.replace(tzinfo=UTC)
        if (
            grant.review_id,
            grant.owner,
            str(grant.request.reviewer_id),
            grant.action_id,
            str(grant.request.request_id),
            grant.revision,
            grant.expires_at,
            grant.revoked_at,
        ) != (
            row.review_id,
            row.owner,
            row.reviewer_id,
            row.action_id,
            row.request_id,
            row.revision,
            expires,
            revoked,
        ):
            raise ValueError("Review row binding changed")
        return grant
    except (ValidationError, ValueError):
        raise ChatError("Сохранённое согласование требует проверки.", 503) from None


def reviewer_is_active(row: AdminUserRow | None) -> bool:
    return bool(row and row.status == "active" and row.role in {"approver", "admin"})


class SqlAlchemyContactReviews:
    def __init__(self, database: OperationDatabase) -> None:
        self._sessions = database.session_factory

    async def by_action(self, action_id: str) -> ContactReviewGrant | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(ContactReviewGrantRow).where(ContactReviewGrantRow.action_id == action_id)
            )
            return review_grant(row) if row else None

    async def by_id(self, review_id: str) -> ContactReviewGrant | None:
        async with self._sessions() as session:
            row = await session.get(ContactReviewGrantRow, review_id)
            return review_grant(row) if row else None

    async def create(self, grant: ContactReviewGrant) -> ContactReviewGrant:
        try:
            async with self._sessions() as session, session.begin():
                row = await session.scalar(
                    select(RetentionContactRow)
                    .where(RetentionContactRow.action_id == grant.action_id)
                    .with_for_update()
                )
                if row is None:
                    raise ChatError("Действие не найдено.", 404)
                action = _action(row)
                reviewer = await session.get(
                    AdminUserRow, str(grant.request.reviewer_id), with_for_update=True
                )
                owner = await session.get(AdminUserRow, grant.owner, with_for_update=True)
                if (
                    not grant.matches(action)
                    or action.status != "proposed"
                    or action.decision is not None
                    or grant.revoked_at is not None
                    or not reviewer_is_active(reviewer)
                    or owner is None
                    or owner.status != "active"
                    or owner.role not in {"operator", "approver", "admin"}
                ):
                    raise ChatError("Условия передачи на согласование изменились.", 409)
                session.add(
                    ContactReviewGrantRow(
                        review_id=grant.review_id,
                        owner=grant.owner,
                        reviewer_id=str(grant.request.reviewer_id),
                        action_id=grant.action_id,
                        request_id=str(grant.request.request_id),
                        revision=0,
                        expires_at=grant.expires_at,
                        revoked_at=None,
                        payload=grant.model_dump(mode="json"),
                    )
                )
                await session.flush()
                session.add(
                    ContactReviewEventRow(
                        review_id=grant.review_id, revision=0, payload=grant.model_dump(mode="json")
                    )
                )
            return grant
        except IntegrityError:
            previous = await self.by_action(grant.action_id)
            if previous and previous.owner == grant.owner and previous.request == grant.request:
                return previous
            raise ChatError("Для этого действия уже сохранено другое согласование.", 409) from None

    async def revoke(self, grant: ContactReviewGrant, *, at: datetime) -> ContactReviewGrant:
        async with self._sessions() as session, session.begin():
            # Same lock order as approval: action first, grant second.
            action_row = await session.scalar(
                select(RetentionContactRow)
                .where(RetentionContactRow.action_id == grant.action_id)
                .with_for_update()
            )
            row = await session.get(ContactReviewGrantRow, grant.review_id, with_for_update=True)
            if row is None or action_row is None:
                raise ChatError("Согласование не найдено.", 404)
            current, action = review_grant(row), _action(action_row)
            if (
                current.owner != grant.owner
                or current.request != grant.request
                or not current.matches(action)
            ):
                raise ChatError("Согласование изменилось.", 409)
            if current.revoked_at is not None:
                return current
            if action.status != "proposed" or action.decision is not None:
                raise ChatError("Решение уже принято; отзыв не отменяет выполненное действие.", 409)
            revoked = ContactReviewGrant.model_validate(
                {**current.model_dump(mode="json"), "revision": 1, "revoked_at": at}
            )
            row.revision, row.revoked_at, row.payload = 1, at, revoked.model_dump(mode="json")
            session.add(
                ContactReviewEventRow(
                    review_id=grant.review_id, revision=1, payload=revoked.model_dump(mode="json")
                )
            )
            return revoked

    async def pending(self, reviewer_id: str, *, now: datetime) -> list[ContactReviewGrant]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(ContactReviewGrantRow)
                .join(RetentionContactRow)
                .where(
                    ContactReviewGrantRow.reviewer_id == reviewer_id,
                    ContactReviewGrantRow.revoked_at.is_(None),
                    ContactReviewGrantRow.expires_at > now,
                )
                .order_by(ContactReviewGrantRow.review_id)
                .limit(21)
            )
            return [review_grant(row) for row in rows]
