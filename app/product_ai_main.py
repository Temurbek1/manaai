from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import audio_moderation, health, mana_ai
from app.api.security import require_bearer_token
from app.core.auth_rate_limiter import AuthenticationRateLimiter
from app.core.config import get_settings
from app.core.logging import configure_application_logging
from app.core.middleware import EXPOSED_RESPONSE_HEADERS, request_trace_middleware
from app.core.openapi import API_DESCRIPTION, OPENAPI_TAGS, SWAGGER_UI_PARAMETERS
from app.core.production import validate_production_api_settings
from app.core.rate_limiter import RequestRateLimiter
from app.core.request_body_limit import RequestBodyLimitMiddleware
from app.core.validation_errors import sanitized_request_validation_handler
from app.mana_ai.application.service import ManaAIAnalysisService
from app.services.audio_moderation_service import build_audio_moderation_runtime
from app.services.mana_ai_openai_gateway import ManaAIOpenAIModelGateway, SystemManaAIClock
from app.services.openai_service import OpenAIService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    openai_service = OpenAIService(settings=settings)
    audio_moderation_runtime = build_audio_moderation_runtime(
        settings=settings,
        openai_service=openai_service,
    )
    app.state.settings = settings
    app.state.audio_moderation_service = audio_moderation_runtime.service
    app.state.mana_ai_analysis_service = ManaAIAnalysisService(
        gateway=ManaAIOpenAIModelGateway(openai_service),
        clock=SystemManaAIClock(),
    )
    audio_moderation_runtime.start()
    try:
        yield
    finally:
        await audio_moderation_runtime.stop()
        await openai_service.close()


def create_app() -> FastAPI:
    settings = get_settings()
    validate_production_api_settings(settings)
    configure_application_logging(
        level=settings.log_level,
        secrets=[
            settings.openai_api_key.get_secret_value(),
            (
                settings.ai_audio_moderation_auth_token.get_secret_value()
                if settings.ai_audio_moderation_auth_token
                else ""
            ),
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
    app.state.request_rate_limiter = RequestRateLimiter(
        request_limit=settings.api_rate_limit_requests,
        window_seconds=settings.api_rate_limit_window_seconds,
    )
    app.add_exception_handler(
        RequestValidationError,
        sanitized_request_validation_handler,
    )
    app.middleware("http")(request_trace_middleware)
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=settings.mana_ai_max_request_body_bytes,
    )
    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=settings.audio_moderation_max_job_body_bytes,
        paths={"/api/v1/audio-moderation/jobs"},
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
        audio_moderation.router,
        prefix="/audio-moderation",
        tags=["audio-moderation"],
    )
    api_router.include_router(
        mana_ai.router,
        prefix="/mana-ai",
        tags=["mana-ai"],
        dependencies=[Depends(require_bearer_token)],
    )
    app.include_router(api_router, prefix="/api/v1")
    return app
