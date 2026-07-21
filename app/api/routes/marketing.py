from typing import cast

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.dependencies import (
    MarketingAnalysisServiceDep,
    MarketingRepositoryDep,
    MarketingSyncServiceDep,
)
from app.core.config import Settings
from app.schemas.marketing import (
    MarketingAnalysisRequest,
    MarketingAnalysisResponse,
    MarketingEntityType,
    MarketingIntegrationConfigResponse,
    MetaSyncRequest,
    MetaSyncResponse,
    RawMarketingIngestRequest,
    RawMarketingIngestResponse,
    RawMarketingRecordListResponse,
)
from app.services.meta_marketing_client import MetaAPIError, MetaConfigurationError
from app.services.openai_service import AIConfigurationError, AIProviderError

router = APIRouter()


@router.get(
    "/config",
    response_model=MarketingIntegrationConfigResponse,
    summary="Show marketing integration configuration",
    description="Returns non-secret Meta/OpenAI integration configuration status.",
)
async def marketing_config(request: Request) -> MarketingIntegrationConfigResponse:
    settings = cast(Settings, request.app.state.settings)
    return MarketingIntegrationConfigResponse(
        meta_configured=settings.is_meta_configured,
        meta_app_id_configured=bool(settings.meta_app_id),
        meta_business_id_configured=bool(settings.meta_business_id),
        meta_ad_account_ids_configured=len(settings.meta_ad_account_ids),
        meta_graph_api_version=settings.meta_graph_api_version,
        openai_configured=settings.is_openai_configured,
        openai_model=settings.openai_model,
        raw_storage_path=str(settings.marketing_database_path),
    )


@router.post(
    "/raw",
    response_model=RawMarketingIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest raw marketing records",
    description="Stores append-only raw marketing JSON records for later KPI and AI analysis.",
)
async def ingest_raw_records(
    payload: RawMarketingIngestRequest,
    repository: MarketingRepositoryDep,
) -> RawMarketingIngestResponse:
    inserted = await repository.insert_raw_records(payload.records)
    return RawMarketingIngestResponse(
        inserted_count=len(inserted),
        record_ids=[record.id for record in inserted],
    )


@router.get(
    "/raw",
    response_model=RawMarketingRecordListResponse,
    summary="List raw marketing records",
    description="Lists stored raw records with optional account and entity filters.",
)
async def list_raw_records(
    repository: MarketingRepositoryDep,
    account_id: str | None = Query(default=None, min_length=1),
    entity_type: MarketingEntityType | None = None,
    limit: int = Query(default=100, ge=1, le=1_000),
    offset: int = Query(default=0, ge=0),
) -> RawMarketingRecordListResponse:
    records, total = await repository.list_raw_records(
        account_ids=[account_id] if account_id else None,
        entity_types=[entity_type] if entity_type else None,
        limit=limit,
        offset=offset,
    )
    return RawMarketingRecordListResponse(
        total=total,
        limit=limit,
        offset=offset,
        records=records,
    )


@router.post(
    "/meta/sync",
    response_model=MetaSyncResponse,
    summary="Sync Meta Marketing API data",
    description=(
        "Fetches configured Meta app/ad account structure and insights through the official "
        "Graph/Marketing API and stores every response as raw records."
    ),
)
async def sync_meta_marketing(
    payload: MetaSyncRequest,
    sync_service: MarketingSyncServiceDep,
) -> MetaSyncResponse:
    try:
        return await sync_service.sync_meta(payload)
    except MetaConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except MetaAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post(
    "/analyze",
    response_model=MarketingAnalysisResponse,
    summary="Generate marketing analytics report",
    description=(
        "Builds deterministic KPIs from stored raw records and returns a structured AI report "
        "for analytics workflows."
    ),
)
async def analyze_marketing(
    payload: MarketingAnalysisRequest,
    analysis_service: MarketingAnalysisServiceDep,
) -> MarketingAnalysisResponse:
    try:
        return await analysis_service.analyze(payload)
    except AIConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
