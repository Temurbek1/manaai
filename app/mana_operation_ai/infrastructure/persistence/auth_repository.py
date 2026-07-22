from datetime import datetime
from typing import cast

from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.mana_operation_ai.application.auth_ports import (
    AdminUserAlreadyExistsError,
    LastActiveAdminError,
)
from app.mana_operation_ai.application.ports import ConcurrentOperationError
from app.mana_operation_ai.domain.auth import (
    AdminSession,
    AdminUser,
    AuthAuditEvent,
    AuthenticatedIdentity,
    AuthRateEvent,
    AuthRateLimit,
    OtpChallenge,
)
from app.mana_operation_ai.domain.enums import (
    AdminUserStatus,
    OtpChallengeStatus,
    UserRole,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    AdminSessionRow,
    AdminUserRow,
    AuthAuditEventRow,
    AuthRateEventRow,
    AuthStateRow,
    OtpChallengeRow,
)


class SqlAlchemyAdminAuthRepository:
    def __init__(self, database: OperationDatabase) -> None:
        self._database = database

    async def bootstrap_admin(self, *, user: AdminUser, event: AuthAuditEvent) -> AdminUser:
        async with self._database.session_factory.begin() as session:
            await _lock_auth_state(session)
            row = (
                await session.scalars(
                    select(AdminUserRow)
                    .where(AdminUserRow.telegram_id == user.telegram_id)
                    .with_for_update(),
                )
            ).one_or_none()
            if row is None:
                effective = user
                session.add(_user_row(effective))
            else:
                current = AdminUser.model_validate(row.payload)
                effective = current.model_copy(
                    update={
                        "role": UserRole.ADMIN,
                        "status": AdminUserStatus.ACTIVE,
                        "updated_at": user.updated_at,
                        "disabled_reason": None,
                    },
                )
                _apply_user(row, effective)
            session.add(
                _audit_row(
                    event.model_copy(update={"subject_user_id": effective.user_id}),
                ),
            )
        return effective

    async def get_user(self, user_id: str) -> AdminUser | None:
        async with self._database.session_factory() as session:
            row = await session.get(AdminUserRow, user_id)
        return AdminUser.model_validate(row.payload) if row is not None else None

    async def get_user_by_telegram_id(self, telegram_id: int) -> AdminUser | None:
        statement = select(AdminUserRow).where(AdminUserRow.telegram_id == telegram_id)
        async with self._database.session_factory() as session:
            row = (await session.scalars(statement)).one_or_none()
        return AdminUser.model_validate(row.payload) if row is not None else None

    async def list_users(self) -> list[AdminUser]:
        async with self._database.session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(AdminUserRow).order_by(
                            AdminUserRow.created_at,
                            AdminUserRow.user_id,
                        ),
                    )
                ).all(),
            )
        return [AdminUser.model_validate(row.payload) for row in rows]

    async def create_user(self, *, user: AdminUser, event: AuthAuditEvent) -> AdminUser:
        try:
            async with self._database.session_factory.begin() as session:
                session.add(_user_row(user))
                session.add(_audit_row(event))
        except IntegrityError as exc:
            raise AdminUserAlreadyExistsError from exc
        return user

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
    ) -> AdminUser:
        async with self._database.session_factory.begin() as session:
            await _lock_auth_state(session)
            row = (
                await session.scalars(
                    select(AdminUserRow).where(AdminUserRow.user_id == user_id).with_for_update(),
                )
            ).one_or_none()
            if row is None:
                raise LookupError("Administrative user was not found")
            current = AdminUser.model_validate(row.payload)
            next_role = role or current.role
            next_status = status or current.status
            removing_active_admin = (
                current.role is UserRole.ADMIN
                and current.status is AdminUserStatus.ACTIVE
                and (next_role is not UserRole.ADMIN or next_status is not AdminUserStatus.ACTIVE)
            )
            if removing_active_admin:
                active_admins = int(
                    (
                        await session.scalar(
                            select(func.count())
                            .select_from(AdminUserRow)
                            .where(
                                AdminUserRow.role == UserRole.ADMIN.value,
                                AdminUserRow.status == AdminUserStatus.ACTIVE.value,
                            ),
                        )
                    )
                    or 0,
                )
                if active_admins <= 1:
                    raise LastActiveAdminError
            effective_reason = (
                None
                if next_status is AdminUserStatus.ACTIVE
                else disabled_reason or current.disabled_reason
            )
            updated = current.model_copy(
                update={
                    "role": next_role,
                    "status": next_status,
                    "disabled_reason": effective_reason,
                    "display_name": display_name if update_display_name else current.display_name,
                    "username": username if update_username else current.username,
                    "consecutive_auth_failures": (
                        0
                        if next_status is AdminUserStatus.ACTIVE
                        and current.status is not AdminUserStatus.ACTIVE
                        else current.consecutive_auth_failures
                    ),
                    "auth_locked_until": (
                        None
                        if next_status is AdminUserStatus.ACTIVE
                        and current.status is not AdminUserStatus.ACTIVE
                        else current.auth_locked_until
                    ),
                    "updated_at": updated_at,
                },
            )
            _apply_user(row, updated)
            if next_status is not AdminUserStatus.ACTIVE:
                await _revoke_sessions_in_transaction(
                    session,
                    user_id=user_id,
                    now=updated_at,
                    reason=f"user_{next_status.value}",
                )
                await _invalidate_challenges_in_transaction(session, user_id=user_id)
            session.add_all([_audit_row(event) for event in events])
        return updated

    async def reserve_challenge(
        self,
        *,
        challenge: OtpChallenge,
        cooldown_since: datetime,
    ) -> bool:
        try:
            async with self._database.session_factory.begin() as session:
                await _lock_auth_state(session)
                active_rows = list(
                    (
                        await session.scalars(
                            select(OtpChallengeRow).where(
                                OtpChallengeRow.user_id == challenge.user_id,
                                OtpChallengeRow.status == OtpChallengeStatus.ACTIVE.value,
                            ),
                        )
                    ).all(),
                )
                if any(
                    OtpChallenge.model_validate(row.payload).issued_at > cooldown_since
                    for row in active_rows
                ):
                    return False
                for row in active_rows:
                    invalidated = OtpChallenge.model_validate(row.payload).model_copy(
                        update={"status": OtpChallengeStatus.INVALIDATED},
                    )
                    _apply_challenge(row, invalidated)
                session.add(_challenge_row(challenge))
        except IntegrityError as exc:
            raise ConcurrentOperationError("OTP challenge reservation was contended") from exc
        return True

    async def get_active_challenge(self, *, user_id: str) -> OtpChallenge | None:
        statement = (
            select(OtpChallengeRow)
            .where(
                OtpChallengeRow.user_id == user_id,
                OtpChallengeRow.status == OtpChallengeStatus.ACTIVE.value,
                OtpChallengeRow.active_slot == 1,
            )
            .order_by(OtpChallengeRow.issued_at.desc())
            .limit(1)
        )
        async with self._database.session_factory() as session:
            row = (await session.scalars(statement)).first()
        return OtpChallenge.model_validate(row.payload) if row is not None else None

    async def apply_challenge_attempt(
        self,
        *,
        challenge_id: str,
        correct: bool,
        now: datetime,
        max_attempts: int,
    ) -> OtpChallenge | None:
        async with self._database.session_factory.begin() as session:
            row = await session.get(OtpChallengeRow, challenge_id)
            if row is None or row.status != OtpChallengeStatus.ACTIVE.value:
                return None
            current = OtpChallenge.model_validate(row.payload)
            if now >= current.expires_at:
                updated = current.model_copy(update={"status": OtpChallengeStatus.EXPIRED})
            elif correct:
                updated = current.model_copy(
                    update={
                        "status": OtpChallengeStatus.CONSUMED,
                        "consumed_at": now,
                    },
                )
            else:
                attempts = current.attempts_count + 1
                updated = current.model_copy(
                    update={
                        "attempts_count": attempts,
                        "status": (
                            OtpChallengeStatus.ATTEMPTS_EXHAUSTED
                            if attempts >= max_attempts
                            else OtpChallengeStatus.ACTIVE
                        ),
                    },
                )
            values = _challenge_values(updated)
            result = await session.execute(
                update(OtpChallengeRow)
                .where(
                    OtpChallengeRow.challenge_id == challenge_id,
                    OtpChallengeRow.status == OtpChallengeStatus.ACTIVE.value,
                    OtpChallengeRow.attempts_count == current.attempts_count,
                )
                .values(**values),
            )
            if result.rowcount != 1:
                return None
        return updated

    async def fail_challenge_delivery(self, *, challenge_id: str, now: datetime) -> None:
        del now
        async with self._database.session_factory.begin() as session:
            row = await session.get(OtpChallengeRow, challenge_id)
            if row is None or row.status != OtpChallengeStatus.ACTIVE.value:
                return
            updated = OtpChallenge.model_validate(row.payload).model_copy(
                update={"status": OtpChallengeStatus.DELIVERY_FAILED},
            )
            _apply_challenge(row, updated)

    async def consume_rate_events(
        self,
        *,
        events: list[AuthRateEvent],
        limits: list[AuthRateLimit],
        since: datetime,
    ) -> bool:
        async with self._database.session_factory.begin() as session:
            await _lock_auth_state(session)
            await session.execute(
                delete(AuthRateEventRow).where(AuthRateEventRow.occurred_at < since),
            )
            for limit in limits:
                count = int(
                    (
                        await session.scalar(
                            select(func.count())
                            .select_from(AuthRateEventRow)
                            .where(
                                AuthRateEventRow.scope == limit.scope,
                                AuthRateEventRow.scope_hmac == limit.scope_hmac,
                                AuthRateEventRow.action.in_(limit.actions),
                                AuthRateEventRow.occurred_at >= since,
                            ),
                        )
                    )
                    or 0,
                )
                if count >= limit.limit:
                    return False
            session.add_all([_rate_event_row(event) for event in events])
        return True

    async def record_auth_failure(
        self,
        *,
        user_id: str,
        now: datetime,
        lockout_failures: int,
        lockout_until: datetime,
    ) -> AdminUser:
        async with self._database.session_factory.begin() as session:
            row = (
                await session.scalars(
                    select(AdminUserRow).where(AdminUserRow.user_id == user_id).with_for_update(),
                )
            ).one()
            current = AdminUser.model_validate(row.payload)
            failures = (
                1
                if current.auth_locked_until is not None and now >= current.auth_locked_until
                else current.consecutive_auth_failures + 1
            )
            updated = current.model_copy(
                update={
                    "consecutive_auth_failures": failures,
                    "auth_locked_until": lockout_until if failures >= lockout_failures else None,
                    "updated_at": now,
                },
            )
            _apply_user(row, updated)
        return updated

    async def create_session(
        self,
        *,
        session: AdminSession,
        old_token_hmac: str | None,
        login_at: datetime,
        event: AuthAuditEvent,
    ) -> AuthenticatedIdentity:
        async with self._database.session_factory.begin() as database_session:
            if old_token_hmac is not None:
                old_row = (
                    await database_session.scalars(
                        select(AdminSessionRow).where(
                            AdminSessionRow.token_hmac == old_token_hmac,
                            AdminSessionRow.revoked_at.is_(None),
                        ),
                    )
                ).one_or_none()
                if old_row is not None:
                    old = AdminSession.model_validate(old_row.payload).model_copy(
                        update={
                            "revoked_at": login_at,
                            "revocation_reason": "session_rotated",
                        },
                    )
                    _apply_session(old_row, old)
            user_row = await database_session.get(AdminUserRow, session.user_id)
            if user_row is None:
                raise LookupError("Administrative user was not found")
            user = AdminUser.model_validate(user_row.payload).model_copy(
                update={
                    "last_login_at": login_at,
                    "updated_at": login_at,
                    "consecutive_auth_failures": 0,
                    "auth_locked_until": None,
                },
            )
            _apply_user(user_row, user)
            database_session.add(_session_row(session))
            database_session.add(_audit_row(event))
        return AuthenticatedIdentity(user=user, session=session)

    async def get_identity_by_session_hmac(
        self,
        *,
        token_hmac: str,
        now: datetime,
    ) -> AuthenticatedIdentity | None:
        async with self._database.session_factory.begin() as session:
            session_row = (
                await session.scalars(
                    select(AdminSessionRow).where(AdminSessionRow.token_hmac == token_hmac),
                )
            ).one_or_none()
            if session_row is None:
                return None
            admin_session = AdminSession.model_validate(session_row.payload)
            if admin_session.revoked_at is not None or now >= admin_session.expires_at:
                return None
            user_row = await session.get(AdminUserRow, admin_session.user_id)
            if user_row is None:
                return None
            user = AdminUser.model_validate(user_row.payload)
            if user.status is not AdminUserStatus.ACTIVE:
                return None
            touched = admin_session.model_copy(update={"last_seen_at": now})
            _apply_session(session_row, touched)
        return AuthenticatedIdentity(user=user, session=touched)

    async def revoke_session(
        self,
        *,
        token_hmac: str,
        now: datetime,
        reason: str,
        event: AuthAuditEvent | None,
    ) -> bool:
        async with self._database.session_factory.begin() as session:
            row = (
                await session.scalars(
                    select(AdminSessionRow).where(AdminSessionRow.token_hmac == token_hmac),
                )
            ).one_or_none()
            if row is None or row.revoked_at is not None:
                return False
            current = AdminSession.model_validate(row.payload).model_copy(
                update={"revoked_at": now, "revocation_reason": reason},
            )
            _apply_session(row, current)
            if event is not None:
                session.add(_audit_row(event))
        return True

    async def revoke_user_sessions(
        self,
        *,
        user_id: str,
        now: datetime,
        reason: str,
        event: AuthAuditEvent,
    ) -> int:
        async with self._database.session_factory.begin() as session:
            count = await _revoke_sessions_in_transaction(
                session,
                user_id=user_id,
                now=now,
                reason=reason,
            )
            session.add(_audit_row(event))
        return count

    async def save_audit_event(self, event: AuthAuditEvent) -> None:
        async with self._database.session_factory.begin() as session:
            session.add(_audit_row(event))

    async def list_auth_audit_events(
        self,
        *,
        subject_user_id: str | None = None,
        limit: int = 200,
    ) -> list[AuthAuditEvent]:
        filters = (
            [AuthAuditEventRow.subject_user_id == subject_user_id]
            if subject_user_id is not None
            else []
        )
        statement = (
            select(AuthAuditEventRow)
            .where(*filters)
            .order_by(AuthAuditEventRow.occurred_at.desc())
            .limit(limit)
        )
        async with self._database.session_factory() as session:
            rows = list((await session.scalars(statement)).all())
        return [AuthAuditEvent.model_validate(row.payload) for row in rows]


