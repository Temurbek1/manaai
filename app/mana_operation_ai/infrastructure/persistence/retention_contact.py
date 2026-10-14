"""Isolated typed SQL state: old action readers/workers never see this family."""

from datetime import UTC, timedelta

from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.retention_contact import (
    RetentionContactAction,
    RetentionContactEvent,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    ChatTopicRow,
    RetentionContactEventRow,
    RetentionContactGuardRow,
    RetentionContactRow,
)


def _action(row: RetentionContactRow) -> RetentionContactAction:
    try:
        value = RetentionContactAction.model_validate(row.payload)
        if (value.action_id, value.owner, value.topic_id, value.status, value.revision) != (
            row.action_id,
            row.owner,
            row.topic_id,
            row.status,
            row.revision,
        ):
            raise ValueError("Private row binding changed")
        if row.request_id != str(value.request.request_id) or row.decision_id != (
            str(value.decision.request_id) if value.decision else None
        ):
            raise ValueError("Private request binding changed")
        return value
    except (ValidationError, ValueError):
        raise ChatError("Сохранённое контактное действие требует проверки.", 503) from None


class SqlAlchemyRetentionContacts:
    def __init__(self, database: OperationDatabase) -> None:
        self._sessions = database.session_factory

    async def by_request(self, owner: str, request_id: str) -> RetentionContactAction | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(RetentionContactRow).where(
                    RetentionContactRow.owner == owner,
                    RetentionContactRow.request_id == request_id,
                )
            )
            return _action(row) if row is not None else None

    async def get(self, owner: str, action_id: str) -> RetentionContactAction:
        async with self._sessions() as session:
            row = await session.scalar(
                select(RetentionContactRow).where(
                    RetentionContactRow.owner == owner,
                    RetentionContactRow.action_id == action_id,
                )
            )
            if row is None:
                raise ChatError("Действие не найдено.", 404)
            return _action(row)

    async def create(self, action: RetentionContactAction) -> RetentionContactAction:
        try:
            async with self._sessions() as session, session.begin():
                owned = await session.scalar(
                    select(ChatTopicRow.topic_id).where(
                        ChatTopicRow.owner == action.owner,
                        ChatTopicRow.topic_id == action.topic_id,
                    )
                )
                if owned is None:
                    raise ChatError("Тема не найдена.", 404)
                if action.revision != 0 or action.status not in {"proposed", "refused"}:
                    raise ChatError("Недопустимое начальное состояние.")
                session.add(
                    RetentionContactRow(
                        action_id=action.action_id,
                        owner=action.owner,
                        topic_id=action.topic_id,
                        request_id=str(action.request.request_id),
                        decision_id=None,
                        status=action.status,
                        revision=0,
                        payload=action.model_dump(mode="json"),
                    )
                )
                await session.flush()
                session.add(
                    RetentionContactEventRow(
                        action_id=action.action_id,
                        revision=0,
                        payload=RetentionContactEvent(
                            action_id=action.action_id,
                            revision=0,
                            at=action.prepared_at,
                            status=action.status,
                            code=action.result_code,
                        ).model_dump(mode="json"),
                    )
                )
            return action
        except IntegrityError:
            existing = await self.by_request(action.owner, str(action.request.request_id))
            if (
                existing is not None
                and existing.topic_id == action.topic_id
                and existing.request == action.request
            ):
                return existing
            raise ChatError("Запрос уже связан с другим контактным действием.") from None

    async def transition(
        self,
        previous: RetentionContactAction,
        updated: RetentionContactAction,
        event: RetentionContactEvent,
    ) -> bool:
        graph = {
            "proposed": {"rejected", "dispatching", "refused"},
            "dispatching": {"verified", "uncertain", "refused"},
            "uncertain": {"verified"},
        }
        if (
            updated.status not in graph.get(previous.status, set())
            or updated.revision != previous.revision + 1
        ):
            raise ChatError("Недопустимый переход контактного действия.")
        mutable = {"status", "revision", "decision", "decided_by", "delivery", "result_code"}
        if previous.model_dump(exclude=mutable) != updated.model_dump(exclude=mutable) or (
            previous.decision is not None
            and (previous.decision != updated.decision or previous.decided_by != updated.decided_by)
        ):
            raise ChatError("Условия контактного действия не могут измениться.")
        if (event.action_id, event.revision, event.status, event.code) != (
            updated.action_id,
            updated.revision,
            updated.status,
            updated.result_code,
        ):
            raise ChatError("Событие не соответствует контактному действию.")
        try:
            async with self._sessions() as session, session.begin():
                row = await session.scalar(
                    select(RetentionContactRow)
                    .where(
                        RetentionContactRow.action_id == previous.action_id,
                        RetentionContactRow.owner == previous.owner,
                    )
                    .with_for_update()
                )
                if row is None or _action(row) != previous:
                    return False
                account = previous.request.parameters.account_ref
                guard = await session.scalar(
                    select(RetentionContactGuardRow)
                    .where(
                        RetentionContactGuardRow.account_ref == account,
                    )
                    .with_for_update()
                )
                if updated.status == "dispatching":
                    if guard is not None:
                        expires = guard.expires_at
                        if expires is not None:
                            expires = (
                                expires.replace(tzinfo=UTC)
                                if expires.tzinfo is None
                                else expires.astimezone(UTC)
                            )
                        if expires is None or expires > event.at:
                            raise ChatError(
                                "Контакт уже выполняется или действует ограничение частоты."
                            )
                        guard.action_id, guard.expires_at = updated.action_id, None
                    else:
                        session.add(
                            RetentionContactGuardRow(
                                account_ref=account, action_id=updated.action_id, expires_at=None
                            )
                        )
                elif guard is not None and guard.action_id == updated.action_id:
                    if updated.status == "verified" and updated.delivery is not None:
                        guard.expires_at = updated.delivery.accepted_at + timedelta(days=7)
                    elif updated.status == "refused":
                        # Only the pre-dispatch branch may prove that nothing was sent.
                        await session.execute(
                            delete(RetentionContactGuardRow).where(
                                RetentionContactGuardRow.account_ref == account,
                                RetentionContactGuardRow.action_id == updated.action_id,
                            )
                        )
                changed = await session.execute(
                    update(RetentionContactRow)
                    .where(
                        RetentionContactRow.action_id == previous.action_id,
                        RetentionContactRow.revision == previous.revision,
                    )
                    .values(
                        status=updated.status,
                        revision=updated.revision,
                        decision_id=str(updated.decision.request_id) if updated.decision else None,
                        payload=updated.model_dump(mode="json"),
                    )
                )
                if changed.rowcount != 1:
                    raise ChatError("Контактное действие изменилось; выполнение не допущено.")
                session.add(
                    RetentionContactEventRow(
                        action_id=updated.action_id,
                        revision=updated.revision,
                        payload=event.model_dump(mode="json"),
                    )
                )
            return True
        except IntegrityError:
            raise ChatError(
                "Решение или контакт уже зарезервированы. Повторной отправки нет."
            ) from None
