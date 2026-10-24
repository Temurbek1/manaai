"""Backend-owned language/preferences and push observations, never raw send access."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.routes.mana_family_agents import ServiceDep, controlled, no_store
from app.api.security import require_backend_bearer_token
from app.mana_ai.application.proactive_parent import ProactiveParentService
from app.mana_ai.domain.chat import ParentChatId
from app.mana_ai.domain.proactive_parent import (
    ParentContactContext,
    ParentPushPage,
    ParentPushState,
)

router = APIRouter(
    tags=["mana-notifications"],
    dependencies=[Depends(require_backend_bearer_token), Depends(no_store)],
)


def get_proactive(service: ServiceDep) -> ProactiveParentService:
    if service.proactive is None:
        raise HTTPException(status_code=503, detail={"code": "parent_proactive_disabled"})
    return service.proactive


ProactiveDep = Annotated[ProactiveParentService, Depends(get_proactive)]


@router.post(
    "/parent-touch/contact-context",
    response_model=ParentContactContext,
    summary="Register verified recipient language and separate contact permissions",
    description="Trusted backend only; derive parent_id from the authorized family. "
    "Can be registered before the parent's first chat message. Language/timezone are "
    "presentation, never source/write authority. Supply verified current preferences and "
    "an explicit expiry; no invented default locale or inferred marketing consent. "
    "Exact event replay never changes the original context or sends a notification.",
)
async def register_contact(
    service: ProactiveDep, payload: ParentContactContext
) -> ParentContactContext:
    return await controlled(service.register(payload))


@router.get("/parent-touch/contact-context", response_model=ParentContactContext)
async def read_contact(
    service: ProactiveDep, parent_id: Annotated[ParentChatId, Query()]
) -> ParentContactContext:
    return await controlled(service.context(parent_id))


@router.get(
    "/parent-touch/notifications",
    response_model=ParentPushPage,
    summary="Observe same-parent pushes attached to already saved chat messages",
    description="SQL only. No push/model/source dispatch. Provider queueing, including zero "
    "devices, does not prove device delivery or opening. Unknown attempts never auto-retry.",
)
async def read_notifications(
    service: ProactiveDep,
    parent_id: Annotated[ParentChatId, Query()],
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ParentPushPage:
    return await controlled(service.pushes(parent_id, after=after, limit=limit))


@router.get("/parent-touch/notifications/{push_id}", response_model=ParentPushState)
async def read_notification(
    service: ProactiveDep, push_id: UUID, parent_id: Annotated[ParentChatId, Query()]
) -> ParentPushState:
    return await controlled(service.push(parent_id, push_id))