async def _lock_auth_state(session: AsyncSession) -> None:
    row = await session.get(AuthStateRow, "admin_guard", with_for_update=True)
    if row is None:
        session.add(AuthStateRow(state_key="admin_guard", revision=1))
        await session.flush()
    result = await session.execute(
        update(AuthStateRow)
        .where(AuthStateRow.state_key == "admin_guard")
        .values(revision=AuthStateRow.revision + 1),
    )
    if result.rowcount != 1:
        raise ConcurrentOperationError("Authentication state lock was not acquired")


async def _revoke_sessions_in_transaction(
    session: AsyncSession,
    *,
    user_id: str,
    now: datetime,
    reason: str,
) -> int:
    rows = list(
        (
            await session.scalars(
                select(AdminSessionRow).where(
                    AdminSessionRow.user_id == user_id,
                    AdminSessionRow.revoked_at.is_(None),
                ),
            )
        ).all(),
    )
    for row in rows:
        revoked = AdminSession.model_validate(row.payload).model_copy(
            update={"revoked_at": now, "revocation_reason": reason},
        )
        _apply_session(row, revoked)
    return len(rows)


async def _invalidate_challenges_in_transaction(
    session: AsyncSession,
    *,
    user_id: str,
) -> None:
    rows = list(
        (
            await session.scalars(
                select(OtpChallengeRow).where(
                    OtpChallengeRow.user_id == user_id,
                    OtpChallengeRow.status == OtpChallengeStatus.ACTIVE.value,
                ),
            )
        ).all(),
    )
    for row in rows:
        invalidated = OtpChallenge.model_validate(row.payload).model_copy(
            update={"status": OtpChallengeStatus.INVALIDATED},
        )
        _apply_challenge(row, invalidated)


