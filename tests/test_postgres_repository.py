import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.cost_control import CostBudgetExceeded
from app.mana_operation_ai.application.ports import ConcurrentOperationError
from app.mana_operation_ai.domain.chat import MessageCreate, TopicCreate
from app.mana_operation_ai.domain.cost_control import CostLimits, ProductScope, ResourceUsage
from app.mana_operation_ai.domain.enums import AgentRunStatus, AgentStatus, TriggerType
from app.mana_operation_ai.domain.goals import GoalCommand, GoalCreate
from app.mana_operation_ai.domain.models import AgentDefinition, AgentRun, AgentSchedule, Analysis
from app.mana_operation_ai.domain.retention import EngagementAssessment
from app.mana_operation_ai.domain.shared_data import SourceBinding
from app.mana_operation_ai.infrastructure.persistence.assessment_store import (
    SqlAlchemyEngagementAssessmentStore,
)
from app.mana_operation_ai.infrastructure.persistence.chat_repository import (
    SqlAlchemyChatRepository,
)
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import AgentScheduleRow
from app.mana_operation_ai.infrastructure.persistence.repository import (
    SqlAlchemyOperationRepository,
)
from app.mana_operation_ai.infrastructure.persistence.shared_data_store import (
    SqlAlchemySharedDataStore,
)
from tests.test_operation_cost_ledger import Clock, attribution

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    POSTGRES_URL is None,
    reason="TEST_POSTGRES_URL is required for isolated PostgreSQL integration tests",
)


async def test_postgres_goal_claim_controls_fencing_and_recovery() -> None:
    assert POSTGRES_URL is not None
    databases = [OperationDatabase(POSTGRES_URL), OperationDatabase(POSTGRES_URL)]
    clock = Clock()
    chats = SqlAlchemyChatRepository(databases[0], hourly_limit=20, daily_limit=200)
    await chats.initialize()
    repos = [SqlAlchemyGoalRepository(db, clock) for db in databases]
    try:
        topic = await chats.create(
            "postgres-goal-owner",
            TopicCreate(
                agent_id="retention-agent", product="mana", title="Durable PostgreSQL goal"
            ),
        )
        request = GoalCreate(
            request_id=uuid4(), objective="Analyze retention using saved aggregate evidence."
        )
        created = await asyncio.gather(
            *[repos[i % 2].create("postgres-goal-owner", topic, request) for i in range(12)]
        )
        assert len({item.goal_id for item in created}) == 1
        claims = await asyncio.gather(*[repos[i % 2].claim() for i in range(20)])
        winners = [item for item in claims if item is not None]
        assert len(winners) == 1
        claimed = winners[0][1]
        assert await repos[0].save(
            "postgres-goal-owner",
            claimed,
            claimed.model_copy(update={"steps_used": 1, "accounted_microusd": 30_000}),
        )
        held = await repos[1].get("postgres-goal-owner", claimed.goal_id)
        pause = GoalCommand(request_id=uuid4(), command="pause", expected_revision=held.revision)
        paused = await repos[0].command("postgres-goal-owner", held.goal_id, pause)
        assert (
            await repos[1].command("postgres-goal-owner", held.goal_id, pause)
        ).status == "paused"
        assert not await repos[1].save(
            "postgres-goal-owner", held, held.model_copy(update={"status": "completed"})
        )
        with pytest.raises(ChatError, match="не найдена"):
            await repos[1].get("different-owner", held.goal_id)
        clock.value += timedelta(minutes=6)
        assert await repos[1].claim() is None
        recovered = await repos[0].get("postgres-goal-owner", held.goal_id)
        assert recovered.status == "paused" and recovered.lease_until is None
        assert recovered.accounted_microusd == paused.accounted_microusd == 30_000
        resumed = await repos[1].command(
            "postgres-goal-owner",
            held.goal_id,
            GoalCommand(request_id=uuid4(), command="resume", expected_revision=recovered.revision),
        )
        assert resumed.status == "queued" and resumed.steps_used == 1
    finally:
        for db in databases:
            await db.dispose()


