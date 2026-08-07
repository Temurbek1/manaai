from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, mana_ai
from app.api.security import require_api_key
from app.core.auth_rate_limiter import AuthenticationRateLimiter
from app.core.config import get_settings
from app.core.logging import configure_application_logging
from app.core.middleware import EXPOSED_RESPONSE_HEADERS, request_trace_middleware
from app.core.openapi import API_DESCRIPTION, OPENAPI_TAGS, SWAGGER_UI_PARAMETERS
from app.core.request_body_limit import RequestBodyLimitMiddleware
from app.mana_ai.application.service import ManaAIAnalysisService
from app.services.mana_ai_openai_gateway import ManaAIOpenAIModelGateway, SystemManaAIClock
from app.services.openai_service import OpenAIService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    openai_service = OpenAIService(settings=settings)
    app.state.settings = settings
    app.state.mana_ai_analysis_service = ManaAIAnalysisService(
        gateway=ManaAIOpenAIModelGateway(openai_service),
        clock=SystemManaAIClock(),
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.app_env == "production" and not settings.is_app_api_key_configured:
        raise RuntimeError("APP_API_KEY is required for the production MANA AI API")
    if (
        settings.app_env == "production"
        and settings.app_api_key is not None
        and len(settings.app_api_key.get_secret_value()) < 32
    ):
        raise RuntimeError("APP_API_KEY must contain at least 32 characters in production")
    if settings.app_env == "production" and not settings.is_openai_configured:
        raise RuntimeError("OPENAI_API_KEY is required for the production MANA AI API")
    configure_application_logging(
        level=settings.log_level,
        secrets=[
            settings.openai_api_key.get_secret_value(),
            settings.app_api_key.get_secret_value() if settings.app_api_key else "",
        ],
    )
    app = FastAPI(
        title=f"{settings.app_name} MANA AI",
        summary="Read-only request/response AI API for the MANA application.",
        description=API_DESCRIPTION,
        version=settings.app_version,
        contact={"name": "ManaAI API maintainers"},
        license_info={"name": "Proprietary"},
        openapi_tags=OPENAPI_TAGS,
        swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
        docs_url="/docs" if settings.is_docs_enabled else None,
        redoc_url="/redoc" if settings.is_docs_enabled else None,
        openapi_url="/openapi.json" if settings.is_docs_enabled else None,
        lifespan=lifespan,
    )
    app.state.auth_rate_limiter = AuthenticationRateLimiter(
        failure_limit=settings.auth_failure_limit,
        window_seconds=settings.auth_failure_window_seconds,
    )
    app.middleware("http")(request_trace_middleware)
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=settings.mana_ai_max_request_body_bytes,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=EXPOSED_RESPONSE_HEADERS,
    )

    api_router = APIRouter()
    api_router.include_router(health.router, prefix="/health", tags=["health"])
    api_router.include_router(
        mana_ai.router,
        prefix="/mana-ai",
        tags=["mana-ai"],
        dependencies=[Depends(require_api_key)],
    )
    app.include_router(api_router, prefix="/api/v1")
    return app
