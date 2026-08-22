from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for operation-platform persistence rows."""


class AdminUserRow(Base):
    __tablename__ = "operation_admin_users"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[str] = mapped_column(String(128))
    auth_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class OtpChallengeRow(Base):
    __tablename__ = "operation_auth_otp_challenges"
    __table_args__ = (
        UniqueConstraint("user_id", "active_slot", name="uq_operation_auth_active_challenge"),
        Index("idx_operation_auth_challenge_user_issued", "user_id", "issued_at"),
    )

    challenge_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("operation_admin_users.user_id"),
        index=True,
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    code_hmac: Mapped[str] = mapped_column(String(64))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True)
    active_slot: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class AdminSessionRow(Base):
    __tablename__ = "operation_admin_sessions"
    __table_args__ = (Index("idx_operation_admin_session_user_expiry", "user_id", "expires_at"),)

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("operation_admin_users.user_id"),
        index=True,
    )
    token_hmac: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_hmac: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class AuthAuditEventRow(Base):
    __tablename__ = "operation_auth_audit_events"
    __table_args__ = (
        Index("idx_operation_auth_audit_subject_time", "subject_user_id", "occurred_at"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("operation_admin_users.user_id"),
        index=True,
    )
    subject_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("operation_admin_users.user_id"),
        index=True,
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class AuthRateEventRow(Base):
    __tablename__ = "operation_auth_rate_events"
    __table_args__ = (
        Index(
            "idx_operation_auth_rate_scope_time",
            "scope",
            "scope_hmac",
            "action",
            "occurred_at",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope: Mapped[str] = mapped_column(String(24))
    scope_hmac: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthStateRow(Base):
    __tablename__ = "operation_auth_state"

    state_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)


class AgentRow(Base):
    __tablename__ = "operation_agents"

    agent_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    definition: Mapped[dict[str, object]] = mapped_column(JSON)


class AgentConfigurationRow(Base):
    __tablename__ = "operation_agent_configurations"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "capability_key",
            "version",
            name="uq_operation_configuration_capability_version",
        ),
        Index(
            "idx_operation_configuration_active_version",
            "agent_id",
            "capability_key",
            "active",
            "version",
        ),
    )

    configuration_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("operation_agents.agent_id"), index=True)
    capability_key: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class AgentScheduleRow(Base):
    __tablename__ = "operation_agent_schedules"
    __table_args__ = (Index("idx_operation_schedule_due", "enabled", "next_run_at"),)

    schedule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("operation_agents.agent_id"), index=True)
    capability_key: Mapped[str] = mapped_column(String(80), index=True)
    job_type: Mapped[str] = mapped_column(String(80), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, index=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class AgentRunRow(Base):
    __tablename__ = "operation_agent_runs"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "capability_key",
            "idempotency_key",
            name="uq_operation_run_capability_idempotency",
        ),
        Index(
            "idx_operation_run_agent_started",
            "agent_id",
            "capability_key",
            "started_at",
        ),
        Index("idx_operation_run_status_updated", "status", "updated_at"),
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("operation_agents.agent_id"), index=True)
    capability_key: Mapped[str] = mapped_column(String(80), index=True)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    trigger: Mapped[str] = mapped_column(String(32), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class DataSnapshotRow(Base):
    __tablename__ = "operation_data_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("operation_agent_runs.run_id"), index=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("operation_agents.agent_id", name="fk_operation_snapshot_agent"),
        index=True,
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    checksum: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class AnalysisRow(Base):
    __tablename__ = "operation_analyses"

    analysis_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("operation_agent_runs.run_id"),
        unique=True,
        index=True,
    )
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("operation_data_snapshots.snapshot_id"),
        index=True,
    )
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class FindingRow(Base):
    __tablename__ = "operation_findings"

    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("operation_agent_runs.run_id"), index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("operation_analyses.analysis_id"))
    finding_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class RecommendationRow(Base):
    __tablename__ = "operation_recommendations"

    recommendation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("operation_agent_runs.run_id"), index=True)
    action_type: Mapped[str] = mapped_column(String(40), index=True)
    provider_object_id: Mapped[str] = mapped_column(String(255), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class ActionProposalRow(Base):
    __tablename__ = "operation_action_proposals"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        Index("idx_operation_proposal_object", "provider", "provider_object_id"),
        Index("idx_operation_proposal_status_created", "status", "created_at"),
        Index(
            "idx_operation_proposal_object_status",
            "provider",
            "provider_object_id",
            "status",
        ),
    )

    proposal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("operation_agent_runs.run_id"), index=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("operation_agents.agent_id", name="fk_operation_proposal_agent"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(40))
    provider_object_id: Mapped[str] = mapped_column(String(255))
    action_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class ApprovalRequestRow(Base):
    __tablename__ = "operation_approval_requests"
    __table_args__ = (Index("idx_operation_approval_status_requested", "status", "requested_at"),)

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("operation_action_proposals.proposal_id"),
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    requested_by: Mapped[str] = mapped_column(String(128))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class ApprovalDecisionRow(Base):
    __tablename__ = "operation_approval_decisions"

    approval_id: Mapped[str] = mapped_column(
        ForeignKey("operation_approval_requests.approval_id"),
        primary_key=True,
    )
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey(
            "operation_action_proposals.proposal_id",
            name="fk_operation_decision_proposal",
        ),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    decided_by: Mapped[str] = mapped_column(String(128))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class ActionExecutionRow(Base):
    __tablename__ = "operation_action_executions"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        Index("idx_operation_execution_status_attempted", "status", "attempted_at"),
    )

    execution_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(
        ForeignKey("operation_action_proposals.proposal_id"),
        unique=True,
        index=True,
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("operation_agent_runs.run_id", name="fk_operation_execution_run"),
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class ActionVerificationRow(Base):
    __tablename__ = "operation_action_verifications"

    verification_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("operation_action_executions.execution_id"),
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class AgentReportRow(Base):
    __tablename__ = "operation_agent_reports"
    __table_args__ = (
        UniqueConstraint("run_id", "report_type", name="uq_operation_report_run_type"),
        Index("idx_operation_report_agent_created", "agent_id", "created_at"),
    )

    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("operation_agents.agent_id", name="fk_operation_report_agent"),
        index=True,
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("operation_agent_runs.run_id"), index=True)
    report_type: Mapped[str] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    human_readable: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class AuditEventRow(Base):
    __tablename__ = "operation_audit_events"
    __table_args__ = (Index("idx_operation_audit_run_occurred", "run_id", "occurred_at"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True)
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("operation_agents.agent_id", name="fk_operation_audit_agent"),
        index=True,
    )
    capability_key: Mapped[str | None] = mapped_column(String(80), index=True)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("operation_agent_runs.run_id", name="fk_operation_audit_run"),
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class OutcomeEvaluationRow(Base):
    __tablename__ = "operation_outcome_evaluations"
    __table_args__ = (Index("idx_operation_outcome_run_evaluated", "run_id", "evaluated_at"),)

    evaluation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("operation_agent_runs.run_id", name="fk_operation_outcome_run"),
        index=True,
    )
    proposal_id: Mapped[str | None] = mapped_column(
        ForeignKey("operation_action_proposals.proposal_id", name="fk_operation_outcome_proposal"),
        index=True,
    )
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("operation_agents.agent_id", name="fk_operation_outcome_agent"),
        index=True,
    )
    capability_key: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class IntegrationHealthRow(Base):
    __tablename__ = "operation_integration_health"

    integration_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)


class SystemControlRow(Base):
    __tablename__ = "operation_system_controls"

    control_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[str] = mapped_column(String(128))


class JobLockRow(Base):
    __tablename__ = "operation_job_locks"

    lock_key: Mapped[str] = mapped_column(String(180), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128))
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
