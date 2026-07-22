from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.mana_operation_ai.domain.enums import AgentStatus, IntegrationStatus
from app.mana_operation_ai.domain.models import (
    ActionExecution,
    ActionProposal,
    ActionVerification,
    AgentConfiguration,
    AgentDefinition,
    AgentReport,
    AgentRun,
    AgentRunResult,
    AgentSchedule,
    ApprovalDecision,
    ApprovalRequest,
    AuditEvent,
    DataSnapshot,
    Finding,
    IntegrationHealth,
    Recommendation,
)


class Page[ItemT](BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    limit: int
    offset: int
    items: list[ItemT]


class AgentDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: AgentDefinition
    configuration: AgentConfiguration | None
    schedules: list[AgentSchedule]
    integration_health: list[IntegrationHealth]
    kill_switch_enabled: bool


class AgentStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AgentStatus


class RunDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: AgentRun
    timeline: list[AuditEvent]
    snapshots: list[DataSnapshot]
    findings: list[Finding]
    recommendations: list[Recommendation]
    proposals: list[ActionProposal]


class RunNowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type: str = Field(default="analysis", min_length=1, max_length=80)
    correlation_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)


class ManualRunAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    job_type: str
    correlation_id: str
    status: Literal["accepted"] = "accepted"


class ConfigurationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, JsonValue]


class ScheduleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cron_expression: str = Field(min_length=5, max_length=120)
    timezone: str = Field(min_length=1, max_length=64)
    enabled: bool


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: bool
    reason: str = Field(min_length=1, max_length=1_000)
    correlation_id: str = Field(min_length=1, max_length=128)


class ExecuteApprovedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correlation_id: str = Field(min_length=1, max_length=128)


class WriteForbiddenDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal["write_operation_forbidden"] = "write_operation_forbidden"
    message: str
    provider_mode: Literal["live_read_only"] = "live_read_only"
    provider_request_sent: Literal[False] = False


class WriteForbiddenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: WriteForbiddenDetail


class BulkApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_ids: list[str] = Field(min_length=1, max_length=50)
    approve: bool
    reason: str = Field(min_length=1, max_length=1_000)
    correlation_id: str = Field(min_length=1, max_length=128)


class ApprovalLifecycleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal: ActionProposal
    approval_decision: ApprovalDecision | None
    execution: ActionExecution | None
    verification: ActionVerification | None
    run: AgentRunResult


class KillSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class KillSwitchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str
    enabled: bool


class DashboardAgent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    display_name: str
    status: AgentStatus
    health: IntegrationStatus
    last_run: datetime | None
    next_run: datetime | None
    last_duration_ms: int | None
    success_rate: str
    pending_approvals: int
    recent_incidents: int


class DashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents: list[DashboardAgent]
    global_kill_switch: bool
    generated_at: datetime


AgentPage = Page[AgentDefinition]
RunPage = Page[AgentRun]
FindingPage = Page[Finding]
RecommendationPage = Page[Recommendation]
ProposalPage = Page[ActionProposal]
ApprovalPage = Page[ApprovalRequest]
ExecutionPage = Page[ActionExecution]
ReportPage = Page[AgentReport]
AuditPage = Page[AuditEvent]
ConfigurationPage = Page[AgentConfiguration]
SchedulePage = Page[AgentSchedule]
IntegrationHealthResponse = IntegrationHealth
