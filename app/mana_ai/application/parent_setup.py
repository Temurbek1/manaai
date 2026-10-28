"""Reuse already acquired profiles and publish support through the one parent chat."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from app.mana_ai.application.chat_ports import ParentChatError, ParentChildrenSource
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.parent_setup import ParentSetupFact


class ParentSetupSink(Protocol):
    async def observe_setup_facts(
        self, facts: tuple[ParentSetupFact, ...], now: datetime
    ) -> bool: ...
    async def invalidate_setup_profile(self, parent_id: str, now: datetime) -> None: ...
    async def close_setup_source(self) -> None: ...


class ParentSetupStore(ParentSetupSink, Protocol):
    async def publish_setup(self, now: datetime) -> bool: ...


class SetupProfileSource:
    """The existing caller owns its one read; this wrapper creates no read or retry."""

    def __init__(
        self, source: ParentChildrenSource, sink: ParentSetupSink, *, clock: Callable[[], datetime]
    ) -> None:
        self._source, self._sink, self._clock = source, sink, clock

    async def read(self, parent_id: str) -> ParentChildContext:
        try:
            raw = await self._source.read(parent_id)
            context = ParentChildContext.model_validate(raw.model_dump())
            if context.parent_id != parent_id:
                raise ParentChatError("setup_profile_owner_mismatch", 403)
            if context.children_complete is not True:
                await self._sink.invalidate_setup_profile(parent_id, self._clock())
                return context
            await self._sink.observe_setup_facts(
                (
                    ParentSetupFact(
                        parent_id=parent_id,
                        collected_at=context.collected_at,
                        connected_child_ids=tuple(
                            sorted(child.child_id for child in context.children if child.connected)
                        ),
                    ),
                ),
                self._clock(),
            )
            return context
        except BaseException as error:
            if isinstance(error, ParentChatError) and error.code in {
                "child_source_auth_denied",
                "child_source_auth_cooling_down",
            }:
                await asyncio.shield(self._sink.close_setup_source())
            await asyncio.shield(self._sink.invalidate_setup_profile(parent_id, self._clock()))
            raise


class ParentSetupService:
    def __init__(self, store: ParentSetupStore, *, clock: Callable[[], datetime]) -> None:
        self._store, self._clock = store, clock

    async def process_one(self) -> bool:
        return await self._store.publish_setup(self._clock())
