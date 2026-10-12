from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, TypedDict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.mana_operation_ai.application.chat_ports import ChatError, SessionContextTooLarge
from app.mana_operation_ai.application.goal_ports import SavedTaskPage
from app.mana_operation_ai.application.model_continuation import continuation_scope_digest
from app.mana_operation_ai.application.ports import Clock
from app.mana_operation_ai.domain.agent_tools import REPORT_PAGE_TOOL, TASK_HISTORY_TOOLS
from app.mana_operation_ai.domain.chat import ChatTopic, ProductScope
from app.mana_operation_ai.domain.goals import (
    GoalCommand,
    GoalCreate,
    GoalEvent,
    GoalStatus,
    OperationGoal,
)
from app.mana_operation_ai.domain.session import SessionMemory
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    ChatBudgetRow,
    GoalCommandRow,
    GoalRow,
)
from app.mana_operation_ai.infrastructure.persistence.workspace_events import append_goal_event


class _WorkspaceCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1, 2, 3, 4, 5, 6, 7, 8] = 1
    analysis_scope: Literal["current", "saved_snapshot"] | None = None
    goal: OperationGoal


class _GoalStorage(TypedDict):
    status: str
    revision: int
    updated_at: datetime
    payload: dict[str, object]
    workspace_status: str | None
    workspace_payload: dict[str, object] | None


@dataclass(frozen=True)
class WorkspaceRollbackReport:
    active_goals: int
    live_leases: int
    paused_goals: int = 0


def _goal(row: GoalRow) -> OperationGoal:
    if row.workspace_payload is None and row.workspace_status is None:
        return OperationGoal.model_validate(row.payload)
    try:
        checkpoint = _WorkspaceCheckpoint.model_validate(row.workspace_payload)
    except ValidationError as exc:
        raise ChatError("Сохранённая цель требует совместимой версии рабочей среды.", 503) from exc
    goal = checkpoint.goal
    memory = goal.session_memory
    extended_context = _extended_context(goal)
    continuation = goal.model_continuation
    format_feedback = (
        goal.model_feedback is not None and goal.model_feedback.code == "invalid_decision"
    )
    paged_reports = _paged_reports(goal)
    if (
        (checkpoint.version == 8) != paged_reports
        or (checkpoint.version == 5)
        != (not paged_reports and extended_context and continuation is None)
        or (checkpoint.version == 7) != (not paged_reports and format_feedback)
        or (checkpoint.version == 6)
        != (not paged_reports and continuation is not None and not format_feedback)
        or (
            continuation is None and (goal.model_feedback is not None or goal.model_recoveries != 0)
        )
        or (
            checkpoint.version in (5, 6, 7, 8)
            and checkpoint.analysis_scope != goal.request.analysis_scope
        )
        or (checkpoint.version not in (5, 6, 7, 8) and checkpoint.analysis_scope is not None)
        or (
            checkpoint.version not in (5, 6, 7, 8)
            and (checkpoint.version == 4) != (goal.request.analysis_scope == "saved_snapshot")
        )
        or (checkpoint.version == 1 and memory is not None)
        or (checkpoint.version == 2 and memory is None)
        or (checkpoint.version == 2 and memory is not None and bool(memory.actions))
        or (checkpoint.version == 3 and (memory is None or not memory.actions))
        or (paged_reports and goal.request.execution_mode != "agent")
        or (
            paged_reports
            and any(
                len(item.summary) > 5000 and item.report_read_progress is None
                for item in goal.evidence
            )
        )
        or (paged_reports and any(item.product != goal.product for item in goal.evidence))
        or (
            memory is not None
            and (memory.topic_id != goal.topic_id or memory.product != goal.product)
        )
        or (
            continuation is not None
            and (
                goal.request.execution_mode != "agent"
                or continuation.scope_digest != continuation_scope_digest(row.owner, goal)
            )
        )
    ):
        raise ChatError("Сохранённая цель требует проверки совместимости контекста.", 503)
    if row.workspace_status != goal.status or row.revision != goal.revision:
        raise ChatError("Сохранённая цель требует проверки совместимости версии.", 503)
    return goal


