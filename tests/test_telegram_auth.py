import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.mana_operation_ai.application.auth_ports import (
    TelegramDeliveryError,
    TelegramDeliveryFailure,
)
from app.mana_operation_ai.application.auth_service import (
    AdminAuthService,
    AuthenticationError,
    UserManagementError,
)
from app.mana_operation_ai.application.runtime import UuidGenerator
from app.mana_operation_ai.domain.auth import AuthPolicy
from app.mana_operation_ai.domain.enums import (
    AdminUserStatus,
    OtpChallengeStatus,
    UserRole,
)
from app.mana_operation_ai.infrastructure.persistence.auth_repository import (
    SqlAlchemyAdminAuthRepository,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    AdminSessionRow,
    OtpChallengeRow,
)

HMAC_SECRET = "test-only-auth-hmac-secret-with-high-entropy-123456789"
BOOTSTRAP_TELEGRAM_ID = 976835256


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 22, 12, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, **kwargs: int) -> None:
        self.current += timedelta(**kwargs)


class CapturingTelegramSender:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, int]] = []
        self.failure: TelegramDeliveryFailure | None = None

    async def send_login_code(self, *, telegram_id: int, code: str, ttl_seconds: int) -> None:
        if self.failure is not None:
            raise TelegramDeliveryError(self.failure)
        self.messages.append((telegram_id, code, ttl_seconds))


def policy(**overrides: int) -> AuthPolicy:
    values = {
        "otp_ttl_seconds": 60,
        "resend_cooldown_seconds": 5,
        "max_verify_attempts": 3,
        "request_limit_per_user": 5,
        "request_limit_per_ip": 20,
        "verify_limit_per_ip": 30,
        "global_request_limit": 1_000,
        "rate_window_seconds": 900,
        "lockout_failures": 5,
        "lockout_seconds": 120,
        "session_ttl_seconds": 3_600,
    }
    values.update(overrides)
    return AuthPolicy.model_validate(values)


async def auth_fixture(
    database_path: Path,
    *,
    auth_policy: AuthPolicy | None = None,
) -> tuple[
    OperationDatabase,
    SqlAlchemyAdminAuthRepository,
    AdminAuthService,
    MutableClock,
    CapturingTelegramSender,
]:
    database = OperationDatabase(f"sqlite+aiosqlite:///{database_path}")
    await database.create_schema()
    repository = SqlAlchemyAdminAuthRepository(database)
    clock = MutableClock()
    sender = CapturingTelegramSender()
    service = AdminAuthService(
        repository=repository,
        sender=sender,
        clock=clock,
        ids=UuidGenerator(),
        policy=auth_policy or policy(),
        hmac_secret=HMAC_SECRET,
        bot_username="mana_test_bot",
    )
    await service.bootstrap_admins((BOOTSTRAP_TELEGRAM_ID,))
    return database, repository, service, clock, sender


async def test_otp_is_six_digits_hmac_only_exactly_sixty_seconds_and_single_use(
    tmp_path: Path,
) -> None:
    database, repository, service, clock, sender = await auth_fixture(tmp_path / "otp.db")
    try:
        result = await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="192.0.2.10",
            user_agent="pytest",
        )
        assert result.expires_in_seconds == 60
        assert result.bot_url == "https://t.me/mana_test_bot"
        assert len(sender.messages) == 1
        _, code, ttl = sender.messages[0]
        assert len(code) == 6 and code.isdigit()
        assert ttl == 60

        user = await repository.get_user_by_telegram_id(BOOTSTRAP_TELEGRAM_ID)
        assert user is not None
        challenge = await repository.get_active_challenge(user_id=user.user_id)
        assert challenge is not None
        assert challenge.expires_at - challenge.issued_at == timedelta(seconds=60)
        assert challenge.code_hmac != code
        assert "code" not in challenge.model_dump(exclude={"code_hmac"})

        issued = await service.verify_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            code=code,
            client_ip="192.0.2.10",
            user_agent="pytest",
            old_session_token=None,
        )
        assert issued.identity.user.user_id == user.user_id
        assert issued.session_token not in issued.identity.session.model_dump_json()
        assert issued.csrf_token not in issued.identity.session.model_dump_json()
        with pytest.raises(AuthenticationError, match="Authentication failed") as reused:
            await service.verify_code(
                telegram_id=BOOTSTRAP_TELEGRAM_ID,
                code=code,
                client_ip="192.0.2.10",
                user_agent="pytest",
                old_session_token=None,
            )
        assert reused.value.code == "invalid_or_expired_code"
    finally:
        await database.dispose()


