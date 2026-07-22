import secrets
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Header, HTTPException, Request, status

from app.core.config import Settings
from app.mana_operation_ai.application.auth_service import AdminAuthService
from app.mana_operation_ai.domain.auth import AuthenticatedIdentity
from app.mana_operation_ai.domain.enums import AdminUserStatus, UserRole

SESSION_COOKIE_NAME = "mana_admin_session"
CSRF_COOKIE_NAME = "mana_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"


def get_auth_service(request: Request) -> AdminAuthService:
    service = getattr(request.app.state, "admin_auth_service", None)
    if not isinstance(service, AdminAuthService):
        raise HTTPException(status_code=503, detail="Authentication service is unavailable")
    return service


async def optional_session_identity(request: Request) -> AuthenticatedIdentity | None:
    service = get_auth_service(request)
    return await service.authenticate_session(request.cookies.get(SESSION_COOKIE_NAME))


async def require_session_identity(request: Request) -> AuthenticatedIdentity:
    identity = await optional_session_identity(request)
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return identity


async def require_admin_identity(request: Request) -> AuthenticatedIdentity:
    identity = await require_session_identity(request)
    if (
        identity.user.role is not UserRole.ADMIN
        or identity.user.status is not AdminUserStatus.ACTIVE
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator required")
    return identity


def require_csrf(
    request: Request,
    identity: AuthenticatedIdentity,
    supplied_token: str | None,
) -> None:
    validate_request_origin(request)
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if (
        supplied_token is None
        or cookie_token is None
        or not secrets.compare_digest(
            supplied_token,
            cookie_token,
        )
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    service = get_auth_service(request)
    if not service.validate_csrf(identity=identity, csrf_token=supplied_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


def validate_request_origin(request: Request) -> None:
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        raise HTTPException(status_code=500, detail="Application settings are unavailable")
    origin = request.headers.get("origin")
    if origin is None:
        if settings.is_secure_cookie_environment:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin is required")
        return
    normalized = _normalize_origin(origin)
    trusted = {_normalize_origin(item) for item in settings.mana_trusted_origins}
    if not trusted and settings.app_env in {"local", "development"}:
        parsed = urlsplit(normalized)
        if parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
            return
    if normalized not in trusted:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Untrusted origin")


def _normalize_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


AuthServiceDep = Annotated[AdminAuthService, Depends(get_auth_service)]
OptionalIdentityDep = Annotated[AuthenticatedIdentity | None, Depends(optional_session_identity)]
SessionIdentityDep = Annotated[AuthenticatedIdentity, Depends(require_session_identity)]
AdminIdentityDep = Annotated[AuthenticatedIdentity, Depends(require_admin_identity)]
CsrfHeader = Annotated[str | None, Header(alias=CSRF_HEADER_NAME)]
