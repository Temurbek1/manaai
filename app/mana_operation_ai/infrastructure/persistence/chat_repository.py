from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.chat import (
    ChatTopic,
    ChatTurn,
    MessageCreate,
    RecentConversation,
    TopicCreate,
    TranscriptPage,
)
from app.mana_operation_ai.domain.session import SessionUserContext
from app.mana_operation_ai.domain.workspace_events import ChatTextEvent
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    ChatBudgetRow,
    ChatTopicRow,
    ChatTurnRow,
    WorkspaceEventRow,
)

ACTIVE = ("reading", "thinking")


def _turn(row: ChatTurnRow) -> ChatTurn:
    return ChatTurn.model_validate(
        {**row.payload, **(row.context_metadata or {}), **(row.workspace_metadata or {})}
    )


def _storage(turn: ChatTurn) -> dict[str, object]:
    """Keep the prior release's JSON readable during application-only rollback.

    New source provenance/inference fields live in an additive nullable column.
    Old code sees unknown provenance and no unsupported Parent confirmation card,
    never a fabricated read grant. Migration does not rewrite historical rows.
    """
    payload = turn.model_dump(
        mode="json",
        exclude={
            "read_confirmation",
            "analysis_kind",
            "model_choice",
            "reasoning",
            "execution_mode",
            "response_language",
            "session_memory",
            "preview",
            "preview_revision",
        },
    )
    metadata = {
        "analysis_kind": turn.analysis_kind,
        "model_choice": turn.model_choice,
        "reasoning": turn.reasoning,
        "sources": payload["sources"],
        "next_action": "none" if turn.next_action == "start_goal" else turn.next_action,
    }
    payload["sources"] = [
        {
            "report_id": source.report_id,
            "run_id": source.run_id,
            "created_at": source.created_at.isoformat(),
            "title": source.title,
            "scope_verified": False,
        }
        for source in turn.sources
    ]
    if turn.next_action in ("mana_parents", "start_goal"):
        payload["next_action"] = "none"
    workspace = None
    if (
        turn.execution_mode == "agent"
        or turn.next_action == "start_goal"
        or turn.session_memory
        or turn.preview_revision
        or turn.response_language is not None
    ):
        workspace = {
            **({"response_language": turn.response_language} if turn.response_language else {}),
            "execution_mode": turn.execution_mode,
            "next_action": turn.next_action,
            "session_memory": turn.session_memory.model_dump(mode="json")
            if turn.session_memory
            else None,
            **(
                {"preview": turn.preview, "preview_revision": turn.preview_revision}
                if turn.preview_revision
                else {}
            ),
        }
    return {"payload": payload, "context_metadata": metadata, "workspace_metadata": workspace}


