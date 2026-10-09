"""Add private durable goal workspaces.

Revision ID: a19d38f610ac
Revises: f83a4c2d910b
"""

import sqlalchemy as sa
from alembic import op

revision = "a19d38f610ac"
down_revision = "f83a4c2d910b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_goals",
        sa.Column("goal_id", sa.String(36), primary_key=True),
        sa.Column(
            "topic_id",
            sa.String(36),
            sa.ForeignKey("operation_chat_topics.topic_id"),
            nullable=False,
        ),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("owner", "request_id", name="uq_goal_request"),
    )
    for column in ("topic_id", "owner", "status", "updated_at"):
        op.create_index(f"ix_operation_goals_{column}", "operation_goals", [column])
    op.create_table(
        "operation_goal_commands",
        sa.Column("command_id", sa.String(36), primary_key=True),
        sa.Column(
            "goal_id", sa.String(36), sa.ForeignKey("operation_goals.goal_id"), nullable=False
        ),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("goal_id", "request_id", name="uq_goal_command"),
    )
    op.create_index("ix_operation_goal_commands_goal_id", "operation_goal_commands", ["goal_id"])


def downgrade() -> None:
    op.drop_table("operation_goal_commands")
    op.drop_table("operation_goals")
