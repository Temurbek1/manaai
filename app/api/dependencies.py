from typing import Annotated, cast

from fastapi import Depends, Request

from app.services.marketing_analysis_service import MarketingAnalysisService
from app.services.marketing_repository import MarketingRepository
from app.services.marketing_sync_service import MarketingSyncService
from app.services.openai_service import OpenAIService


def get_openai_service(request: Request) -> OpenAIService:
    return cast(OpenAIService, request.app.state.openai_service)


def get_marketing_repository(request: Request) -> MarketingRepository:
    return cast(MarketingRepository, request.app.state.marketing_repository)


def get_marketing_sync_service(request: Request) -> MarketingSyncService:
    return cast(MarketingSyncService, request.app.state.marketing_sync_service)


def get_marketing_analysis_service(request: Request) -> MarketingAnalysisService:
    return cast(MarketingAnalysisService, request.app.state.marketing_analysis_service)


OpenAIServiceDep = Annotated[OpenAIService, Depends(get_openai_service)]
MarketingRepositoryDep = Annotated[MarketingRepository, Depends(get_marketing_repository)]
MarketingSyncServiceDep = Annotated[MarketingSyncService, Depends(get_marketing_sync_service)]
MarketingAnalysisServiceDep = Annotated[
    MarketingAnalysisService,
    Depends(get_marketing_analysis_service),
]
