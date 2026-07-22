from datetime import datetime

from pydantic import Field, JsonValue, field_validator, model_validator

from app.mana_operation_ai.domain.enums import (
    AdminUserStatus,
    AuthAuditEventType,
    OtpChallengeStatus,
    UserRole,
)
from app.mana_operation_ai.domain.models import DomainModel

MAX_TELEGRAM_ID = 9_007_199_254_740_991


class AdminUser(DomainModel):
    user_id: str = Field(min_length=36, max_length=36)
    telegram_id: int = Field(gt=0, le=MAX_TELEGRAM_ID)
    display_name: str | None = Field(default=None, max_length=160)
    username: str | None = Field(default=None, max_length=64)
    role: UserRole
    status: AdminUserStatus
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None
    created_by: str = Field(min_length=1, max_length=128)
    disabled_reason: str | None = Field(default=None, max_length=500)
    profile_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    consecutive_auth_failures: int = Field(default=0, ge=0)
    auth_locked_until: datetime | None = None

    @model_validator(mode="after")
    def validate_disabled_state(self) -> "AdminUser":
        if self.status is AdminUserStatus.ACTIVE and self.disabled_reason is not None:
            raise ValueError("active user cannot retain a disabled reason")
        if self.status is AdminUserStatus.DISABLED and self.disabled_reason is None:
            raise ValueError("disabled user requires a reason")
        return self

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value: str) -> str:
        from uuid import UUID

        if str(UUID(value)) != value:
            raise ValueError("user_id must be a canonical UUID")
        return value


class OtpChallenge(DomainModel):
    challenge_id: str = Field(min_length=36, max_length=36)
    user_id: str = Field(min_length=36, max_length=36)
    telegram_id: int = Field(gt=0, le=MAX_TELEGRAM_ID)
    code_hmac: str = Field(min_length=64, max_length=64)
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None
    attempts_count: int = Field(default=0, ge=0)
    request_ip_hash: str = Field(min_length=64, max_length=64)
    request_user_agent_hash: str | None = Field(default=None, min_length=64, max_length=64)
    status: OtpChallengeStatus

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "OtpChallenge":
        if self.expires_at <= self.issued_at:
            raise ValueError("OTP expiration must follow issuance")
        if self.status is OtpChallengeStatus.CONSUMED and self.consumed_at is None:
            raise ValueError("consumed OTP challenge requires consumed_at")
        return self


class AdminSession(DomainModel):
    session_id: str = Field(min_length=36, max_length=36)
    user_id: str = Field(min_length=36, max_length=36)
    token_hmac: str = Field(min_length=64, max_length=64)
    csrf_hmac: str = Field(min_length=64, max_length=64)
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    revocation_reason: str | None = Field(default=None, max_length=200)
    request_ip_hash: str = Field(min_length=64, max_length=64)
    request_user_agent_hash: str | None = Field(default=None, min_length=64, max_length=64)

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None


class AuthAuditEvent(DomainModel):
    event_id: str = Field(min_length=36, max_length=36)
    event_type: AuthAuditEventType
    occurred_at: datetime
    actor_user_id: str | None = Field(default=None, min_length=36, max_length=36)
    subject_user_id: str | None = Field(default=None, min_length=36, max_length=36)
    request_ip_hash: str | None = Field(default=None, min_length=64, max_length=64)
    summary: str = Field(min_length=1, max_length=500)
    details: dict[str, JsonValue] = Field(default_factory=dict)


class AuthenticatedIdentity(DomainModel):
    user: AdminUser
    session: AdminSession


class IssuedSession(DomainModel):
    identity: AuthenticatedIdentity
    session_token: str = Field(min_length=43, max_length=128)
    csrf_token: str = Field(min_length=43, max_length=128)


class AuthPolicy(DomainModel):
    otp_ttl_seconds: int = Field(ge=60, le=60)
    resend_cooldown_seconds: int = Field(ge=5, le=300)
    max_verify_attempts: int = Field(ge=3, le=10)
    request_limit_per_user: int = Field(ge=1, le=100)
    request_limit_per_ip: int = Field(ge=2, le=1_000)
    verify_limit_per_ip: int = Field(ge=5, le=2_000)
    global_request_limit: int = Field(ge=20, le=100_000)
    rate_window_seconds: int = Field(ge=60, le=86_400)
    lockout_failures: int = Field(ge=5, le=100)
    lockout_seconds: int = Field(ge=30, le=86_400)
    session_ttl_seconds: int = Field(ge=900, le=604_800)


class RequestCodeResult(DomainModel):
    message: str
    expires_in_seconds: int
    resend_after_seconds: int
    bot_url: str | None


class AuthRateEvent(DomainModel):
    event_id: str = Field(min_length=36, max_length=36)
    scope: str = Field(min_length=1, max_length=24)
    scope_hmac: str = Field(min_length=64, max_length=64)
    action: str = Field(min_length=1, max_length=32)
    occurred_at: datetime


class AuthRateLimit(DomainModel):
    scope: str = Field(min_length=1, max_length=24)
    scope_hmac: str = Field(min_length=64, max_length=64)
    actions: tuple[str, ...] = Field(min_length=1)
    limit: int = Field(ge=1)
