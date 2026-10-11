from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.mana_operation_ai.api.security import ActorDep, require_role
from app.mana_operation_ai.api.workspace_stream import workspace_stream_response
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.workspace_events import WorkspaceEventService
from app.mana_operation_ai.application.workspace_service import OperationWorkspaceService
from app.mana_operation_ai.domain.chat import MessageCreate
from app.mana_operation_ai.domain.enums import UserRole
from app.mana_operation_ai.domain.workspace import WorkspaceTurn
from app.mana_operation_ai.domain.workspace_events import WorkspaceEventPage


def get_workspace(request: Request) -> OperationWorkspaceService:
    return cast(OperationWorkspaceService, request.app.state.operation_workspace_service)


WorkspaceDep = Annotated[OperationWorkspaceService, Depends(get_workspace)]
router = APIRouter()


def get_events(request: Request) -> WorkspaceEventService:
    return cast(WorkspaceEventService, request.app.state.operation_workspace_events)


EventsDep = Annotated[WorkspaceEventService, Depends(get_events)]


@router.get("/topics/{topic_id}/events", response_model=WorkspaceEventPage)
async def events(
    topic_id: str,
    service: EventsDep,
    actor: ActorDep,
    after: Annotated[int, Query(ge=0, le=9007199254740991)] = 0,
) -> WorkspaceEventPage:
    require_role(actor, UserRole.VIEWER)
    try:
        return await service.page(actor.actor_id, topic_id, after)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get(
    "/topics/{topic_id}/stream",
    response_class=StreamingResponse,
    response_model=None,
    responses={
        200: {
            "description": "SSE workspace events; typed frames match WorkspaceEvent in /events.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def stream(
    topic_id: str,
    request: Request,
    service: EventsDep,
    actor: ActorDep,
    after: Annotated[int, Query(ge=0, le=9007199254740991)] = 0,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    require_role(actor, UserRole.VIEWER)
    if last_event_id is not None:
        if not last_event_id.isascii() or not last_event_id.isdigit() or len(last_event_id) > 16:
            raise HTTPException(400, "Invalid Last-Event-ID")
        cursor = int(last_event_id)
        if cursor > 9007199254740991 or (after and after != cursor):
            raise HTTPException(400, "Invalid Last-Event-ID")
        after = cursor
    # Fail before sending SSE headers for disabled/foreign topics or bad cursors.
    first = await events(topic_id, service, actor, after)
    return await workspace_stream_response(request, service, actor, topic_id, after, first)


@router.post("/topics/{topic_id}/messages", response_model=WorkspaceTurn)
async def send_message(
    topic_id: str, payload: MessageCreate, service: WorkspaceDep, actor: ActorDep
) -> WorkspaceTurn:
    require_role(actor, UserRole.OPERATOR)
    try:
        return await service.send(actor.actor_id, topic_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
