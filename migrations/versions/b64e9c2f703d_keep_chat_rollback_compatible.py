"""Keep new chat metadata separate from the prior release's persisted JSON.

Revision ID: b64e9c2f703d
Revises: a19d38f610ac
"""

import sqlalchemy as sa
from alembic import op

revision = "b64e9c2f703d"
down_revision = "a19d38f610ac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("operation_chat_turns", sa.Column("context_metadata", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("operation_chat_turns", "context_metadata")
