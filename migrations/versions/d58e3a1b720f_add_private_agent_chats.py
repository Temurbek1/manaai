"""Add private agent topics and bounded conversation turns.

Revision ID: d58e3a1b720f
Revises: c41d9e7a2f30
"""

import sqlalchemy as sa
from alembic import op

revision = "d58e3a1b720f"
down_revision = "c41d9e7a2f30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    budget = op.create_table(
        "operation_chat_budget",
        sa.Column("budget_id", sa.String(16), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "operation_chat_topics",
        sa.Column("topic_id", sa.String(36), primary_key=True),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "operation_chat_turns",
        sa.Column("turn_id", sa.String(36), primary_key=True),
        sa.Column(
            "topic_id",
            sa.String(36),
            sa.ForeignKey("operation_chat_topics.topic_id"),
            nullable=False,
        ),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("topic_id", "request_id", name="uq_chat_request"),
    )
    for table, columns in (
        ("operation_chat_topics", ("owner", "updated_at")),
        ("operation_chat_turns", ("topic_id", "owner", "status", "created_at")),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])
    op.bulk_insert(budget, [{"budget_id": "global", "revision": 0}])


def downgrade() -> None:
    for table in ("operation_chat_turns", "operation_chat_topics", "operation_chat_budget"):
        op.drop_table(table)
