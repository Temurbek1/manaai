from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response

from app.api.security import require_backend_bearer_token
from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.parent_chat import ParentChatService
from app.mana_ai.domain.chat import (
    ParentChatHistory,
    ParentChatId,
    ParentChatRequest,
    ParentChatResponse,
)

router = APIRouter(dependencies=[Depends(require_backend_bearer_token)])


def get_parent_chat_service(request: Request) -> ParentChatService:
    service = getattr(request.app.state, "parent_chat_service", None)
    if not isinstance(service, ParentChatService):
        raise HTTPException(status_code=503, detail={"code": "parent_chat_disabled"})
    return service


ChatServiceDep = Annotated[ParentChatService, Depends(get_parent_chat_service)]


def _http_error(error: ParentChatError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code},
        headers={"Retry-After": str(error.retry_after)} if error.retry_after else None,
    )


@router.get(
    "/chat",
    response_model=ParentChatHistory,
    summary="Read the parent's single chat and current daily allowance",
    description=(
        "Backend-to-backend only. Derive parent_id from the authenticated app session; "
        "never accept another parent's ID from the mobile client. No source or model calls. "
        "Messages are chronological within the latest page. Page backwards with "
        "next_before_turn_id; limit counts turns, not messages."
    ),
)
async def read_parent_chat(
    service: ChatServiceDep,
    response: Response,
    parent_id: Annotated[ParentChatId, Query()],
    before_turn_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> ParentChatHistory:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await service.history(parent_id, before=before_turn_id, limit=limit)
    except ParentChatError as exc:
        raise _http_error(exc) from None
    except Exception:
        raise HTTPException(status_code=503, detail={"code": "chat_storage_unavailable"}) from None


@router.post(
    "/chat",
    response_model=ParentChatResponse,
    summary="Send a message in the parent's single persistent chat",
    description=(
        "Backend-to-backend only, using the profile/Firebase parent ID (not Firebase Auth UID). "
        "The backend authenticates the parent and derives this ID from its session. "
        "Replies use the latest message's language. request_id is mandatory: reuse it with "
        "the identical body after transport loss; never generate a new ID to retry inference. "
        "Daily quota counts all input and output tokens, including bounded history/context. "
        "Unknown dispatched costs remain reserved, even across daily rollover. "
        "Fresh MANA child profile context is ownership-filtered, with no collection scans."
        " Optional minimized child_observations come only from the authenticated backend; "
        "every child must still be connected to this parent in the fresh profile read. "
        "Observations must include their actual time/usage period, not collection time."
    ),
    responses={
        401: {"description": "Backend authentication failed"},
        403: {"description": "An observation references a child not connected to this parent"},
        404: {"description": "Parent profile not found"},
        409: {"description": "Conflicting request or an earlier request is unresolved"},
        429: {"description": "Daily token/request limit reached"},
        502: {"description": "Model rejected the request or returned no usable answer"},
        503: {"description": "Disabled, source/storage failure or unknown model receipt"},
    },
)
async def send_parent_chat(
    service: ChatServiceDep,
    response: Response,
    payload: Annotated[
        ParentChatRequest,
        Body(
            openapi_examples={
                "default": {
                    "value": {
                        "parent_id": "123",
                        "request_id": "8270fbd2-1579-4c44-955c-6703ac27098f",
                        "message": "Как помочь ребёнку со сном?",
                    }
                }
            }
        ),
    ],
) -> ParentChatResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return await service.send(payload)
    except ParentChatError as exc:
        raise _http_error(exc) from None
    except Exception:
        raise HTTPException(status_code=503, detail={"code": "chat_storage_unavailable"}) from None
