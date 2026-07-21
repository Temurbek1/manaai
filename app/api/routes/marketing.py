from typing import cast

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.dependencies import (
    MarketingAnalysisServiceDep,
    MarketingGraphServiceDep,
    MarketingPatternServiceDep,
    MarketingRepositoryDep,
    MarketingSyncServiceDep,
)
from app.core.config import Settings
from app.schemas.marketing import (
    MarketingAnalysisReportListResponse,
    MarketingAnalysisRequest,
    MarketingAnalysisResponse,
    MarketingEntityType,
    MarketingGraphRequest,
    MarketingGraphResponse,
    MarketingIntegrationConfigResponse,
    MarketingPatternsRequest,
    MarketingPatternsResponse,
    MetaDiscoveryResponse,
    MetaInsightsAsyncJobCreateResponse,
    MetaInsightsAsyncJobIngestRequest,
    MetaInsightsAsyncJobIngestResponse,
    MetaInsightsAsyncJobRequest,
    MetaInsightsAsyncJobStatusResponse,
    MetaSyncRequest,
    MetaSyncResponse,
    RawMarketingIngestRequest,
    RawMarketingIngestResponse,
    RawMarketingRecordListResponse,
    RawMarketingRecordSearchRequest,
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
    "/raw/search",
    response_model=RawMarketingRecordListResponse,
    summary="Search raw marketing records",
    description=(
        "Searches stored raw records by account, entity, provider id, date range, and exact "
        "top-level payload or breakdown dimension values for audit workflows."
    ),
)
async def search_raw_records(
    payload: RawMarketingRecordSearchRequest,
    repository: MarketingRepositoryDep,
) -> RawMarketingRecordListResponse:
    payload_filters = {**payload.payload_filters, **payload.dimension_filters}
    records, total = await repository.list_raw_records(
        account_ids=payload.account_ids,
        entity_types=payload.entity_types,
        provider_record_ids=payload.provider_record_ids,
        date_start=payload.date_start,
        date_stop=payload.date_stop,
        payload_filters=payload_filters,
        limit=payload.limit,
        offset=payload.offset,
    )
    return RawMarketingRecordListResponse(
        total=total,
        limit=payload.limit,
        offset=payload.offset,
        records=records,
    )


@router.post(
    "/meta/sync",
    response_model=MetaSyncResponse,
    summary="Sync Meta Marketing API data",
    description=(
        "Fetches configured Meta app/ad account structure and insights through the official "
        "Graph/Marketing API and stores every response as raw records. Insights sync supports "
        "breakdowns, action_breakdowns, and time_increment for granular segment analysis."
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
    "/meta/discover",
    response_model=MetaDiscoveryResponse,
    summary="Discover Meta app and ad accounts",
    description=(
        "Fetches configured Meta app metadata and accessible ad accounts through the official "
        "Graph API, then stores every payload as raw records."
    ),
)
async def discover_meta_assets(
    sync_service: MarketingSyncServiceDep,
) -> MetaDiscoveryResponse:
    try:
        return await sync_service.discover_meta_assets()
    except MetaConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except MetaAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post(
    "/meta/insights/jobs",
    response_model=MetaInsightsAsyncJobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create Meta async insights job",
    description=(
        "Submits an asynchronous Meta Ads Insights job for larger report pulls and stores "
        "the job creation payload as raw data."
    ),
)
async def create_meta_insights_job(
    payload: MetaInsightsAsyncJobRequest,
    sync_service: MarketingSyncServiceDep,
) -> MetaInsightsAsyncJobCreateResponse:
    try:
        return await sync_service.create_insights_async_job(payload)
    except MetaConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except MetaAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get(
    "/meta/insights/jobs/{report_run_id}",
    response_model=MetaInsightsAsyncJobStatusResponse,
    summary="Get Meta async insights job status",
    description="Polls a Meta Ads Insights async job without storing secrets or tokens.",
)
async def get_meta_insights_job_status(
    report_run_id: str,
    sync_service: MarketingSyncServiceDep,
) -> MetaInsightsAsyncJobStatusResponse:
    try:
        return await sync_service.get_insights_async_job_status(report_run_id)
    except MetaConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except MetaAPIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post(
    "/meta/insights/jobs/{report_run_id}/ingest",
    response_model=MetaInsightsAsyncJobIngestResponse,
    summary="Ingest Meta async insights job results",
    description="Downloads completed async insights results and stores each row as raw data.",
)
async def ingest_meta_insights_job_results(
    report_run_id: str,
    payload: MetaInsightsAsyncJobIngestRequest,
    sync_service: MarketingSyncServiceDep,
) -> MetaInsightsAsyncJobIngestResponse:
    try:
        return await sync_service.ingest_insights_async_job_results(
            report_run_id=report_run_id,
            request=payload,
        )
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


@router.get(
    "/reports",
    response_model=MarketingAnalysisReportListResponse,
    summary="List saved marketing analysis reports",
    description="Lists saved AI/deterministic marketing analysis reports for audit and reuse.",
)
async def list_marketing_reports(
    repository: MarketingRepositoryDep,
    limit: int = Query(default=100, ge=1, le=1_000),
    offset: int = Query(default=0, ge=0),
) -> MarketingAnalysisReportListResponse:
    reports, total = await repository.list_analysis_reports(limit=limit, offset=offset)
    return MarketingAnalysisReportListResponse(
        total=total,
        limit=limit,
        offset=offset,
        reports=reports,
    )


@router.get(
    "/reports/{report_id}",
    response_model=MarketingAnalysisResponse,
    summary="Get saved marketing analysis report",
    description="Returns one saved typed marketing analysis response by report id.",
)
async def get_marketing_report(
    report_id: str,
    repository: MarketingRepositoryDep,
) -> MarketingAnalysisResponse:
    report = await repository.get_analysis_report(report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Marketing analysis report was not found",
        )
    return report


@router.post(
    "/graph",
    response_model=MarketingGraphResponse,
    summary="Build marketing entity graph",
    description=(
        "Builds a relationship graph from stored raw Meta records: app, business, ad "
        "accounts, pixels, custom conversions, custom audiences, campaigns, ad sets, "
        "ads, creatives, and insight measurements."
    ),
)
async def build_marketing_graph(
    payload: MarketingGraphRequest,
    graph_service: MarketingGraphServiceDep,
) -> MarketingGraphResponse:
    return await graph_service.build(payload)


@router.post(
    "/patterns",
    response_model=MarketingPatternsResponse,
    summary="Detect deterministic marketing patterns",
    description=(
        "Builds KPI rows from stored raw insights and returns deterministic patterns before "
        "any AI interpretation."
    ),
)
async def detect_marketing_patterns(
    payload: MarketingPatternsRequest,
    pattern_service: MarketingPatternServiceDep,
) -> MarketingPatternsResponse:
    return await pattern_service.detect(payload)
