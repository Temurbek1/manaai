"""Thin, authenticated contact-sandbox transport; no provider or Goal tool dispatch."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request

from app.mana_operation_ai.api.security import ActorDep, require_role
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.workspace_retention_contacts import (
    WorkspaceRetentionContacts,
)
from app.mana_operation_ai.domain.enums import UserRole
from app.mana_operation_ai.domain.retention_contact import RetentionContactDecision
from app.mana_operation_ai.domain.workspace_retention_contacts import (
    WorkspaceContactPage,
    WorkspaceContactPrepare,
    WorkspaceContactReconcile,
    WorkspaceContactView,
)


def get_contacts(request: Request) -> WorkspaceRetentionContacts:
    return cast(
        WorkspaceRetentionContacts, request.app.state.operation_workspace_retention_contacts
    )


ContactsDep = Annotated[WorkspaceRetentionContacts, Depends(get_contacts)]
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


@router.post("/prepare", response_model=WorkspaceContactView)
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
