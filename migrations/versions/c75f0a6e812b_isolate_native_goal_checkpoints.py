"""Isolate native Goals from legacy worker claims and strict JSON readers.

Revision ID: c75f0a6e812b
Revises: b64e9c2f703d
"""

import sqlalchemy as sa
from alembic import op

revision = "c75f0a6e812b"
down_revision = "b64e9c2f703d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Additive only: no backfill, source reads, schedule changes or historical rewrites.
    op.add_column("operation_goals", sa.Column("workspace_status", sa.String(16), nullable=True))
    op.add_column("operation_goals", sa.Column("workspace_payload", sa.JSON(), nullable=True))
    op.create_index(
        "idx_operation_goals_workspace_status_updated",
        "operation_goals",
        ["workspace_status", "updated_at"],
    )


def downgrade() -> None:
    # Application rollback retains these columns/history. Schema downgrade is destructive
    # once native Goals exist and is therefore refused, even for completed Goals.
    connection = op.get_bind()
    count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM operation_goals "
            "WHERE workspace_status IS NOT NULL OR workspace_payload IS NOT NULL"
        )
    )
    if count:
        raise RuntimeError("Native Goal history exists; use application-only rollback instead")
    op.drop_index("idx_operation_goals_workspace_status_updated", "operation_goals")
    op.drop_column("operation_goals", "workspace_payload")
    op.drop_column("operation_goals", "workspace_status")
