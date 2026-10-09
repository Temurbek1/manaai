from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.ports import Clock
from app.mana_operation_ai.domain.chat import ChatTopic
from app.mana_operation_ai.domain.goals import GoalCommand, GoalCreate, GoalEvent, OperationGoal
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    ChatBudgetRow,
    GoalCommandRow,
    GoalRow,
)


class SqlAlchemyGoalRepository:
    """SQL claims, optimistic fencing and durable controls across API/worker replicas."""

    def __init__(self, database: OperationDatabase, clock: Clock) -> None:
        self._sessions = database.session_factory
        self._clock = clock

    async def _lock(self, session: AsyncSession) -> None:
        await session.execute(
            update(ChatBudgetRow)
            .where(ChatBudgetRow.budget_id == "global")
            .values(revision=ChatBudgetRow.revision + 1)
        )

    async def _owned(self, session: AsyncSession, owner: str, goal_id: str) -> GoalRow:
        row = await session.scalar(
            select(GoalRow).where(GoalRow.goal_id == goal_id, GoalRow.owner == owner)
        )
        if row is None:
            raise ChatError("Цель не найдена.", 404)
        return row

    def _store(self, row: GoalRow, goal: OperationGoal) -> None:
        row.status = goal.status
        row.revision = goal.revision
        row.updated_at = goal.updated_at
        row.payload = goal.model_dump(mode="json")

    async def create(self, owner: str, topic: ChatTopic, request: GoalCreate) -> OperationGoal:
        async with self._sessions() as session, session.begin():
            await self._lock(session)
            existing = await session.scalar(
                select(GoalRow).where(
                    GoalRow.owner == owner, GoalRow.request_id == str(request.request_id)
                )
            )
            if existing:
                goal = OperationGoal.model_validate(existing.payload)
                if goal.topic_id != topic.topic_id or goal.request != request:
                    raise ChatError("Идентификатор уже используется другой целью.")
                return goal
            count = await session.scalar(
                select(func.count())
                .select_from(GoalRow)
                .where(GoalRow.owner == owner, GoalRow.status.not_in(("completed", "cancelled")))
            )
            if (count or 0) >= 20:
                raise ChatError("Достигнут лимит: 20 незавершённых целей на пользователя.", 429)
            active = await session.scalar(
                select(GoalRow.goal_id)
                .where(
                    GoalRow.topic_id == topic.topic_id,
                    GoalRow.status.not_in(("completed", "cancelled")),
                )
                .limit(1)
            )
            if active:
                raise ChatError("В этой теме уже есть незавершённая цель.")
            now = self._clock.now()
            goal = OperationGoal(
                goal_id=str(uuid4()),
                topic_id=topic.topic_id,
                agent_id=topic.agent_id,
                product=topic.product,
                request=request,
                created_at=now,
                updated_at=now,
                events=[GoalEvent(at=now, kind="created", message=request.objective)],
            )
            row = GoalRow(
                goal_id=goal.goal_id,
                topic_id=goal.topic_id,
                owner=owner,
                request_id=str(request.request_id),
            )
            self._store(row, goal)
            session.add(row)
            return goal

    async def list(self, owner: str, topic_id: str) -> list[OperationGoal]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(GoalRow)
                .where(GoalRow.owner == owner, GoalRow.topic_id == topic_id)
                .order_by(GoalRow.updated_at.desc())
                .limit(100)
            )
            return [OperationGoal.model_validate(row.payload) for row in rows]

    async def get(self, owner: str, goal_id: str) -> OperationGoal:
        async with self._sessions() as session:
            return OperationGoal.model_validate(
                (await self._owned(session, owner, goal_id)).payload
            )

    async def command(self, owner: str, goal_id: str, payload: GoalCommand) -> OperationGoal:
        async with self._sessions() as session, session.begin():
            await self._lock(session)
            row = await self._owned(session, owner, goal_id)
            goal = OperationGoal.model_validate(row.payload)
            prior = await session.scalar(
                select(GoalCommandRow).where(
                    GoalCommandRow.goal_id == goal_id,
                    GoalCommandRow.request_id == str(payload.request_id),
                )
            )
            if prior:
                if prior.payload != payload.model_dump(mode="json"):
                    raise ChatError("Идентификатор команды уже использован.")
                return goal
            if goal.revision != payload.expected_revision:
                raise ChatError("Состояние цели изменилось. Обновите страницу.")
            count = await session.scalar(
                select(func.count())
                .select_from(GoalCommandRow)
                .where(GoalCommandRow.goal_id == goal_id)
            )
            if (count or 0) >= 90 and payload.command not in ("cancel", "pause"):
                raise ChatError("Лимит управления целью исчерпан; создайте новую цель.", 429)
            if goal.status in ("completed", "cancelled"):
                raise ChatError("Цель закрыта. Для новой задачи создайте новую цель.")
            now = self._clock.now()
            if (
                payload.command in ("resume", "steer", "approve_read")
                and goal.lease_until
                and goal.lease_until > now
            ):
                raise ChatError("Текущий шаг ещё заканчивается. Дождитесь его остановки.")
            message = ""
            if payload.command == "pause":
                goal.status = "paused"
                message = "Цель приостановлена. Уже отправленный запрос может быть оплачен."
            elif payload.command == "cancel":
                goal.status = "cancelled"
                message = "Цель отменена. История сохранена."
            elif payload.command == "steer":
                if not payload.message.strip() or len(goal.instructions) >= 20:
                    raise ChatError("Добавьте уточнение; максимум 20 уточнений на цель.")
                goal.instructions.append(payload.message)
                goal.phase = "investigate" if goal.plan else "plan"
                goal.status = "queued"
                message = payload.message
            elif payload.command == "approve_read":
                if (
                    goal.status != "waiting"
                    or goal.requested_capability is None
                    or goal.read_attempted
                ):
                    raise ChatError("Нет ожидающего запроса на чтение.")
                goal.approved_capability = goal.requested_capability
                goal.status = "queued"
                message = "Подтверждён один read-only анализ. Доступ, приложение, "
                "интервал и бюджет проверяются отдельно."
            else:
                if goal.status not in ("paused", "waiting"):
                    raise ChatError("Цель уже выполняется.")
                goal.status = "queued"
                message = "Продолжаем с сохранённого шага; предыдущие расходы и лимиты сохранены."
            goal.waiting_reason = ""
            if payload.command not in ("pause", "cancel"):
                goal.lease_until = None
            goal.revision += 1
            goal.updated_at = now
            goal.events.append(GoalEvent(at=now, kind="control", message=message))
            goal.events = goal.events[-100:]
            self._store(row, goal)
            session.add(
                GoalCommandRow(
                    command_id=str(uuid4()),
                    goal_id=goal_id,
                    request_id=str(payload.request_id),
                    payload=payload.model_dump(mode="json"),
                )
            )
            return goal

    async def claim(self) -> tuple[str, OperationGoal] | None:
        # Empty queues cause no locking write and no upstream/source requests.
        async with self._sessions() as session:
            candidates = await session.scalars(
                select(GoalRow).where(GoalRow.status.in_(("queued", "running", "paused")))
            )
            now = self._clock.now()
            if not any(
                row.status == "queued"
                or (goal := OperationGoal.model_validate(row.payload)).lease_until is not None
                and goal.lease_until <= now
                for row in candidates
            ):
                return None
        async with self._sessions() as session, session.begin():
            await self._lock(session)
            now = self._clock.now()
            # A lost in-flight call must not be blindly retried after restart.
            running = await session.scalars(
                select(GoalRow).where(GoalRow.status.in_(("running", "paused")))
            )
            for row in running:
                goal = OperationGoal.model_validate(row.payload)
                if goal.lease_until and goal.lease_until <= now:
                    if goal.status == "running":
                        goal.status = "waiting"
                        goal.waiting_reason = "Шаг прерван. Исход запроса неизвестен; "
                        "резерв расходов сохранён. Автоматического повтора нет."
                        goal.events.append(
                            GoalEvent(at=now, kind="recovery", message=goal.waiting_reason)
                        )
                    goal.lease_until = None
                    goal.revision += 1
                    goal.updated_at = now
                    self._store(row, goal)
            await session.flush()
            queued_row = await session.scalar(
                select(GoalRow)
                .where(GoalRow.status == "queued")
                .order_by(GoalRow.updated_at, GoalRow.goal_id)
                .limit(1)
            )
            if queued_row is None:
                return None
            goal = OperationGoal.model_validate(queued_row.payload)
            goal.status = "running"
            goal.lease_until = now + timedelta(minutes=5)
            goal.revision += 1
            goal.updated_at = now
            self._store(queued_row, goal)
            return queued_row.owner, goal

    async def save(self, owner: str, before: OperationGoal, after: OperationGoal) -> bool:
        after = after.model_copy(
            update={"revision": before.revision + 1, "updated_at": self._clock.now()}
        )
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(GoalRow)
                .where(
                    GoalRow.goal_id == before.goal_id,
                    GoalRow.owner == owner,
                    GoalRow.revision == before.revision,
                )
                .values(
                    status=after.status,
                    revision=after.revision,
                    updated_at=after.updated_at,
                    payload=after.model_dump(mode="json"),
                )
            )
            return bool(result.rowcount)
