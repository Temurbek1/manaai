from fastapi import APIRouter, Depends

from app.api.routes import ai, health, marketing
from app.api.security import require_api_key

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(
    ai.router,
    prefix="/ai",
    tags=["ai"],
    dependencies=[Depends(require_api_key)],
)
api_router.include_router(
    marketing.router,
    prefix="/marketing",
    tags=["marketing"],
    dependencies=[Depends(require_api_key)],
)
