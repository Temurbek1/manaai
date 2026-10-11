"""Persist public workspace notifications atomically with task checkpoints."""

import sqlalchemy as sa
from alembic import op

revision = "e97b2c0a134d"
down_revision = "d86a1b9f023c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_workspace_events",
        sa.Column(
            "event_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column(
            "topic_id",
            sa.String(36),
            sa.ForeignKey("operation_chat_topics.topic_id"),
            nullable=False,
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "idx_workspace_events_owner_topic_cursor",
        "operation_workspace_events",
        ["owner", "topic_id", "event_id"],
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text(
            "SELECT (SELECT COUNT(*) FROM operation_workspace_events) + "
            "(SELECT COUNT(*) FROM operation_goals WHERE workspace_payload IS NOT NULL "
            "OR workspace_status IS NOT NULL) + "
            "(SELECT COUNT(*) FROM operation_chat_turns WHERE workspace_metadata IS NOT NULL)"
        )
    )
    if count:
        raise RuntimeError("Workspace history exists; use application-only rollback instead")
    op.drop_index(
        "idx_workspace_events_owner_topic_cursor", table_name="operation_workspace_events"
    )
    op.drop_table("operation_workspace_events")
