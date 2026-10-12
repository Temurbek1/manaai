"""Bounded authenticated SSE transport; reconnect is observation, never task execution."""

import asyncio
from collections.abc import AsyncIterator
from time import monotonic

import anyio
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.mana_operation_ai.api.security import recheck_actor, require_role
from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.workspace_events import WorkspaceEventService
from app.mana_operation_ai.domain.enums import UserRole
from app.mana_operation_ai.domain.workspace_events import ChatTextEvent, WorkspaceNotificationPage


class BoundedWorkspaceStream(StreamingResponse):
    """Also bound blocked network sends, not only the notification generator."""

    def __init__(
        self,
        content: AsyncIterator[str],
        service: WorkspaceEventService,
        lease: str,
        seconds: float,
    ) -> None:
        super().__init__(
            content,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, no-transform",
                "X-Accel-Buffering": "no",
            },
        )
        self._service, self._lease, self._seconds = service, lease, seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            with anyio.move_on_after(self._seconds + 5):
                await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self._service.release(self._lease)


async def workspace_stream_response(
    request: Request,
    service: WorkspaceEventService,
    actor: ActorContext,
    topic_id: str,
    after: int,
    first: WorkspaceNotificationPage,
) -> StreamingResponse:
    settings = request.app.state.settings
    try:
        lease = await service.acquire(actor.actor_id, settings.operation_workspace_stream_seconds)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc

    async def notifications() -> AsyncIterator[str]:
        cursor, page = after, first
        started = heartbeat = monotonic()
        try:
            yield ": connected\n\n"
            while monotonic() - started < settings.operation_workspace_stream_seconds:
                if await request.is_disconnected():
                    return
                try:
                    identity = await recheck_actor(request)
                    if identity.actor_id != actor.actor_id:
                        raise HTTPException(401, "Session changed")
                    require_role(identity, UserRole.VIEWER)
                except HTTPException:
                    yield "event: access_revoked\ndata: {}\n\n"
                    return
                except Exception:
                    yield "event: unavailable\ndata: {}\n\n"
                    return
                for event in page.items:
                    name = "chat_text" if isinstance(event, ChatTextEvent) else "workspace"
                    yield (
                        f"id: {event.event_id}\nevent: {name}\ndata: {event.model_dump_json()}\n\n"
                    )
                    cursor = event.event_id
                if not page.has_more:
                    if monotonic() - heartbeat >= 10:
                        yield ": heartbeat\n\n"
                        heartbeat = monotonic()
                    await asyncio.sleep(settings.operation_workspace_event_poll_seconds)
                try:
                    page = await service.notifications(actor.actor_id, topic_id, cursor)
                except Exception:
                    # No upstream exception text or implicit restart after lost observation.
                    yield "event: unavailable\ndata: {}\n\n"
                    return
            yield "event: reconnect\ndata: {}\n\n"
        finally:
            await service.release(lease)

    return BoundedWorkspaceStream(
        notifications(), service, lease, settings.operation_workspace_stream_seconds
    )