async def test_expired_wrong_and_superseded_codes_are_rejected(tmp_path: Path) -> None:
    database, repository, service, clock, sender = await auth_fixture(tmp_path / "expiry.db")
    try:
        await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="192.0.2.11",
            user_agent=None,
        )
        first_code = sender.messages[-1][1]
        clock.advance(seconds=901)
        await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="192.0.2.11",
            user_agent=None,
        )
        second_code = sender.messages[-1][1]
        assert first_code != second_code
        with pytest.raises(AuthenticationError) as superseded:
            await service.verify_code(
                telegram_id=BOOTSTRAP_TELEGRAM_ID,
                code=first_code,
                client_ip="192.0.2.11",
                user_agent=None,
                old_session_token=None,
            )
        assert superseded.value.code == "invalid_code"

        clock.advance(seconds=61)
        with pytest.raises(AuthenticationError) as expired:
            await service.verify_code(
                telegram_id=BOOTSTRAP_TELEGRAM_ID,
                code=second_code,
                client_ip="192.0.2.11",
                user_agent=None,
                old_session_token=None,
            )
        assert expired.value.code == "expired_code"

        async with database.session_factory() as session:
            rows = list((await session.scalars(select(OtpChallengeRow))).all())
        statuses = [OtpChallengeStatus(row.status) for row in rows]
        assert OtpChallengeStatus.INVALIDATED in statuses
        assert OtpChallengeStatus.EXPIRED in statuses
        assert all("code" not in row.payload or "code_hmac" in row.payload for row in rows)
    finally:
        await database.dispose()


async def test_unknown_identity_is_generic_and_never_delivered(tmp_path: Path) -> None:
    database, _, service, _, sender = await auth_fixture(tmp_path / "unknown.db")
    try:
        result = await service.request_code(
            telegram_id=123456789,
            client_ip="192.0.2.12",
            user_agent=None,
        )
        assert result.message.startswith("If access is enabled")
        assert sender.messages == []
        with pytest.raises(AuthenticationError) as invalid:
            await service.verify_code(
                telegram_id=123456789,
                code="000000",
                client_ip="192.0.2.12",
                user_agent=None,
                old_session_token=None,
            )
        assert invalid.value.code == "invalid_code"
    finally:
        await database.dispose()


async def test_concurrent_resends_reserve_only_one_active_code(tmp_path: Path) -> None:
    database, repository, service, clock, sender = await auth_fixture(
        tmp_path / "resend.db",
        auth_policy=policy(request_limit_per_user=100),
    )
    try:
        await asyncio.gather(
            *(
                service.request_code(
                    telegram_id=BOOTSTRAP_TELEGRAM_ID,
                    client_ip=f"192.0.2.{index}",
                    user_agent=None,
                )
                for index in range(1, 9)
            ),
        )
        assert len(sender.messages) == 1
        user = await repository.get_user_by_telegram_id(BOOTSTRAP_TELEGRAM_ID)
        assert user is not None
        assert await repository.get_active_challenge(user_id=user.user_id) is not None

        clock.advance(seconds=6)
        before = len(sender.messages)
        await asyncio.gather(
            *(
                service.request_code(
                    telegram_id=BOOTSTRAP_TELEGRAM_ID,
                    client_ip=f"198.51.100.{index}",
                    user_agent=None,
                )
                for index in range(1, 9)
            ),
        )
        assert len(sender.messages) == before + 1
    finally:
        await database.dispose()


async def test_rate_limit_lockout_and_recovery(tmp_path: Path) -> None:
    database, _, service, clock, sender = await auth_fixture(
        tmp_path / "limits.db",
        auth_policy=policy(request_limit_per_user=1, lockout_failures=5),
    )
    try:
        await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="203.0.113.2",
            user_agent=None,
        )
        with pytest.raises(AuthenticationError) as limited:
            await service.request_code(
                telegram_id=BOOTSTRAP_TELEGRAM_ID,
                client_ip="203.0.113.3",
                user_agent=None,
            )
        assert limited.value.code == "rate_limited"
        clock.advance(seconds=901)
        await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="203.0.113.2",
            user_agent=None,
        )
        code = sender.messages[-1][1]
        for _ in range(3):
            with pytest.raises(AuthenticationError):
                await service.verify_code(
                    telegram_id=BOOTSTRAP_TELEGRAM_ID,
                    code="000000" if code != "000000" else "999999",
                    client_ip="203.0.113.2",
                    user_agent=None,
                    old_session_token=None,
                )
        clock.advance(seconds=901)
        await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="203.0.113.2",
            user_agent=None,
        )
        code = sender.messages[-1][1]
        for _ in range(2):
            with pytest.raises(AuthenticationError):
                await service.verify_code(
                    telegram_id=BOOTSTRAP_TELEGRAM_ID,
                    code="000000" if code != "000000" else "999999",
                    client_ip="203.0.113.2",
                    user_agent=None,
                    old_session_token=None,
                )
        with pytest.raises(AuthenticationError) as locked:
            await service.verify_code(
                telegram_id=BOOTSTRAP_TELEGRAM_ID,
                code=code,
                client_ip="203.0.113.2",
                user_agent=None,
                old_session_token=None,
            )
        assert locked.value.code == "temporarily_locked"
        clock.advance(seconds=901)
        await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="203.0.113.2",
            user_agent=None,
        )
        recovered_code = sender.messages[-1][1]
        issued = await service.verify_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            code=recovered_code,
            client_ip="203.0.113.2",
            user_agent=None,
            old_session_token=None,
        )
        assert issued.identity.user.auth_locked_until is None
    finally:
        await database.dispose()


