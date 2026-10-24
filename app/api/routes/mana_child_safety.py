from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.routes.mana_family_agents import controlled, get_parent_touch_service, no_store
from app.api.security import require_backend_bearer_token
from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.chat import ParentChatId
from app.mana_ai.domain.child_safety import (
    SafetyAssessmentPage,
    SafetyBudget,
    SafetyJobState,
    SafetyJobView,
    SafetyTarget,
)
from app.mana_ai.domain.child_safety_api import (
    ChildSafetyAgreementRequest,
    ChildSafetyAgreementResponse,
    ChildSafetyAssistantAdmission,
    ChildSafetyAssistantReceipt,
    ChildSafetyBehaviourRequest,
    ChildSafetyBehaviourResponse,
    ChildSafetyContentRequest,
    ChildSafetyContentResponse,
    ChildSafetyFamilyDigestRequest,
    ChildSafetyFamilyDigestResponse,
    ChildSafetyGamingRequest,
    ChildSafetyGamingResponse,
    ChildSafetyLocationRequest,
    ChildSafetyLocationResponse,
    ChildSafetySafetyMonitorRequest,
    ChildSafetySafetyMonitorResponse,
    ChildSafetyScamRequest,
    ChildSafetyScamResponse,
    ChildSafetyScreenTimeRequest,
    ChildSafetyScreenTimeResponse,
)
from app.mana_ai.domain.requests import ManaAIRequest

router = APIRouter(
    prefix="/child-safety",
    tags=["mana-child-safety"],
    dependencies=[Depends(require_backend_bearer_token), Depends(no_store)],
)


def get_child_safety_service(
    touch: Annotated[ParentTouchService, Depends(get_parent_touch_service)],
) -> ChildSafetyService:
    if touch.safety is None:
        raise HTTPException(status_code=503, detail={"code": "child_safety_disabled"})
    return touch.safety


ServiceDep = Annotated[ChildSafetyService, Depends(get_child_safety_service)]
ADMISSION = (
    "Backend-only. Derive parent_id from the authenticated MANA profile; child_id must equal "
    "analysis.subject.subject_id. This admits a durable asynchronous job, not a verified result "
    "or a chat send. Ownership is checked freshly before model work under a separate explicit "
    "server budget. Reuse request_id and the identical body after transport loss. Unchanged "
    "observations coalesce even with a new nonce. Poll assessments; GET/replay never dispatches. "
    "Internal results cannot execute controls or speak to the parent; use Parent-Touch."
)


async def admit[ReceiptT: SafetyJobState](
    service: ChildSafetyService,
    target: SafetyTarget,
    analysis: ManaAIRequest,
    response_type: type[ReceiptT],
) -> ReceiptT:
    view = await controlled(service.admit(target, analysis))
    return response_type.model_validate(
        view.model_dump(exclude={"result"})
        | {
            "analysis": view.result.analysis.model_dump()
            if view.result and view.result.analysis
            else None,
            "question_id": view.result.question_id if view.result else None,
        }
    )


@router.get(
    "/assessments/{job_id}",
    response_model=SafetyJobView,
    summary="Observe one same-family assessment",
)
async def read_assessment(
    service: ServiceDep, job_id: UUID, parent_id: Annotated[ParentChatId, Query()]
) -> SafetyJobView:
    return await controlled(service.assessment(parent_id, job_id))


