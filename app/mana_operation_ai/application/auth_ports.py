from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.mana_operation_ai.domain.auth import (
    AdminSession,
    AdminUser,
    AuthAuditEvent,
    AuthenticatedIdentity,
    AuthRateEvent,
    AuthRateLimit,
    OtpChallenge,
)
from app.mana_operation_ai.domain.enums import AdminUserStatus, UserRole


class TelegramDeliveryFailure(StrEnum):
    BOT_NOT_STARTED = "bot_not_started"
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNAVAILABLE = "unavailable"


class TelegramDeliveryError(RuntimeError):
    def __init__(self, failure: TelegramDeliveryFailure) -> None:
        super().__init__("Telegram delivery failed")
        self.failure = failure


class LastActiveAdminError(RuntimeError):
    """The requested change would leave no active administrative user."""


class AdminUserAlreadyExistsError(RuntimeError):
    """A durable administrative user already owns the Telegram identity."""


class TelegramOtpSender(Protocol):
    async def send_login_code(self, *, telegram_id: int, code: str, ttl_seconds: int) -> None: ...


class AdminAuthRepository(Protocol):
    async def bootstrap_admin(self, *, user: AdminUser, event: AuthAuditEvent) -> AdminUser: ...

    async def get_user(self, user_id: str) -> AdminUser | None: ...

    async def get_user_by_telegram_id(self, telegram_id: int) -> AdminUser | None: ...

    async def list_users(self) -> list[AdminUser]: ...

    async def create_user(self, *, user: AdminUser, event: AuthAuditEvent) -> AdminUser: ...

    async def update_user_access(
        self,
        *,
        user_id: str,
        role: UserRole | None,
        status: AdminUserStatus | None,
        disabled_reason: str | None,
        display_name: str | None,
        username: str | None,
        update_display_name: bool,
        update_username: bool,
        updated_at: datetime,
        events: list[AuthAuditEvent],
    ) -> AdminUser: ...

    async def reserve_challenge(
        self,
        *,
        challenge: OtpChallenge,
        cooldown_since: datetime,
    ) -> bool: ...

    async def get_active_challenge(self, *, user_id: str) -> OtpChallenge | None: ...

    async def apply_challenge_attempt(
        self,
        *,
        challenge_id: str,
        correct: bool,
        now: datetime,
        max_attempts: int,
    ) -> OtpChallenge | None: ...

    async def fail_challenge_delivery(self, *, challenge_id: str, now: datetime) -> None: ...

    async def consume_rate_events(
        self,
        *,
        events: list[AuthRateEvent],
        limits: list[AuthRateLimit],
        since: datetime,
    ) -> bool: ...

    async def record_auth_failure(
        self,
        *,
        user_id: str,
        now: datetime,
        lockout_failures: int,
        lockout_until: datetime,
    ) -> AdminUser: ...

    async def create_session(
        self,
        *,
        session: AdminSession,
        old_token_hmac: str | None,
        login_at: datetime,
        event: AuthAuditEvent,
    ) -> AuthenticatedIdentity: ...

    async def get_identity_by_session_hmac(
        self,
        *,
        token_hmac: str,
        now: datetime,
    ) -> AuthenticatedIdentity | None: ...

    async def revoke_session(
        self,
        *,
        token_hmac: str,
        now: datetime,
        reason: str,
        event: AuthAuditEvent | None,
    ) -> bool: ...

    async def revoke_user_sessions(
        self,
        *,
        user_id: str,
        now: datetime,
        reason: str,
        event: AuthAuditEvent,
    ) -> int: ...

    async def save_audit_event(self, event: AuthAuditEvent) -> None: ...

    async def list_auth_audit_events(
        self,
        *,
        subject_user_id: str | None = None,
        limit: int = 200,
    ) -> list[AuthAuditEvent]: ...
