"""Typed parent-assistant actions; only Parent-Touch publishes their messages."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from app.mana_ai.application.chat_ports import ParentChatError, ParentChildrenSource
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest, ParentTouchMessageState
from app.mana_ai.domain.parent_reminders import (
    ParentReminder,
    ReminderConfirmation,
    ReminderDeliveryClaim,
    ReminderScope,
)


class ParentReminderStore(Protocol):
    async def reminder_scope(
        self, parent_id: str, turn_id: int, now: datetime
    ) -> ReminderScope | None: ...
    async def reminder_state(
        self, parent_id: str, now: datetime
    ) -> tuple[tuple[ParentReminder, ...], ReminderConfirmation | None]: ...
    async def publish_reminder_confirmation(self, now: datetime) -> bool: ...
    async def publish_ready_reminder(self, now: datetime) -> bool: ...
    async def assistant_control(
        self, request: ParentTouchMessageRequest, now: datetime
    ) -> ParentTouchMessageState | None: ...
    async def claim_due_reminder(self, now: datetime) -> ReminderDeliveryClaim | None: ...
    async def finish_due_reminder(
        self,
        claim: ReminderDeliveryClaim,
        now: datetime,
        *,
        verified_parent: bool,
        context_at: datetime | None = None,
        error: str | None = None,
        unknown: bool = False,
    ) -> None: ...


class ParentReminderService:
    def __init__(
        self,
        store: ParentReminderStore,
        children: ParentChildrenSource,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._store, self._children, self._clock = store, children, clock

    async def control(self, request: ParentTouchMessageRequest) -> ParentTouchMessageState | None:
        return await self._store.assistant_control(request, self._clock())

    async def scope(self, parent_id: str, turn_id: int) -> ReminderScope | None:
        return await self._store.reminder_scope(parent_id, turn_id, self._clock())

    async def history_metadata(
        self, parent_id: str
    ) -> tuple[tuple[ParentReminder, ...], ReminderConfirmation | None]:
        return await self._store.reminder_state(parent_id, self._clock())

    async def process_one(self) -> bool:
        if await self._store.publish_ready_reminder(self._clock()):
            return True
        if await self._store.publish_reminder_confirmation(self._clock()):
            return True
        claim = await self._store.claim_due_reminder(self._clock())
        if claim is None:
            return False
        try:
            raw = await self._children.read(claim.reminder.parent_id)
            context = ParentChildContext.model_validate(raw.model_dump())
            now = self._clock()
            verified = context.parent_id == claim.reminder.parent_id and (
                now - timedelta(seconds=180) <= context.collected_at <= now
            )
            await self._store.finish_due_reminder(
                claim,
                now,
                verified_parent=verified,
                context_at=context.collected_at if verified else None,
                error=None if verified else "ownership_denied",
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self._store.finish_due_reminder(
                    claim,
                    self._clock(),
                    verified_parent=False,
                    error="ownership_unknown",
                    unknown=True,
                )
            )
            raise
        except ParentChatError as error:
            await self._store.finish_due_reminder(
                claim,
                self._clock(),
                verified_parent=False,
                error="backend_auth_denied"
                if error.code == "child_source_auth_denied"
                else "ownership_unknown",
                unknown=error.code != "child_source_auth_denied",
            )
        except Exception:
            await self._store.finish_due_reminder(
                claim,
                self._clock(),
                verified_parent=False,
                error="ownership_unknown",
                unknown=True,
            )
        return True
