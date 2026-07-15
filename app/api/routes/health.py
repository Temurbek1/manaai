from fastapi import APIRouter

from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter()


@router.get(
    "/live",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Returns service process liveness for container orchestration.",
)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="Returns readiness information for configured service dependencies.",
)
async def readiness() -> ReadinessResponse:
    return ReadinessResponse(status="ok", dependencies={"openai_config": "configured"})