def _payload(model: BaseModel) -> dict[str, object]:
    return cast(dict[str, object], model.model_dump(mode="json"))


def _user_row(user: AdminUser) -> AdminUserRow:
    return AdminUserRow(
        user_id=user.user_id,
        telegram_id=user.telegram_id,
        role=user.role.value,
        status=user.status.value,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
        created_by=user.created_by,
        auth_locked_until=user.auth_locked_until,
        payload=_payload(user),
    )


def _apply_user(row: AdminUserRow, user: AdminUser) -> None:
    row.role = user.role.value
    row.status = user.status.value
    row.updated_at = user.updated_at
    row.last_login_at = user.last_login_at
    row.auth_locked_until = user.auth_locked_until
    row.payload = _payload(user)


def _challenge_row(challenge: OtpChallenge) -> OtpChallengeRow:
    return OtpChallengeRow(
        challenge_id=challenge.challenge_id,
        user_id=challenge.user_id,
        telegram_id=challenge.telegram_id,
        code_hmac=challenge.code_hmac,
        issued_at=challenge.issued_at,
        expires_at=challenge.expires_at,
        consumed_at=challenge.consumed_at,
        attempts_count=challenge.attempts_count,
        status=challenge.status.value,
        active_slot=1 if challenge.status is OtpChallengeStatus.ACTIVE else None,
        payload=_payload(challenge),
    )


