"""Reconstruct topic-owned continuation from SQL history, without source/provider reads."""

from datetime import datetime
from typing import cast

from pydantic import JsonValue

from app.mana_operation_ai.application.chat_ports import ChatRepository, SessionContextTooLarge
from app.mana_operation_ai.application.goal_ports import GoalRepository
from app.mana_operation_ai.domain.session import (
    SessionCheckpoint,
    SessionEvidenceReference,
    SessionMemory,
    SessionUserContext,
)


class OperationSessionContext:
    def __init__(self, chats: ChatRepository, goals: GoalRepository) -> None:
        self._chats = chats
        self._goals = goals

    async def read(self, owner: str, topic_id: str, *, before: datetime) -> SessionMemory | None:
        topic = await self._chats.topic(owner, topic_id)
        history = await self._goals.closed_history(owner, topic_id, before=before)
        goals = [goal for goal in history.goals if goal.product == topic.product]
        records: dict[tuple[str, str], SessionUserContext] = {}

        def add(kind: str, text: str, origin: str) -> None:
            # Exact deduplication, not a model-invented summary or shortened constraints.
            if text:
                record = SessionUserContext(kind=kind, text=text, origin_id=origin)
                records.setdefault((kind, text), record)
            if len(records) > 400:
                raise SessionContextTooLarge()

        for turn in await self._chats.turns(owner, topic_id):
            if turn.created_at < before:
                add("user_message", turn.message, turn.turn_id)
        for goal in goals:
            if goal.session_memory is not None:
                memory = goal.session_memory
                if memory.topic_id == topic_id and memory.product == topic.product:
                    for record in memory.user_context:
                        add(record.kind, record.text, record.origin_id)
            add("prior_objective", goal.request.objective, goal.goal_id)
            add("prior_criteria", goal.request.success_criteria, goal.goal_id)
            add("constraint", goal.request.constraints, goal.goal_id)
            for instruction in goal.instructions:
                add("instruction", instruction, goal.goal_id)
            for prior_turn in goal.request.conversation_history:
                add("user_message", prior_turn.user, goal.goal_id)
        if not records and not goals:
            return None
        return SessionMemory(
            topic_id=topic_id,
            product=topic.product,
            captured_at=before,
            user_context=list(records.values()),
            checkpoints=[
                SessionCheckpoint(
                    goal_id=goal.goal_id,
                    status=goal.status,
                    updated_at=goal.updated_at,
                    result=goal.result[:2000],
                    result_shortened=len(goal.result) > 2000,
                    sources=[
                        SessionEvidenceReference(
                            report_id=item.report_id,
                            capability_key=item.capability_key,
                            product=item.product,
                            collected_at=item.collected_at,
                            fresh_until=item.fresh_until,
                            refresh_status=item.refresh_status,
                            limitations=item.limitations,
                            shortened=item.shortened,
                        )
                        for item in goal.evidence
                        if item.product == topic.product
                    ],
                )
                for goal in goals[:3]
            ],
            older_checkpoints_omitted=history.older_goals_omitted + max(0, len(goals) - 3),
        )


def session_memory_payload(memory: SessionMemory, *, now: datetime) -> dict[str, JsonValue]:
    snapshot = memory.model_copy(deep=True)
    for checkpoint in snapshot.checkpoints:
        for source in checkpoint.sources:
            collected, expires = source.collected_at, source.fresh_until
            if (
                collected is None
                or expires is None
                or collected.utcoffset() is None
                or expires.utcoffset() is None
                or collected > now
                or expires <= collected
            ):
                source.refresh_status = "unknown"
            elif now >= expires:
                source.refresh_status = "stale"
    return cast(dict[str, JsonValue], snapshot.model_dump(mode="json"))
