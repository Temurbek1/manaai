"""Scoped human transport; no peer access to the original topic or Goals."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request

from app.mana_operation_ai.api.auth_security import CsrfHeader, SessionIdentityDep, require_csrf
from app.mana_operation_ai.api.security import require_role
from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.contact_reviews import WorkspaceContactReviews
from app.mana_operation_ai.domain.contact_reviews import (
    ContactReviewCreate,
    ContactReviewItem,
    ContactReviewOptions,
    ContactReviewPage,
    ContactReviewReceipt,
)
from app.mana_operation_ai.domain.enums import UserRole
from app.mana_operation_ai.domain.retention_contact import RetentionContactDecision
from app.mana_operation_ai.domain.workspace_retention_contacts import (
    WorkspaceContactReconcile,
    WorkspaceContactView,
)


def get_reviews(request: Request) -> WorkspaceContactReviews:
    return cast(WorkspaceContactReviews, request.app.state.operation_workspace_contact_reviews)


ReviewDep = Annotated[WorkspaceContactReviews, Depends(get_reviews)]


async def human_review_actor(
    request: Request, identity: SessionIdentityDep, supplied_csrf: CsrfHeader = None
) -> ActorContext:
    if not request.app.state.settings.mana_telegram_auth_enabled:
        raise HTTPException(503, "Personal browser sessions are required for peer reviews")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_csrf(request, identity, supplied_csrf)
    return ActorContext(actor_id=identity.user.user_id, role=identity.user.role)


ActorDep = Annotated[ActorContext, Depends(human_review_actor)]
router = APIRouter()
OWNER_PATH = "/topics/{topic_id}/messages/{turn_id}/retention-contacts/{action_id}/review"


@router.get(OWNER_PATH, response_model=ContactReviewOptions)
async def options(
    topic_id: str, turn_id: str, action_id: str, service: ReviewDep, actor: ActorDep
) -> ContactReviewOptions:
    require_role(actor, UserRole.OPERATOR)
    try:
        return await service.options(actor, topic_id, turn_id, action_id)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post(OWNER_PATH, response_model=ContactReviewReceipt)
async def share(
    topic_id: str,
    turn_id: str,
    action_id: str,
    payload: ContactReviewCreate,
    service: ReviewDep,
    actor: ActorDep,
) -> ContactReviewReceipt:
    require_role(actor, UserRole.OPERATOR)
    try:
        return await service.share(actor, topic_id, turn_id, action_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post(OWNER_PATH + "/revoke", response_model=ContactReviewReceipt)
async def revoke(
    topic_id: str,
    turn_id: str,
    action_id: str,
    payload: WorkspaceContactReconcile,
    service: ReviewDep,
    actor: ActorDep,
) -> ContactReviewReceipt:
    require_role(actor, UserRole.OPERATOR)
    try:
        return await service.revoke(actor, topic_id, turn_id, action_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/retention-contact-reviews", response_model=ContactReviewPage)
async def page(service: ReviewDep, actor: ActorDep) -> ContactReviewPage:
    require_role(actor, UserRole.APPROVER)
    try:
        return await service.page(actor)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/retention-contact-reviews/{review_id}", response_model=ContactReviewItem)
async def item(review_id: str, service: ReviewDep, actor: ActorDep) -> ContactReviewItem:
    require_role(actor, UserRole.APPROVER)
    try:
        return await service.item(actor, review_id)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post(
    "/retention-contact-reviews/{review_id}/{action_id}/decision",
    response_model=WorkspaceContactView,
)
async def decide(
    review_id: str,
    action_id: str,
    payload: RetentionContactDecision,
    service: ReviewDep,
    actor: ActorDep,
) -> WorkspaceContactView:
    require_role(actor, UserRole.APPROVER)
    try:
        return await service.decide(actor, review_id, action_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post(
    "/retention-contact-reviews/{review_id}/{action_id}/reconcile",
    response_model=WorkspaceContactView,
)
async def reconcile(
    review_id: str,
    action_id: str,
    payload: WorkspaceContactReconcile,
    service: ReviewDep,
    actor: ActorDep,
) -> WorkspaceContactView:
    require_role(actor, UserRole.APPROVER)
    try:
        return await service.reconcile(actor, review_id, action_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
