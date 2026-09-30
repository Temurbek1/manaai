import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.ports import ConcurrentOperationError
from app.mana_operation_ai.domain.chat import MessageCreate, TopicCreate
from app.mana_operation_ai.domain.enums import AgentRunStatus, AgentStatus, TriggerType
from app.mana_operation_ai.domain.models import AgentDefinition, AgentRun, AgentSchedule
from app.mana_operation_ai.infrastructure.persistence.chat_repository import (
    SqlAlchemyChatRepository,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import AgentScheduleRow
from app.mana_operation_ai.infrastructure.persistence.repository import (
    SqlAlchemyOperationRepository,
)

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    POSTGRES_URL is None,
    reason="TEST_POSTGRES_URL is required for isolated PostgreSQL integration tests",
)


async def test_postgres_chat_budget_serializes_across_connections() -> None:
    assert POSTGRES_URL is not None
    first_db = OperationDatabase(POSTGRES_URL)
    second_db = OperationDatabase(POSTGRES_URL)
    first = SqlAlchemyChatRepository(first_db, hourly_limit=1, daily_limit=1)
    second = SqlAlchemyChatRepository(second_db, hourly_limit=1, daily_limit=1)
    try:
        await first.initialize()
        topics = [
            await repository.create(
                owner,
                TopicCreate(
                    agent_id="growth-agent",
                    product="mana",
                    title="Concurrent budget test",
                ),
            )
            for repository, owner in ((first, "pg-chat-alice"), (second, "pg-chat-bob"))
        ]
        results = await asyncio.gather(
            first.reserve(
                "pg-chat-alice",
                topics[0].topic_id,
                MessageCreate(request_id=uuid4(), message="One"),
            ),
            second.reserve(
                "pg-chat-bob", topics[1].topic_id, MessageCreate(request_id=uuid4(), message="Two")
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, tuple) for result in results) == 1
        errors = [result for result in results if isinstance(result, ChatError)]
        assert len(errors) == 1 and errors[0].status == 429
    finally:
        await first_db.dispose()
        await second_db.dispose()


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
    # Existing production JSON predates the safety fields. Claims must still work
    # without a data migration, while all new writes persist the defaults.
    async with database.session_factory.begin() as session:
        row = await session.get(AgentScheduleRow, schedule.schedule_id)
        assert row is not None
        row.payload = {
            key: value
            for key, value in row.payload.items()
            if key not in {"circuit_open", "consecutive_permanent_failures"}
        }
    advanced = schedule.model_copy(
        update={"last_run_at": now, "next_run_at": now + timedelta(hours=6)},
    )
    claims = await asyncio.gather(
        *(repository.claim_schedule(current=schedule, advanced=advanced) for _ in range(16)),
    )
    assert claims.count(True) == 1

    tripped = advanced.model_copy(
        update={
            "enabled": False,
            "circuit_open": True,
            "consecutive_permanent_failures": 3,
        }
    )
    race = await asyncio.gather(
        repository.claim_schedule(current=advanced, advanced=tripped),
        *(repository.save_schedule(advanced) for _ in range(16)),
        return_exceptions=True,
    )
    assert race[0] is True
    assert all(
        result is None or isinstance(result, ConcurrentOperationError) for result in race[1:]
    )
    saved = (await repository.list_schedules("postgres-agent"))[0]
    assert saved.circuit_open and not saved.enabled
    assert saved.consecutive_permanent_failures == 3

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
