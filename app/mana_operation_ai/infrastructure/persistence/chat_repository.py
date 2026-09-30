from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.chat import ChatTopic, ChatTurn, MessageCreate, TopicCreate
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    ChatBudgetRow,
    ChatTopicRow,
    ChatTurnRow,
)

ACTIVE = ("reading", "thinking")


class SqlAlchemyChatRepository:
    def __init__(self, database: OperationDatabase, *, hourly_limit: int, daily_limit: int) -> None:
        self._sessions = database.session_factory
        self._hourly_limit = hourly_limit
        self._daily_limit = daily_limit

    async def initialize(self) -> None:
        # Migration seeds production. This also supports isolated create_schema test databases.
        async with self._sessions() as session:
            if await session.get(ChatBudgetRow, "global") is None:
                session.add(ChatBudgetRow(budget_id="global", revision=0))
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()

    async def topics(self, owner: str) -> list[ChatTopic]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(ChatTopicRow)
                .where(ChatTopicRow.owner == owner)
                .order_by(ChatTopicRow.updated_at.desc())
                .limit(100)
            )
            return [ChatTopic.model_validate(row.payload) for row in rows]

    async def create(self, owner: str, payload: TopicCreate) -> ChatTopic:
        async with self._sessions() as session, session.begin():
            await self._lock_budget(session)
            count = await session.scalar(
                select(func.count()).select_from(ChatTopicRow).where(ChatTopicRow.owner == owner)
            )
            if (count or 0) >= 100:
                raise ChatError("Достигнут лимит: 100 тем на пользователя.", 429)
            now = datetime.now(UTC)
            topic = ChatTopic(
                **payload.model_dump(), topic_id=str(uuid4()), created_at=now, updated_at=now
            )
            session.add(
                ChatTopicRow(
                    topic_id=topic.topic_id,
                    owner=owner,
                    updated_at=now,
                    payload=topic.model_dump(mode="json"),
                )
            )
            return topic

    async def _owned(self, session: AsyncSession, owner: str, topic_id: str) -> ChatTopicRow:
        row = await session.scalar(
            select(ChatTopicRow).where(
                ChatTopicRow.topic_id == topic_id, ChatTopicRow.owner == owner
            )
        )
        if row is None:
            raise ChatError("Тема не найдена.", 404)
        return row

    async def topic(self, owner: str, topic_id: str) -> ChatTopic:
        async with self._sessions() as session:
            row = await self._owned(session, owner, topic_id)
            return ChatTopic.model_validate(row.payload)

    async def turns(self, owner: str, topic_id: str) -> list[ChatTurn]:
        async with self._sessions() as session, session.begin():
            await self._owned(session, owner, topic_id)
            await self._expire(session)
            rows = await session.scalars(
                select(ChatTurnRow)
                .where(ChatTurnRow.topic_id == topic_id, ChatTurnRow.owner == owner)
                .order_by(ChatTurnRow.created_at, ChatTurnRow.turn_id)
                .limit(100)
            )
            return [ChatTurn.model_validate(row.payload) for row in rows]

    async def _lock_budget(self, session: AsyncSession) -> None:
        # A real write serializes admission on PostgreSQL AND SQLite, across API processes.
        await session.execute(
            update(ChatBudgetRow)
            .where(ChatBudgetRow.budget_id == "global")
            .values(revision=ChatBudgetRow.revision + 1)
        )

    async def _expire(self, session: AsyncSession) -> None:
        rows = await session.scalars(
            select(ChatTurnRow).where(
                ChatTurnRow.status.in_(ACTIVE),
                ChatTurnRow.created_at < datetime.now(UTC) - timedelta(minutes=3),
            )
        )
        for row in rows:
            turn = ChatTurn.model_validate(row.payload).model_copy(
                update={
                    "status": "failed",
                    "answer": "Ответ прерван. Автоматического повторного запроса не будет.",
                }
            )
            await session.execute(
                update(ChatTurnRow)
                .where(ChatTurnRow.turn_id == row.turn_id, ChatTurnRow.status.in_(ACTIVE))
                .values(status=turn.status, payload=turn.model_dump(mode="json"))
            )

    async def reserve(
        self, owner: str, topic_id: str, payload: MessageCreate
    ) -> tuple[ChatTurn, bool]:
        async with self._sessions() as session, session.begin():
            await self._lock_budget(session)
            topic_row = await self._owned(session, owner, topic_id)
            await self._expire(session)
            existing = await session.scalar(
                select(ChatTurnRow).where(
                    ChatTurnRow.topic_id == topic_id,
                    ChatTurnRow.request_id == str(payload.request_id),
                )
            )
            if existing is not None:
                turn = ChatTurn.model_validate(existing.payload)
                if turn.message != payload.message:
                    raise ChatError("Идентификатор запроса уже использован для другого сообщения.")
                return turn, False
            active = await session.scalar(
                select(ChatTurnRow.turn_id)
                .where(ChatTurnRow.owner == owner, ChatTurnRow.status.in_(ACTIVE))
                .limit(1)
            )
            if active:
                raise ChatError("Дождитесь ответа в другой теме или остановите его.")
            now = datetime.now(UTC)
            recent = await session.scalar(
                select(func.count())
                .select_from(ChatTurnRow)
                .where(
                    ChatTurnRow.owner == owner,
                    ChatTurnRow.created_at >= now - timedelta(hours=1),
                )
            )
            daily = await session.scalar(
                select(func.count())
                .select_from(ChatTurnRow)
                .where(ChatTurnRow.created_at >= now - timedelta(days=1))
            )
            if (recent or 0) >= self._hourly_limit or (daily or 0) >= self._daily_limit:
                raise ChatError("Лимит сообщений исчерпан. Попробуйте позже.", 429)
            count = await session.scalar(
                select(func.count())
                .select_from(ChatTurnRow)
                .where(ChatTurnRow.topic_id == topic_id)
            )
            if (count or 0) >= 100:
                raise ChatError("В теме уже 100 сообщений. Создайте новую тему.", 429)
            turn = ChatTurn(
                turn_id=str(uuid4()),
                topic_id=topic_id,
                request_id=payload.request_id,
                message=payload.message,
                status="reading",
                created_at=now,
            )
            topic = ChatTopic.model_validate(topic_row.payload).model_copy(
                update={"updated_at": now}
            )
            topic_row.payload = topic.model_dump(mode="json")
            topic_row.updated_at = now
            session.add(
                ChatTurnRow(
                    turn_id=turn.turn_id,
                    topic_id=topic_id,
                    owner=owner,
                    request_id=str(payload.request_id),
                    status=turn.status,
                    created_at=now,
                    payload=turn.model_dump(mode="json"),
                )
            )
            return turn, True

    async def update(self, turn: ChatTurn) -> bool:
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(ChatTurnRow)
                .where(ChatTurnRow.turn_id == turn.turn_id, ChatTurnRow.status.in_(ACTIVE))
                .values(status=turn.status, payload=turn.model_dump(mode="json"))
            )
            return bool(result.rowcount)

    async def cancel(self, owner: str, topic_id: str, turn_id: str) -> ChatTurn:
        async with self._sessions() as session:
            await self._owned(session, owner, topic_id)
            row = await session.scalar(
                select(ChatTurnRow).where(
                    ChatTurnRow.turn_id == turn_id,
                    ChatTurnRow.topic_id == topic_id,
                    ChatTurnRow.owner == owner,
                )
            )
            if row is None:
                raise ChatError("Сообщение не найдено.", 404)
            turn = ChatTurn.model_validate(row.payload)
        if turn.status in ACTIVE:
            turn = turn.model_copy(
                update={
                    "status": "cancelled",
                    "answer": "Ответ остановлен. Уже отправленный запрос к AI может быть оплачен.",
                }
            )
            await self.update(turn)
        return next(item for item in await self.turns(owner, topic_id) if item.turn_id == turn_id)
