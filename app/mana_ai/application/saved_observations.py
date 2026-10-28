"""Ownership-filtered saved inspection; no external source port or fallback exists."""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from app.mana_ai.application.chat_ports import ParentChatError, ParentChildrenSource
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.saved_observations import SavedObservationReceipt, SavedObservationTarget


class SavedObservationInspector(Protocol):
    async def inspect(
        self, target: SavedObservationTarget, now: datetime
    ) -> SavedObservationReceipt: ...


class SavedObservationService:
    def __init__(
        self,
        reader: SavedObservationInspector,
        children: ParentChildrenSource,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._reader, self._children, self._clock = reader, children, clock

    async def inspect(self, target: SavedObservationTarget) -> SavedObservationReceipt:
        target = SavedObservationTarget.model_validate(target.model_dump())
        context = ParentChildContext.model_validate(
            (await self._children.read(target.parent_id)).model_dump()
        )
        now = self._clock()
        if (
            context.parent_id != target.parent_id
            or not now - timedelta(seconds=180) <= context.collected_at <= now
            or len({c.child_id for c in context.children}) != len(context.children)
            or not any(c.child_id == target.child_id and c.connected for c in context.children)
        ):
            raise ParentChatError("saved_observation_ownership_denied", 403)
        return await self._reader.inspect(target, now)
