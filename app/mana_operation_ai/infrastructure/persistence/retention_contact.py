"""Isolated typed SQL state: old action readers/workers never see this family."""

from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.mana_operation_ai.application.chat_ports import ChatError, SessionContextTooLarge
from app.mana_operation_ai.domain.retention_contact import (
    RetentionContactAction,
    RetentionContactEvent,
)
from app.mana_operation_ai.domain.workspace_retention_contacts import WorkspaceContactHistory
from app.mana_operation_ai.infrastructure.persistence.contact_reviews import (
    review_grant,
    reviewer_is_active,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    AdminUserRow,
    ChatTopicRow,
    ChatTurnRow,
    ContactReviewGrantRow,
    RetentionContactEventRow,
    RetentionContactGuardRow,
    RetentionContactRow,
)
from app.mana_operation_ai.infrastructure.persistence.retention_contact_state import (
    contact_action as _action,
)


class SqlAlchemyRetentionContacts:
    def __init__(self, database: OperationDatabase, *, history_event_limit: int = 400) -> None:
        if not 4 <= history_event_limit <= 10000:
            raise ValueError("Contact history capture requires an explicit bounded SQL event limit")
        self._sessions = database.session_factory
        self._history_event_limit = history_event_limit

    async def history(
        self, owner: str, topic_id: str, *, before: datetime
    ) -> list[WorkspaceContactHistory]:
        if before.utcoffset() is None:
            raise ValueError("Contact history requires an aware capture cutoff")
        latest: dict[str, WorkspaceContactHistory] = {}
        seen: dict[str, RetentionContactEvent] = {}
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(RetentionContactRow, RetentionContactEventRow)
                    .join(RetentionContactEventRow)
                    .join(ChatTopicRow, ChatTopicRow.topic_id == RetentionContactRow.topic_id)
                    .where(
                        RetentionContactRow.owner == owner,
                        RetentionContactRow.topic_id == topic_id,
                        ChatTopicRow.owner == owner,
                        ChatTopicRow.payload["product"].as_string() == "mana",
                    )
                    .order_by(RetentionContactRow.action_id, RetentionContactEventRow.revision)
                    .limit(self._history_event_limit + 1)
                )
            ).all()
            if len(rows) > self._history_event_limit:
                raise SessionContextTooLarge()
            for row, event_row in rows:
                action = _action(row)
                try:
                    event = RetentionContactEvent.model_validate(event_row.payload)
                    previous = seen.get(action.action_id)
                    if (
                        (event.action_id, event.revision)
                        != (event_row.action_id, event_row.revision)
                        or event.revision > action.revision
                        or event.at < action.prepared_at
                        or (previous is not None and event.at < previous.at)
                        or (
                            event.revision == action.revision
                            and (event.status, event.code) != (action.status, action.result_code)
                        )
                    ):
                        raise ValueError("Contact event binding changed")
                except (ValidationError, ValueError):
                    raise ChatError("История контактного действия требует проверки.", 503) from None
                seen[action.action_id] = event
                # Revision events provide the original state at the cutoff, even
                # if this action's current row changed after generation started.
                if action.turn_id is None or event.at >= before:
                    continue
                latest[action.action_id] = WorkspaceContactHistory(
                    action_id=action.action_id,
                    turn_id=action.turn_id,
                    at=event.at,
                    revision=event.revision,
                    status=event.status,
                    template=action.message.template,
                    language=action.message.language,
                    message_sha256=action.message.sha256,
                )
        return sorted(latest.values(), key=lambda item: (item.at, item.action_id), reverse=True)[:3]

    async def list_for_turn(
        self, owner: str, topic_id: str, turn_id: str
    ) -> list[RetentionContactAction]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(RetentionContactRow)
                .where(
                    RetentionContactRow.owner == owner,
                    RetentionContactRow.topic_id == topic_id,
                    RetentionContactRow.payload["turn_id"].as_string() == turn_id,
                )
                .order_by(RetentionContactRow.action_id)
                .limit(4)
            )
            return [_action(row) for row in rows]

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
                if action.turn_id is not None:
                    turn = await session.scalar(
                        select(ChatTurnRow).where(
                            ChatTurnRow.turn_id == action.turn_id,
                            ChatTurnRow.topic_id == action.topic_id,
                            ChatTurnRow.owner == action.owner,
                        )
                    )
                    if (
                        turn is None
                        or turn.status != "completed"
                        or (turn.workspace_metadata or {}).get("execution_mode") != "agent"
                        or (turn.workspace_metadata or {}).get("next_action")
                        != "retention_contacts"
                    ):
                        raise ChatError(
                            "Контактное действие не связано с запросившим сообщением.", 403
                        )
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
                and existing.turn_id == action.turn_id
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
                if previous.status == "proposed" and updated.decided_by not in {
                    None,
                    previous.owner,
                }:
                    grant_row = await session.scalar(
                        select(ContactReviewGrantRow)
                        .where(ContactReviewGrantRow.action_id == previous.action_id)
                        .with_for_update()
                    )
                    reviewer = await session.get(
                        AdminUserRow, updated.decided_by, with_for_update=True
                    )
                    owner = await session.get(AdminUserRow, previous.owner, with_for_update=True)
                    if grant_row is None:
                        raise ChatError("Для этого сотрудника нет согласования.", 403)
                    grant = review_grant(grant_row)
                    if (
                        not grant.matches(previous)
                        or str(grant.request.reviewer_id) != updated.decided_by
                        or grant.revoked_at is not None
                        or event.at >= grant.expires_at
                        or not reviewer_is_active(reviewer)
                        or owner is None
                        or owner.status != "active"
                        or owner.role not in {"operator", "approver", "admin"}
                    ):
                        raise ChatError("Доступ к согласованию отозван или истёк.", 403)
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
