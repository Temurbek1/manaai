"""Append to the journal in the same transaction as a successful Goal state change."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.goals import OperationGoal
from app.mana_operation_ai.domain.workspace_events import (
    WorkspaceEvent,
    WorkspaceEventPage,
    WorkspaceToolState,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import ChatTopicRow, WorkspaceEventRow


def append_goal_event(session: AsyncSession, owner: str, goal: OperationGoal) -> None:
    message = goal.events[-1].message if goal.events else "Состояние задачи обновлено."
    if goal.tools and goal.tools[-1].status == "started":
        message = "Готовлю следующий инструмент."
    elif goal.status == "running":
        message = "Работаю над следующим шагом."
    elif goal.waiting_reason:
        message = goal.waiting_reason
    event = WorkspaceEvent(
        event_id=0,
        topic_id=goal.topic_id,
        goal_id=goal.goal_id,
        revision=goal.revision,
        at=goal.updated_at,
        status=goal.status,
        phase=goal.phase,
        message=message[:2000],
        message_shortened=len(message) > 2000,
        plan=goal.plan,
        tools=[
            WorkspaceToolState(call_id=t.call_id, name=t.call.name, status=t.status)
            for t in goal.tools
        ],
    )
    session.add(
        WorkspaceEventRow(
            owner=owner,
            topic_id=goal.topic_id,
            payload=event.model_dump(mode="json", exclude={"event_id"}),
        )
    )


class SqlAlchemyWorkspaceEvents:
    def __init__(self, database: OperationDatabase) -> None:
        self._sessions = database.session_factory

    async def page(self, owner: str, topic_id: str, after: int) -> WorkspaceEventPage:
        async with self._sessions() as session:
            owned = await session.scalar(
                select(ChatTopicRow.topic_id).where(
                    ChatTopicRow.topic_id == topic_id,
                    ChatTopicRow.owner == owner,
                )
            )
            if owned is None:
                raise ChatError("Тема не найдена.", 404)
            tip = await session.scalar(
                select(func.max(WorkspaceEventRow.event_id)).where(
                    WorkspaceEventRow.owner == owner,
                    WorkspaceEventRow.topic_id == topic_id,
                )
            )
            if after > (tip or 0):
                raise ChatError("Недействительный курсор рабочего прогресса.", 409)
            rows = list(
                await session.scalars(
                    select(WorkspaceEventRow)
                    .where(
                        WorkspaceEventRow.owner == owner,
                        WorkspaceEventRow.topic_id == topic_id,
                        WorkspaceEventRow.event_id > after,
                    )
                    .order_by(WorkspaceEventRow.event_id)
                    .limit(51)
                )
            )
            items = [WorkspaceEvent(event_id=row.event_id, **row.payload) for row in rows[:50]]
            return WorkspaceEventPage(
                items=items,
                next_cursor=items[-1].event_id if items else after,
                has_more=len(rows) > 50,
            )
