from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.mana_operation_ai.api.chat_router import ChatDep
from app.mana_operation_ai.api.contact_review_router import router as contact_review_router
from app.mana_operation_ai.api.manual_action_control_router import router as manual_controls_router
from app.mana_operation_ai.api.security import ActorDep, require_role
from app.mana_operation_ai.api.workspace_retention_router import router as retention_contacts_router
from app.mana_operation_ai.api.workspace_stream import workspace_stream_response
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.model_continuation import public_goal
from app.mana_operation_ai.application.workspace_actions import WorkspaceActionService
from app.mana_operation_ai.application.workspace_events import WorkspaceEventService
from app.mana_operation_ai.application.workspace_service import OperationWorkspaceService
from app.mana_operation_ai.domain.chat import MessageCreate, TranscriptPage
from app.mana_operation_ai.domain.enums import UserRole
from app.mana_operation_ai.domain.workspace import WorkspaceTurn
from app.mana_operation_ai.domain.workspace_actions import (
    WorkspaceActionDecision,
    WorkspaceActionPage,
    WorkspaceActionView,
)
from app.mana_operation_ai.domain.workspace_events import (
    WorkspaceEventPage,
    WorkspaceNotificationPage,
)


def get_workspace(request: Request) -> OperationWorkspaceService:
    return cast(OperationWorkspaceService, request.app.state.operation_workspace_service)


WorkspaceDep = Annotated[OperationWorkspaceService, Depends(get_workspace)]
router = APIRouter()
router.include_router(retention_contacts_router)
router.include_router(contact_review_router)
router.include_router(manual_controls_router)


@router.get("/topics/{topic_id}/messages", response_model=TranscriptPage)
async def transcript(
    topic_id: str,
    service: ChatDep,
    actor: ActorDep,
    before: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=30)] = 20,
) -> TranscriptPage:
    require_role(actor, UserRole.VIEWER)
    try:
        return await service.transcript(actor.actor_id, topic_id, before=before, limit=limit)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


def get_events(request: Request) -> WorkspaceEventService:
    return cast(WorkspaceEventService, request.app.state.operation_workspace_events)


EventsDep = Annotated[WorkspaceEventService, Depends(get_events)]


def get_actions(request: Request) -> WorkspaceActionService:
    return cast(WorkspaceActionService, request.app.state.operation_workspace_actions)


ActionsDep = Annotated[WorkspaceActionService, Depends(get_actions)]


@router.get("/topics/{topic_id}/messages/{turn_id}/actions", response_model=WorkspaceActionPage)
async def actions(
    topic_id: str, turn_id: str, service: ActionsDep, actor: ActorDep
) -> WorkspaceActionPage:
    require_role(actor, UserRole.VIEWER)
    try:
        return await service.page(actor.actor_id, topic_id, turn_id)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post(
    "/topics/{topic_id}/messages/{turn_id}/actions/{proposal_id}/decision",
    response_model=WorkspaceActionView,
)
async def decide_action(
    topic_id: str,
    turn_id: str,
    proposal_id: str,
    payload: WorkspaceActionDecision,
    service: ActionsDep,
    actor: ActorDep,
) -> WorkspaceActionView:
    require_role(actor, UserRole.APPROVER)
    try:
        return await service.decide(actor, topic_id, turn_id, proposal_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


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
            "description": "SSE workspace/chat_text events; typed frames match /notifications.",
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
    try:
        first = await service.notifications(actor.actor_id, topic_id, after)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return await workspace_stream_response(request, service, actor, topic_id, after, first)


@router.get("/topics/{topic_id}/notifications", response_model=WorkspaceNotificationPage)
async def notifications(
    topic_id: str,
    service: EventsDep,
    actor: ActorDep,
    after: Annotated[int, Query(ge=0, le=9007199254740991)] = 0,
) -> WorkspaceNotificationPage:
    require_role(actor, UserRole.VIEWER)
    try:
        return await service.notifications(actor.actor_id, topic_id, after)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/topics/{topic_id}/messages", response_model=WorkspaceTurn)
async def send_message(
    topic_id: str, payload: MessageCreate, service: WorkspaceDep, actor: ActorDep
) -> WorkspaceTurn:
    require_role(actor, UserRole.OPERATOR)
    try:
        result = await service.send(actor.actor_id, topic_id, payload)
        return result.model_copy(update={"goal": public_goal(result.goal) if result.goal else None})
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
