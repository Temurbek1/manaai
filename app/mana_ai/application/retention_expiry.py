"""Reuse profile acquisition; Parent-Touch publishes one exact host-owned reminder."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from app.mana_ai.application.chat_ports import ParentChatError, ParentChildrenSource
from app.mana_ai.domain.chat import ParentChildContext


class RetentionExpiryPort(Protocol):
    async def observe_expiry_profile(
        self, parent_id: str, context: ParentChildContext, now: datetime
    ) -> None: ...
    async def publish_expiry(self, now: datetime) -> bool: ...
    async def invalidate_expiry_profile(self, parent_id: str, now: datetime) -> None: ...
    async def close_expiry_source(self) -> None: ...


class RetentionProfileSource:
    def __init__(
        self,
        source: ParentChildrenSource,
        sink: RetentionExpiryPort,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._source, self._sink, self._clock = source, sink, clock

    async def read(self, parent_id: str) -> ParentChildContext:
        try:
            raw = await self._source.read(parent_id)
            context = ParentChildContext.model_validate(raw.model_dump())
            if context.parent_id != parent_id:
                raise ParentChatError("expiry_profile_owner_mismatch", 403)
            await self._sink.observe_expiry_profile(parent_id, context, self._clock())
        except BaseException as error:
            if isinstance(error, ParentChatError) and error.code in {
                "child_source_auth_denied",
                "child_source_auth_cooling_down",
            }:
                await asyncio.shield(self._sink.close_expiry_source())
            await asyncio.shield(self._sink.invalidate_expiry_profile(parent_id, self._clock()))
            raise
        return context


class RetentionExpiryService:
    def __init__(self, store: RetentionExpiryPort, *, clock: Callable[[], datetime]) -> None:
        self._store, self._clock = store, clock

    async def process_one(self) -> bool:
        return await self._store.publish_expiry(self._clock())
