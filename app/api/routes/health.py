from fastapi import APIRouter, Request, Response, status

from app.core.config import get_settings
from app.mana_ai.application.audio_moderation import AudioModerationService
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter()


@router.get(
    "/live",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns service process liveness for container orchestration.",
)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="Returns readiness information for configured service dependencies.",
)
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    settings = get_settings()
    dependencies = {
        "openai_config": "configured" if settings.is_openai_configured else "missing",
        "audio_moderation": "disabled",
    }
    if settings.audio_moderation_enabled:
        service = getattr(request.app.state, "audio_moderation_service", None)
        dependencies["audio_moderation"] = (
            "ready"
            if isinstance(service, AudioModerationService) and service.is_running
            else "unavailable"
        )
    ready = dependencies["openai_config"] == "configured" and dependencies[
        "audio_moderation"
    ] not in {"unavailable"}
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ok" if ready else "unavailable",
        dependencies=dependencies,
    )
