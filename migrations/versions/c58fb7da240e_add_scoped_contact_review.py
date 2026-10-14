"""Add exact single-action peer reviews without sharing private topics.

Revision ID: c58fb7da240e
Revises: b47ea6c9130d
"""

import sqlalchemy as sa
from alembic import op

revision = "c58fb7da240e"
down_revision = "b47ea6c9130d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_contact_review_grants",
        sa.Column("review_id", sa.String(36), primary_key=True),
        sa.Column(
            "owner", sa.String(36), sa.ForeignKey("operation_admin_users.user_id"), nullable=False
        ),
        sa.Column(
            "reviewer_id",
            sa.String(36),
            sa.ForeignKey("operation_admin_users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "action_id",
            sa.String(64),
            sa.ForeignKey("operation_retention_contacts.action_id"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("action_id", name="uq_contact_review_action"),
        sa.UniqueConstraint("owner", "request_id", name="uq_contact_review_request"),
    )
    op.create_index(
        "ix_operation_contact_review_grants_reviewer_id",
        "operation_contact_review_grants",
        ["reviewer_id"],
    )
    op.create_table(
        "operation_contact_review_events",
        sa.Column(
            "review_id",
            sa.String(36),
            sa.ForeignKey("operation_contact_review_grants.review_id"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("operation_contact_review_events", "operation_contact_review_grants"):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise RuntimeError("Cannot downgrade populated contact review history")
    op.drop_table("operation_contact_review_events")
    op.drop_index(
        "ix_operation_contact_review_grants_reviewer_id",
        table_name="operation_contact_review_grants",
    )
    op.drop_table("operation_contact_review_grants")
