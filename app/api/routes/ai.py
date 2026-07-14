from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import OpenAIServiceDep
from app.schemas.ai import ChatRequest, ChatResponse, SummarizeRequest, SummarizeResponse
from app.services.openai_service import AIProviderError

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, openai_service: OpenAIServiceDep) -> ChatResponse:
    try:
        return await openai_service.chat(payload)
    except AIProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize(
    payload: SummarizeRequest,
    openai_service: OpenAIServiceDep,
) -> SummarizeResponse:
    try:
        return await openai_service.summarize(payload)
    except AIProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
