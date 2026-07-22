import asyncio
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from pydantic import JsonValue

from app.mana_operation_ai.application.auth_ports import (
    AdminAuthRepository,
    AdminUserAlreadyExistsError,
    LastActiveAdminError,
    TelegramDeliveryError,
    TelegramOtpSender,
)
from app.mana_operation_ai.application.ports import Clock, IdGenerator
from app.mana_operation_ai.domain.auth import (
    AdminSession,
    AdminUser,
    AuthAuditEvent,
    AuthenticatedIdentity,
    AuthPolicy,
    AuthRateEvent,
    AuthRateLimit,
    IssuedSession,
    OtpChallenge,
    RequestCodeResult,
)
from app.mana_operation_ai.domain.enums import (
    AdminUserStatus,
    AuthAuditEventType,
    OtpChallengeStatus,
    UserRole,
)


class AuthenticationError(RuntimeError):
    def __init__(self, code: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__("Authentication failed")
        self.code = code
        self.retry_after_seconds = retry_after_seconds


class AuthenticationUnavailableError(RuntimeError):
    """Telegram authentication is not securely configured."""


class UserManagementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__("Administrative user mutation failed")
        self.code = code


class AdminAuthService:
    def __init__(
        self,
        *,
        repository: AdminAuthRepository,
        sender: TelegramOtpSender,
        clock: Clock,
        ids: IdGenerator,
        policy: AuthPolicy,
        hmac_secret: str | None,
        bot_username: str | None,
    ) -> None:
        self._repository = repository
        self._sender = sender
        self._clock = clock
        self._ids = ids
        self._policy = policy
        self._hmac_key = hmac_secret.encode("utf-8") if hmac_secret is not None else None
        self._bot_url = f"https://t.me/{bot_username}" if bot_username is not None else None
        self._identity_locks: dict[int, asyncio.Lock] = {}
        self._identity_locks_guard = asyncio.Lock()

    async def bootstrap_admins(self, telegram_ids: tuple[int, ...]) -> list[AdminUser]:
        now = self._clock.now()
        users: list[AdminUser] = []
        for telegram_id in telegram_ids:
            user = AdminUser(
                user_id=self._ids.new(),
                telegram_id=telegram_id,
                role=UserRole.ADMIN,
                status=AdminUserStatus.ACTIVE,
                created_at=now,
                updated_at=now,
                created_by="telegram-bootstrap",
            )
            event = self._event(
                AuthAuditEventType.BOOTSTRAP_APPLIED,
                subject_user_id=user.user_id,
                summary="Bootstrap administrator access reconciled",
                details={"role": UserRole.ADMIN.value},
            )
            users.append(await self._repository.bootstrap_admin(user=user, event=event))
        return users

    async def request_code(
        self,
        *,
        telegram_id: int,
        client_ip: str,
        user_agent: str | None,
    ) -> RequestCodeResult:
        self._require_hmac()
        now = self._clock.now()
        identity_scope = self._scope_hmac("telegram", str(telegram_id))
        ip_scope = self._scope_hmac("ip", client_ip)
        global_scope = self._scope_hmac("global", "all")
        if not await self._consume_request_limits(
            identity_scope=identity_scope,
            ip_scope=ip_scope,
            global_scope=global_scope,
            now=now,
        ):
            await self._repository.save_audit_event(
                self._event(
                    AuthAuditEventType.AUTH_RATE_LIMITED,
                    request_ip_hash=ip_scope,
                    summary="Telegram login-code request was rate limited",
                ),
            )
            raise AuthenticationError(
                "rate_limited",
                retry_after_seconds=self._policy.rate_window_seconds,
            )
        result = self._generic_request_result()
        lock = await self._identity_lock(telegram_id)
        async with lock:
            user = await self._repository.get_user_by_telegram_id(telegram_id)
            if user is None or user.status is not AdminUserStatus.ACTIVE:
                self._dummy_code_work(telegram_id)
                return result
            if user.auth_locked_until is not None and now < user.auth_locked_until:
                return result
            code = f"{secrets.randbelow(1_000_000):06d}"
            challenge_id = self._ids.new()
            challenge = OtpChallenge(
                challenge_id=challenge_id,
                user_id=user.user_id,
                telegram_id=user.telegram_id,
                code_hmac=self._otp_hmac(challenge_id, telegram_id, code),
                issued_at=now,
                expires_at=now + timedelta(seconds=self._policy.otp_ttl_seconds),
                request_ip_hash=ip_scope,
                request_user_agent_hash=self._optional_scope_hmac("user_agent", user_agent),
                status=OtpChallengeStatus.ACTIVE,
            )
            reserved = await self._repository.reserve_challenge(
                challenge=challenge,
                cooldown_since=now - timedelta(seconds=self._policy.resend_cooldown_seconds),
            )
            if not reserved:
                return result
            try:
                await self._sender.send_login_code(
                    telegram_id=telegram_id,
                    code=code,
                    ttl_seconds=self._policy.otp_ttl_seconds,
                )
            except TelegramDeliveryError as exc:
                await self._repository.fail_challenge_delivery(
                    challenge_id=challenge.challenge_id,
                    now=now,
                )
                await self._repository.save_audit_event(
                    self._event(
                        AuthAuditEventType.LOGIN_CODE_DELIVERY_FAILED,
                        subject_user_id=user.user_id,
                        request_ip_hash=ip_scope,
                        summary="Login code delivery was unavailable",
                        details={"failure": exc.failure.value},
                    ),
                )
                return result
            await self._repository.save_audit_event(
                self._event(
                    AuthAuditEventType.LOGIN_CODE_REQUESTED,
                    subject_user_id=user.user_id,
                    request_ip_hash=ip_scope,
                    summary="One-time login code requested",
                    details={"expires_in_seconds": self._policy.otp_ttl_seconds},
                ),
            )
        return result

    async def verify_code(
        self,
        *,
        telegram_id: int,
        code: str,
        client_ip: str,
        user_agent: str | None,
        old_session_token: str | None,
    ) -> IssuedSession:
        self._require_hmac()
        now = self._clock.now()
        ip_scope = self._scope_hmac("ip", client_ip)
        if not await self._consume_verify_limit(ip_scope=ip_scope, now=now):
            await self._repository.save_audit_event(
                self._event(
                    AuthAuditEventType.AUTH_RATE_LIMITED,
                    request_ip_hash=ip_scope,
                    summary="Telegram login-code verification was rate limited",
                ),
            )
            raise AuthenticationError(
                "rate_limited",
                retry_after_seconds=self._policy.rate_window_seconds,
            )
        lock = await self._identity_lock(telegram_id)
        async with lock:
            user = await self._repository.get_user_by_telegram_id(telegram_id)
            if user is None or user.status is not AdminUserStatus.ACTIVE:
                self._dummy_verify(code)
                raise AuthenticationError("invalid_code")
            if user.auth_locked_until is not None and now < user.auth_locked_until:
                retry = max(1, int((user.auth_locked_until - now).total_seconds()))
                raise AuthenticationError("temporarily_locked", retry_after_seconds=retry)
            challenge = await self._repository.get_active_challenge(user_id=user.user_id)
            if challenge is None:
                self._dummy_verify(code)
                raise AuthenticationError("invalid_or_expired_code")
            candidate = self._otp_hmac(challenge.challenge_id, telegram_id, code)
            correct = hmac.compare_digest(candidate, challenge.code_hmac)
            updated = await self._repository.apply_challenge_attempt(
                challenge_id=challenge.challenge_id,
                correct=correct,
                now=now,
                max_attempts=self._policy.max_verify_attempts,
            )
            if updated is None:
                raise AuthenticationError("invalid_or_reused_code")
            if updated.status is OtpChallengeStatus.EXPIRED:
                raise AuthenticationError("expired_code")
            if updated.status is not OtpChallengeStatus.CONSUMED:
                await self._record_failed_verification(user=user, ip_scope=ip_scope, now=now)
                code_name = (
                    "attempts_exhausted"
                    if updated.status is OtpChallengeStatus.ATTEMPTS_EXHAUSTED
                    else "invalid_code"
                )
                raise AuthenticationError(code_name)
            return await self._issue_session(
                user=user,
                ip_scope=ip_scope,
                user_agent=user_agent,
                old_session_token=old_session_token,
                now=now,
            )

    async def authenticate_session(self, session_token: str | None) -> AuthenticatedIdentity | None:
        if session_token is None or self._hmac_key is None:
            return None
        return await self._repository.get_identity_by_session_hmac(
            token_hmac=self._session_hmac(session_token),
            now=self._clock.now(),
        )

    def validate_csrf(self, *, identity: AuthenticatedIdentity, csrf_token: str | None) -> bool:
        if csrf_token is None or self._hmac_key is None:
            return False
        return hmac.compare_digest(self._csrf_hmac(csrf_token), identity.session.csrf_hmac)

    async def logout(
        self,
        *,
        identity: AuthenticatedIdentity,
        session_token: str,
        request_ip: str,
    ) -> None:
        now = self._clock.now()
        await self._repository.revoke_session(
            token_hmac=self._session_hmac(session_token),
            now=now,
            reason="user_logout",
            event=self._event(
                AuthAuditEventType.LOGOUT,
                actor_user_id=identity.user.user_id,
                subject_user_id=identity.user.user_id,
                request_ip_hash=self._scope_hmac("ip", request_ip),
                summary="Administrative session logged out",
            ),
        )

    async def list_users(self) -> list[AdminUser]:
        return await self._repository.list_users()

    async def create_user(
        self,
        *,
        actor: AdminUser,
        telegram_id: int,
        role: UserRole,
        display_name: str | None,
        username: str | None,
    ) -> AdminUser:
        self._require_admin(actor)
        now = self._clock.now()
        user = AdminUser(
            user_id=self._ids.new(),
            telegram_id=telegram_id,
            display_name=display_name,
            username=username,
            role=role,
            status=AdminUserStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            created_by=actor.user_id,
        )
        event = self._event(
            AuthAuditEventType.USER_CREATED,
            actor_user_id=actor.user_id,
            subject_user_id=user.user_id,
            summary="Administrative user created",
            details={"role": role.value},
        )
        try:
            return await self._repository.create_user(user=user, event=event)
        except AdminUserAlreadyExistsError as exc:
            raise UserManagementError("telegram_id_already_exists") from exc

    async def update_user_access(
        self,
        *,
        actor: AdminUser,
        user_id: str,
        role: UserRole | None,
        status: AdminUserStatus | None,
        disabled_reason: str | None,
        display_name: str | None = None,
        username: str | None = None,
        update_display_name: bool = False,
        update_username: bool = False,
    ) -> AdminUser:
        self._require_admin(actor)
        current = await self._repository.get_user(user_id)
        if current is None:
            raise UserManagementError("user_not_found")
        if actor.user_id == user_id and (
            (role is not None and role is not current.role)
            or (status is not None and status is not current.status)
        ):
            raise UserManagementError("self_access_change_forbidden")
        now = self._clock.now()
        events: list[AuthAuditEvent] = []
        profile_fields: list[str] = []
        if update_display_name and display_name != current.display_name:
            profile_fields.append("display_name")
        if update_username and username != current.username:
            profile_fields.append("username")
        if profile_fields:
            events.append(
                self._event(
                    AuthAuditEventType.USER_PROFILE_CHANGED,
                    actor_user_id=actor.user_id,
                    subject_user_id=user_id,
                    summary="Administrative user profile changed",
                    details={"fields": ",".join(profile_fields)},
                ),
            )
        if role is not None and role is not current.role:
            events.append(
                self._event(
                    AuthAuditEventType.USER_ROLE_CHANGED,
                    actor_user_id=actor.user_id,
                    subject_user_id=user_id,
                    summary="Administrative user role changed",
                    details={"from": current.role.value, "to": role.value},
                ),
            )
        if status is not None and status is not current.status:
            events.append(
                self._event(
                    AuthAuditEventType.USER_STATUS_CHANGED,
                    actor_user_id=actor.user_id,
                    subject_user_id=user_id,
                    summary="Administrative user status changed",
                    details={"from": current.status.value, "to": status.value},
                ),
            )
        if not events:
            return current
        try:
            return await self._repository.update_user_access(
                user_id=user_id,
                role=role,
                status=status,
                disabled_reason=disabled_reason,
                display_name=display_name,
                username=username,
                update_display_name=update_display_name,
                update_username=update_username,
                updated_at=now,
                events=events,
            )
        except LastActiveAdminError as exc:
            raise UserManagementError("last_active_admin") from exc

    async def revoke_user_sessions(self, *, actor: AdminUser, user_id: str) -> int:
        self._require_admin(actor)
        if await self._repository.get_user(user_id) is None:
            raise UserManagementError("user_not_found")
        now = self._clock.now()
        return await self._repository.revoke_user_sessions(
            user_id=user_id,
            now=now,
            reason="administrator_revoked_sessions",
            event=self._event(
                AuthAuditEventType.USER_SESSIONS_REVOKED,
                actor_user_id=actor.user_id,
                subject_user_id=user_id,
                summary="All administrative sessions revoked",
            ),
        )

    async def list_user_audit(self, *, actor: AdminUser, user_id: str) -> list[AuthAuditEvent]:
        self._require_admin(actor)
        if await self._repository.get_user(user_id) is None:
            raise UserManagementError("user_not_found")
        return await self._repository.list_auth_audit_events(subject_user_id=user_id)

    async def _issue_session(
        self,
        *,
        user: AdminUser,
        ip_scope: str,
        user_agent: str | None,
        old_session_token: str | None,
        now: datetime,
    ) -> IssuedSession:
        session_token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        session = AdminSession(
            session_id=self._ids.new(),
            user_id=user.user_id,
            token_hmac=self._session_hmac(session_token),
            csrf_hmac=self._csrf_hmac(csrf_token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=self._policy.session_ttl_seconds),
            request_ip_hash=ip_scope,
            request_user_agent_hash=self._optional_scope_hmac("user_agent", user_agent),
        )
        old_token_hmac = (
            self._session_hmac(old_session_token) if old_session_token is not None else None
        )
        identity = await self._repository.create_session(
            session=session,
            old_token_hmac=old_token_hmac,
            login_at=now,
            event=self._event(
                AuthAuditEventType.LOGIN_SUCCEEDED,
                actor_user_id=user.user_id,
                subject_user_id=user.user_id,
                request_ip_hash=ip_scope,
                summary="Telegram one-time code login succeeded",
                details={"session_expires_at": session.expires_at.isoformat()},
            ),
        )
        return IssuedSession(
            identity=identity,
            session_token=session_token,
            csrf_token=csrf_token,
        )

    async def _record_failed_verification(
        self,
        *,
        user: AdminUser,
        ip_scope: str,
        now: datetime,
    ) -> None:
        updated = await self._repository.record_auth_failure(
            user_id=user.user_id,
            now=now,
            lockout_failures=self._policy.lockout_failures,
            lockout_until=now + timedelta(seconds=self._policy.lockout_seconds),
        )
        await self._repository.save_audit_event(
            self._event(
                AuthAuditEventType.LOGIN_FAILED,
                subject_user_id=user.user_id,
                request_ip_hash=ip_scope,
                summary="Telegram one-time code verification failed",
                details={
                    "temporarily_locked": (
                        updated.auth_locked_until is not None and now < updated.auth_locked_until
                    ),
                },
            ),
        )

    async def _consume_request_limits(
        self,
        *,
        identity_scope: str,
        ip_scope: str,
        global_scope: str,
        now: datetime,
    ) -> bool:
        since = now - timedelta(seconds=self._policy.rate_window_seconds)
        limits = [
            AuthRateLimit(
                scope=scope,
                scope_hmac=scope_hmac,
                actions=("request",),
                limit=limit,
            )
            for scope, scope_hmac, limit in (
                ("telegram", identity_scope, self._policy.request_limit_per_user),
                ("ip", ip_scope, self._policy.request_limit_per_ip),
                ("global", global_scope, self._policy.global_request_limit),
            )
        ]
        events = [
            AuthRateEvent(
                event_id=self._ids.new(),
                scope=scope,
                scope_hmac=scope_hmac,
                action="request",
                occurred_at=now,
            )
            for scope, scope_hmac in (
                ("telegram", identity_scope),
                ("ip", ip_scope),
                ("global", global_scope),
            )
        ]
        return await self._repository.consume_rate_events(
            events=events,
            limits=limits,
            since=since,
        )

    async def _consume_verify_limit(self, *, ip_scope: str, now: datetime) -> bool:
        return await self._repository.consume_rate_events(
            events=[
                AuthRateEvent(
                    event_id=self._ids.new(),
                    scope="ip",
                    scope_hmac=ip_scope,
                    action="verify",
                    occurred_at=now,
                ),
            ],
            limits=[
                AuthRateLimit(
                    scope="ip",
                    scope_hmac=ip_scope,
                    actions=("verify",),
                    limit=self._policy.verify_limit_per_ip,
                ),
            ],
            since=now - timedelta(seconds=self._policy.rate_window_seconds),
        )

    async def _identity_lock(self, telegram_id: int) -> asyncio.Lock:
        async with self._identity_locks_guard:
            return self._identity_locks.setdefault(telegram_id, asyncio.Lock())

    def _require_hmac(self) -> None:
        if self._hmac_key is None:
            raise AuthenticationUnavailableError

    def _otp_hmac(self, challenge_id: str, telegram_id: int, code: str) -> str:
        return self._digest(f"otp:{challenge_id}:{telegram_id}:{code}")

    def _session_hmac(self, token: str) -> str:
        return self._digest(f"session:{token}")

    def _csrf_hmac(self, token: str) -> str:
        return self._digest(f"csrf:{token}")

    def _scope_hmac(self, scope: str, value: str) -> str:
        return self._digest(f"scope:{scope}:{value}")

    def _optional_scope_hmac(self, scope: str, value: str | None) -> str | None:
        return self._scope_hmac(scope, value[:512]) if value else None

    def _digest(self, value: str) -> str:
        self._require_hmac()
        if self._hmac_key is None:
            raise AuthenticationUnavailableError
        return hmac.new(self._hmac_key, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def _dummy_code_work(self, telegram_id: int) -> None:
        self._digest(f"unknown:{telegram_id}:{secrets.token_hex(8)}")

    def _dummy_verify(self, code: str) -> None:
        candidate = self._digest(f"unknown-code:{code}")
        hmac.compare_digest(candidate, "0" * 64)

    def _generic_request_result(self) -> RequestCodeResult:
        return RequestCodeResult(
            message=(
                "If access is enabled, a login code was sent. If no message arrives, "
                "open the MANA bot, press Start, and request a new code."
            ),
            expires_in_seconds=self._policy.otp_ttl_seconds,
            resend_after_seconds=self._policy.resend_cooldown_seconds,
            bot_url=self._bot_url,
        )

    def _event(
        self,
        event_type: AuthAuditEventType,
        *,
        summary: str,
        actor_user_id: str | None = None,
        subject_user_id: str | None = None,
        request_ip_hash: str | None = None,
        details: dict[str, JsonValue] | None = None,
    ) -> AuthAuditEvent:
        return AuthAuditEvent(
            event_id=self._ids.new(),
            event_type=event_type,
            occurred_at=self._clock.now(),
            actor_user_id=actor_user_id,
            subject_user_id=subject_user_id,
            request_ip_hash=request_ip_hash,
            summary=summary,
            details=details or {},
        )

    @staticmethod
    def _require_admin(user: AdminUser) -> None:
        if user.role is not UserRole.ADMIN or user.status is not AdminUserStatus.ACTIVE:
            raise UserManagementError("admin_required")
