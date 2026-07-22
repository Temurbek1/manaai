from fastapi import APIRouter

from app.mana_ai.domain.contracts import (
    ManaAICapabilitiesResponse,
    ManaAICapability,
    ManaAICapabilityInfo,
)

router = APIRouter()


@router.get(
    "/capabilities",
    response_model=ManaAICapabilitiesResponse,
    summary="List the payload-scoped MANA AI contracts",
)
async def list_capabilities() -> ManaAICapabilitiesResponse:
    return ManaAICapabilitiesResponse(
        capabilities=[
            ManaAICapabilityInfo(capability=capability, status="foundation")
            for capability in ManaAICapability
        ],
    )
