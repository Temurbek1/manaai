"""Bound fictional contact preparation before target reads, without rewriting history.

Revision ID: d69ac8eb351f
Revises: c58fb7da240e
"""

import sqlalchemy as sa
from alembic import op

revision = "d69ac8eb351f"
down_revision = "c58fb7da240e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_contact_preparation_gate",
        sa.Column("gate_id", sa.String(40), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
    )
    op.create_table(
        "operation_contact_preparations",
        sa.Column("claim_id", sa.String(36), primary_key=True),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column(
            "topic_id",
            sa.String(36),
            sa.ForeignKey("operation_chat_topics.topic_id"),
            nullable=False,
        ),
        sa.Column("turn_id", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("target_sha256", sa.String(64), nullable=False),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "action_id",
            sa.String(64),
            sa.ForeignKey("operation_retention_contacts.action_id"),
            nullable=True,
        ),
        sa.UniqueConstraint("owner", "request_id", name="uq_contact_preparation_request"),
        sa.UniqueConstraint("action_id"),
        sa.CheckConstraint(
            "(status = 'pending' AND action_id IS NULL) OR "
            "(status = 'recorded' AND action_id IS NOT NULL)",
            name="ck_contact_preparation_state",
        ),
    )
    for name, columns in [
        ("idx_contact_preparation_owner_time", ["owner", "admitted_at"]),
        ("idx_contact_preparation_turn", ["owner", "topic_id", "turn_id", "status"]),
        ("idx_contact_preparation_target", ["target_sha256", "status"]),
        ("ix_operation_contact_preparations_admitted_at", ["admitted_at"]),
    ]:
        op.create_index(name, "operation_contact_preparations", columns)


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("operation_contact_preparations", "operation_contact_preparation_gate"):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated preparation admissions or policy holds")
    op.drop_table("operation_contact_preparations")
    op.drop_table("operation_contact_preparation_gate")
