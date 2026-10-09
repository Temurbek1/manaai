"""Add durable shared operational resource admission.

Revision ID: e76b2d1c904a
Revises: d58e3a1b720f
"""

import sqlalchemy as sa
from alembic import op

revision = "e76b2d1c904a"
down_revision = "d58e3a1b720f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_cost_periods",
        sa.Column("period_key", sa.String(32), primary_key=True),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
    )
    op.create_table(
        "operation_cost_reservations",
        sa.Column("reservation_id", sa.String(36), primary_key=True),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_keys", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("actual", sa.JSON(), nullable=True),
        sa.Column("attribution", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_operation_cost_reservations_reserved_at",
        "operation_cost_reservations",
        ["reserved_at"],
    )
    op.create_table(
        "operation_shared_source_gates",
        sa.Column("binding_key", sa.String(64), primary_key=True),
        sa.Column("product", sa.String(16), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "operation_shared_aggregates",
        sa.Column("query_key", sa.String(64), primary_key=True),
        sa.Column(
            "binding_key",
            sa.String(64),
            sa.ForeignKey("operation_shared_source_gates.binding_key"),
            nullable=False,
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_operation_shared_aggregates_binding_key",
        "operation_shared_aggregates",
        ["binding_key"],
    )


def downgrade() -> None:
    op.drop_table("operation_shared_aggregates")
    op.drop_table("operation_shared_source_gates")
    op.drop_table("operation_cost_reservations")
    op.drop_table("operation_cost_periods")
