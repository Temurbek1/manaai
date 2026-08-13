from fastapi import APIRouter, Depends

from app.api.routes import ai, health, mana_ai, marketing
from app.api.security import require_bearer_token
from app.mana_operation_ai.api.auth_router import auth_router, users_router
from app.mana_operation_ai.api.router import router as operation_router

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
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