@router.get(
    "/assessments",
    response_model=SafetyAssessmentPage,
    summary="Page same-family safety jobs (SQL only)",
)
async def read_assessments(
    service: ServiceDep,
    parent_id: Annotated[ParentChatId, Query()],
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SafetyAssessmentPage:
    return await controlled(service.assessments(parent_id, after=after, limit=limit))


@router.get(
    "/budget", response_model=SafetyBudget, summary="Read safety tokens independently of chat quota"
)
async def read_budget(
    service: ServiceDep, parent_id: Annotated[ParentChatId, Query()]
) -> SafetyBudget:
    return await controlled(service.budget(parent_id))


@router.post(
    "/safety-monitor",
    response_model=ChildSafetySafetyMonitorResponse,
    status_code=202,
    description=ADMISSION,
)
async def safety_monitor(
    payload: ChildSafetySafetyMonitorRequest, service: ServiceDep
) -> ChildSafetySafetyMonitorResponse:
    return await admit(service, payload, payload.analysis, ChildSafetySafetyMonitorResponse)


@router.post(
    "/family-digest",
    response_model=ChildSafetyFamilyDigestResponse,
    status_code=202,
    description=ADMISSION,
)
async def family_digest(
    payload: ChildSafetyFamilyDigestRequest, service: ServiceDep
) -> ChildSafetyFamilyDigestResponse:
    return await admit(service, payload, payload.analysis, ChildSafetyFamilyDigestResponse)


@router.post(
    "/adaptive-screen-time",
    response_model=ChildSafetyScreenTimeResponse,
    status_code=202,
    description=ADMISSION,
)
async def screen_time(
    payload: ChildSafetyScreenTimeRequest, service: ServiceDep
) -> ChildSafetyScreenTimeResponse:
    return await admit(service, payload, payload.analysis, ChildSafetyScreenTimeResponse)


@router.post(
    "/location-intelligence",
    response_model=ChildSafetyLocationResponse,
    status_code=202,
    description=ADMISSION,
)
async def location(
    payload: ChildSafetyLocationRequest, service: ServiceDep
) -> ChildSafetyLocationResponse:
    return await admit(service, payload, payload.analysis, ChildSafetyLocationResponse)


@router.post(
    "/smart-content-filter",
    response_model=ChildSafetyContentResponse,
    status_code=202,
    description=ADMISSION,
)
async def content(
    payload: ChildSafetyContentRequest, service: ServiceDep
) -> ChildSafetyContentResponse:
    return await admit(service, payload, payload.analysis, ChildSafetyContentResponse)


@router.post(
    "/scam-privacy-shield",
    response_model=ChildSafetyScamResponse,
    status_code=202,
    description=ADMISSION,
)
async def scam(payload: ChildSafetyScamRequest, service: ServiceDep) -> ChildSafetyScamResponse:
    return await admit(service, payload, payload.analysis, ChildSafetyScamResponse)


@router.post(
    "/ai-gaming-safety",
    response_model=ChildSafetyGamingResponse,
    status_code=202,
    description=ADMISSION,
)
async def gaming(
    payload: ChildSafetyGamingRequest, service: ServiceDep
) -> ChildSafetyGamingResponse:
    return await admit(service, payload, payload.analysis, ChildSafetyGamingResponse)


@router.post(
    "/child-safety-assistant",
    response_model=ChildSafetyAssistantReceipt,
    status_code=202,
    description=ADMISSION,
)
async def assistant(
    payload: ChildSafetyAssistantAdmission, service: ServiceDep
) -> ChildSafetyAssistantReceipt:
    return await admit(service, payload, payload.analysis, ChildSafetyAssistantReceipt)


@router.post(
    "/family-agreement",
    response_model=ChildSafetyAgreementResponse,
    status_code=202,
    description=ADMISSION,
)
async def agreement(
    payload: ChildSafetyAgreementRequest, service: ServiceDep
) -> ChildSafetyAgreementResponse:
    return await admit(service, payload, payload.analysis, ChildSafetyAgreementResponse)


@router.post(
    "/behaviour-anomaly",
    response_model=ChildSafetyBehaviourResponse,
    status_code=202,
    description=ADMISSION,
)
async def behaviour(
    payload: ChildSafetyBehaviourRequest, service: ServiceDep
) -> ChildSafetyBehaviourResponse:
    return await admit(service, payload, payload.analysis, ChildSafetyBehaviourResponse)
