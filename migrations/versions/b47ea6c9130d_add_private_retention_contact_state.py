"""Isolate sandbox contact intents, recipient reservations and audit from old action JSON.

Revision ID: b47ea6c9130d
Revises: a36d9f7b802c
"""

import sqlalchemy as sa
from alembic import op

revision = "b47ea6c9130d"
down_revision = "a36d9f7b802c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_retention_contacts",
        sa.Column("action_id", sa.String(64), primary_key=True),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column(
            "topic_id",
            sa.String(36),
            sa.ForeignKey("operation_chat_topics.topic_id"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("decision_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("owner", "request_id", name="uq_retention_contact_request"),
        sa.UniqueConstraint("owner", "decision_id", name="uq_retention_contact_decision"),
    )
    op.create_index(
        "ix_operation_retention_contacts_owner", "operation_retention_contacts", ["owner"]
    )
    op.create_index(
        "ix_operation_retention_contacts_topic_id", "operation_retention_contacts", ["topic_id"]
    )
    op.create_table(
        "operation_retention_contact_guards",
        sa.Column("account_ref", sa.String(69), primary_key=True),
        sa.Column(
            "action_id",
            sa.String(64),
            sa.ForeignKey("operation_retention_contacts.action_id"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "operation_retention_contact_events",
        sa.Column(
            "action_id",
            sa.String(64),
            sa.ForeignKey("operation_retention_contacts.action_id"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    connection = op.get_bind()
    for name in [
        "operation_retention_contact_events",
        "operation_retention_contact_guards",
        "operation_retention_contacts",
    ]:
        if connection.execute(sa.text(f"SELECT 1 FROM {name} LIMIT 1")).first() is not None:
            raise RuntimeError("Cannot downgrade populated retention contact history")
    op.drop_table("operation_retention_contact_events")
    op.drop_table("operation_retention_contact_guards")
    op.drop_index(
        "ix_operation_retention_contacts_topic_id", table_name="operation_retention_contacts"
    )
    op.drop_index(
        "ix_operation_retention_contacts_owner", table_name="operation_retention_contacts"
    )
    op.drop_table("operation_retention_contacts")
