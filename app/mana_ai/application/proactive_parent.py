"""Private recipient preferences and one-attempt delivery of committed-chat pushes."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.parent_notifications import (
    ParentPushGateway,
    ParentPushRejected,
    ParentPushUnknown,
)
from app.mana_ai.domain.proactive_parent import (
    ParentContactContext,
    ParentPushClaim,
    ParentPushOutcome,
    ParentPushPage,
    ParentPushState,
)


class ProactiveParentStore(Protocol):
    async def ingest_contact_context(
        self, context: ParentContactContext, now: datetime
    ) -> ParentContactContext: ...

    async def contact_context(
        self, parent_id: str, now: datetime
    ) -> ParentContactContext | None: ...

    async def claim_push(self, now: datetime) -> ParentPushClaim | None: ...

    async def finish_push(
        self, claim: ParentPushClaim, outcome: ParentPushOutcome, now: datetime
    ) -> ParentPushState: ...

    async def pushes(self, parent_id: str, *, after: int, limit: int) -> ParentPushPage: ...

    async def push(self, parent_id: str, push_id: UUID) -> ParentPushState: ...


class ProactiveParentService:
    def __init__(
        self,
        store: ProactiveParentStore,
        *,
        clock: Callable[[], datetime],
        gateway: ParentPushGateway | None = None,
    ) -> None:
        self._store, self._clock, self._gateway = store, clock, gateway
        self._auth_cooldown_until: datetime | None = None

    async def register(self, context: ParentContactContext) -> ParentContactContext:
        return await self._store.ingest_contact_context(context, self._clock())

    async def context(self, parent_id: str) -> ParentContactContext:
        context = await self._store.contact_context(parent_id, self._clock())
        if context is None:
            raise ParentChatError("parent_contact_context_unavailable", 404)
        return context

    async def pushes(self, parent_id: str, *, after: int, limit: int) -> ParentPushPage:
        return await self._store.pushes(parent_id, after=after, limit=limit)

    async def push(self, parent_id: str, push_id: UUID) -> ParentPushState:
        return await self._store.push(parent_id, push_id)

    async def process_one(self) -> ParentPushState | None:
        if self._gateway is None:
            return None
        if self._auth_cooldown_until and self._clock() < self._auth_cooldown_until:
            return None
        claim = await self._store.claim_push(self._clock())
        if claim is None:
            return None
        cancelled = False
        try:
            receipt = await self._gateway.send(claim.message)
            outcome = ParentPushOutcome(
                status="queued_by_provider" if receipt.queued_devices else "not_queued",
                queued_devices=receipt.queued_devices,
                error_code=None if receipt.queued_devices else "parent_push_no_registered_devices",
            )
        except ParentPushRejected as exc:
            outcome = ParentPushOutcome(status="not_queued", error_code=exc.code)
            if exc.code in {"parent_push_auth_rejected", "parent_push_not_authorized"}:
                self._auth_cooldown_until = self._clock() + timedelta(seconds=60)
        except ParentPushUnknown as exc:
            outcome = ParentPushOutcome(status="unknown", error_code=exc.code)
            if exc.code == "parent_push_auth_unavailable":
                self._auth_cooldown_until = self._clock() + timedelta(seconds=60)
        except (Exception, asyncio.CancelledError) as exc:
            outcome = ParentPushOutcome(status="unknown", error_code="parent_push_outcome_unknown")
            cancelled = isinstance(exc, asyncio.CancelledError)
        # A committed chat message is never undone, and a lost push receipt never
        # requeues work or causes another model call. A cancelled network send
        # still owns its durable unknown claim.
        state = await asyncio.shield(self._store.finish_push(claim, outcome, self._clock()))
        if cancelled:
            raise asyncio.CancelledError
        return state
