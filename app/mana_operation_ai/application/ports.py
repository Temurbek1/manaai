from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from pydantic import JsonValue

from app.mana_operation_ai.domain.enums import (
    ActionStatus,
    AgentRunStatus,
    AgentStatus,
    ApprovalStatus,
    ProviderMode,
)
from app.mana_operation_ai.domain.marketing import (
    AdsCollectionRequest,
    AdsSnapshot,
    ProviderActionResult,
    ProviderObjectState,
)
from app.mana_operation_ai.domain.models import (
    ActionExecution,
    ActionParameters,
    ActionProposal,
    ActionVerification,
    AgentConfiguration,
    AgentDefinition,
    AgentReport,
    AgentRun,
    AgentRunResult,
    AgentSchedule,
    Analysis,
    ApprovalDecision,
    ApprovalRequest,
    AuditEvent,
    DataSnapshot,
    Finding,
    IntegrationHealth,
    Recommendation,
)


class ConcurrentOperationError(RuntimeError):
    """Raised when persisted state changed before a guarded mutation committed."""


class ProviderOperationError(RuntimeError):
    """Base error exposed by provider-neutral integration ports."""


class ProviderTransientError(ProviderOperationError):
    """The provider operation can be retried without assuming a write occurred."""


class ProviderPermanentError(ProviderOperationError):
    """The provider rejected an operation that will not succeed unchanged."""


class ProviderObjectNotFoundError(ProviderPermanentError):
    """The target provider object no longer exists or is inaccessible."""


class ProviderWriteUncertainError(ProviderOperationError):
    """A write was dispatched but its final provider outcome is unknown."""


class WriteOperationForbidden(ProviderPermanentError):
    """The provider is deliberately incapable of executing this write."""


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new(self) -> str: ...


