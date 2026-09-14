import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.mana_ai.application.audio_moderation import (
    AudioModerationQueueFullError,
    AudioModerationService,
    AudioModerationSubmissionError,
    AudioModerationUnavailableError,
)
from app.mana_ai.domain.audio_moderation import (
    AudioModerationAcceptedResponse,
    AudioModerationJobRequest,
)

router = APIRouter()

audio_moderation_bearer = HTTPBearer(
    scheme_name="AudioModerationBearerToken",
    description="Send AI_AUDIO_MODERATION_AUTH_TOKEN as a bearer token.",
    auto_error=False,
)


async def require_audio_moderation_token(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(audio_moderation_bearer),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    expected = settings.ai_audio_moderation_auth_token
    if not settings.audio_moderation_enabled or expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio moderation is not enabled",
        )
    supplied = credentials.credentials if credentials is not None else None
    if supplied is None or not secrets.compare_digest(supplied, expected.get_secret_value()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_audio_moderation_service(request: Request) -> AudioModerationService:
    service = getattr(request.app.state, "audio_moderation_service", None)
    if not isinstance(service, AudioModerationService):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio moderation worker is unavailable",
        )
    return service


@router.post(
    "/jobs",
    response_model=AudioModerationAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_audio_moderation_token)],
    responses={
        400: {"description": "The URLs violate the configured safety policy."},
        401: {"description": "The shared service token is missing or invalid."},
        422: {"description": "The job payload is invalid."},
        503: {"description": "The service is paused, unavailable, or at capacity."},
    },
)
async def submit_audio_moderation_job(
    payload: AudioModerationJobRequest,
    service: Annotated[AudioModerationService, Depends(get_audio_moderation_service)],
) -> AudioModerationAcceptedResponse:
    try:
        return await service.submit(payload)
    except AudioModerationSubmissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except AudioModerationQueueFullError:
        raise HTTPException(
            status_code=503,
            detail="Audio moderation is at capacity",
            headers={"Retry-After": "60"},
        ) from None
    except AudioModerationUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Audio moderation worker is unavailable",
        ) from None
