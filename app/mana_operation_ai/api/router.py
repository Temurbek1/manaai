import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from pydantic import JsonValue, ValidationError

from app.mana_operation_ai.api.dependencies import OperationAdminServiceDep
from app.mana_operation_ai.api.schemas import (
    AgentDetailResponse,
    AgentPage,
    AgentStatusRequest,
    ApprovalDecisionRequest,
    ApprovalLifecycleResponse,
    ApprovalPage,
    AuditPage,
    BulkApprovalDecisionRequest,
    ConfigurationCreateRequest,
    ConfigurationPage,
    DashboardAgent,
    DashboardResponse,
    ExecuteApprovedRequest,
    ExecutionPage,
    FindingPage,
    IntegrationHealthResponse,
    KillSwitchRequest,
    KillSwitchResponse,
    ManualRunAccepted,
    ProposalPage,
    RecommendationPage,
    ReportPage,
    RunDetailResponse,
    RunNowRequest,
    RunPage,
    SchedulePage,
    ScheduleUpdateRequest,
    WriteForbiddenDetail,
    WriteForbiddenResponse,
)
from app.mana_operation_ai.api.security import ActorDep, ActorResponse, require_role
from app.mana_operation_ai.application.action_lifecycle import (
    ActionReconciliationRequiredError,
    ActionSafetyError,
    ApprovalPermissionError,
    StaleProposalError,
)
from app.mana_operation_ai.application.admin_service import UnsafeBulkApprovalError
from app.mana_operation_ai.application.agent_service import (
    AgentRunLockedError,
    AgentUnavailableError,
)
from app.mana_operation_ai.application.ports import (
    ConcurrentOperationError,
    WriteOperationForbidden,
)
from app.mana_operation_ai.domain.enums import (
    ActionStatus,
    AgentRunStatus,
    AgentStatus,
    ApprovalStatus,
    IntegrationStatus,
    ProviderMode,
    UserRole,
)
from app.mana_operation_ai.domain.marketing import MarketingOverview
from app.mana_operation_ai.domain.models import (
    AgentConfiguration,
    AgentDefinition,
    AgentReport,
    AgentSchedule,
)

router = APIRouter()


@router.get(
    "/session",
    response_model=ActorResponse,
    summary="Resolve the authenticated operation actor",
)
async def operation_session(actor: ActorDep, request: Request) -> ActorResponse:
    require_role(actor, UserRole.VIEWER)
    provider = request.app.state.settings.operation_ads_provider
    provider_mode = (
        ProviderMode.LIVE_READ_ONLY if provider == "meta" else ProviderMode.FAKE_EXECUTABLE
    )
    return ActorResponse(
        actor_id=actor.actor_id,
        role=actor.role,
        ads_provider=provider,
        provider_mode=provider_mode,
        live_meta_read_only=provider_mode is ProviderMode.LIVE_READ_ONLY,
    )


