import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from app.core.auth_rate_limiter import AuthenticationRateLimiter
from app.core.config import Settings
from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.domain.enums import ProviderMode, UserRole


class ActorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str
    role: UserRole
    ads_provider: str
    provider_mode: ProviderMode
    live_meta_read_only: bool


ROLE_RANK = {
    UserRole.VIEWER: 0,
    UserRole.OPERATOR: 1,
    UserRole.APPROVER: 2,
    UserRole.ADMIN: 3,
}


async def resolve_actor(
    request: Request,
    supplied_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    supplied_actor_id: Annotated[str | None, Header(alias="X-MANA-Actor-ID")] = None,
    supplied_role: Annotated[str | None, Header(alias="X-MANA-Role")] = None,
) -> ActorContext:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise HTTPException(status_code=500, detail="Application settings are unavailable")
    actor_id = supplied_actor_id or settings.operation_default_actor_id
    if settings.app_env == "production":
        role = _production_role(settings, supplied_api_key)
        if role is None:
            client_key = request.client.host if request.client is not None else "unknown"
            limiter = request.app.state.auth_rate_limiter
            if not isinstance(limiter, AuthenticationRateLimiter):
                raise HTTPException(status_code=500, detail="Authentication limiter is unavailable")
            retry_after = await limiter.record_failure(client_key)
            if retry_after is not None:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many failed authentication attempts",
                    headers={"Retry-After": str(retry_after)},
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing internal operation API key",
            )
        client_key = request.client.host if request.client is not None else "unknown"
        limiter = request.app.state.auth_rate_limiter
        if isinstance(limiter, AuthenticationRateLimiter):
            await limiter.clear(client_key)
        return ActorContext(actor_id=f"internal-{role.value}", role=role)
    try:
        role = UserRole(supplied_role or settings.operation_default_role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid X-MANA-Role") from exc
    return ActorContext(actor_id=actor_id, role=role)


def require_role(actor: ActorContext, minimum: UserRole) -> None:
    if ROLE_RANK[actor.role] < ROLE_RANK[minimum]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"The {minimum.value} role is required",
        )


def _production_role(settings: Settings, supplied_api_key: str | None) -> UserRole | None:
    if supplied_api_key is None:
        return None
    candidates = [
        (UserRole.ADMIN, settings.operation_admin_api_key),
        (UserRole.APPROVER, settings.operation_approver_api_key),
        (UserRole.OPERATOR, settings.operation_operator_api_key),
        (UserRole.VIEWER, settings.operation_viewer_api_key),
        (UserRole.ADMIN, settings.app_api_key),
    ]
    for role, secret in candidates:
        if secret is not None and secrets.compare_digest(
            supplied_api_key,
            secret.get_secret_value(),
        ):
            return role
    return None


ActorDep = Annotated[ActorContext, Depends(resolve_actor)]
