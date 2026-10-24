"""Trusted MANA-backend conversion events; neither mobile nor administrative tools."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.routes.mana_family_agents import ServiceDep, controlled, no_store
from app.api.security import require_backend_bearer_token
from app.mana_ai.application.conversion import ConversionService
from app.mana_ai.domain.chat import ParentChatId
from app.mana_ai.domain.conversion import (
    ConversionAdmission,
    ConversionOutcome,
    ConversionProposal,
    ConversionProposalPage,
    ConversionSnapshot,
)
from app.mana_ai.domain.conversion_accounts import ConversionAccountRead
from app.mana_ai.domain.conversion_grants import TrialAcceptance, TrialGrantState

router = APIRouter(
    prefix="/conversion-agent",
    tags=["mana-conversion"],
    dependencies=[Depends(require_backend_bearer_token), Depends(no_store)],
)


def get_conversion(service: ServiceDep) -> ConversionService:
    if service.conversion is None:
        raise HTTPException(status_code=503, detail={"code": "conversion_agent_disabled"})
    return service.conversion


ConversionDep = Annotated[ConversionService, Depends(get_conversion)]


@router.post(
    "/events",
    response_model=ConversionAdmission,
    status_code=202,
    summary="Observe verified adult-account subscription and activity facts",
    description="Backend-only MANA profile ID. Requires confirmed subscription state, dated "
    "parent activity and marketing consent, never raw child data. An identical event replays "
    "its original admission without reads or sends. Increasing revision and observation date "
    "are mandatory; GET/status never dispatch. A queued proposal is not a delivered offer. "
    "Only Parent-Touch may publish, after fresh eligibility and conversation priority checks.",
)
async def observe_account(
    service: ConversionDep, payload: ConversionSnapshot
) -> ConversionAdmission:
    return await controlled(service.observe(payload))


@router.get(
    "/source-observations/{event_id}",
    response_model=ConversionAccountRead,
    summary="Observe one durable account-source read without dispatch",
    description="Backend-only same-parent SQL receipt. GET, reconnect and replay never read "
    "Manakids, call a model, send push or retry a pending/unknown source request. "
    "A verified selected record is not contact consent or proof of paid conversion.",
)
async def source_observation(
    service: ConversionDep, event_id: UUID, parent_id: Annotated[ParentChatId, Query()]
) -> ConversionAccountRead:
    if service.accounts is None:
        raise HTTPException(status_code=503, detail={"code": "conversion_account_source_disabled"})
    return await controlled(service.accounts.observation(parent_id, event_id))


@router.get(
    "/proposals",
    response_model=ConversionProposalPage,
    summary="Observe a parent's conversion history",
)
async def proposals(
    service: ConversionDep,
    parent_id: Annotated[ParentChatId, Query()],
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ConversionProposalPage:
    return await controlled(service.proposals(parent_id, after=after, limit=limit))


@router.get(
    "/proposals/{proposal_id}",
    response_model=ConversionProposal,
    summary="Observe one same-family offer",
)
async def proposal(
    service: ConversionDep,
    proposal_id: UUID,
    parent_id: Annotated[ParentChatId, Query()],
) -> ConversionProposal:
    return await controlled(service.proposal(parent_id, proposal_id))


@router.post(
    "/outcomes",
    response_model=ConversionProposal,
    summary="Record an explicit parent reaction or verified payment receipt",
    description="Interest is not a purchase. Payment needs the exact billed offer/amount/currency "
    "and a unique billing receipt, after actual publication and within the offer's validity. "
    "Opt-out suppresses future offers permanently; snapshots cannot silently re-enable it. "
    "Never infer a payment or consent from chat text, current tariff, click or model output. "
    "This endpoint neither charges, grants a subscription, creates a discount nor sends push.",
)
async def outcome(service: ConversionDep, payload: ConversionOutcome) -> ConversionProposal:
    return await controlled(service.outcome(payload))


@router.post(
    "/trial-acceptances",
    response_model=TrialGrantState,
    summary="Accept one non-paid Maxsus tariff offer after explicit parent consent",
    description="Backend-only. Requires the parent's actual same-chat activation message "
    "and frozen offer. Days come from the approved catalog, never client/model fields. "
    "No payment, transaction or paid subscription is created. Exact replay observes "
    "the durable action and never repeats a provider call, including unknown outcomes.",
)
async def accept_trial(service: ConversionDep, payload: TrialAcceptance) -> TrialGrantState:
    if service.grants is None:
        raise HTTPException(status_code=503, detail={"code": "trial_grants_disabled"})
    return await controlled(service.grants.accept(payload))


@router.get(
    "/trial-grants",
    response_model=TrialGrantState,
    summary="Observe a parent's non-paid grant without provider calls or retry",
)
async def read_grant(
    service: ConversionDep, parent_id: Annotated[ParentChatId, Query()]
) -> TrialGrantState:
    if service.grants is None:
        raise HTTPException(status_code=503, detail={"code": "trial_grants_disabled"})
    return await controlled(service.grants.state(parent_id))