class SqlAlchemyChatRepository:
    def __init__(
        self,
        database: OperationDatabase,
        *,
        hourly_limit: int,
        daily_limit: int,
        topic_message_limit: int = 100,
        stream_events_enabled: bool = False,
    ) -> None:
        if not 100 <= topic_message_limit <= 10000:
            raise ValueError("Topic message capacity must be between 100 and 10000")
        self._sessions = database.session_factory
        self._hourly_limit = hourly_limit
        self._daily_limit = daily_limit
        self._topic_message_limit = topic_message_limit
        self._stream_events_enabled = stream_events_enabled

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
            rows = (
                await session.execute(
                    select(*self._public_columns())
                    .where(ChatTurnRow.topic_id == topic_id, ChatTurnRow.owner == owner)
                    .order_by(ChatTurnRow.created_at.desc(), ChatTurnRow.turn_id.desc())
                    .limit(100)
                )
            ).all()
            return list(reversed([self._public_turn(row) for row in rows]))

    async def turn(self, owner: str, topic_id: str, turn_id: str) -> ChatTurn:
        async with self._sessions() as session:
            await self._owned(session, owner, topic_id)
            row = await session.scalar(
                select(ChatTurnRow).where(
                    ChatTurnRow.owner == owner,
                    ChatTurnRow.topic_id == topic_id,
                    ChatTurnRow.turn_id == turn_id,
                )
            )
            if row is None:
                raise ChatError("Сообщение не найдено.", 404)
            return _turn(row)

    @staticmethod
    def _public_columns() -> tuple[Any, ...]:
        # Do not fetch/decode repeated private session-memory blobs for a history page.
        return (
            ChatTurnRow.payload,
            ChatTurnRow.context_metadata,
            ChatTurnRow.workspace_metadata["execution_mode"].as_string(),
            ChatTurnRow.workspace_metadata["next_action"].as_string(),
            ChatTurnRow.workspace_metadata["preview"].as_string(),
            ChatTurnRow.workspace_metadata["preview_revision"].as_integer(),
        )

    @staticmethod
    def _public_turn(row: Any) -> ChatTurn:
        payload, metadata, mode, action, preview, preview_revision = row
        return ChatTurn.model_validate(
            {
                **payload,
                **(metadata or {}),
                **({"execution_mode": mode} if mode is not None else {}),
                **({"next_action": action} if action is not None else {}),
                "session_memory": None,
                "preview": preview or "",
                "preview_revision": preview_revision or 0,
            }
        )

    async def transcript_page(
        self, owner: str, topic_id: str, *, before: str | None, limit: int = 20
    ) -> TranscriptPage:
        if not 1 <= limit <= 30:
            raise ChatError("Размер страницы должен быть от 1 до 30.", 422)
        async with self._sessions() as session:
            topic = ChatTopic.model_validate((await self._owned(session, owner, topic_id)).payload)
            conditions = [ChatTurnRow.owner == owner, ChatTurnRow.topic_id == topic_id]
            if before is not None:
                anchor = await session.execute(
                    select(ChatTurnRow.created_at, ChatTurnRow.turn_id).where(
                        ChatTurnRow.owner == owner,
                        ChatTurnRow.topic_id == topic_id,
                        ChatTurnRow.turn_id == before,
                    )
                )
                point = anchor.one_or_none()
                if point is None:
                    raise ChatError("Курсор истории недоступен в этой теме.", 404)
                conditions.append(
                    or_(
                        ChatTurnRow.created_at < point[0],
                        and_(ChatTurnRow.created_at == point[0], ChatTurnRow.turn_id < point[1]),
                    )
                )
            rows = list(
                (
                    await session.execute(
                        select(*self._public_columns())
                        .where(*conditions)
                        .order_by(ChatTurnRow.created_at.desc(), ChatTurnRow.turn_id.desc())
                        .limit(limit + 1)
                    )
                ).all()
            )
            turns = list(reversed([self._public_turn(row) for row in rows[:limit]]))
            return TranscriptPage(
                topic=topic,
                turns=turns,
                has_more=len(rows) > limit,
                next_cursor=turns[0].turn_id if len(rows) > limit else None,
            )

    async def recent_conversation(
        self, owner: str, topic_id: str, *, before: datetime
    ) -> RecentConversation:
        async with self._sessions() as session:
            await self._owned(session, owner, topic_id)
            conditions = [
                ChatTurnRow.owner == owner,
                ChatTurnRow.topic_id == topic_id,
                ChatTurnRow.status == "completed",
                ChatTurnRow.created_at < before,
            ]
            rows = (
                await session.execute(
                    select(*self._public_columns())
                    .where(*conditions)
                    .order_by(ChatTurnRow.created_at.desc(), ChatTurnRow.turn_id.desc())
                    .limit(6)
                )
            ).all()
            count = await session.scalar(
                select(func.count()).select_from(ChatTurnRow).where(*conditions)
            )
            return RecentConversation(
                turns=list(reversed([self._public_turn(row) for row in rows])),
                older_turns_omitted=max(0, (count or 0) - 6),
            )

    async def user_context(
        self, owner: str, topic_id: str, *, before: datetime
    ) -> AsyncGenerator[SessionUserContext, None]:
        async with self._sessions() as session:
            await self._owned(session, owner, topic_id)
            stream = await session.stream(
                select(ChatTurnRow.turn_id, ChatTurnRow.payload["message"].as_string())
                .where(
                    ChatTurnRow.owner == owner,
                    ChatTurnRow.topic_id == topic_id,
                    ChatTurnRow.created_at < before,
                )
                .order_by(ChatTurnRow.created_at, ChatTurnRow.turn_id)
                .execution_options(yield_per=50)
            )
            async for row in stream:
                yield SessionUserContext(kind="user_message", text=row[1], origin_id=row[0])

    async def _lock_budget(self, session: AsyncSession) -> None:
        # A real write serializes admission on PostgreSQL AND SQLite, across API processes.
        await session.execute(
            update(ChatBudgetRow)
            .where(ChatBudgetRow.budget_id == "global")
            .values(revision=ChatBudgetRow.revision + 1)
        )

    async def _expire(self, session: AsyncSession) -> None:
        await self._lock_writes(session)
        rows = await session.scalars(
            select(ChatTurnRow)
            .where(
                ChatTurnRow.status.in_(ACTIVE),
                ChatTurnRow.created_at < datetime.now(UTC) - timedelta(minutes=3),
            )
            .with_for_update(skip_locked=True)
        )
        for row in rows:
            turn = _turn(row).model_copy(
                update={
                    "status": "failed",
                    "answer": "Ответ прерван. Автоматического повторного запроса не будет.",
                }
            )
            await self._update(session, row, turn)

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
                turn = _turn(existing)
                if (
                    turn.message != payload.message
                    or turn.model_choice != payload.model_choice
                    or turn.reasoning != payload.reasoning
                    or turn.execution_mode != payload.execution_mode
                    or turn.response_language != payload.response_language
                ):
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
            if (count or 0) >= self._topic_message_limit:
                raise ChatError(
                    f"Достигнут лимит темы: {self._topic_message_limit} сообщений.", 429
                )
            turn = ChatTurn(
                turn_id=str(uuid4()),
                topic_id=topic_id,
                request_id=payload.request_id,
                message=payload.message,
                model_choice=payload.model_choice,
                reasoning=payload.reasoning,
                execution_mode=payload.execution_mode,
                response_language=payload.response_language,
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
                    **_storage(turn),
                )
            )
            return turn, True

    async def update(self, turn: ChatTurn) -> bool:
        async with self._sessions() as session, session.begin():
            await self._lock_writes(session)
            row = await session.scalar(
                select(ChatTurnRow)
                .where(ChatTurnRow.turn_id == turn.turn_id, ChatTurnRow.topic_id == turn.topic_id)
                .with_for_update()
            )
            if row is None or row.status not in ACTIVE:
                return False
            return await self._update(session, row, turn)

    async def _lock_writes(self, session: AsyncSession) -> None:
        # Share the Goal journal fence: cursor allocation must follow commit
        # order across both kinds of events. It also replaces SQLite's ignored
        # FOR UPDATE for preview/stop/recovery races. Never hold it over I/O.
        await self._lock_budget(session)

    async def _update(self, session: AsyncSession, row: ChatTurnRow, turn: ChatTurn) -> bool:
        prior = _turn(row)
        terminal = turn.status not in ACTIVE and prior.preview_revision > 0
        turn = turn.model_copy(
            update={
                "preview": prior.preview,
                "preview_revision": prior.preview_revision + int(terminal),
            }
        )
        result = await session.execute(
            update(ChatTurnRow)
            .where(ChatTurnRow.turn_id == turn.turn_id, ChatTurnRow.status.in_(ACTIVE))
            .values(status=turn.status, **_storage(turn))
        )
        if result.rowcount and terminal:
            event = ChatTextEvent(
                event_id=0,
                topic_id=turn.topic_id,
                turn_id=turn.turn_id,
                revision=turn.preview_revision,
                at=datetime.now(UTC),
                status=turn.status,
                offset=len(turn.preview),
                final_answer=turn.answer,
            )
            session.add(
                WorkspaceEventRow(
                    owner=row.owner,
                    topic_id=turn.topic_id,
                    payload=event.model_dump(mode="json", exclude={"event_id"}),
                )
            )
        return bool(result.rowcount)

    async def preview(self, owner: str, topic_id: str, turn_id: str, text: str) -> bool:
        if not self._stream_events_enabled:
            raise ChatError("Поток текста отключён.", 503)
        if len(text) > 16000:
            raise ChatError("Черновик ответа достиг лимита.", 422)
        async with self._sessions() as session, session.begin():
            await self._lock_writes(session)
            await self._owned(session, owner, topic_id)
            row = await session.scalar(
                select(ChatTurnRow)
                .where(
                    ChatTurnRow.turn_id == turn_id,
                    ChatTurnRow.owner == owner,
                    ChatTurnRow.topic_id == topic_id,
                )
                .with_for_update()
            )
            if row is None or row.status not in ACTIVE:
                return False
            prior = _turn(row)
            if not text.startswith(prior.preview):
                raise ChatError("Поток ответа изменил уже переданный префикс.")
            if text == prior.preview:
                return True
            if prior.preview_revision >= 128:
                return True  # Final validated reply still replaces the draft once.
            revision = prior.preview_revision + 1
            metadata = {
                **(row.workspace_metadata or {}),
                "preview": text,
                "preview_revision": revision,
            }
            result = await session.execute(
                update(ChatTurnRow)
                .where(
                    ChatTurnRow.turn_id == turn_id,
                    ChatTurnRow.status.in_(ACTIVE),
                    func.coalesce(
                        ChatTurnRow.workspace_metadata["preview_revision"].as_integer(), 0
                    )
                    == prior.preview_revision,
                )
                .values(workspace_metadata=metadata)
            )
            if not result.rowcount:
                return False
            event = ChatTextEvent(
                event_id=0,
                topic_id=topic_id,
                turn_id=turn_id,
                revision=revision,
                at=datetime.now(UTC),
                status="thinking",
                offset=len(prior.preview),
                delta=text[len(prior.preview) :],
            )
            session.add(
                WorkspaceEventRow(
                    owner=owner,
                    topic_id=topic_id,
                    payload=event.model_dump(mode="json", exclude={"event_id"}),
                )
            )
            return True

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
            turn = _turn(row)
        if turn.status in ACTIVE:
            turn = turn.model_copy(
                update={
                    "status": "cancelled",
                    "answer": "Ответ остановлен. Уже отправленный запрос к AI может быть оплачен.",
                }
            )
            await self.update(turn)
        return await self.turn(owner, topic_id, turn_id)
