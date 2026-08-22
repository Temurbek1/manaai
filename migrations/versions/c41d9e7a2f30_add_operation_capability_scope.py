"""add operation capability scope

Revision ID: c41d9e7a2f30
Revises: 8b7c2e4d901a
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c41d9e7a2f30"
down_revision: str | None = "8b7c2e4d901a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADVERTISING_CAPABILITY = "growth.advertising"


def _capability_for(agent_id: str | None) -> str | None:
    if agent_id is None:
        return None
    if agent_id in {"marketing-agent", "growth-agent"}:
        return ADVERTISING_CAPABILITY
    return f"{agent_id[:65]}.legacy"


def _backfill_payloads() -> None:
    connection = op.get_bind()
    metadata = sa.MetaData()
    metadata.reflect(
        connection,
        only=[
            "operation_agents",
            "operation_agent_configurations",
            "operation_agent_schedules",
            "operation_agent_runs",
            "operation_data_snapshots",
            "operation_audit_events",
        ],
    )
    agents = metadata.tables["operation_agents"]
    for row in connection.execute(
        sa.select(agents.c.agent_id, agents.c.definition),
    ).mappings():
        definition = dict(row["definition"])
        capability_key = _capability_for(row["agent_id"])
        definition.setdefault("default_capability_key", capability_key)
        normalized = []
        for capability in definition.get("capabilities", []):
            item = dict(capability)
            item.setdefault("agent_id", row["agent_id"])
            item.setdefault("input_schema", {})
            item.setdefault("output_schema", {})
            item.setdefault("required_integrations", [])
            item.setdefault("supported_triggers", [])
            normalized.append(item)
        definition["capabilities"] = normalized
        connection.execute(
            agents.update()
            .where(agents.c.agent_id == row["agent_id"])
            .values(definition=definition),
        )

    for table_name, primary_key in [
        ("operation_agent_configurations", "configuration_id"),
        ("operation_agent_schedules", "schedule_id"),
        ("operation_agent_runs", "run_id"),
        ("operation_data_snapshots", "snapshot_id"),
        ("operation_audit_events", "event_id"),
    ]:
        table = metadata.tables[table_name]
        for row in connection.execute(
            sa.select(table.c[primary_key], table.c.agent_id, table.c.payload),
        ).mappings():
            capability_key = _capability_for(row["agent_id"])
            payload = dict(row["payload"])
            payload.setdefault("capability_key", capability_key)
            values: dict[str, object] = {"payload": payload}
            if "capability_key" in table.c:
                values["capability_key"] = capability_key
            if table_name == "operation_agent_schedules" and row["agent_id"] == "marketing-agent":
                payload["enabled"] = False
                values["enabled"] = False
            connection.execute(
                table.update().where(table.c[primary_key] == row[primary_key]).values(**values),
            )


def _unique_name(table_name: str, columns: set[str], fallback: str) -> str:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints(table_name):
        if set(constraint["column_names"]) == columns and constraint.get("name"):
            return str(constraint["name"])
    return fallback


def upgrade() -> None:
    op.add_column(
        "operation_agent_configurations",
        sa.Column("capability_key", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "operation_agent_schedules",
        sa.Column("capability_key", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "operation_agent_runs",
        sa.Column("capability_key", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "operation_audit_events",
        sa.Column("capability_key", sa.String(length=80), nullable=True),
    )
    _backfill_payloads()

    naming_convention = {
        "uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s",
    }
    configuration_unique = _unique_name(
        "operation_agent_configurations",
        {"agent_id", "version"},
        "uq_operation_agent_configurations_agent_id_version",
    )
    with op.batch_alter_table(
        "operation_agent_configurations",
        naming_convention=naming_convention,
    ) as batch:
        batch.alter_column("capability_key", existing_type=sa.String(length=80), nullable=False)
        batch.drop_constraint(configuration_unique, type_="unique")
        batch.create_unique_constraint(
            "uq_operation_configuration_capability_version",
            ["agent_id", "capability_key", "version"],
        )
        batch.drop_index("idx_operation_configuration_active_version")
        batch.create_index(
            "idx_operation_configuration_active_version",
            ["agent_id", "capability_key", "active", "version"],
        )
        batch.create_index(
            "ix_operation_agent_configurations_capability_key",
            ["capability_key"],
        )

    run_unique = _unique_name(
        "operation_agent_runs",
        {"agent_id", "idempotency_key"},
        "uq_operation_agent_runs_agent_id_idempotency_key",
    )
    with op.batch_alter_table(
        "operation_agent_runs",
        naming_convention=naming_convention,
    ) as batch:
        batch.alter_column("capability_key", existing_type=sa.String(length=80), nullable=False)
        batch.drop_constraint(run_unique, type_="unique")
        batch.create_unique_constraint(
            "uq_operation_run_capability_idempotency",
            ["agent_id", "capability_key", "idempotency_key"],
        )
        batch.drop_index("idx_operation_run_agent_started")
        batch.create_index(
            "idx_operation_run_agent_started",
            ["agent_id", "capability_key", "started_at"],
        )
        batch.create_index("ix_operation_agent_runs_capability_key", ["capability_key"])

    with op.batch_alter_table("operation_agent_schedules") as batch:
        batch.alter_column("capability_key", existing_type=sa.String(length=80), nullable=False)
        batch.create_index("ix_operation_agent_schedules_capability_key", ["capability_key"])
    op.create_index(
        "ix_operation_audit_events_capability_key",
        "operation_audit_events",
        ["capability_key"],
    )

    op.create_table(
        "operation_outcome_evaluations",
        sa.Column("evaluation_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("proposal_id", sa.String(length=64), nullable=True),
        sa.Column("agent_id", sa.String(length=80), nullable=False),
        sa.Column("capability_key", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["operation_agent_runs.run_id"],
            name="fk_operation_outcome_run",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["operation_action_proposals.proposal_id"],
            name="fk_operation_outcome_proposal",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["operation_agents.agent_id"],
            name="fk_operation_outcome_agent",
        ),
        sa.PrimaryKeyConstraint("evaluation_id"),
    )
    op.create_index(
        "idx_operation_outcome_run_evaluated",
        "operation_outcome_evaluations",
        ["run_id", "evaluated_at"],
    )
    for column in ["run_id", "proposal_id", "agent_id", "capability_key", "status", "evaluated_at"]:
        op.create_index(
            f"ix_operation_outcome_evaluations_{column}",
            "operation_outcome_evaluations",
            [column],
        )


def downgrade() -> None:
    for column in ["evaluated_at", "status", "capability_key", "agent_id", "proposal_id", "run_id"]:
        op.drop_index(
            f"ix_operation_outcome_evaluations_{column}",
            table_name="operation_outcome_evaluations",
        )
    op.drop_index(
        "idx_operation_outcome_run_evaluated",
        table_name="operation_outcome_evaluations",
    )
    op.drop_table("operation_outcome_evaluations")

    naming_convention = {
        "uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s",
    }
    with op.batch_alter_table(
        "operation_agent_runs",
        naming_convention=naming_convention,
    ) as batch:
        batch.drop_index("ix_operation_agent_runs_capability_key")
        batch.drop_index("idx_operation_run_agent_started")
        batch.create_index("idx_operation_run_agent_started", ["agent_id", "started_at"])
        batch.drop_constraint("uq_operation_run_capability_idempotency", type_="unique")
        batch.create_unique_constraint(
            "uq_operation_agent_runs_agent_id_idempotency_key",
            ["agent_id", "idempotency_key"],
        )
        batch.drop_column("capability_key")
    with op.batch_alter_table(
        "operation_agent_configurations",
        naming_convention=naming_convention,
    ) as batch:
        batch.drop_index("ix_operation_agent_configurations_capability_key")
        batch.drop_index("idx_operation_configuration_active_version")
        batch.create_index(
            "idx_operation_configuration_active_version",
            ["agent_id", "active", "version"],
        )
        batch.drop_constraint("uq_operation_configuration_capability_version", type_="unique")
        batch.create_unique_constraint(
            "uq_operation_agent_configurations_agent_id_version",
            ["agent_id", "version"],
        )
        batch.drop_column("capability_key")
    with op.batch_alter_table("operation_agent_schedules") as batch:
        batch.drop_index("ix_operation_agent_schedules_capability_key")
        batch.drop_column("capability_key")
    op.drop_index(
        "ix_operation_audit_events_capability_key",
        table_name="operation_audit_events",
    )
    op.drop_column("operation_audit_events", "capability_key")
