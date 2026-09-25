import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

from app.mana_operation_ai.domain.enums import AgentRunStatus, AgentStatus, TriggerType
from app.mana_operation_ai.domain.models import AgentDefinition, AgentRun, AgentSchedule
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.repository import (
    SqlAlchemyOperationRepository,
)

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    POSTGRES_URL is None,
    reason="TEST_POSTGRES_URL is required for isolated PostgreSQL integration tests",
)


async def test_postgres_distributed_claims_and_idempotent_run_creation() -> None:
    if POSTGRES_URL is None:
        raise AssertionError("TEST_POSTGRES_URL must be set after skip evaluation")
    database = OperationDatabase(POSTGRES_URL)
    repository = SqlAlchemyOperationRepository(database)
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    await repository.register_agent(
        AgentDefinition(
            agent_id="postgres-agent",
            display_name="PostgreSQL Agent",
            description="Exercises production database concurrency semantics",
            version="1.0.0",
            status=AgentStatus.ENABLED,
            capabilities=[],
            default_capability_key="postgres.default",
            configuration_schema={"type": "object"},
            registered_at=now,
        ),
    )
    lock_results = await asyncio.gather(
        *(
            repository.acquire_lock(
                key="postgres-concurrent-lock",
                owner_id=f"worker-{index}",
                now=now,
                expires_at=now + timedelta(minutes=5),
            )
            for index in range(16)
        ),
    )
    assert lock_results.count(True) == 1

    schedule = AgentSchedule(
        schedule_id="postgres-schedule",
        agent_id="postgres-agent",
        capability_key="postgres.default",
        job_type="analysis",
        cron_expression="0 */6 * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=now,
    )
    await repository.save_schedule(schedule)
    advanced = schedule.model_copy(
        update={"last_run_at": now, "next_run_at": now + timedelta(hours=6)},
    )
    claims = await asyncio.gather(
        *(repository.claim_schedule(current=schedule, advanced=advanced) for _ in range(16)),
    )
    assert claims.count(True) == 1

    template = AgentRun(
        run_id="postgres-run-0",
        agent_id="postgres-agent",
        capability_key="postgres.default",
        correlation_id="postgres-correlation",
        trigger=TriggerType.SCHEDULE,
        initiated_by="scheduler",
        status=AgentRunStatus.QUEUED,
        configuration_version=1,
        idempotency_key="postgres-one-occurrence",
        started_at=now,
        updated_at=now,
    )
    runs = await asyncio.gather(
        *(
            repository.create_run(
                template.model_copy(update={"run_id": f"postgres-run-{index}"}),
            )
            for index in range(16)
        ),
    )
    assert len({run.run_id for run in runs}) == 1
    await database.dispose()
