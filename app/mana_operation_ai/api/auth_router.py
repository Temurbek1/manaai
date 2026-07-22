from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.config import Settings
from app.mana_operation_ai.api.auth_schemas import (
    AdminUserResponse,
    AuthAuditEventResponse,
    AuthAuditPage,
    AuthSessionResponse,
    CreateAdminUserRequest,
    RequestCodeResponse,
    SessionRevocationResponse,
    SessionUserResponse,
    TelegramCodeRequest,
    TelegramIdentityRequest,
    UpdateAdminUserRequest,
    UserPage,
)
from app.mana_operation_ai.api.auth_security import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    AdminIdentityDep,
    AuthServiceDep,
    CsrfHeader,
    OptionalIdentityDep,
    SessionIdentityDep,
    require_csrf,
    validate_request_origin,
)
from app.mana_operation_ai.application.auth_service import (
    AuthenticationError,
    AuthenticationUnavailableError,
    UserManagementError,
)
from app.mana_operation_ai.domain.enums import ProviderMode

auth_router = APIRouter()
users_router = APIRouter()


@auth_router.post(
    "/telegram/request-code",
    response_model=RequestCodeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a Telegram one-time login code",
)
async def request_telegram_code(
    payload: TelegramIdentityRequest,
    request: Request,
    service: AuthServiceDep,
) -> RequestCodeResponse:
    validate_request_origin(request)
    try:
        result = await service.request_code(
            telegram_id=payload.telegram_id,
            client_ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except AuthenticationUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Telegram authentication is unavailable"
        ) from exc
    except AuthenticationError as exc:
        raise _authentication_http_error(exc) from exc
    return RequestCodeResponse.model_validate(result)


@auth_router.post(
    "/telegram/verify-code",
    response_model=AuthSessionResponse,
    summary="Verify a Telegram one-time code and establish a session",
)
async def verify_telegram_code(
    payload: TelegramCodeRequest,
    request: Request,
    response: Response,
    service: AuthServiceDep,
) -> AuthSessionResponse:
    validate_request_origin(request)
    try:
        issued = await service.verify_code(
            telegram_id=payload.telegram_id,
            code=payload.code,
            client_ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            old_session_token=request.cookies.get(SESSION_COOKIE_NAME),
        )
    except AuthenticationUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Telegram authentication is unavailable"
        ) from exc
    except AuthenticationError as exc:
        raise _authentication_http_error(exc) from exc
    settings = _settings(request)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=issued.session_token,
        max_age=settings.mana_session_ttl_seconds,
        secure=settings.is_secure_cookie_environment,
        httponly=True,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=issued.csrf_token,
        max_age=settings.mana_session_ttl_seconds,
        secure=settings.is_secure_cookie_environment,
        httponly=False,
        samesite="lax",
        path="/",
    )
    return _session_response(request, issued.identity)


@auth_router.get(
    "/session",
    response_model=AuthSessionResponse,
    summary="Read the current administrative browser session",
)
async def auth_session(
    request: Request,
    identity: OptionalIdentityDep,
) -> AuthSessionResponse:
    if identity is None:
        return AuthSessionResponse(authenticated=False)
    return _session_response(request, identity)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    identity: SessionIdentityDep,
    csrf_token: CsrfHeader = None,
) -> None:
    require_csrf(request, identity, csrf_token)
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    await service.logout(
        identity=identity,
        session_token=session_token,
        request_ip=_client_ip(request),
    )
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=_settings(request).is_secure_cookie_environment,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME,
        path="/",
        secure=_settings(request).is_secure_cookie_environment,
        httponly=False,
        samesite="lax",
    )


@users_router.get("", response_model=UserPage, summary="List administrative users")
async def list_users(service: AuthServiceDep, identity: AdminIdentityDep) -> UserPage:
    del identity
    users = await service.list_users()
    return UserPage(items=[_user_response(user) for user in users], total=len(users))


@users_router.post(
    "",
    response_model=AdminUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant administrative-panel access to a Telegram identity",
)
async def create_user(
    payload: CreateAdminUserRequest,
    request: Request,
    service: AuthServiceDep,
    identity: AdminIdentityDep,
    csrf_token: CsrfHeader = None,
) -> AdminUserResponse:
    require_csrf(request, identity, csrf_token)
    try:
        user = await service.create_user(
            actor=identity.user,
            telegram_id=payload.telegram_id,
            role=payload.role,
            display_name=payload.display_name,
            username=payload.username,
        )
    except UserManagementError as exc:
        raise _user_management_http_error(exc) from exc
    return _user_response(user)


