"""Durable topic-owned human action intents; legacy action JSON remains unchanged."""

import sqlalchemy as sa
from alembic import op

revision = "f08c3d1b245e"
down_revision = "e97b2c0a134d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_workspace_actions",
        sa.Column("receipt_id", sa.String(36), primary_key=True),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column(
            "topic_id",
            sa.String(36),
            sa.ForeignKey("operation_chat_topics.topic_id"),
            nullable=False,
        ),
        sa.Column(
            "turn_id", sa.String(36), sa.ForeignKey("operation_chat_turns.turn_id"), nullable=False
        ),
        sa.Column(
            "proposal_id",
            sa.String(64),
            sa.ForeignKey("operation_action_proposals.proposal_id"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("proposal_id", name="uq_workspace_action_proposal"),
        sa.UniqueConstraint("owner", "request_id", name="uq_workspace_action_request"),
    )
    op.create_index(
        "idx_workspace_action_owner_topic_created",
        "operation_workspace_actions",
        ["owner", "topic_id", "created_at"],
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text(
            "SELECT (SELECT COUNT(*) FROM operation_workspace_actions) + "
            "(SELECT COUNT(*) FROM operation_workspace_events) + "
            "(SELECT COUNT(*) FROM operation_goals WHERE workspace_payload IS NOT NULL "
            "OR workspace_status IS NOT NULL) + "
            "(SELECT COUNT(*) FROM operation_chat_turns WHERE workspace_metadata IS NOT NULL)"
        )
    )
    if count:
        raise RuntimeError("Workspace history exists; use application-only rollback instead")
    op.drop_index(
        "idx_workspace_action_owner_topic_created", table_name="operation_workspace_actions"
    )
    op.drop_table("operation_workspace_actions")
