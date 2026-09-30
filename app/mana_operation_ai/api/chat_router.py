from typing import Annotated, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.mana_operation_ai.api.dependencies import OperationAdminServiceDep
from app.mana_operation_ai.api.security import ActorDep, require_role
from app.mana_operation_ai.application.agent_service import (
    AgentRunLockedError,
    AgentUnavailableError,
)
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.chat_service import OperationChatService
from app.mana_operation_ai.domain.chat import (
    AnalysisRequest,
    ChatAnalysisState,
    ChatAvailability,
    ChatTopic,
    ChatTurn,
    MessageCreate,
    TopicCreate,
    TopicDetail,
)
from app.mana_operation_ai.domain.enums import UserRole


def get_chat_service(request: Request) -> OperationChatService:
    return cast(OperationChatService, request.app.state.operation_chat_service)


ChatDep = Annotated[OperationChatService, Depends(get_chat_service)]
router = APIRouter()


@router.post("/topics/{topic_id}/analysis", response_model=ChatTurn, status_code=202)
async def request_analysis(
    topic_id: str,
    payload: AnalysisRequest,
    service: ChatDep,
    actor: ActorDep,
    admin: OperationAdminServiceDep,
    background_tasks: BackgroundTasks,
) -> ChatTurn:
    require_role(actor, UserRole.OPERATOR)
    try:
        topic, turn, admitted = await service.prepare_analysis(actor.actor_id, topic_id, payload)
        if admitted:
            background_tasks.add_task(
                admin.run_in_background,
                agent_id=topic.agent_id,
                capability_key=admin.default_capability_key(topic.agent_id),
                job_type="analysis",
                actor=actor,
                correlation_id=turn.turn_id,
                idempotency_key=f"chat-{turn.turn_id}",
            )
        return turn
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except (AgentUnavailableError, AgentRunLockedError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/topics/{topic_id}/analysis/{turn_id}", response_model=ChatAnalysisState)
async def analysis_state(
    topic_id: str,
    turn_id: str,
    service: ChatDep,
    actor: ActorDep,
) -> ChatAnalysisState:
    try:
        return await service.analysis_state(actor.actor_id, topic_id, turn_id)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/availability", response_model=ChatAvailability)
async def availability(service: ChatDep, actor: ActorDep) -> ChatAvailability:
    return service.availability


@router.get("/topics", response_model=list[ChatTopic])
async def topics(service: ChatDep, actor: ActorDep) -> list[ChatTopic]:
    return await service.repository.topics(actor.actor_id)


@router.post("/topics", response_model=ChatTopic, status_code=201)
async def create_topic(payload: TopicCreate, service: ChatDep, actor: ActorDep) -> ChatTopic:
    try:
        return await service.create(actor.actor_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/topics/{topic_id}", response_model=TopicDetail)
async def topic_detail(topic_id: str, service: ChatDep, actor: ActorDep) -> TopicDetail:
    try:
        return await service.detail(actor.actor_id, topic_id)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/topics/{topic_id}/messages", response_model=ChatTurn)
async def send_message(
    topic_id: str,
    payload: MessageCreate,
    service: ChatDep,
    actor: ActorDep,
) -> ChatTurn:
    try:
        return await service.send(actor.actor_id, topic_id, payload)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/topics/{topic_id}/messages/{turn_id}/stop", response_model=ChatTurn)
async def stop_message(
    topic_id: str,
    turn_id: str,
    service: ChatDep,
    actor: ActorDep,
) -> ChatTurn:
    try:
        return await service.repository.cancel(actor.actor_id, topic_id, turn_id)
    except ChatError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
