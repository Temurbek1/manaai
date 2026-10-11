from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request

from app.mana_operation_ai.api.security import ActorDep, require_role
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.workspace_service import OperationWorkspaceService
from app.mana_operation_ai.domain.chat import MessageCreate
from app.mana_operation_ai.domain.enums import UserRole
from app.mana_operation_ai.domain.workspace import WorkspaceTurn


def get_workspace(request: Request) -> OperationWorkspaceService:
    return cast(OperationWorkspaceService, request.app.state.operation_workspace_service)


WorkspaceDep = Annotated[OperationWorkspaceService, Depends(get_workspace)]
router = APIRouter()


@router.post("/topics/{topic_id}/messages", response_model=WorkspaceTurn)
async def send_message(
    topic_id: str, payload: MessageCreate, service: WorkspaceDep, actor: ActorDep
) -> WorkspaceTurn:
    require_role(actor, UserRole.OPERATOR)
    try:
        return await service.send(actor.actor_id, topic_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
