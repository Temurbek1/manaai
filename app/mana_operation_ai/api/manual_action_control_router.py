"""Workspace routing retains the owning operational service and existing audit controls."""

from fastapi import APIRouter, HTTPException

from app.mana_operation_ai.api.dependencies import OperationAdminServiceDep
from app.mana_operation_ai.api.security import ActorDep, require_role
from app.mana_operation_ai.domain.enums import UserRole
from app.mana_operation_ai.domain.manual_action_controls import (
    ManualActionControlChange,
    ManualActionControlPage,
    ManualActionControlView,
)

router = APIRouter(prefix="/manual-action-controls")


@router.get("", response_model=ManualActionControlPage)
async def controls(
    admin: OperationAdminServiceDep, actor: ActorDep, agent_id: str | None = None
) -> ManualActionControlPage:
    require_role(actor, UserRole.VIEWER)
    try:
        return await admin.manual_action_controls(agent_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/{agent_id}/{capability_key}", response_model=ManualActionControlView)
async def change_control(
    agent_id: str,
    capability_key: str,
    payload: ManualActionControlChange,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> ManualActionControlView:
    require_role(actor, UserRole.ADMIN)
    try:
        return await admin.set_manual_action_control(
            agent_id=agent_id,
            capability_key=capability_key,
            enabled=payload.enabled,
            actor=actor,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