async def test_bootstrap_is_idempotent_and_last_admin_and_self_guards_hold(
    tmp_path: Path,
) -> None:
    database, repository, service, _, _ = await auth_fixture(tmp_path / "admin.db")
    try:
        first = await repository.get_user_by_telegram_id(BOOTSTRAP_TELEGRAM_ID)
        assert first is not None
        created = await service.create_user(
            actor=first,
            telegram_id=51456737,
            role=UserRole.OPERATOR,
            display_name="Second User",
            username="second_user",
        )
        with pytest.raises(UserManagementError) as self_change:
            await service.update_user_access(
                actor=first,
                user_id=first.user_id,
                role=UserRole.VIEWER,
                status=None,
                disabled_reason=None,
            )
        assert self_change.value.code == "self_access_change_forbidden"

        with pytest.raises(UserManagementError) as last_admin:
            await service.update_user_access(
                actor=first,
                user_id=first.user_id,
                role=None,
                status=AdminUserStatus.DISABLED,
                disabled_reason="Security review",
            )
        assert last_admin.value.code == "self_access_change_forbidden"

        await service.bootstrap_admins((BOOTSTRAP_TELEGRAM_ID, 51456737))
        preserved = await repository.get_user(created.user_id)
        assert preserved is not None
        assert preserved.display_name == "Second User"
        assert preserved.username == "second_user"
        assert preserved.role is UserRole.ADMIN
        assert preserved.user_id == created.user_id
        assert len(await service.list_users()) == 2

        disabled_first = await service.update_user_access(
            actor=preserved,
            user_id=first.user_id,
            role=None,
            status=AdminUserStatus.DISABLED,
            disabled_reason="Access review",
        )
        assert disabled_first.status is AdminUserStatus.DISABLED
        with pytest.raises(UserManagementError) as last_admin:
            await service.update_user_access(
                actor=first,
                user_id=preserved.user_id,
                role=UserRole.VIEWER,
                status=None,
                disabled_reason=None,
            )
        assert last_admin.value.code == "last_active_admin"
    finally:
        await database.dispose()


async def test_disabled_user_is_denied_without_identity_enumeration(tmp_path: Path) -> None:
    database, repository, service, _, sender = await auth_fixture(tmp_path / "disabled.db")
    try:
        admin = await repository.get_user_by_telegram_id(BOOTSTRAP_TELEGRAM_ID)
        assert admin is not None
        user = await service.create_user(
            actor=admin,
            telegram_id=51456737,
            role=UserRole.VIEWER,
            display_name=None,
            username=None,
        )
        await service.update_user_access(
            actor=admin,
            user_id=user.user_id,
            role=None,
            status=AdminUserStatus.DISABLED,
            disabled_reason="Access removed",
        )
        known = await service.request_code(
            telegram_id=user.telegram_id,
            client_ip="192.0.2.20",
            user_agent=None,
        )
        unknown = await service.request_code(
            telegram_id=123123123,
            client_ip="192.0.2.21",
            user_agent=None,
        )
        assert known == unknown
        assert sender.messages == []
    finally:
        await database.dispose()