async def test_postgres_shared_resource_admission_and_idempotent_settlement() -> None:
    assert POSTGRES_URL is not None
    databases = [OperationDatabase(POSTGRES_URL), OperationDatabase(POSTGRES_URL)]
    clock = Clock(datetime(2100, 1, 1, tzinfo=UTC))
    policy = CostLimits(
        daily=ResourceUsage(provider_requests=10, input_tokens=100),
        monthly=ResourceUsage(provider_requests=10, input_tokens=100),
    )
    ledgers = [SqlAlchemyCostLedger(db, clock=clock, limits=policy) for db in databases]
    try:
        admitted = await asyncio.gather(
            *[
                ledgers[index % 2].reserve(
                    ResourceUsage(provider_requests=1, input_tokens=8), attribution=attribution()
                )
                for index in range(30)
            ],
            return_exceptions=True,
        )
        assert sum(isinstance(item, CostBudgetExceeded) for item in admitted) == 20
        reservations = [item for item in admitted if not isinstance(item, BaseException)]
        assert len(reservations) == 10
        await asyncio.gather(
            *[
                ledgers[index % 2].settle(
                    reservations[0].reservation_id,
                    actual=ResourceUsage(provider_requests=1, input_tokens=2),
                )
                for index in range(8)
            ]
        )
        usage = (await ledgers[0].periods())[0].usage
        assert usage.provider_requests == 10 and usage.input_tokens == 74
    finally:
        for db in databases:
            await db.dispose()


async def test_postgres_shared_source_single_flight_and_durable_failure() -> None:
    assert POSTGRES_URL is not None
    databases = [OperationDatabase(POSTGRES_URL), OperationDatabase(POSTGRES_URL)]
    clock = Clock()
    stores = [SqlAlchemySharedDataStore(db, clock=clock) for db in databases]
    source = SourceBinding(product="mana", source="fixture-ga4", fingerprint="a" * 64)
    key = hashlib.sha256(b"fixture-query").hexdigest()
    try:
        claims = await asyncio.gather(
            *[stores[index % 2].admit(source, query_key=key) for index in range(20)]
        )
        winners = [claim for claim in claims if claim.token is not None]
        assert len(winners) == 1
        await stores[0].fail(winners[0], permanent=True)
        clock.value += timedelta(days=1)
        assert (await stores[1].admit(source, query_key=key)).reason == "blocked"
    finally:
        for db in databases:
            await db.dispose()


async def test_postgres_assessment_reuse_is_immutable_and_product_scoped() -> None:
    assert POSTGRES_URL is not None
    databases = [OperationDatabase(POSTGRES_URL), OperationDatabase(POSTGRES_URL)]
    stores = [SqlAlchemyEngagementAssessmentStore(db) for db in databases]
    now = datetime(2026, 10, 8, 12, tzinfo=UTC)
    key = hashlib.sha256(b"postgres-assessment-fixture").hexdigest()
    result = EngagementAssessment(
        product=ProductScope.MANA,
        valid_until=now + timedelta(hours=6),
        analysis=Analysis(
            analysis_id="pg-assessment",
            run_id="pg-fixture",
            snapshot_id="pg-fixture",
            calculated_at=now,
            metrics={},
            baseline_metrics={},
            data_quality_score=1,
        ),
        findings=[],
    )
    try:
        await stores[0].put(key, result)
        changed = result.model_copy(update={"valid_until": now + timedelta(days=1)})
        await asyncio.gather(*[stores[index % 2].put(key, changed) for index in range(16)])
        assert await stores[1].get(key, product=ProductScope.MANA, now=now) == result
        assert await stores[1].get(key, product=ProductScope.REC360, now=now) is None
        assert await stores[1].get(key, product=ProductScope.MANA, now=result.valid_until) is None
    finally:
        for db in databases:
            await db.dispose()


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
