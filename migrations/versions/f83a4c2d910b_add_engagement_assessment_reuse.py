"""Add scoped deterministic engagement result reuse.

Revision ID: f83a4c2d910b
Revises: e76b2d1c904a
"""

import sqlalchemy as sa
from alembic import op

revision = "f83a4c2d910b"
down_revision = "e76b2d1c904a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_engagement_assessments",
        sa.Column("assessment_key", sa.String(64), primary_key=True),
        sa.Column("product", sa.String(16), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_operation_engagement_assessments_valid_until",
        "operation_engagement_assessments",
        ["valid_until"],
    )


def downgrade() -> None:
    op.drop_table("operation_engagement_assessments")
