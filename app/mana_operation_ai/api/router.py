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
    description=(
        "Returns the actor identifier and role resolved from the request credentials, together "
        "with the configured ads provider and its mode. Requires at least the `viewer` role. "
        "When `live_meta_read_only` is `true` the provider is LIVE Meta and every write "
        "execution is refused with 403."
    ),
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
    description=(
        "Returns the latest Marketing Agent picture: freshly probed integration health for the "
        "default ads provider, the most recent stored ads snapshot with its per-breakdown "
        "performance, the active configuration and the agent schedules. Requires at least the "
        "`viewer` role. The snapshot fields stay `null` until a run has stored ads data."
    ),
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
    description=(
        "Returns one summary row per registered agent (health, last and next run, last run "
        "duration, success rate over the 100 most recent runs, pending approvals and recent "
        "failures) plus the current global kill-switch state. Requires at least the `viewer` "
        "role. `success_rate` is the literal string `unavailable` while an agent has no runs."
    ),
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


@router.get(
    "/agents",
    response_model=AgentPage,
    summary="List registered agents",
    description=(
        "Returns the registered agent definitions ordered by `sort_by` and `sort_order`, then "
        "paginated with `limit` and `offset`. Requires at least the `viewer` role. Sorting and "
        "pagination happen in memory, so `total` always reports the size of the whole catalog."
    ),
)
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
    description=(
        "Copies an agent implementation loaded by this process into the operational catalog, "
        "records an `agent_registered` audit event and returns the stored definition with 201. "
        "Requires the `admin` role. Returns 404 when no implementation is loaded under that "
        "identifier."
    ),
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


@router.get(
    "/agents/{agent_id}",
    response_model=AgentDetailResponse,
    summary="Get an agent",
    description=(
        "Returns the agent definition together with its latest configuration, its schedules, a "
        "freshly probed integration health report and the state of its dedicated kill switch. "
        "Requires at least the `viewer` role. Returns 404 when the agent is not in the catalog."
    ),
)
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
    description=(
        "Sets the agent lifecycle status to the value in the body and records an "
        "`agent_status_changed` audit event. Requires the `admin` role. Returns 404 when the "
        "agent is not in the catalog."
    ),
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


@router.post(
    "/agents/{agent_id}/enable",
    response_model=AgentDefinition,
    summary="Enable an agent",
    description=(
        "Shortcut that sets the agent status to `enabled`, the only status in which scheduled "
        "and manual runs are accepted, and records an audit event. Requires the `admin` role. "
        "Returns 404 when the agent is not in the catalog."
    ),
)
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


@router.post(
    "/agents/{agent_id}/disable",
    response_model=AgentDefinition,
    summary="Disable an agent",
    description=(
        "Shortcut that sets the agent status to `disabled`, after which scheduled and manual "
        "runs are refused until the agent is enabled again. Requires the `admin` role. Returns "
        "404 when the agent is not in the catalog."
    ),
)
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


@router.post(
    "/agents/{agent_id}/pause",
    response_model=AgentDefinition,
    summary="Pause an agent",
    description=(
        "Shortcut that sets the agent status to `paused`; while it is paused a manual run "
        "request is rejected with 409. Requires the `admin` role. Returns 404 when the agent is "
        "not in the catalog."
    ),
)
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


@router.post(
    "/agents/{agent_id}/resume",
    response_model=AgentDefinition,
    summary="Resume a paused agent",
    description=(
        "Shortcut that sets the agent status back to `enabled` after a pause or a disable. "
        "Requires the `admin` role. Returns 404 when the agent is not in the catalog."
    ),
)
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
    description=(
        "Checks that the agent is enabled, has a configuration and is not blocked by a kill "
        "switch, then queues the job as a background task and answers 202 with the correlation "
        "identifier the run will use; the run itself is not awaited. Requires at least the "
        "`operator` role. Send `idempotency_key` so a retried request joins the existing run "
        "instead of starting a second one. Returns 409 when the agent is unavailable (disabled, "
        "unconfigured or killed). A 202 response confirms acceptance, not successful completion; "
        "inspect the run history for background lock, timeout, provider, or analysis failures."
    ),
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


@router.get(
    "/runs",
    response_model=RunPage,
    summary="List agent runs",
    description=(
        "Returns agent runs newest first, optionally filtered by `agent_id` and by `status`, "
        "paginated with `limit` and `offset`. Requires at least the `viewer` role. `total` "
        "counts every run matching the filters, not just the returned page."
    ),
)
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
    description=(
        "Returns the run with its audit timeline, stored data snapshots, findings, "
        "recommendations and action proposals in a single payload. Requires at least the "
        "`viewer` role. Each related collection is capped at its 1000 most recent entries. "
        "Returns 404 when the run identifier is unknown."
    ),
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