class OperationRepository(Protocol):
    async def register_agent(self, definition: AgentDefinition) -> None: ...

    async def get_agent(self, agent_id: str) -> AgentDefinition | None: ...

    async def list_agents(self) -> list[AgentDefinition]: ...

    async def set_agent_status(self, agent_id: str, status: AgentStatus) -> AgentDefinition: ...

    async def save_configuration(self, configuration: AgentConfiguration) -> None: ...

    async def latest_configuration(self, agent_id: str) -> AgentConfiguration | None: ...

    async def list_configurations(self, agent_id: str) -> list[AgentConfiguration]: ...

    async def save_schedule(self, schedule: AgentSchedule) -> None: ...

    async def list_schedules(self, agent_id: str | None = None) -> list[AgentSchedule]: ...

    async def due_schedules(self, now: datetime) -> list[AgentSchedule]: ...

    async def claim_schedule(
        self,
        *,
        current: AgentSchedule,
        advanced: AgentSchedule,
    ) -> bool: ...

    async def create_run(self, run: AgentRun) -> AgentRun: ...

    async def update_run(self, run: AgentRun) -> None: ...

    async def get_run(self, run_id: str) -> AgentRun | None: ...

    async def list_runs(
        self,
        *,
        agent_id: str | None = None,
        status: AgentRunStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AgentRun], int]: ...

    async def save_snapshot(self, snapshot: DataSnapshot) -> None: ...

    async def list_snapshots(self, run_id: str) -> list[DataSnapshot]: ...

    async def save_analysis(self, analysis: Analysis) -> None: ...

    async def save_findings(self, findings: Sequence[Finding]) -> None: ...

    async def list_findings(
        self,
        *,
        run_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Finding], int]: ...

    async def save_recommendations(self, recommendations: Sequence[Recommendation]) -> None: ...

    async def list_recommendations(
        self,
        *,
        run_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Recommendation], int]: ...

    async def create_action_request(
        self,
        proposal: ActionProposal,
        approval: ApprovalRequest | None,
    ) -> tuple[ActionProposal, ApprovalRequest | None]: ...

    async def update_proposal(self, proposal: ActionProposal) -> None: ...

    async def get_proposal(self, proposal_id: str) -> ActionProposal | None: ...

    async def list_proposals(
        self,
        *,
        run_id: str | None = None,
        status: ActionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ActionProposal], int]: ...

    async def get_approval_for_proposal(self, proposal_id: str) -> ApprovalRequest | None: ...

    async def apply_approval_decision(
        self,
        request: ApprovalRequest,
        decision: ApprovalDecision,
        proposal: ActionProposal,
    ) -> None: ...

    async def list_approvals(
        self,
        *,
        status: ApprovalStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ApprovalRequest], int]: ...

    async def save_execution(self, execution: ActionExecution) -> ActionExecution: ...

    async def finalize_action_state(
        self,
        *,
        proposal: ActionProposal,
        execution: ActionExecution,
        verification: ActionVerification | None = None,
    ) -> None: ...

    async def get_execution_by_idempotency(self, key: str) -> ActionExecution | None: ...

    async def get_execution_for_proposal(self, proposal_id: str) -> ActionExecution | None: ...

    async def get_verification_for_execution(
        self,
        execution_id: str,
    ) -> ActionVerification | None: ...

    async def list_executions(
        self,
        *,
        agent_id: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ActionExecution], int]: ...

    async def save_report(self, report: AgentReport) -> None: ...

    async def get_report(self, report_id: str) -> AgentReport | None: ...

    async def list_reports(
        self,
        *,
        agent_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AgentReport], int]: ...

    async def save_audit_event(self, event: AuditEvent) -> None: ...

    async def list_audit_events(
        self,
        *,
        correlation_id: str | None = None,
        run_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[AuditEvent], int]: ...

    async def save_integration_health(self, health: IntegrationHealth) -> None: ...

    async def get_integration_health(self, integration_id: str) -> IntegrationHealth | None: ...

    async def set_control(
        self,
        *,
        key: str,
        enabled: bool,
        updated_at: datetime,
        updated_by: str,
    ) -> None: ...

    async def get_control(self, key: str, *, default: bool = False) -> bool: ...

    async def acquire_lock(
        self,
        *,
        key: str,
        owner_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> bool: ...

    async def release_lock(self, *, key: str, owner_id: str) -> None: ...

    async def cleanup_before(self, cutoff: datetime) -> dict[str, int]: ...


class AdsPlatform(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def provider_mode(self) -> ProviderMode: ...

    async def collect(self, request: AdsCollectionRequest) -> AdsSnapshot: ...

    async def health(self) -> IntegrationHealth: ...

    async def get_object_state(
        self,
        object_type: str,
        provider_object_id: str,
    ) -> ProviderObjectState: ...

    async def execute(
        self,
        *,
        object_type: str,
        provider_object_id: str,
        parameters: ActionParameters,
        idempotency_key: str,
    ) -> ProviderActionResult: ...


class NotificationPort(Protocol):
    async def send(
        self,
        *,
        channels: Sequence[str],
        subject: str,
        message: str,
        metadata: dict[str, JsonValue],
    ) -> None: ...


class OperationalAgent(Protocol):
    @property
    def definition(self) -> AgentDefinition: ...

    @property
    def default_configuration(self) -> dict[str, JsonValue]: ...

    def default_schedules(self) -> list[AgentSchedule]: ...

    def schedules_for_configuration(
        self,
        values: dict[str, JsonValue],
        existing: Sequence[AgentSchedule],
    ) -> list[AgentSchedule]: ...

    def validate_configuration(self, values: dict[str, JsonValue]) -> dict[str, JsonValue]: ...

    async def health(self) -> list[IntegrationHealth]: ...

    async def execute(
        self,
        *,
        run: AgentRun,
        job_type: str,
        configuration: AgentConfiguration,
    ) -> AgentRunResult: ...

    async def finalize_after_actions(self, run_id: str) -> AgentRunResult: ...