@users_router.patch(
    "/{user_id}",
    response_model=AdminUserResponse,
    summary="Change an administrative user's role or access status",
)
async def update_user(
    user_id: str,
    payload: UpdateAdminUserRequest,
    request: Request,
    service: AuthServiceDep,
    identity: AdminIdentityDep,
    csrf_token: CsrfHeader = None,
) -> AdminUserResponse:
    require_csrf(request, identity, csrf_token)
    try:
        user = await service.update_user_access(
            actor=identity.user,
            user_id=user_id,
            role=payload.role,
            status=payload.status,
            disabled_reason=payload.disabled_reason,
            display_name=payload.display_name,
            username=payload.username,
            update_display_name="display_name" in payload.model_fields_set,
            update_username="username" in payload.model_fields_set,
        )
    except UserManagementError as exc:
        raise _user_management_http_error(exc) from exc
    return _user_response(user)


@users_router.post(
    "/{user_id}/sessions/revoke",
    response_model=SessionRevocationResponse,
    summary="Revoke all active sessions for an administrative user",
)
async def revoke_user_sessions(
    user_id: str,
    request: Request,
    service: AuthServiceDep,
    identity: AdminIdentityDep,
    csrf_token: CsrfHeader = None,
) -> SessionRevocationResponse:
    require_csrf(request, identity, csrf_token)
    try:
        count = await service.revoke_user_sessions(actor=identity.user, user_id=user_id)
    except UserManagementError as exc:
        raise _user_management_http_error(exc) from exc
    return SessionRevocationResponse(revoked_sessions=count)


@users_router.get(
    "/{user_id}/audit",
    response_model=AuthAuditPage,
    summary="Read security audit events for an administrative user",
)
async def user_audit(
    user_id: str,
    service: AuthServiceDep,
    identity: AdminIdentityDep,
) -> AuthAuditPage:
    try:
        events = await service.list_user_audit(actor=identity.user, user_id=user_id)
    except UserManagementError as exc:
        raise _user_management_http_error(exc) from exc
    items = [AuthAuditEventResponse.model_validate(event) for event in events]
    return AuthAuditPage(items=items, total=len(items))


def _settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if not isinstance(settings, Settings):
        raise HTTPException(status_code=500, detail="Application settings are unavailable")
    return settings


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _user_response(user: object) -> AdminUserResponse:
    return AdminUserResponse.model_validate(user)


def _session_response(request: Request, identity: object) -> AuthSessionResponse:
    from app.mana_operation_ai.domain.auth import AuthenticatedIdentity

    if not isinstance(identity, AuthenticatedIdentity):
        raise TypeError("Authenticated identity is required")
    settings = _settings(request)
    provider_mode = (
        ProviderMode.LIVE_READ_ONLY
        if settings.operation_ads_provider == "meta"
        else ProviderMode.FAKE_EXECUTABLE
    )
    return AuthSessionResponse(
        authenticated=True,
        user=SessionUserResponse(
            user_id=identity.user.user_id,
            telegram_id=identity.user.telegram_id,
            display_name=identity.user.display_name,
            username=identity.user.username,
            role=identity.user.role,
            permissions=_role_permissions(identity.user.role.value),
        ),
        expires_at=identity.session.expires_at,
        ads_provider=settings.operation_ads_provider,
        provider_mode=provider_mode.value,
        live_meta_read_only=provider_mode is ProviderMode.LIVE_READ_ONLY,
    )


def _role_permissions(role: str) -> list[str]:
    permissions = ["view"]
    if role in {"operator", "approver", "admin"}:
        permissions.append("operate")
    if role in {"approver", "admin"}:
        permissions.append("approve")
    if role == "admin":
        permissions.append("administer")
    return permissions


def _authentication_http_error(exc: AuthenticationError) -> HTTPException:
    statuses = {
        "rate_limited": status.HTTP_429_TOO_MANY_REQUESTS,
        "temporarily_locked": status.HTTP_429_TOO_MANY_REQUESTS,
        "invalid_code": status.HTTP_401_UNAUTHORIZED,
        "invalid_or_expired_code": status.HTTP_401_UNAUTHORIZED,
        "invalid_or_reused_code": status.HTTP_401_UNAUTHORIZED,
        "expired_code": status.HTTP_401_UNAUTHORIZED,
        "attempts_exhausted": status.HTTP_401_UNAUTHORIZED,
    }
    headers = (
        {"Retry-After": str(exc.retry_after_seconds)}
        if exc.retry_after_seconds is not None
        else None
    )
    return HTTPException(
        status_code=statuses.get(exc.code, status.HTTP_401_UNAUTHORIZED),
        detail=exc.code,
        headers=headers,
    )


def _user_management_http_error(exc: UserManagementError) -> HTTPException:
    statuses = {
        "admin_required": status.HTTP_403_FORBIDDEN,
        "self_access_change_forbidden": status.HTTP_409_CONFLICT,
        "last_active_admin": status.HTTP_409_CONFLICT,
        "telegram_id_already_exists": status.HTTP_409_CONFLICT,
        "user_not_found": status.HTTP_404_NOT_FOUND,
    }
    return HTTPException(status_code=statuses.get(exc.code, 400), detail=exc.code)
