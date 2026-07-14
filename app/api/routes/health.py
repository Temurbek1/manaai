from fastapi import APIRouter

from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter()


@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadinessResponse)
async def readiness() -> ReadinessResponse:
    return ReadinessResponse(status="ok", dependencies={"openai_config": "configured"})
