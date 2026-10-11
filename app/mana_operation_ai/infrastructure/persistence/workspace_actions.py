"""Reserve a human intent before dispatch; replay only observes its domain outcome."""

from datetime import datetime

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.workspace_actions import WorkspaceActionReceipt
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    ChatBudgetRow,
    ChatTopicRow,
    ChatTurnRow,
    WorkspaceActionRow,
)


def _receipt(payload: object) -> WorkspaceActionReceipt:
    try:
        return WorkspaceActionReceipt.model_validate(payload)
    except ValidationError as exc:
        raise ChatError(
            "Сохранённое решение требует совместимой версии или проверки.", 503
        ) from exc


class SqlAlchemyWorkspaceActions:
    def __init__(self, database: OperationDatabase) -> None:
        self._sessions = database.session_factory

    async def get(
        self, owner: str, topic_id: str, turn_id: str, proposal_id: str
    ) -> WorkspaceActionReceipt | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(WorkspaceActionRow).where(
                    WorkspaceActionRow.owner == owner,
                    WorkspaceActionRow.topic_id == topic_id,
                    WorkspaceActionRow.turn_id == turn_id,
                    WorkspaceActionRow.proposal_id == proposal_id,
                )
            )
            return _receipt(row.payload) if row is not None else None

    async def admit(
        self, owner: str, receipt: WorkspaceActionReceipt
    ) -> tuple[WorkspaceActionReceipt, bool]:
        try:
            async with self._sessions() as session, session.begin():
                # Shared SQL fence, not a process-local lock. SQLite starts with a write.
                await session.execute(
                    update(ChatBudgetRow)
                    .where(ChatBudgetRow.budget_id == "global")
                    .values(revision=ChatBudgetRow.revision + 1)
                )
                owned = await session.scalar(
                    select(ChatTurnRow.turn_id)
                    .join(ChatTopicRow, ChatTopicRow.topic_id == ChatTurnRow.topic_id)
                    .where(
                        ChatTopicRow.owner == owner,
                        ChatTopicRow.topic_id == receipt.topic_id,
                        ChatTurnRow.owner == owner,
                        ChatTurnRow.turn_id == receipt.turn_id,
                    )
                )
                if owned is None:
                    raise ChatError("Сообщение не найдено.", 404)
                row = await session.scalar(
                    select(WorkspaceActionRow).where(
                        WorkspaceActionRow.owner == owner,
                        WorkspaceActionRow.request_id == str(receipt.request.request_id),
                    )
                )
                if row is None:
                    row = await session.scalar(
                        select(WorkspaceActionRow).where(
                            WorkspaceActionRow.proposal_id == receipt.proposal_id
                        )
                    )
                if row is not None:
                    saved = _receipt(row.payload)
                    if row.owner != owner or (
                        saved.topic_id,
                        saved.turn_id,
                        saved.proposal_id,
                        saved.request,
                        saved.parameters,
                    ) != (
                        receipt.topic_id,
                        receipt.turn_id,
                        receipt.proposal_id,
                        receipt.request,
                        receipt.parameters,
                    ):
                        raise ChatError("Для этого запроса уже есть решение. Обновите состояние.")
                    return saved, False
                session.add(
                    WorkspaceActionRow(
                        receipt_id=receipt.receipt_id,
                        owner=owner,
                        topic_id=receipt.topic_id,
                        turn_id=receipt.turn_id,
                        proposal_id=receipt.proposal_id,
                        request_id=str(receipt.request.request_id),
                        created_at=receipt.created_at,
                        payload=receipt.model_dump(mode="json"),
                    )
                )
            return receipt, True
        except IntegrityError as exc:
            raise ChatError("Решение уже обрабатывается. Обновите состояние.") from exc

    async def finish(self, owner: str, receipt: WorkspaceActionReceipt) -> None:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(WorkspaceActionRow)
                .where(
                    WorkspaceActionRow.receipt_id == receipt.receipt_id,
                    WorkspaceActionRow.owner == owner,
                )
                .with_for_update()
            )
            if row is None:
                raise ChatError("Решение не найдено.", 404)
            saved = _receipt(row.payload)
            immutable = saved.model_copy(
                update={"state": receipt.state, "message": receipt.message}
            )
            if immutable != receipt or saved.state != "dispatching":
                raise ChatError("Состояние решения изменилось.")
            row.payload = receipt.model_dump(mode="json")

    async def receipts(
        self,
        owner: str,
        topic_id: str,
        *,
        turn_id: str | None = None,
        before: datetime | None = None,
        limit: int = 3,
    ) -> list[WorkspaceActionReceipt]:
        async with self._sessions() as session:
            query = select(WorkspaceActionRow).where(
                WorkspaceActionRow.owner == owner,
                WorkspaceActionRow.topic_id == topic_id,
            )
            if turn_id is not None:
                query = query.where(WorkspaceActionRow.turn_id == turn_id)
            if before is not None:
                query = query.where(WorkspaceActionRow.created_at < before)
            rows = await session.scalars(
                query.order_by(
                    WorkspaceActionRow.created_at.desc(), WorkspaceActionRow.receipt_id.desc()
                ).limit(min(3, max(1, limit)))
            )
            return [_receipt(row.payload) for row in rows]
