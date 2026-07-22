"""harden operation constraints and indexes

Revision ID: 6ddfe7f9abc8
Revises: a57f606d9211
Create Date: 2026-07-22 16:25:16.145669
"""

from collections.abc import Sequence

from alembic import op

revision: str = "6ddfe7f9abc8"
down_revision: str | None = "a57f606d9211"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("operation_action_executions") as batch:
        batch.drop_index("ix_operation_action_executions_proposal_id")
        batch.create_index(
            "ix_operation_action_executions_proposal_id",
            ["proposal_id"],
            unique=True,
        )
        batch.create_index(
            "idx_operation_execution_status_attempted",
            ["status", "attempted_at"],
        )
        batch.create_foreign_key(
            "fk_operation_execution_run",
            "operation_agent_runs",
            ["run_id"],
            ["run_id"],
        )
    with op.batch_alter_table("operation_action_proposals") as batch:
        batch.create_index(
            "idx_operation_proposal_object_status",
            ["provider", "provider_object_id", "status"],
        )
        batch.create_index(
            "idx_operation_proposal_status_created",
            ["status", "created_at"],
        )
        batch.create_foreign_key(
            "fk_operation_proposal_agent",
            "operation_agents",
            ["agent_id"],
            ["agent_id"],
        )
    op.create_index(
        "idx_operation_configuration_active_version",
        "operation_agent_configurations",
        ["agent_id", "active", "version"],
    )
    with op.batch_alter_table("operation_agent_reports") as batch:
        batch.create_index(
            "idx_operation_report_agent_created",
            ["agent_id", "created_at"],
        )
        batch.create_unique_constraint(
            "uq_operation_report_run_type",
            ["run_id", "report_type"],
        )
        batch.create_foreign_key(
            "fk_operation_report_agent",
            "operation_agents",
            ["agent_id"],
            ["agent_id"],
        )
    op.create_index(
        "idx_operation_run_agent_started",
        "operation_agent_runs",
        ["agent_id", "started_at"],
    )
    op.create_index(
        "idx_operation_run_status_updated",
        "operation_agent_runs",
        ["status", "updated_at"],
    )
    op.create_index(
        "idx_operation_schedule_due",
        "operation_agent_schedules",
        ["enabled", "next_run_at"],
    )
    with op.batch_alter_table("operation_analyses") as batch:
        batch.drop_index("ix_operation_analyses_run_id")
        batch.create_index("ix_operation_analyses_run_id", ["run_id"], unique=True)
    with op.batch_alter_table("operation_approval_decisions") as batch:
        batch.create_foreign_key(
            "fk_operation_decision_proposal",
            "operation_action_proposals",
            ["proposal_id"],
            ["proposal_id"],
        )
    op.create_index(
        "idx_operation_approval_status_requested",
        "operation_approval_requests",
        ["status", "requested_at"],
    )
    with op.batch_alter_table("operation_audit_events") as batch:
        batch.create_index(
            "idx_operation_audit_run_occurred",
            ["run_id", "occurred_at"],
        )
        batch.create_foreign_key(
            "fk_operation_audit_run",
            "operation_agent_runs",
            ["run_id"],
            ["run_id"],
        )
        batch.create_foreign_key(
            "fk_operation_audit_agent",
            "operation_agents",
            ["agent_id"],
            ["agent_id"],
        )
    with op.batch_alter_table("operation_data_snapshots") as batch:
        batch.create_foreign_key(
            "fk_operation_snapshot_agent",
            "operation_agents",
            ["agent_id"],
            ["agent_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("operation_data_snapshots") as batch:
        batch.drop_constraint("fk_operation_snapshot_agent", type_="foreignkey")
    with op.batch_alter_table("operation_audit_events") as batch:
        batch.drop_constraint("fk_operation_audit_agent", type_="foreignkey")
        batch.drop_constraint("fk_operation_audit_run", type_="foreignkey")
        batch.drop_index("idx_operation_audit_run_occurred")
    op.drop_index(
        "idx_operation_approval_status_requested",
        table_name="operation_approval_requests",
    )
    with op.batch_alter_table("operation_approval_decisions") as batch:
        batch.drop_constraint("fk_operation_decision_proposal", type_="foreignkey")
    with op.batch_alter_table("operation_analyses") as batch:
        batch.drop_index("ix_operation_analyses_run_id")
        batch.create_index("ix_operation_analyses_run_id", ["run_id"])
    op.drop_index("idx_operation_schedule_due", table_name="operation_agent_schedules")
    op.drop_index("idx_operation_run_status_updated", table_name="operation_agent_runs")
    op.drop_index("idx_operation_run_agent_started", table_name="operation_agent_runs")
    with op.batch_alter_table("operation_agent_reports") as batch:
        batch.drop_constraint("fk_operation_report_agent", type_="foreignkey")
        batch.drop_constraint("uq_operation_report_run_type", type_="unique")
        batch.drop_index("idx_operation_report_agent_created")
    op.drop_index(
        "idx_operation_configuration_active_version",
        table_name="operation_agent_configurations",
    )
    with op.batch_alter_table("operation_action_proposals") as batch:
        batch.drop_constraint("fk_operation_proposal_agent", type_="foreignkey")
        batch.drop_index("idx_operation_proposal_status_created")
        batch.drop_index("idx_operation_proposal_object_status")
    with op.batch_alter_table("operation_action_executions") as batch:
        batch.drop_constraint("fk_operation_execution_run", type_="foreignkey")
        batch.drop_index("idx_operation_execution_status_attempted")
        batch.drop_index("ix_operation_action_executions_proposal_id")
        batch.create_index("ix_operation_action_executions_proposal_id", ["proposal_id"])