async def test_attempts_exhausted_and_resend_cooldown_are_enforced(tmp_path: Path) -> None:
    database, repository, service, _, sender = await auth_fixture(tmp_path / "attempts.db")
    try:
        await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="192.0.2.22",
            user_agent=None,
        )
        await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="192.0.2.22",
            user_agent=None,
        )
        assert len(sender.messages) == 1
        code = sender.messages[0][1]
        wrong = "000000" if code != "000000" else "999999"
        failures: list[str] = []
        for _ in range(3):
            with pytest.raises(AuthenticationError) as failure:
                await service.verify_code(
                    telegram_id=BOOTSTRAP_TELEGRAM_ID,
                    code=wrong,
                    client_ip="192.0.2.22",
                    user_agent=None,
                    old_session_token=None,
                )
            failures.append(failure.value.code)
        assert failures == ["invalid_code", "invalid_code", "attempts_exhausted"]
        user = await repository.get_user_by_telegram_id(BOOTSTRAP_TELEGRAM_ID)
        assert user is not None
        assert await repository.get_active_challenge(user_id=user.user_id) is None
    finally:
        await database.dispose()


async def test_per_ip_rate_limit_is_atomic(tmp_path: Path) -> None:
    database, _, service, _, _ = await auth_fixture(
        tmp_path / "ip-limit.db",
        auth_policy=policy(request_limit_per_user=100, request_limit_per_ip=2),
    )
    try:
        results = await asyncio.gather(
            *(
                service.request_code(
                    telegram_id=100000000 + index,
                    client_ip="198.51.100.50",
                    user_agent=None,
                )
                for index in range(8)
            ),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, Exception) for result in results) == 2
        limited = [result for result in results if isinstance(result, AuthenticationError)]
        assert len(limited) == 6
        assert all(result.code == "rate_limited" for result in limited)
    finally:
        await database.dispose()


async def test_concurrent_verification_creates_one_session(tmp_path: Path) -> None:
    database, _, service, _, sender = await auth_fixture(tmp_path / "verify-race.db")
    try:
        await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="192.0.2.23",
            user_agent=None,
        )
        code = sender.messages[-1][1]
        results = await asyncio.gather(
            *(
                service.verify_code(
                    telegram_id=BOOTSTRAP_TELEGRAM_ID,
                    code=code,
                    client_ip=f"192.0.2.{index}",
                    user_agent=None,
                    old_session_token=None,
                )
                for index in range(30, 38)
            ),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, Exception) for result in results) == 1
        assert sum(isinstance(result, AuthenticationError) for result in results) == 7
        async with database.session_factory() as session:
            sessions = list((await session.scalars(select(AdminSessionRow))).all())
        assert len(sessions) == 1
    finally:
        await database.dispose()


async def test_session_rotation_expiry_logout_and_delivery_failure(tmp_path: Path) -> None:
    database, repository, service, clock, sender = await auth_fixture(
        tmp_path / "sessions.db",
        auth_policy=policy(session_ttl_seconds=900),
    )
    try:
        await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="192.0.2.24",
            user_agent=None,
        )
        first = await service.verify_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            code=sender.messages[-1][1],
            client_ip="192.0.2.24",
            user_agent=None,
            old_session_token=None,
        )
        clock.advance(seconds=6)
        await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="192.0.2.24",
            user_agent=None,
        )
        second = await service.verify_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            code=sender.messages[-1][1],
            client_ip="192.0.2.24",
            user_agent=None,
            old_session_token=first.session_token,
        )
        assert await service.authenticate_session(first.session_token) is None
        assert await service.authenticate_session(second.session_token) is not None
        await service.logout(
            identity=second.identity,
            session_token=second.session_token,
            request_ip="192.0.2.24",
        )
        assert await service.authenticate_session(second.session_token) is None

        clock.advance(seconds=6)
        await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="192.0.2.24",
            user_agent=None,
        )
        expiring = await service.verify_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            code=sender.messages[-1][1],
            client_ip="192.0.2.24",
            user_agent=None,
            old_session_token=None,
        )
        clock.advance(seconds=900)
        assert await service.authenticate_session(expiring.session_token) is None

        clock.advance(seconds=6)
        sender.failure = TelegramDeliveryFailure.BOT_NOT_STARTED
        generic = await service.request_code(
            telegram_id=BOOTSTRAP_TELEGRAM_ID,
            client_ip="192.0.2.24",
            user_agent=None,
        )
        assert generic.message.startswith("If access is enabled")
        user = await repository.get_user_by_telegram_id(BOOTSTRAP_TELEGRAM_ID)
        assert user is not None
        assert await repository.get_active_challenge(user_id=user.user_id) is None
        audit = await repository.list_auth_audit_events(subject_user_id=user.user_id)
        assert any(event.event_type.value == "login_code_delivery_failed" for event in audit)
        serialized_audit = "\n".join(event.model_dump_json() for event in audit)
        assert all(code not in serialized_audit for _, code, _ in sender.messages)
    finally:
        await database.dispose()
