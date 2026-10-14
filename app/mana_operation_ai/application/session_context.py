"""Reconstruct topic-owned continuation from SQL history, without source/provider reads."""

from contextlib import aclosing
from datetime import datetime
from typing import cast

from pydantic import JsonValue

from app.mana_operation_ai.application.chat_ports import ChatRepository, SessionContextTooLarge
from app.mana_operation_ai.application.goal_ports import GoalRepository
from app.mana_operation_ai.application.retention.contact_ports import RetentionContactHistoryReader
from app.mana_operation_ai.application.workspace_action_ports import WorkspaceActionHistoryReader
from app.mana_operation_ai.domain.session import (
    SessionCheckpoint,
    SessionEvidenceReference,
    SessionMemory,
    SessionUserContext,
)


class OperationSessionContext:
    def __init__(
        self,
        chats: ChatRepository,
        goals: GoalRepository,
        actions: WorkspaceActionHistoryReader | None = None,
        contacts: RetentionContactHistoryReader | None = None,
    ) -> None:
        self._chats = chats
        self._goals = goals
        self._actions = actions
        self._contacts = contacts

    async def read(self, owner: str, topic_id: str, *, before: datetime) -> SessionMemory | None:
        topic = await self._chats.topic(owner, topic_id)
        actions = (
            await self._actions.history(owner, topic_id, before=before) if self._actions else []
        )
        contacts = (
            await self._contacts.history(owner, topic_id, before=before) if self._contacts else []
        )
        records: dict[str, SessionUserContext] = {}
        checkpoints: list[SessionCheckpoint] = []
        closed_count = 0

        def add(kind: str, text: str, origin: str) -> None:
            # Exact deduplication, not a model-invented summary or shortened constraints.
            if text:
                record = SessionUserContext(kind=kind, text=text, origin_id=origin)
                prior = records.get(text)
                if prior is None:
                    records[text] = record
                elif kind != prior.kind and kind not in prior.also_kinds:
                    prior.also_kinds.append(record.kind)
            if len(records) > 400:
                raise SessionContextTooLarge()

        async with aclosing(
            self._chats.user_context(owner, topic_id, before=before)
        ) as records_stream:
            async for record in records_stream:
                add(record.kind, record.text, record.origin_id)
        async with aclosing(
            self._goals.closed_context(owner, topic_id, product=topic.product, before=before)
        ) as closed:
            async for goal in closed:
                closed_count += 1
                if goal.session_memory is not None:
                    memory = goal.session_memory
                    if memory.topic_id == topic_id and memory.product == topic.product:
                        for record in memory.user_context:
                            add(record.kind, record.text, record.origin_id)
                            for kind in record.also_kinds:
                                add(kind, record.text, record.origin_id)
                add("prior_objective", goal.request.objective, goal.goal_id)
                add("prior_criteria", goal.request.success_criteria, goal.goal_id)
                add("constraint", goal.request.constraints, goal.goal_id)
                for instruction in goal.instructions:
                    add("instruction", instruction, goal.goal_id)
                for prior_turn in goal.request.conversation_history:
                    add("user_message", prior_turn.user, goal.goal_id)
                if len(checkpoints) >= 3:
                    continue
                checkpoints.append(
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
                )
        if not records and not checkpoints and not actions and not contacts:
            return None
        return SessionMemory(
            topic_id=topic_id,
            product=topic.product,
            captured_at=before,
            user_context=list(records.values()),
            actions=actions,
            retention_contacts=contacts,
            checkpoints=checkpoints,
            older_checkpoints_omitted=max(0, closed_count - len(checkpoints)),
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
