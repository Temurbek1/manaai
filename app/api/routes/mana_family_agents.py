"""Backend-only family coordination; never the administrative agents API."""

from collections.abc import Awaitable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.api.security import require_backend_bearer_token
from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.chat import ParentChatId
from app.mana_ai.domain.family_agents import (
    AgentQuestionPage,
    AgentQuestionReceipt,
    AgentQuestionRequest,
    FamilyAgentDirectory,
    ParentTouchDeliveryRequest,
    ParentTouchHistory,
    ParentTouchMessageRequest,
    ParentTouchMessageState,
    ParentTouchRequest,
    ParentTouchResponse,
)


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(dependencies=[Depends(require_backend_bearer_token), Depends(no_store)])


def get_parent_touch_service(request: Request) -> ParentTouchService:
    service = getattr(request.app.state, "parent_chat_service", None)
    if not isinstance(service, ParentTouchService):
        raise HTTPException(status_code=503, detail={"code": "parent_touch_disabled"})
    return service


ServiceDep = Annotated[ParentTouchService, Depends(get_parent_touch_service)]


async def controlled[Result](operation: Awaitable[Result]) -> Result:
    try:
        return await operation
    except ParentChatError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code},
            headers={"Retry-After": str(exc.retry_after)} if exc.retry_after else None,
        ) from None
    except Exception:
        raise HTTPException(
            status_code=503, detail={"code": "family_service_unavailable"}
        ) from None


@router.get(
    "/agents", response_model=FamilyAgentDirectory, summary="Read family-agent availability"
)
async def read_agents(service: ServiceDep) -> FamilyAgentDirectory:
    return service.directory()


@router.get(
    "/parent-touch/chat",
    response_model=ParentTouchHistory,
    summary="Read the parent's one chat and exact reply identities",
    description="Backend-only. SQL observation: no source read, model call or question delivery. "
    "message_questions maps visible assistant turns to their frozen question identities. "
    "active_question may be outside the requested page; fetch its turn before showing a reply UI. "
    "message_notices maps delivered assessments to assistant turns; pending_notices is not "
    "a send confirmation or a guarantee of immediate delivery.",
)
async def read_chat(
    service: ServiceDep,
    parent_id: Annotated[ParentChatId, Query()],
    before_turn_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> ParentTouchHistory:
    return await controlled(
        service.read_touch_history(parent_id, before=before_turn_id, limit=limit)
    )


@router.post(
    "/parent-touch/chat",
    response_model=ParentTouchResponse,
    summary="Send a parent message to Parent-Touch",
    description="Derive parent_id from the authenticated MANA backend session. One chat only. "
    "Reuse the identical request_id/body after transport loss. reply_to_question_id explicitly "
    "binds an answer to one previously displayed question; omitted metadata never answers it. "
    "A replay preserves the original asked_question, not the current active question. "
    "The existing /chat shares this service, history and 2000-token default allowance.",
)
async def send_chat(service: ServiceDep, payload: ParentTouchRequest) -> ParentTouchResponse:
    return await controlled(service.send_touch(payload))


@router.post(
    "/parent-touch/messages",
    response_model=ParentTouchMessageState,
    status_code=202,
    summary="Admit one review-first parent message to the single chat",
    description="Backend-only. SQL admission; Child-Safety reviews this exact message before "
    "Parent-Touch communicates its guidance. Reuse the identical UUID/body after HTTP loss. "
    "Poll the message status or the same chat history; GET never dispatches. One pending "
    "message per parent, 2000 daily chat tokens and a separate specialist budget. Waiting "
    "and preparation expire after five minutes without automatic retry. New sensor data "
    "uses the typed Child-Safety endpoints, not this conversational request.",
)
async def admit_message(
    service: ServiceDep, payload: ParentTouchMessageRequest
) -> ParentTouchMessageState:
    return await controlled(service.admit_message(payload))


@router.get(
    "/parent-touch/messages/{request_id}",
    response_model=ParentTouchMessageState,
    summary="Observe a same-family review-first message without redispatch",
)
async def read_message(
    service: ServiceDep,
    request_id: UUID,
    parent_id: Annotated[ParentChatId, Query()],
) -> ParentTouchMessageState:
    return await controlled(service.message_state(parent_id, request_id))


@router.post(
    "/parent-touch/deliver",
    response_model=ParentTouchResponse,
    summary="Deliver one queued specialist communication in the same chat",
    description="Explicit backend dispatch, not a GET side effect or push notification. "
    "No fabricated parent message. Requires prior parent text for its frozen language/script, "
    "fresh child ownership and the shared Parent-Touch allowance. Reuse the exact request ID; "
    "a new nonce cannot repeat the same question/notice context. An urgent notice may interrupt "
    "an awaiting question without opening another question. Unknown receipts remain held. "
    "Optional resume_deferred_request_id explicitly identifies a previous-day delivery refused "
    "before inference only for daily_token_budget_exceeded. A new request_id admits the same "
    "still-valid choice/language context once per local day, with fresh ownership/quota checks. "
    "This is not automatic retry; paid, unknown, changed or expired work cannot resume.",
)
async def deliver_question(
    service: ServiceDep,
    payload: ParentTouchDeliveryRequest,
) -> ParentTouchResponse:
    return await controlled(service.deliver(payload))


@router.get(
    "/parent-touch/requests",
    response_model=AgentQuestionPage,
    summary="Observe same-family specialist requests (backend only)",
)
async def read_requests(
    service: ServiceDep,
    parent_id: Annotated[ParentChatId, Query()],
    after: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AgentQuestionPage:
    return await controlled(service.requests(parent_id, after=after, limit=limit))


@router.post(
    "/parent-touch/requests",
    response_model=AgentQuestionReceipt,
    status_code=201,
    summary="Admit a registered specialist's information need, without sending it",
    description="Trusted backend coordination only; do not expose this producer API to mobile. "
    "Fresh own-child validation precedes a new intent. Durable nonce/body/revision deduplication "
    "runs before source I/O; failed or abandoned admissions never auto-retry. "
    "Priority is 0–3 (higher first), FIFO for ties; one parent has only one active question.",
)
async def request_question(
    service: ServiceDep, payload: AgentQuestionRequest
) -> AgentQuestionReceipt:
    return await controlled(service.request_question(payload))