@router.get(
    "/marketing/overview",
    response_model=MarketingOverview,
    summary="Get the current Marketing Agent operating view",
)
async def marketing_overview(
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> MarketingOverview:
    require_role(actor, UserRole.VIEWER)
    return await admin.marketing_overview()


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Get the operational-agent dashboard",
)
async def dashboard(
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> DashboardResponse:
    require_role(actor, UserRole.VIEWER)
    agents = await admin.repository.list_agents()
    pending_proposals, _ = await admin.repository.list_proposals(
        status=ActionStatus.AWAITING_APPROVAL,
        limit=10_000,
    )
    schedules = await admin.repository.list_schedules()
    dashboard_agents: list[DashboardAgent] = []
    for agent in agents:
        health_checks = await admin.agent_health(agent.agent_id)
        runs, total = await admin.repository.list_runs(agent_id=agent.agent_id, limit=100)
        completed = sum(item.status is AgentRunStatus.COMPLETED for item in runs)
        success_rate = "unavailable" if total == 0 else str(completed / min(total, 100))
        last = runs[0] if runs else None
        duration_ms = None
        if last is not None and last.completed_at is not None:
            duration_ms = max(int((last.completed_at - last.started_at).total_seconds() * 1_000), 0)
        next_run = min(
            (
                item.next_run_at
                for item in schedules
                if item.agent_id == agent.agent_id and item.enabled and item.next_run_at is not None
            ),
            default=None,
        )
        dashboard_agents.append(
            DashboardAgent(
                agent_id=agent.agent_id,
                display_name=agent.display_name,
                status=agent.status,
                health=(
                    health_checks[0].status if health_checks else IntegrationStatus.UNCONFIGURED
                ),
                last_run=last.started_at if last else None,
                next_run=next_run,
                last_duration_ms=duration_ms,
                success_rate=success_rate,
                pending_approvals=sum(
                    item.agent_id == agent.agent_id for item in pending_proposals
                ),
                recent_incidents=sum(item.status is AgentRunStatus.FAILED for item in runs),
            ),
        )
    return DashboardResponse(
        agents=dashboard_agents,
        global_kill_switch=await admin.repository.get_control("global_kill_switch"),
        generated_at=datetime.now(UTC),
    )


@router.get("/agents", response_model=AgentPage, summary="List registered agents")
async def list_agents(
    admin: OperationAdminServiceDep,
    actor: ActorDep,
    limit: int = Query(default=100, ge=1, le=1_000),
    offset: int = Query(default=0, ge=0),
    sort_by: Literal["agent_id", "display_name", "status"] = "agent_id",
    sort_order: Literal["asc", "desc"] = "asc",
) -> AgentPage:
    require_role(actor, UserRole.VIEWER)
    agents = await admin.repository.list_agents()
    agents.sort(
        key=lambda item: str(getattr(item, sort_by)).casefold(),
        reverse=sort_order == "desc",
    )
    return AgentPage(
        total=len(agents),
        limit=limit,
        offset=offset,
        items=agents[offset : offset + limit],
    )


@router.post(
    "/agents/{agent_id}/register",
    response_model=AgentDefinition,
    status_code=status.HTTP_201_CREATED,
    summary="Register an agent implementation loaded by the application",
)
async def register_agent(
    agent_id: str,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> AgentDefinition:
    require_role(actor, UserRole.ADMIN)
    try:
        return await admin.register_loaded_agent(agent_id=agent_id, actor=actor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/agents/{agent_id}", response_model=AgentDetailResponse, summary="Get an agent")
async def get_agent(
    agent_id: str,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> AgentDetailResponse:
    require_role(actor, UserRole.VIEWER)
    agent = await admin.repository.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent was not found")
    return AgentDetailResponse(
        agent=agent,
        configuration=await admin.repository.latest_configuration(agent_id),
        schedules=await admin.repository.list_schedules(agent_id),
        integration_health=await admin.agent_health(agent_id),
        kill_switch_enabled=await admin.repository.get_control(
            f"agent_kill_switch:{agent_id}",
        ),
    )


@router.post(
    "/agents/{agent_id}/status",
    response_model=AgentDefinition,
    summary="Change agent status",
)
async def set_agent_status(
    agent_id: str,
    payload: AgentStatusRequest,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> AgentDefinition:
    require_role(actor, UserRole.ADMIN)
    try:
        return await admin.set_agent_status(agent_id=agent_id, status=payload.status, actor=actor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/enable", response_model=AgentDefinition)
async def enable_agent(
    agent_id: str,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> AgentDefinition:
    require_role(actor, UserRole.ADMIN)
    try:
        return await admin.set_agent_status(
            agent_id=agent_id,
            status=AgentStatus.ENABLED,
            actor=actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/disable", response_model=AgentDefinition)
async def disable_agent(
    agent_id: str,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> AgentDefinition:
    require_role(actor, UserRole.ADMIN)
    try:
        return await admin.set_agent_status(
            agent_id=agent_id,
            status=AgentStatus.DISABLED,
            actor=actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/pause", response_model=AgentDefinition)
async def pause_agent(
    agent_id: str,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> AgentDefinition:
    require_role(actor, UserRole.ADMIN)
    try:
        return await admin.set_agent_status(
            agent_id=agent_id,
            status=AgentStatus.PAUSED,
            actor=actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/resume", response_model=AgentDefinition)
async def resume_agent(
    agent_id: str,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> AgentDefinition:
    require_role(actor, UserRole.ADMIN)
    try:
        return await admin.set_agent_status(
            agent_id=agent_id,
            status=AgentStatus.ENABLED,
            actor=actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/agents/{agent_id}/run",
    response_model=ManualRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run an agent job now",
)
async def run_agent_now(
    agent_id: str,
    payload: RunNowRequest,
    background_tasks: BackgroundTasks,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> ManualRunAccepted:
    require_role(actor, UserRole.OPERATOR)
    try:
        await admin.validate_run(agent_id)
        correlation_id = payload.correlation_id or admin.new_identifier()
        background_tasks.add_task(
            admin.run_in_background,
            agent_id=agent_id,
            job_type=payload.job_type,
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=payload.idempotency_key,
        )
        return ManualRunAccepted(
            agent_id=agent_id,
            job_type=payload.job_type,
            correlation_id=correlation_id,
        )
    except AgentUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AgentRunLockedError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc


@router.get("/runs", response_model=RunPage, summary="List agent runs")
async def list_runs(
    admin: OperationAdminServiceDep,
    actor: ActorDep,
    agent_id: str | None = None,
    run_status: Annotated[AgentRunStatus | None, Query(alias="status")] = None,
    limit: int = Query(default=100, ge=1, le=1_000),
    offset: int = Query(default=0, ge=0),
) -> RunPage:
    require_role(actor, UserRole.VIEWER)
    items, total = await admin.repository.list_runs(
        agent_id=agent_id,
        status=run_status,
        limit=limit,
        offset=offset,
    )
    return RunPage(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/runs/{run_id}",
    response_model=RunDetailResponse,
    summary="Get a run and its timeline",
)
async def get_run(
    run_id: str,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> RunDetailResponse:
    require_role(actor, UserRole.VIEWER)
    run = await admin.repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run was not found")
    audit, _ = await admin.repository.list_audit_events(run_id=run_id, limit=1_000)
    snapshots = await admin.repository.list_snapshots(run_id)
    findings, _ = await admin.repository.list_findings(run_id=run_id, limit=1_000)
    recommendations, _ = await admin.repository.list_recommendations(run_id=run_id, limit=1_000)
    proposals, _ = await admin.repository.list_proposals(run_id=run_id, limit=1_000)
    return RunDetailResponse(
        run=run,
        timeline=audit,
        snapshots=snapshots,
        findings=findings,
        recommendations=recommendations,
        proposals=proposals,
    )


@router.get("/agents/{agent_id}/configurations", response_model=ConfigurationPage)
async def list_configurations(
    agent_id: str,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> ConfigurationPage:
    require_role(actor, UserRole.VIEWER)
    items = await admin.repository.list_configurations(agent_id)
    return ConfigurationPage(total=len(items), limit=len(items) or 1, offset=0, items=items)


@router.get("/agents/{agent_id}/configuration-schema", response_model=dict[str, JsonValue])
async def configuration_schema(
    agent_id: str,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> dict[str, JsonValue]:
    require_role(actor, UserRole.VIEWER)
    agent = await admin.repository.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent was not found")
    return agent.configuration_schema


@router.post(
    "/agents/{agent_id}/configurations",
    response_model=AgentConfiguration,
    status_code=status.HTTP_201_CREATED,
)
async def create_configuration(
    agent_id: str,
    payload: ConfigurationCreateRequest,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> AgentConfiguration:
    require_role(actor, UserRole.ADMIN)
    try:
        return await admin.create_configuration(
            agent_id=agent_id,
            values=payload.values,
            actor=actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=json.loads(exc.json(include_url=False)),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConcurrentOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/schedules", response_model=SchedulePage)
async def list_schedules(
    admin: OperationAdminServiceDep,
    actor: ActorDep,
    agent_id: str | None = None,
) -> SchedulePage:
    require_role(actor, UserRole.VIEWER)
    items = await admin.repository.list_schedules(agent_id)
    return SchedulePage(total=len(items), limit=len(items) or 1, offset=0, items=items)


@router.put("/schedules/{schedule_id}", response_model=AgentSchedule)
async def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdateRequest,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> AgentSchedule:
    require_role(actor, UserRole.ADMIN)
    try:
        return await admin.update_schedule(
            schedule_id=schedule_id,
            cron_expression=payload.cron_expression,
            timezone=payload.timezone,
            enabled=payload.enabled,
            actor=actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConcurrentOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/findings", response_model=FindingPage)
async def list_findings(
    admin: OperationAdminServiceDep,
    actor: ActorDep,
    run_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1_000),
    offset: int = Query(default=0, ge=0),
) -> FindingPage:
    require_role(actor, UserRole.VIEWER)
    items, total = await admin.repository.list_findings(run_id=run_id, limit=limit, offset=offset)
    return FindingPage(total=total, limit=limit, offset=offset, items=items)


@router.get("/recommendations", response_model=RecommendationPage)
async def list_recommendations(
    admin: OperationAdminServiceDep,
    actor: ActorDep,
    run_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1_000),
    offset: int = Query(default=0, ge=0),
) -> RecommendationPage:
    require_role(actor, UserRole.VIEWER)
    items, total = await admin.repository.list_recommendations(
        run_id=run_id,
        limit=limit,
        offset=offset,
    )
    return RecommendationPage(total=total, limit=limit, offset=offset, items=items)


@router.get("/action-proposals", response_model=ProposalPage)
async def list_action_proposals(
    admin: OperationAdminServiceDep,
    actor: ActorDep,
    run_id: str | None = None,
    proposal_status: Annotated[ActionStatus | None, Query(alias="status")] = None,
    limit: int = Query(default=100, ge=1, le=1_000),
    offset: int = Query(default=0, ge=0),
) -> ProposalPage:
    require_role(actor, UserRole.VIEWER)
    items, total = await admin.repository.list_proposals(
        run_id=run_id,
        status=proposal_status,
        limit=limit,
        offset=offset,
    )
    return ProposalPage(total=total, limit=limit, offset=offset, items=items)


@router.get("/approvals", response_model=ApprovalPage)
async def list_approvals(
    admin: OperationAdminServiceDep,
    actor: ActorDep,
    approval_status: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
    limit: int = Query(default=100, ge=1, le=1_000),
    offset: int = Query(default=0, ge=0),
) -> ApprovalPage:
    require_role(actor, UserRole.VIEWER)
    items, total = await admin.repository.list_approvals(
        status=approval_status,
        limit=limit,
        offset=offset,
    )
    return ApprovalPage(total=total, limit=limit, offset=offset, items=items)


@router.post("/approvals/{proposal_id}/decision", response_model=ApprovalLifecycleResponse)
async def decide_approval(
    proposal_id: str,
    payload: ApprovalDecisionRequest,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> ApprovalLifecycleResponse:
    require_role(actor, UserRole.APPROVER)
    try:
        lifecycle, run = await admin.decide_approval(
            proposal_id=proposal_id,
            approve=payload.approve,
            reason=payload.reason,
            actor=actor,
            correlation_id=payload.correlation_id,
        )
    except ApprovalPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StaleProposalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ActionSafetyError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except ActionReconciliationRequiredError as exc:
        raise HTTPException(status_code=202, detail=str(exc)) from exc
    except ConcurrentOperationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WriteOperationForbidden as exc:
        raise _write_forbidden_http_exception(exc) from exc
    return ApprovalLifecycleResponse(
        proposal=lifecycle.proposal,
        approval_decision=lifecycle.approval_decision,
        execution=lifecycle.execution,
        verification=lifecycle.verification,
        run=run,
    )


@router.post("/approvals/bulk-decision", response_model=list[ApprovalLifecycleResponse])
async def bulk_decide_approval(
    payload: BulkApprovalDecisionRequest,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> list[ApprovalLifecycleResponse]:
    require_role(actor, UserRole.APPROVER)
    try:
        results = await admin.bulk_decide(
            proposal_ids=payload.proposal_ids,
            approve=payload.approve,
            reason=payload.reason,
            actor=actor,
            correlation_id=payload.correlation_id,
        )
    except UnsafeBulkApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ApprovalPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ActionReconciliationRequiredError as exc:
        raise HTTPException(status_code=202, detail=str(exc)) from exc
    except (StaleProposalError, ActionSafetyError, ConcurrentOperationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WriteOperationForbidden as exc:
        raise _write_forbidden_http_exception(exc) from exc
    return [
        ApprovalLifecycleResponse(
            proposal=lifecycle.proposal,
            approval_decision=lifecycle.approval_decision,
            execution=lifecycle.execution,
            verification=lifecycle.verification,
            run=run,
        )
        for lifecycle, run in results
    ]


@router.get("/executions", response_model=ExecutionPage)
async def list_executions(
    admin: OperationAdminServiceDep,
    actor: ActorDep,
    agent_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1_000),
    offset: int = Query(default=0, ge=0),
) -> ExecutionPage:
    require_role(actor, UserRole.VIEWER)
    items, total = await admin.repository.list_executions(
        agent_id=agent_id,
        limit=limit,
        offset=offset,
    )
    return ExecutionPage(total=total, limit=limit, offset=offset, items=items)


@router.post(
    "/action-proposals/{proposal_id}/execute",
    response_model=ApprovalLifecycleResponse,
    responses={403: {"model": WriteForbiddenResponse}},
    summary="Execute an already approved proposal after rechecking all safeguards",
)
async def execute_approved_proposal(
    proposal_id: str,
    payload: ExecuteApprovedRequest,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> ApprovalLifecycleResponse:
    require_role(actor, UserRole.APPROVER)
    try:
        lifecycle, run = await admin.execute_approved(
            proposal_id=proposal_id,
            actor=actor,
            correlation_id=payload.correlation_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StaleProposalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ActionSafetyError as exc:
        raise HTTPException(status_code=423, detail=str(exc)) from exc
    except ActionReconciliationRequiredError as exc:
        raise HTTPException(status_code=202, detail=str(exc)) from exc
    except WriteOperationForbidden as exc:
        raise _write_forbidden_http_exception(exc) from exc
    return ApprovalLifecycleResponse(
        proposal=lifecycle.proposal,
        approval_decision=lifecycle.approval_decision,
        execution=lifecycle.execution,
        verification=lifecycle.verification,
        run=run,
    )


def _write_forbidden_http_exception(exc: WriteOperationForbidden) -> HTTPException:
    detail = WriteForbiddenDetail(message=str(exc))
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail.model_dump())


@router.get("/reports", response_model=ReportPage)
async def list_reports(
    admin: OperationAdminServiceDep,
    actor: ActorDep,
    agent_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1_000),
    offset: int = Query(default=0, ge=0),
) -> ReportPage:
    require_role(actor, UserRole.VIEWER)
    items, total = await admin.repository.list_reports(
        agent_id=agent_id,
        limit=limit,
        offset=offset,
    )
    return ReportPage(total=total, limit=limit, offset=offset, items=items)


@router.get("/reports/{report_id}", response_model=AgentReport)
async def get_report(
    report_id: str,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> AgentReport:
    require_role(actor, UserRole.VIEWER)
    report = await admin.repository.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report was not found")
    return report


@router.get(
    "/integrations/{provider}/health",
    response_model=IntegrationHealthResponse,
)
async def integration_health(
    provider: str,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> IntegrationHealthResponse:
    require_role(actor, UserRole.VIEWER)
    try:
        return await admin.integration_health(provider)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/audit-events", response_model=AuditPage)
async def list_audit_events(
    admin: OperationAdminServiceDep,
    actor: ActorDep,
    correlation_id: str | None = None,
    run_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=2_000),
    offset: int = Query(default=0, ge=0),
) -> AuditPage:
    require_role(actor, UserRole.VIEWER)
    items, total = await admin.repository.list_audit_events(
        correlation_id=correlation_id,
        run_id=run_id,
        limit=limit,
        offset=offset,
    )
    return AuditPage(total=total, limit=limit, offset=offset, items=items)


@router.put("/kill-switch/global", response_model=KillSwitchResponse)
async def global_kill_switch(
    payload: KillSwitchRequest,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> KillSwitchResponse:
    require_role(actor, UserRole.ADMIN)
    await admin.set_kill_switch(agent_id=None, enabled=payload.enabled, actor=actor)
    return KillSwitchResponse(scope="global", enabled=payload.enabled)


@router.put("/kill-switch/agents/{agent_id}", response_model=KillSwitchResponse)
async def agent_kill_switch(
    agent_id: str,
    payload: KillSwitchRequest,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> KillSwitchResponse:
    require_role(actor, UserRole.ADMIN)
    await admin.set_kill_switch(agent_id=agent_id, enabled=payload.enabled, actor=actor)
    return KillSwitchResponse(scope=agent_id, enabled=payload.enabled)
