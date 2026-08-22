from enum import StrEnum


class AgentStatus(StrEnum):
    REGISTERED = "registered"
    ENABLED = "enabled"
    DISABLED = "disabled"
    PAUSED = "paused"
    UNHEALTHY = "unhealthy"


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    COLLECTING = "collecting"
    NORMALIZING = "normalizing"
    ANALYZING = "analyzing"
    PROPOSING = "proposing"
    POLICY_CHECK = "policy_check"
    WAITING_APPROVAL = "waiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRunStage(StrEnum):
    COLLECT = "collect"
    NORMALIZE = "normalize"
    ANALYZE = "analyze"
    PROPOSE = "propose"
    POLICY_CHECK = "policy_check"
    APPROVAL = "approval"
    EXECUTE = "execute"
    VERIFY = "verify"
    REPORT = "report"


class TriggerType(StrEnum):
    SCHEDULE = "schedule"
    USER = "user"
    ORCHESTRATOR = "orchestrator"
    API = "api"


class CapabilityRisk(StrEnum):
    READ = "read"
    PROPOSE = "propose"
    WRITE = "write"
    FINANCIAL = "financial"


class IntegrationStatus(StrEnum):
    UNCONFIGURED = "unconfigured"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ProviderMode(StrEnum):
    FAKE_EXECUTABLE = "fake_executable"
    LIVE_READ_ONLY = "live_read_only"


class DataAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ActionType(StrEnum):
    INCREASE_BUDGET = "increase_budget"
    DECREASE_BUDGET = "decrease_budget"
    PAUSE = "pause"
    RESUME = "resume"
    SCALE_AUDIENCE = "scale_audience"
    DISABLE_AUDIENCE = "disable_audience"
    MAINTAIN = "maintain"
    OBSERVE = "observe"
    PROPOSE_TEST = "propose_test"


class GrowthActionType(StrEnum):
    CREATE_EXPERIMENT = "create_experiment"
    STOP_EXPERIMENT = "stop_experiment"


class OutcomeEvaluationStatus(StrEnum):
    PENDING = "pending"
    MEASURED = "measured"
    INCONCLUSIVE = "inconclusive"


class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    POLICY_REJECTED = "policy_rejected"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    PARTIALLY_APPLIED = "partially_applied"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    DRY_RUN = "dry_run"


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    PARTIALLY_APPLIED = "partially_applied"
    FAILED = "failed"
    DRY_RUN = "dry_run"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"


class UserRole(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    APPROVER = "approver"
    ADMIN = "admin"


class AdminUserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    PENDING = "pending"
    REVOKED = "revoked"


class OtpChallengeStatus(StrEnum):
    ACTIVE = "active"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    DELIVERY_FAILED = "delivery_failed"


class AuthAuditEventType(StrEnum):
    BOOTSTRAP_APPLIED = "bootstrap_applied"
    LOGIN_CODE_REQUESTED = "login_code_requested"
    LOGIN_CODE_DELIVERY_FAILED = "login_code_delivery_failed"
    LOGIN_FAILED = "login_failed"
    LOGIN_SUCCEEDED = "login_succeeded"
    SESSION_REVOKED = "session_revoked"
    LOGOUT = "logout"
    USER_CREATED = "user_created"
    USER_PROFILE_CHANGED = "user_profile_changed"
    USER_ROLE_CHANGED = "user_role_changed"
    USER_STATUS_CHANGED = "user_status_changed"
    USER_SESSIONS_REVOKED = "user_sessions_revoked"
    AUTH_RATE_LIMITED = "auth_rate_limited"


class AuditEventType(StrEnum):
    AGENT_REGISTERED = "agent_registered"
    AGENT_STATUS_CHANGED = "agent_status_changed"
    CONFIGURATION_CREATED = "configuration_created"
    SCHEDULE_CHANGED = "schedule_changed"
    RUN_STAGE_CHANGED = "run_stage_changed"
    FINDING_CREATED = "finding_created"
    RECOMMENDATION_CREATED = "recommendation_created"
    ACTION_PROPOSED = "action_proposed"
    POLICY_EVALUATED = "policy_evaluated"
    APPROVAL_DECIDED = "approval_decided"
    ACTION_EXECUTED = "action_executed"
    ACTION_VERIFIED = "action_verified"
    REPORT_CREATED = "report_created"
    KILL_SWITCH_CHANGED = "kill_switch_changed"
    INTEGRATION_CHECKED = "integration_checked"
    WRITE_FORBIDDEN = "write_forbidden"
