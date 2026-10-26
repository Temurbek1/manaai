"""One durable click claim before one typed executor call; reads never dispatch."""

import asyncio
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.mana_ai.application.ports import Clock
from app.mana_ai.domain.chat_actions import (
    ChatActionCard,
    ChatActionClaim,
    ChatActionClick,
    ChatActionCreate,
    ChatActionPage,
    ChatActionResult,
)


class ChatActionStore(Protocol):
    async def create_card(self, request: ChatActionCreate, now: datetime) -> ChatActionCard: ...

    async def action_card(self, parent: str, card: UUID, now: datetime) -> ChatActionCard: ...

    async def action_cards(
        self, parent: str, after: int, limit: int, now: datetime
    ) -> ChatActionPage: ...

    async def claim_card(
        self, card: UUID, click: ChatActionClick, now: datetime
    ) -> ChatActionCard | ChatActionClaim: ...

    async def finish_card(
        self, claim: ChatActionClaim, result: ChatActionResult | None, now: datetime
    ) -> ChatActionCard: ...


class ChatActionExecutor(Protocol):
    async def execute(self, claim: ChatActionClaim) -> ChatActionResult: ...


class ChatActionService:
    def __init__(self, store: ChatActionStore, executor: ChatActionExecutor, clock: Clock) -> None:
        self._store, self._executor, self._clock = store, executor, clock

    async def create(self, request: ChatActionCreate) -> ChatActionCard:
        return await self._store.create_card(request, self._clock.now())

    async def read(self, parent: str, card: UUID) -> ChatActionCard:
        return await self._store.action_card(parent, card, self._clock.now())

    async def list(self, parent: str, *, after: int, limit: int) -> ChatActionPage:
        return await self._store.action_cards(parent, after, limit, self._clock.now())

    async def click(self, card: UUID, request: ChatActionClick) -> ChatActionCard:
        claim = await self._store.claim_card(card, request, self._clock.now())
        if isinstance(claim, ChatActionCard):
            return claim
        try:
            result = await self._executor.execute(claim)
            if result.execution_id != claim.execution_id:
                raise ValueError("Execution receipt does not match the durable claim")
        except asyncio.CancelledError:
            # Even if this reconciliation is interrupted, the committed executing
            # claim is never redispatched by a GET, another nonce or a restart.
            await asyncio.shield(self._store.finish_card(claim, None, self._clock.now()))
            raise
        except Exception:
            return await self._store.finish_card(claim, None, self._clock.now())
        return await self._store.finish_card(claim, result, self._clock.now())
