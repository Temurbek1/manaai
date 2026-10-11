"""Index owner-scoped keyset transcript pages.

Revision ID: a36d9f7b802c
Revises: f08c3d1b245e
"""

from alembic import op

revision = "a36d9f7b802c"
down_revision = "f08c3d1b245e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_chat_transcript_owner_topic_time",
        "operation_chat_turns",
        ["owner", "topic_id", "created_at", "turn_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_chat_transcript_owner_topic_time", table_name="operation_chat_turns")
