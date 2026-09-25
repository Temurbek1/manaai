import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth_rate_limiter import AuthenticationRateLimiter
from app.core.config import Settings, get_settings
from app.core.rate_limiter import RequestRateLimiter

bearer_scheme = HTTPBearer(
    scheme_name="BearerToken",
    description="Send APP_API_KEY as `Authorization: Bearer <token>`.",
    auto_error=False,
)


async def require_bearer_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not settings.is_api_auth_required:
        return

    if not settings.is_app_api_key_configured or settings.app_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="APP_API_KEY must be configured when API authentication is required",
        )

    expected_token = settings.app_api_key.get_secret_value()
    client_key = request.client.host if request.client is not None else "unknown"
    limiter = request.app.state.auth_rate_limiter
    if not isinstance(limiter, AuthenticationRateLimiter):
        raise HTTPException(status_code=500, detail="Authentication limiter is unavailable")

    supplied_token = credentials.credentials if credentials is not None else None
    if supplied_token is None or not secrets.compare_digest(supplied_token, expected_token):
        retry_after = await limiter.record_failure(client_key)
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed authentication attempts",
                headers={"Retry-After": str(retry_after)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    await limiter.clear(client_key)
    await _enforce_request_budget(request, client_key)


async def _enforce_request_budget(request: Request, client_key: str) -> None:
    rate_limiter = getattr(request.app.state, "request_rate_limiter", None)
    if not isinstance(rate_limiter, RequestRateLimiter):
        raise HTTPException(status_code=500, detail="Request rate limiter is unavailable")
    retry_after = await rate_limiter.consume(client_key)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Request rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
