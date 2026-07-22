"""add Telegram OTP authentication

Revision ID: 8b7c2e4d901a
Revises: 6ddfe7f9abc8
Create Date: 2026-07-22 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8b7c2e4d901a"
down_revision: str | None = "6ddfe7f9abc8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operation_admin_users",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("auth_locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        op.f("ix_operation_admin_users_telegram_id"),
        "operation_admin_users",
        ["telegram_id"],
        unique=True,
    )
    for column in ("role", "status", "created_at", "last_login_at", "auth_locked_until"):
        op.create_index(
            op.f(f"ix_operation_admin_users_{column}"),
            "operation_admin_users",
            [column],
            unique=False,
        )

    op.create_table(
        "operation_auth_otp_challenges",
        sa.Column("challenge_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("code_hmac", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["operation_admin_users.user_id"]),
        sa.PrimaryKeyConstraint("challenge_id"),
        sa.UniqueConstraint(
            "user_id",
            "active_slot",
            name="uq_operation_auth_active_challenge",
        ),
    )
    op.create_index(
        "idx_operation_auth_challenge_user_issued",
        "operation_auth_otp_challenges",
        ["user_id", "issued_at"],
        unique=False,
    )
    for column in ("user_id", "telegram_id", "issued_at", "expires_at", "status"):
        op.create_index(
            op.f(f"ix_operation_auth_otp_challenges_{column}"),
            "operation_auth_otp_challenges",
            [column],
            unique=False,
        )

    op.create_table(
        "operation_admin_sessions",
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_hmac", sa.String(length=64), nullable=False),
        sa.Column("csrf_hmac", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["operation_admin_users.user_id"]),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index(
        "idx_operation_admin_session_user_expiry",
        "operation_admin_sessions",
        ["user_id", "expires_at"],
        unique=False,
    )
    for column, unique in (
        ("user_id", False),
        ("token_hmac", True),
        ("created_at", False),
        ("expires_at", False),
        ("revoked_at", False),
    ):
        op.create_index(
            op.f(f"ix_operation_admin_sessions_{column}"),
            "operation_admin_sessions",
            [column],
            unique=unique,
        )

    op.create_table(
        "operation_auth_audit_events",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("subject_user_id", sa.String(length=36), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["operation_admin_users.user_id"]),
        sa.ForeignKeyConstraint(["subject_user_id"], ["operation_admin_users.user_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "idx_operation_auth_audit_subject_time",
        "operation_auth_audit_events",
        ["subject_user_id", "occurred_at"],
        unique=False,
    )
    for column in ("event_type", "occurred_at", "actor_user_id", "subject_user_id"):
        op.create_index(
            op.f(f"ix_operation_auth_audit_events_{column}"),
            "operation_auth_audit_events",
            [column],
            unique=False,
        )

    op.create_table(
        "operation_auth_rate_events",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=24), nullable=False),
        sa.Column("scope_hmac", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "idx_operation_auth_rate_scope_time",
        "operation_auth_rate_events",
        ["scope", "scope_hmac", "action", "occurred_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_operation_auth_rate_events_occurred_at"),
        "operation_auth_rate_events",
        ["occurred_at"],
        unique=False,
    )

    op.create_table(
        "operation_auth_state",
        sa.Column("state_key", sa.String(length=64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("state_key"),
    )
    op.execute(
        sa.text(
            "INSERT INTO operation_auth_state (state_key, revision) VALUES ('admin_guard', 1)",
        ),
    )


def downgrade() -> None:
    op.drop_table("operation_auth_state")
    op.drop_index(
        op.f("ix_operation_auth_rate_events_occurred_at"),
        table_name="operation_auth_rate_events",
    )
    op.drop_index(
        "idx_operation_auth_rate_scope_time",
        table_name="operation_auth_rate_events",
    )
    op.drop_table("operation_auth_rate_events")
    op.drop_index(
        op.f("ix_operation_auth_audit_events_subject_user_id"),
        table_name="operation_auth_audit_events",
    )
    op.drop_index(
        op.f("ix_operation_auth_audit_events_actor_user_id"),
        table_name="operation_auth_audit_events",
    )
    op.drop_index(
        op.f("ix_operation_auth_audit_events_occurred_at"),
        table_name="operation_auth_audit_events",
    )
    op.drop_index(
        op.f("ix_operation_auth_audit_events_event_type"),
        table_name="operation_auth_audit_events",
    )
    op.drop_index(
        "idx_operation_auth_audit_subject_time",
        table_name="operation_auth_audit_events",
    )
    op.drop_table("operation_auth_audit_events")
    op.drop_index(
        op.f("ix_operation_admin_sessions_revoked_at"),
        table_name="operation_admin_sessions",
    )
    op.drop_index(
        op.f("ix_operation_admin_sessions_expires_at"),
        table_name="operation_admin_sessions",
    )
    op.drop_index(
        op.f("ix_operation_admin_sessions_created_at"),
        table_name="operation_admin_sessions",
    )
    op.drop_index(
        op.f("ix_operation_admin_sessions_token_hmac"),
        table_name="operation_admin_sessions",
    )
    op.drop_index(
        op.f("ix_operation_admin_sessions_user_id"),
        table_name="operation_admin_sessions",
    )
    op.drop_index(
        "idx_operation_admin_session_user_expiry",
        table_name="operation_admin_sessions",
    )
    op.drop_table("operation_admin_sessions")
    for column in ("status", "expires_at", "issued_at", "telegram_id", "user_id"):
        op.drop_index(
            op.f(f"ix_operation_auth_otp_challenges_{column}"),
            table_name="operation_auth_otp_challenges",
        )
    op.drop_index(
        "idx_operation_auth_challenge_user_issued",
        table_name="operation_auth_otp_challenges",
    )
    op.drop_table("operation_auth_otp_challenges")
    for column in ("auth_locked_until", "last_login_at", "created_at", "status", "role"):
        op.drop_index(
            op.f(f"ix_operation_admin_users_{column}"),
            table_name="operation_admin_users",
        )
    op.drop_index(
        op.f("ix_operation_admin_users_telegram_id"),
        table_name="operation_admin_users",
    )
    op.drop_table("operation_admin_users")
