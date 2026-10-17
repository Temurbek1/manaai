"""Thin, authenticated contact-sandbox transport; no provider or Goal tool dispatch."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.mana_operation_ai.api.security import ActorDep, require_role
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.contact_result_continuation import (
    ContactResultContinuationService,
)
from app.mana_operation_ai.application.retention.preparation_errors import ContactPreparationError
from app.mana_operation_ai.application.workspace_retention_contacts import (
    WorkspaceRetentionContacts,
)
from app.mana_operation_ai.domain.chat import ChatTurn
from app.mana_operation_ai.domain.contact_continuation import ContactContinueRequest
from app.mana_operation_ai.domain.enums import UserRole
from app.mana_operation_ai.domain.retention_contact import RetentionContactDecision
from app.mana_operation_ai.domain.workspace_retention_contacts import (
    WorkspaceContactPage,
    WorkspaceContactPrepare,
    WorkspaceContactReconcile,
    WorkspaceContactView,
    WorkspacePreparationFailure,
    WorkspacePreparationObservation,
)


def get_contacts(request: Request) -> WorkspaceRetentionContacts:
    return cast(
        WorkspaceRetentionContacts, request.app.state.operation_workspace_retention_contacts
    )


ContactsDep = Annotated[WorkspaceRetentionContacts, Depends(get_contacts)]


def get_continuation(request: Request) -> ContactResultContinuationService:
    return cast(
        ContactResultContinuationService, request.app.state.operation_contact_result_continuation
    )


ContinuationDep = Annotated[ContactResultContinuationService, Depends(get_continuation)]
router = APIRouter(prefix="/topics/{topic_id}/messages/{turn_id}/retention-contacts")


@router.get("", response_model=WorkspaceContactPage)
async def page(
    topic_id: str, turn_id: str, service: ContactsDep, actor: ActorDep
) -> WorkspaceContactPage:
    require_role(actor, UserRole.VIEWER)
    try:
        return await service.page(actor.actor_id, topic_id, turn_id)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/preparation", response_model=WorkspacePreparationObservation)
async def observe_preparation(
    topic_id: str, turn_id: str, request_id: UUID, service: ContactsDep, actor: ActorDep
) -> WorkspacePreparationObservation:
    require_role(actor, UserRole.VIEWER)
    try:
        return await service.observe_preparation(actor.actor_id, topic_id, turn_id, request_id)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post(
    "/prepare",
    response_model=WorkspaceContactView,
    responses={code: {"model": WorkspacePreparationFailure} for code in (409, 423, 429, 503)},
)
async def prepare(
    topic_id: str,
    turn_id: str,
    payload: WorkspaceContactPrepare,
    service: ContactsDep,
    actor: ActorDep,
) -> WorkspaceContactView:
    require_role(actor, UserRole.OPERATOR)
    try:
        return await service.prepare(actor, topic_id, turn_id, payload)
    except ContactPreparationError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": str(exc)}) from exc
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/{action_id}/decision", response_model=WorkspaceContactView)
async def decide(
    topic_id: str,
    turn_id: str,
    action_id: str,
    payload: RetentionContactDecision,
    service: ContactsDep,
    actor: ActorDep,
) -> WorkspaceContactView:
    require_role(actor, UserRole.APPROVER)
    try:
        return await service.decide(actor, topic_id, turn_id, action_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/continue", response_model=ChatTurn)
async def continue_contact(
    topic_id: str,
    turn_id: str,
    payload: ContactContinueRequest,
    service: ContinuationDep,
    actor: ActorDep,
) -> ChatTurn:
    require_role(actor, UserRole.OPERATOR)
    try:
        return await service.continue_with_result(actor, topic_id, turn_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/{action_id}/reconcile", response_model=WorkspaceContactView)
async def reconcile(
    topic_id: str,
    turn_id: str,
    action_id: str,
    payload: WorkspaceContactReconcile,
    service: ContactsDep,
    actor: ActorDep,
) -> WorkspaceContactView:
    require_role(actor, UserRole.APPROVER)
    try:
        return await service.reconcile(actor, topic_id, turn_id, action_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