def _extended_context(goal: OperationGoal) -> bool:
    return any(record.call.name in TASK_HISTORY_TOOLS for record in goal.tools) or bool(
        goal.session_memory and any(item.also_kinds for item in goal.session_memory.user_context)
    )


def _paged_reports(goal: OperationGoal) -> bool:
    return any(record.call.name == REPORT_PAGE_TOOL for record in goal.tools) or any(
        item.report_read_progress is not None or len(item.summary) > 5000 for item in goal.evidence
    )


def _states(*states: GoalStatus) -> ColumnElement[bool]:
    # Legacy images only inspect `status`, and therefore cannot claim native Goals.
    return or_(
        and_(GoalRow.workspace_status.is_(None), GoalRow.status.in_(states)),
        GoalRow.workspace_status.in_(states),
    )


class SqlAlchemyGoalRepository:
    """SQL claims, optimistic fencing and durable controls across API/worker replicas."""

    def __init__(
        self,
        database: OperationDatabase,
        clock: Clock,
        *,
        events_enabled: bool = False,
        context_goal_limit: int = 10000,
    ) -> None:
        if not 1 <= context_goal_limit <= 10000:
            raise ValueError("Session Goal archive capacity must be between 1 and 10000")
        self._sessions = database.session_factory
        self._clock = clock
        self._events_enabled = events_enabled
        self._context_goal_limit = context_goal_limit
        self._substring = func.instr if database.engine.dialect.name == "sqlite" else func.strpos

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

    def _store(self, session: AsyncSession, row: GoalRow, goal: OperationGoal) -> None:
        for key, value in self._storage(goal).items():
            setattr(row, key, value)
        if self._events_enabled:
            append_goal_event(session, row.owner, goal)

    @staticmethod
    def _payload(goal: OperationGoal) -> dict[str, object]:
        payload: dict[str, object] = goal.model_dump(
            mode="json",
            exclude={
                "tools",
                "session_memory",
                "model_continuation",
                "model_feedback",
                "model_recoveries",
            },
        )
        payload["request"] = goal.request.model_dump(
            mode="json",
            exclude={
                "execution_mode",
                "analysis_scope",
                "conversation_history",
                "older_turns_omitted",
            },
        )
        payload["evidence"] = [
            {
                **item.model_dump(mode="json", exclude={"report_read_progress"}),
                "summary": item.summary[:5000],
                "shortened": item.shortened or len(item.summary) > 5000,
            }
            for item in goal.evidence
        ]
        if SqlAlchemyGoalRepository._is_workspace(goal):
            # Closed compatibility projection: old code can display history, but its
            # command terminal-state check and worker claim both deny continuation.
            payload.update(
                status="completed" if goal.status == "completed" else "cancelled",
                lease_until=None,
                requested_capability=None,
                approved_capability=None,
                waiting_reason="Эта цель требует новой рабочей среды. В старой версии "
                "она закрыта для выполнения; полная история сохранена отдельно.",
            )
        return payload

    @staticmethod
    def _is_workspace(goal: OperationGoal) -> bool:
        return bool(
            goal.request.execution_mode == "agent"
            or goal.request.analysis_scope == "saved_snapshot"
            or goal.request.conversation_history
            or goal.request.older_turns_omitted
            or goal.tools
            or goal.session_memory is not None
            or goal.model_continuation is not None
            or "retention.parents.analyze" in (goal.requested_capability, goal.approved_capability)
        )

    @classmethod
    def _storage(cls, goal: OperationGoal) -> _GoalStorage:
        native = cls._is_workspace(goal)
        extended_context = _extended_context(goal)
        continuation = goal.model_continuation is not None
        format_feedback = (
            goal.model_feedback is not None and goal.model_feedback.code == "invalid_decision"
        )
        paged_reports = _paged_reports(goal)
        return {
            "status": ("completed" if goal.status == "completed" else "cancelled")
            if native
            else goal.status,
            "revision": goal.revision,
            "updated_at": goal.updated_at,
            "payload": cls._payload(goal),
            "workspace_status": goal.status if native else None,
            "workspace_payload": _WorkspaceCheckpoint(
                version=8
                if paged_reports
                else 7
                if format_feedback
                else 6
                if continuation
                else 5
                if extended_context
                else 4
                if goal.request.analysis_scope == "saved_snapshot"
                else 3
                if goal.session_memory is not None and goal.session_memory.actions
                else 2
                if goal.session_memory is not None
                else 1,
                analysis_scope=goal.request.analysis_scope
                if extended_context or continuation or paged_reports
                else None,
                goal=goal,
            ).model_dump(
                mode="json",
                exclude={
                    **(
                        {"analysis_scope": True}
                        if not extended_context and not continuation and not paged_reports
                        else {}
                    ),
                    "goal": {
                        **({"model_continuation": True} if not continuation else {}),
                        **(
                            {"model_feedback": True, "model_recoveries": True}
                            if not continuation
                            else {}
                        ),
                        **({"session_memory": True} if goal.session_memory is None else {}),
                        **(
                            {"evidence": {"__all__": {"report_read_progress"}}}
                            if not paged_reports
                            else {}
                        ),
                        **(
                            {"request": {"analysis_scope"}}
                            if goal.request.analysis_scope == "current"
                            else {}
                        ),
                    },
                },
            )
            if native
            else None,
        }

    async def create(
        self,
        owner: str,
        topic: ChatTopic,
        request: GoalCreate,
        *,
        session_memory: SessionMemory | None = None,
    ) -> OperationGoal:
        async with self._sessions() as session, session.begin():
            await self._lock(session)
            existing = await session.scalar(
                select(GoalRow).where(
                    GoalRow.owner == owner, GoalRow.request_id == str(request.request_id)
                )
            )
            if existing:
                goal = _goal(existing)
                if goal.topic_id != topic.topic_id or goal.request != request:
                    raise ChatError("Идентификатор уже используется другой целью.")
                return goal
            count = await session.scalar(
                select(func.count())
                .select_from(GoalRow)
                .where(GoalRow.owner == owner, _states("queued", "running", "paused", "waiting"))
            )
            if (count or 0) >= 20:
                raise ChatError("Достигнут лимит: 20 незавершённых целей на пользователя.", 429)
            active = await session.scalar(
                select(GoalRow.goal_id)
                .where(
                    GoalRow.topic_id == topic.topic_id,
                    _states("queued", "running", "paused", "waiting"),
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
                session_memory=session_memory,
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
            self._store(session, row, goal)
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
            return [_goal(row) for row in rows]

    async def get(self, owner: str, goal_id: str) -> OperationGoal:
        async with self._sessions() as session:
            return _goal(await self._owned(session, owner, goal_id))

    async def find_request(self, owner: str, request_id: str) -> OperationGoal | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(GoalRow).where(GoalRow.owner == owner, GoalRow.request_id == request_id)
            )
            return _goal(row) if row is not None else None

    async def saved_task(
        self,
        owner: str,
        topic_id: str,
        product: ProductScope,
        task_id: str,
        *,
        before: datetime,
    ) -> OperationGoal:
        async with self._sessions() as session:
            row = await session.scalar(
                select(GoalRow).where(
                    GoalRow.owner == owner,
                    GoalRow.topic_id == topic_id,
                    GoalRow.goal_id == task_id,
                    _states("completed", "cancelled"),
                    GoalRow.updated_at < before,
                )
            )
            if row is None:
                raise ChatError("Прошлая задача недоступна в этой теме приложения.", 404)
            goal = _goal(row)
            if (
                goal.product != product
                or goal.status not in ("completed", "cancelled")
                or goal.updated_at.utcoffset() is None
                or goal.updated_at >= before
            ):
                raise ChatError("Прошлая задача недоступна в этой теме приложения.", 404)
            return goal

    async def find_saved_tasks(
        self,
        owner: str,
        topic_id: str,
        product: ProductScope,
        *,
        before: datetime,
        query: str,
        cursor: str | None,
    ) -> SavedTaskPage:
        anchor = (
            await self.saved_task(owner, topic_id, product, cursor, before=before)
            if cursor
            else None
        )
        conditions = [
            GoalRow.owner == owner,
            GoalRow.topic_id == topic_id,
            _states("completed", "cancelled"),
            GoalRow.updated_at < before,
            GoalRow.payload["product"].as_string() == product,
        ]
        if query:
            conditions.append(
                self._substring(GoalRow.payload["request"]["objective"].as_string(), query) > 0
            )
        if anchor is not None:
            conditions.append(
                or_(
                    GoalRow.updated_at < anchor.updated_at,
                    and_(GoalRow.updated_at == anchor.updated_at, GoalRow.goal_id > anchor.goal_id),
                )
            )
        async with self._sessions() as session:
            rows = list(
                await session.scalars(
                    select(GoalRow)
                    .where(*conditions)
                    .order_by(GoalRow.updated_at.desc(), GoalRow.goal_id)
                    .limit(6)
                )
            )
        goals = [_goal(row) for row in rows[:5]]
        if any(
            goal.product != product
            or goal.status not in ("completed", "cancelled")
            or goal.updated_at.utcoffset() is None
            or goal.updated_at >= before
            for goal in goals
        ):
            raise ChatError("История требует проверки привязки к приложению.", 503)
        return SavedTaskPage(goals=goals, next_cursor=goals[-1].goal_id if len(rows) > 5 else None)

    async def closed_context(
        self, owner: str, topic_id: str, *, product: ProductScope, before: datetime
    ) -> AsyncGenerator[OperationGoal, None]:
        """Full quoted-condition history, not the bounded result/history page.

        Stream small SQL batches and retain strict checkpoint validation. Refuse an
        excessive archive explicitly; never treat the first page as all conditions.
        No provider read, model call or state mutation occurs here.
        """
        async with self._sessions() as session:
            stream = await session.stream_scalars(
                select(GoalRow)
                .where(
                    GoalRow.owner == owner,
                    GoalRow.topic_id == topic_id,
                    _states("completed", "cancelled"),
                    GoalRow.updated_at < before,
                )
                .order_by(GoalRow.updated_at.desc(), GoalRow.goal_id)
                .limit(self._context_goal_limit + 1)
                .execution_options(yield_per=8)
            )
            try:
                index = 0
                async for row in stream:
                    if index == self._context_goal_limit:
                        raise SessionContextTooLarge()
                    index += 1
                    try:
                        goal = _goal(row)
                    except ValidationError as exc:
                        raise ChatError(
                            "История целей повреждена; запрос к AI не отправлен.", 503
                        ) from exc
                    if (
                        goal.topic_id != topic_id
                        or goal.status not in ("completed", "cancelled")
                        or goal.updated_at.utcoffset() is None
                        or goal.updated_at >= before
                    ):
                        raise ChatError("История требует проверки привязки к приложению.", 503)
                    if goal.product != product:
                        continue
                    yield goal
            finally:
                await stream.close()

    async def command(self, owner: str, goal_id: str, payload: GoalCommand) -> OperationGoal:
        async with self._sessions() as session, session.begin():
            await self._lock(session)
            row = await self._owned(session, owner, goal_id)
            goal = _goal(row)
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
                payload.command in ("resume", "approve_read")
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
                if not (goal.lease_until and goal.lease_until > now):
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
            if payload.command not in ("pause", "cancel", "steer"):
                goal.lease_until = None
            goal.revision += 1
            goal.updated_at = now
            goal.events.append(GoalEvent(at=now, kind="control", message=message))
            goal.events = goal.events[-100:]
            self._store(session, row, goal)
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
                select(GoalRow).where(_states("queued", "running", "paused"))
            )
            now = self._clock.now()
            if not any(
                (goal := _goal(row)).status == "queued"
                or goal.lease_until is not None
                and goal.lease_until <= now
                for row in candidates
            ):
                return None
        async with self._sessions() as session, session.begin():
            await self._lock(session)
            now = self._clock.now()
            # A lost in-flight call must not be blindly retried after restart.
            running = await session.scalars(select(GoalRow).where(_states("running", "paused")))
            for row in running:
                goal = _goal(row)
                if goal.lease_until and goal.lease_until <= now:
                    for record in goal.tools:
                        if record.status == "started":
                            record.status = "unknown"
                            record.result = "Шаг прерван. Исход неизвестен; повтор не запущен."
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
                    self._store(session, row, goal)
            await session.flush()
            queued_row = await session.scalar(
                select(GoalRow)
                .where(_states("queued"))
                .order_by(GoalRow.updated_at, GoalRow.goal_id)
                .limit(1)
            )
            if queued_row is None:
                return None
            goal = _goal(queued_row)
            goal.status = "running"
            goal.lease_until = now + timedelta(minutes=5)
            goal.revision += 1
            goal.updated_at = now
            self._store(session, queued_row, goal)
            return queued_row.owner, goal

    async def save(self, owner: str, before: OperationGoal, after: OperationGoal) -> bool:
        after = after.model_copy(
            update={"revision": before.revision + 1, "updated_at": self._clock.now()}
        )
        async with self._sessions() as session, session.begin():
            # Share the controls/claims transaction fence. Journal sequence allocation
            # must follow commit order, or a reconnect cursor could skip a late commit.
            await self._lock(session)
            result = await session.execute(
                update(GoalRow)
                .where(
                    GoalRow.goal_id == before.goal_id,
                    GoalRow.owner == owner,
                    GoalRow.revision == before.revision,
                )
                .values(**self._storage(after))
            )
            if result.rowcount and self._events_enabled:
                append_goal_event(session, owner, after)
            return bool(result.rowcount)

    async def workspace_rollback(self, *, apply_pause: bool = False) -> WorkspaceRollbackReport:
        """Explicit release control; never called by the API, scheduler or worker.

        Default is read-only. Before apply, operators must stop/drain the Goals worker.
        A live lease rejects the entire transaction. Lost expired work is preserved as
        unknown with its costs/read consumption, never retried or refunded.
        """
        async with self._sessions() as session, session.begin():
            if apply_pause:
                await self._lock(session)
            rows = list(
                await session.scalars(
                    select(GoalRow).where(
                        GoalRow.workspace_status.in_(("queued", "running", "paused", "waiting"))
                    )
                )
            )
            goals = [_goal(row) for row in rows]
            now = self._clock.now()
            leases = sum(bool(goal.lease_until and goal.lease_until > now) for goal in goals)
            if not apply_pause:
                return WorkspaceRollbackReport(active_goals=len(goals), live_leases=leases)
            if leases:
                raise ChatError("Откат не подготовлен: дождитесь окончания активных шагов.")
            changed = 0
            for row, goal in zip(rows, goals, strict=True):
                if (
                    goal.status == "paused"
                    and goal.lease_until is None
                    and goal.approved_capability is None
                    and all(record.status != "started" for record in goal.tools)
                ):
                    continue
                for record in goal.tools:
                    if record.status == "started":
                        record.status = "unknown"
                        record.result = "Шаг прерван перед откатом. Исход неизвестен; повтора нет."
                goal.status, goal.lease_until, goal.approved_capability = "paused", None, None
                goal.waiting_reason = "Цель приостановлена перед откатом версии. "
                "Продолжение только вручную в совместимой рабочей среде."
                goal.events.append(GoalEvent(at=now, kind="control", message=goal.waiting_reason))
                goal.events = goal.events[-100:]
                goal.updated_at = now
                goal.revision += 1
                self._store(session, row, goal)
                changed += 1
            return WorkspaceRollbackReport(
                active_goals=len(goals), live_leases=0, paused_goals=changed
            )
