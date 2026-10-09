from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request

from app.mana_operation_ai.api.security import ActorDep, require_role
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.goal_service import OperationGoalService
from app.mana_operation_ai.domain.enums import UserRole
from app.mana_operation_ai.domain.goals import (
    GoalAvailability,
    GoalCommand,
    GoalCreate,
    OperationGoal,
)


def get_goal_service(request: Request) -> OperationGoalService:
    return cast(OperationGoalService, request.app.state.operation_goal_service)


GoalDep = Annotated[OperationGoalService, Depends(get_goal_service)]
router = APIRouter()


@router.get("/availability", response_model=GoalAvailability)
async def availability(service: GoalDep, actor: ActorDep) -> GoalAvailability:
    require_role(actor, UserRole.VIEWER)
    return service.availability


@router.get("/topics/{topic_id}", response_model=list[OperationGoal])
async def list_goals(topic_id: str, service: GoalDep, actor: ActorDep) -> list[OperationGoal]:
    require_role(actor, UserRole.VIEWER)
    try:
        return await service.list_goals(actor.actor_id, topic_id)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/topics/{topic_id}", response_model=OperationGoal, status_code=202)
async def create_goal(
    topic_id: str, payload: GoalCreate, service: GoalDep, actor: ActorDep
) -> OperationGoal:
    require_role(actor, UserRole.OPERATOR)
    try:
        return await service.create(actor.actor_id, topic_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/{goal_id}", response_model=OperationGoal)
async def detail(goal_id: str, service: GoalDep, actor: ActorDep) -> OperationGoal:
    require_role(actor, UserRole.VIEWER)
    try:
        return await service.repository.get(actor.actor_id, goal_id)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/{goal_id}/commands", response_model=OperationGoal)
async def control(
    goal_id: str, payload: GoalCommand, service: GoalDep, actor: ActorDep
) -> OperationGoal:
    require_role(actor, UserRole.OPERATOR)
    try:
        return await service.command(actor.actor_id, goal_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