def _challenge_values(challenge: OtpChallenge) -> dict[str, object]:
    return {
        "consumed_at": challenge.consumed_at,
        "attempts_count": challenge.attempts_count,
        "status": challenge.status.value,
        "active_slot": 1 if challenge.status is OtpChallengeStatus.ACTIVE else None,
        "payload": _payload(challenge),
    }


def _apply_challenge(row: OtpChallengeRow, challenge: OtpChallenge) -> None:
    for key, value in _challenge_values(challenge).items():
        setattr(row, key, value)


def _session_row(session: AdminSession) -> AdminSessionRow:
    return AdminSessionRow(
        session_id=session.session_id,
        user_id=session.user_id,
        token_hmac=session.token_hmac,
        csrf_hmac=session.csrf_hmac,
        created_at=session.created_at,
        last_seen_at=session.last_seen_at,
        expires_at=session.expires_at,
        revoked_at=session.revoked_at,
        payload=_payload(session),
    )


def _apply_session(row: AdminSessionRow, session: AdminSession) -> None:
    row.last_seen_at = session.last_seen_at
    row.expires_at = session.expires_at
    row.revoked_at = session.revoked_at
    row.payload = _payload(session)


def _audit_row(event: AuthAuditEvent) -> AuthAuditEventRow:
    return AuthAuditEventRow(
        event_id=event.event_id,
        event_type=event.event_type.value,
        occurred_at=event.occurred_at,
        actor_user_id=event.actor_user_id,
        subject_user_id=event.subject_user_id,
        payload=_payload(event),
    )


def _rate_event_row(event: AuthRateEvent) -> AuthRateEventRow:
    return AuthRateEventRow(
        event_id=event.event_id,
        scope=event.scope,
        scope_hmac=event.scope_hmac,
        action=event.action,
        occurred_at=event.occurred_at,
    )
