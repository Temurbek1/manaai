"""Keep native chat/session fields out of supported legacy readers.

Revision ID: d86a1b9f023c
Revises: c75f0a6e812b
"""

import sqlalchemy as sa
from alembic import op

revision = "d86a1b9f023c"
down_revision = "c75f0a6e812b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Prior checkpoint was unreleased. Do not rewrite historical conversation contents.
    op.add_column("operation_chat_turns", sa.Column("workspace_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text(
            "SELECT (SELECT COUNT(*) FROM operation_chat_turns "
            "WHERE workspace_metadata IS NOT NULL) + "
            "(SELECT COUNT(*) FROM operation_goals "
            "WHERE workspace_status IS NOT NULL OR workspace_payload IS NOT NULL)"
        )
    )
    if count:
        raise RuntimeError("Workspace history exists; use application-only rollback instead")
    op.drop_column("operation_chat_turns", "workspace_metadata")
