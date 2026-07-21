from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.openapi import API_DESCRIPTION, OPENAPI_TAGS, SWAGGER_UI_PARAMETERS
from app.services.marketing_analysis_service import MarketingAnalysisService
from app.services.marketing_metrics import MarketingMetricsBuilder
from app.services.marketing_repository import MarketingRepository
from app.services.marketing_sync_service import MarketingSyncService
from app.services.meta_marketing_client import MetaMarketingClient
from app.services.openai_service import OpenAIService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    openai_service = OpenAIService(settings=settings)
    marketing_repository = MarketingRepository(database_path=settings.marketing_database_path)
    await marketing_repository.initialize()
    meta_client = MetaMarketingClient(settings=settings)
    metrics_builder = MarketingMetricsBuilder(
        conversion_action_types=settings.marketing_conversion_action_types,
        value_action_types=settings.marketing_value_action_types,
    )

    app.state.settings = settings
    app.state.openai_service = openai_service
    app.state.marketing_repository = marketing_repository
    app.state.meta_marketing_client = meta_client
    app.state.marketing_sync_service = MarketingSyncService(
        meta_client=meta_client,
        repository=marketing_repository,
    )
    app.state.marketing_analysis_service = MarketingAnalysisService(
        repository=marketing_repository,
        metrics_builder=metrics_builder,
        openai_service=openai_service,
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        summary="AI integration API layer for ManaAI.",
        description=API_DESCRIPTION,
        version=settings.app_version,
        contact={
            "name": "ManaAI API maintainers",
        },
        license_info={
            "name": "Proprietary",
        },
        openapi_tags=OPENAPI_TAGS,
        swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
        docs_url="/docs" if settings.is_docs_enabled else None,
        redoc_url="/redoc" if settings.is_docs_enabled else None,
        openapi_url="/openapi.json" if settings.is_docs_enabled else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()