@router.get(
    "/agents/{agent_id}/configurations",
    response_model=ConfigurationPage,
    summary="List agent configuration versions",
    description=(
        "Returns every stored configuration version of the agent, highest version first. "
        "Requires at least the `viewer` role. This endpoint is not paginated: the full history "
        "is returned in one response and `limit` merely mirrors the number of items."
    ),
)
async def list_configurations(
    agent_id: str,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> ConfigurationPage:
    require_role(actor, UserRole.VIEWER)
    items = await admin.repository.list_configurations(agent_id)
    return ConfigurationPage(total=len(items), limit=len(items) or 1, offset=0, items=items)


@router.get(
    "/agents/{agent_id}/configuration-schema",
    response_model=dict[str, JsonValue],
    summary="Get the agent configuration schema",
    description=(
        "Returns the JSON Schema that a configuration payload for this agent must satisfy; use "
        "it to build and pre-validate the body sent to the configuration creation endpoint. "
        "Requires at least the `viewer` role. Returns 404 when the agent is not in the catalog."
    ),
)
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
    summary="Create an agent configuration version",
    description=(
        "Validates the submitted values against the agent configuration schema, stores them as "
        "the next version, rebuilds the schedules derived from that configuration and returns "
        "the new version with 201. Requires the `admin` role. Returns 404 for an unknown agent, "
        "422 when the values fail validation, and 409 when a concurrent write already created "
        "that version."
    ),
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


@router.get(
    "/schedules",
    response_model=SchedulePage,
    summary="List schedules",
    description=(
        "Returns the cron schedules of every agent, or of a single agent when `agent_id` is "
        "given, ordered by agent identifier and job type. Requires at least the `viewer` role. "
        "This endpoint is not paginated: all matching schedules come back in one response."
    ),
)
async def list_schedules(
    admin: OperationAdminServiceDep,
    actor: ActorDep,
    agent_id: str | None = None,
) -> SchedulePage:
    require_role(actor, UserRole.VIEWER)
    items = await admin.repository.list_schedules(agent_id)
    return SchedulePage(total=len(items), limit=len(items) or 1, offset=0, items=items)


@router.put(
    "/schedules/{schedule_id}",
    response_model=AgentSchedule,
    summary="Update a schedule",
    description=(
        "Replaces the cron expression, timezone and enabled flag of a schedule, recomputes its "
        "next occurrence and records a `schedule_changed` audit event. Requires the `admin` "
        "role. Returns 404 for an unknown schedule, 422 for an invalid cron expression, and 409 "
        "when a concurrent write already changed the schedule."
    ),
)
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


@router.get(
    "/findings",
    response_model=FindingPage,
    summary="List findings",
    description=(
        "Returns the findings produced by agent analysis, newest first, optionally restricted to "
        "one run through `run_id` and paginated with `limit` and `offset`. Requires at least the "
        "`viewer` role."
    ),
)
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


@router.get(
    "/recommendations",
    response_model=RecommendationPage,
    summary="List recommendations",
    description=(
        "Returns the recommendations derived from findings, newest first, optionally restricted "
        "to one run through `run_id` and paginated with `limit` and `offset`. Requires at least "
        "the `viewer` role. A recommendation is only advisory until it becomes an action "
        "proposal."
    ),
)
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


@router.get(
    "/action-proposals",
    response_model=ProposalPage,
    summary="List action proposals",
    description=(
        "Returns action proposals newest first, optionally filtered by `run_id` and by lifecycle "
        "`status`, paginated with `limit` and `offset`. Requires at least the `viewer` role. "
        "Proposals in status `awaiting_approval` are the ones still waiting for an approver."
    ),
)
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


@router.get(
    "/approvals",
    response_model=ApprovalPage,
    summary="List approval requests",
    description=(
        "Returns approval requests newest first, optionally filtered by `status`, paginated with "
        "`limit` and `offset`. Requires at least the `viewer` role. A request stays `pending` "
        "until it is decided or until the expiration job marks it `expired`."
    ),
)
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


@router.post(
    "/approvals/{proposal_id}/decision",
    response_model=ApprovalLifecycleResponse,
    summary="Approve or reject an action proposal",
    description=(
        "Records the decision on the pending approval and, when the proposal is approved and its "
        "provider is executable, immediately executes and verifies the action; the response "
        "carries the proposal, the decision, the execution, the verification and the refreshed "
        "run. Requires at least the `approver` role, and the requester's own decision is refused "
        "with 403 while self-approval is disabled. Returns 409 for a stale proposal or a "
        "concurrent write, 423 when a safeguard such as a kill switch, an expiry or a competing "
        "execution blocks the action, and 202 when a dispatched write must be reconciled before "
        "any retry. In dry-run mode the provider is never called and the lifecycle ends with "
        "status `dry_run`."
    ),
)
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


@router.post(
    "/approvals/bulk-decision",
    response_model=list[ApprovalLifecycleResponse],
    summary="Decide several action proposals at once",
    description=(
        "Applies the same decision to up to 50 proposals one after another and returns one "
        "lifecycle result per proposal. Requires at least the `approver` role. Returns 409 when "
        "the proposals do not all share a single action type, or when a bulk **approval** "
        "targets anything other than budget-decrease actions. Returns 403 for a forbidden or "
        "self-approval decision, 404 when any proposal is unknown, and 202 when a dispatched "
        "write requires reconciliation."
    ),
)
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


@router.get(
    "/executions",
    response_model=ExecutionPage,
    summary="List action executions",
    description=(
        "Returns provider execution attempts newest first, optionally restricted to one agent "
        "through `agent_id` and paginated with `limit` and `offset`. Requires at least the "
        "`viewer` role. Each item keeps the provider state before the write, the requested "
        "change, the provider response and the idempotency key used."
    ),
)
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
    description=(
        "Re-runs every safeguard for an already approved proposal (kill switches, current "
        "policy, expiry, provider state hash and the per-object lock) and then executes and "
        "verifies it. Requires at least the `approver` role. Repeating the call is safe: the "
        "stored execution for the proposal idempotency key is returned instead of writing "
        "twice. Returns 403 with a `write_operation_forbidden` body when the provider is LIVE "
        "Meta and therefore read-only, 409 for a stale proposal, 423 when a safeguard blocks "
        "the action, and 202 when a dispatched write requires reconciliation."
    ),
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


@router.get(
    "/reports",
    response_model=ReportPage,
    summary="List agent reports",
    description=(
        "Returns generated agent reports newest first, optionally restricted to one agent "
        "through `agent_id` and paginated with `limit` and `offset`. Requires at least the "
        "`viewer` role."
    ),
)
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


@router.get(
    "/reports/{report_id}",
    response_model=AgentReport,
    summary="Get a report",
    description=(
        "Returns one stored report in full, with its reporting period, structured payload, "
        "human-readable body and data-quality notes. Requires at least the `viewer` role. "
        "Returns 404 when the report identifier is unknown."
    ),
)
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
    summary="Check an ads provider integration",
    description=(
        "Probes the named ads platform, stores the resulting health record and returns it with "
        "its status, latency and any error detail. Requires at least the `viewer` role. Returns "
        "404 when no platform is registered under that provider name."
    ),
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


@router.get(
    "/audit-events",
    response_model=AuditPage,
    summary="List audit events",
    description=(
        "Returns the append-only audit trail newest first, optionally filtered by "
        "`correlation_id` or `run_id`, paginated with `limit` (up to 2000) and `offset`. "
        "Requires at least the `viewer` role. Filtering by `correlation_id` is the way to "
        "reconstruct everything a single manual run or approval decision produced."
    ),
)
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


@router.put(
    "/kill-switch/global",
    response_model=KillSwitchResponse,
    summary="Set the global kill switch",
    description=(
        "Enables or disables the global kill switch and records a `kill_switch_changed` audit "
        "event; the response echoes the resulting scope and state. Requires the `admin` role. "
        "While it is enabled every agent run is refused with 409 and every action execution is "
        "blocked with 423, whatever the per-agent settings are."
    ),
)
async def global_kill_switch(
    payload: KillSwitchRequest,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> KillSwitchResponse:
    require_role(actor, UserRole.ADMIN)
    await admin.set_kill_switch(agent_id=None, enabled=payload.enabled, actor=actor)
    return KillSwitchResponse(scope="global", enabled=payload.enabled)


@router.put(
    "/kill-switch/agents/{agent_id}",
    response_model=KillSwitchResponse,
    summary="Set an agent kill switch",
    description=(
        "Enables or disables the kill switch of a single agent and records a "
        "`kill_switch_changed` audit event; the response echoes the agent scope and state. "
        "Requires the `admin` role. While it is enabled that agent cannot start a run and none "
        "of its approved actions can be executed."
    ),
)
async def agent_kill_switch(
    agent_id: str,
    payload: KillSwitchRequest,
    admin: OperationAdminServiceDep,
    actor: ActorDep,
) -> KillSwitchResponse:
    require_role(actor, UserRole.ADMIN)
    await admin.set_kill_switch(agent_id=agent_id, enabled=payload.enabled, actor=actor)
    return KillSwitchResponse(scope=agent_id, enabled=payload.enabled)
