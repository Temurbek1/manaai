from fastapi import APIRouter, Depends

from app.api.routes import (
    ai,
    audio_moderation,
    health,
    mana_ai,
    mana_ai_chat,
    mana_child_safety,
    mana_conversion,
    mana_family_agents,
    mana_parent_proactive,
    marketing,
)
from app.api.security import require_bearer_token
from app.mana_operation_ai.api.auth_router import auth_router, users_router
from app.mana_operation_ai.api.router import router as operation_router

api_router = APIRouter()
api_router.include_router(mana_ai_chat.router, prefix="/mana-ai", tags=["mana-ai"])
api_router.include_router(mana_family_agents.router, prefix="/mana-ai", tags=["mana-ai"])
api_router.include_router(mana_child_safety.router, prefix="/mana-ai", tags=["mana-ai"])
api_router.include_router(mana_conversion.router, prefix="/mana-ai", tags=["mana-ai"])
api_router.include_router(mana_parent_proactive.router, prefix="/mana-ai", tags=["mana-ai"])
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(
    audio_moderation.router,
    prefix="/audio-moderation",
    tags=["audio-moderation"],
)
api_router.include_router(auth_router, prefix="/auth", tags=["authentication"])
api_router.include_router(users_router, prefix="/admin/users", tags=["admin-users"])
api_router.include_router(
    ai.router,
    prefix="/ai",
    tags=["ai"],
    dependencies=[Depends(require_bearer_token)],
)
api_router.include_router(
    operation_router,
    prefix="/admin/operation",
    tags=["operation-admin"],
)
api_router.include_router(
    marketing.router,
    prefix="/marketing",
    tags=["marketing"],
    dependencies=[Depends(require_bearer_token)],
)
api_router.include_router(
    mana_ai.router,
    prefix="/mana-ai",
    tags=["mana-ai"],
    dependencies=[Depends(require_bearer_token)],
)
