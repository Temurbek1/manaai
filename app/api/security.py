import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.core.auth_rate_limiter import AuthenticationRateLimiter
from app.core.config import Settings, get_settings

API_KEY_HEADER_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


async def require_api_key(
    request: Request,
    supplied_api_key: Annotated[str | None, Security(api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not settings.is_api_auth_required:
        return

    if not settings.is_app_api_key_configured or settings.app_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="APP_API_KEY must be configured when API authentication is required",
        )

    expected_api_key = settings.app_api_key.get_secret_value()
    client_key = request.client.host if request.client is not None else "unknown"
    limiter = request.app.state.auth_rate_limiter
    if not isinstance(limiter, AuthenticationRateLimiter):
        raise HTTPException(status_code=500, detail="Authentication limiter is unavailable")
    if supplied_api_key is None or not secrets.compare_digest(supplied_api_key, expected_api_key):
        retry_after = await limiter.record_failure(client_key)
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed authentication attempts",
                headers={"Retry-After": str(retry_after)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    await limiter.clear(client_key)
