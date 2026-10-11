import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.cost_control import CostBudgetExceeded
from app.mana_operation_ai.application.ports import ConcurrentOperationError
from app.mana_operation_ai.application.workspace_actions import WorkspaceActionService
from app.mana_operation_ai.domain.agent_tools import AgentToolCall, AgentToolRecord
from app.mana_operation_ai.domain.chat import MessageCreate, TopicCreate
from app.mana_operation_ai.domain.chat import ProductScope as ChatProductScope
from app.mana_operation_ai.domain.cost_control import CostLimits, ProductScope, ResourceUsage
from app.mana_operation_ai.domain.enums import AgentRunStatus, AgentStatus, TriggerType, UserRole
from app.mana_operation_ai.domain.goals import GoalCommand, GoalCreate
from app.mana_operation_ai.domain.models import AgentDefinition, AgentRun, AgentSchedule, Analysis
from app.mana_operation_ai.domain.retention import EngagementAssessment
from app.mana_operation_ai.domain.shared_data import SourceBinding
from app.mana_operation_ai.domain.workspace_actions import WorkspaceActionDecision
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
from app.mana_operation_ai.infrastructure.persistence.workspace_actions import (
    SqlAlchemyWorkspaceActions,
)
from app.mana_operation_ai.infrastructure.persistence.workspace_events import (
    SqlAlchemyWorkspaceEvents,
)
from tests.test_operation_cost_ledger import Clock, attribution

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    POSTGRES_URL is None,
    reason="TEST_POSTGRES_URL is required for isolated PostgreSQL integration tests",
)


async def test_postgres_saved_task_paging_literal_search_and_scope() -> None:
    assert POSTGRES_URL is not None
    database = OperationDatabase(POSTGRES_URL)
    clock = Clock()
    chats = SqlAlchemyChatRepository(database, hourly_limit=20, daily_limit=200)
    await chats.initialize()
    repository = SqlAlchemyGoalRepository(database, clock)
    try:
        topic = await chats.create(
            "postgres-history-owner",
            TopicCreate(
                agent_id="operations-orchestrator", product="mana", title="Private saved tasks"
            ),
        )
        ids = []
        for index in range(7):
            goal = await repository.create(
                "postgres-history-owner",
                topic,
                GoalCreate(
                    request_id=uuid4(), objective=f"Историческая задача {index}: literal % _ text."
                ),
            )
            assert await repository.save(
                "postgres-history-owner", goal, goal.model_copy(update={"status": "completed"})
            )
            ids.append(goal.goal_id)
        before = clock.now() + timedelta(seconds=1)
        first = await repository.find_saved_tasks(
            "postgres-history-owner",
            topic.topic_id,
            "mana",
            before=before,
            query="literal % _",
            cursor=None,
        )
        assert len(first.goals) == 5 and first.next_cursor is not None
        second = await repository.find_saved_tasks(
            "postgres-history-owner",
            topic.topic_id,
            "mana",
            before=before,
            query="literal % _",
            cursor=first.next_cursor,
        )
        assert len(second.goals) == 2 and second.next_cursor is None
        assert {item.goal_id for item in first.goals + second.goals} == set(ids)
        assert not (
            await repository.find_saved_tasks(
                "postgres-history-owner",
                topic.topic_id,
                "mana",
                before=before,
                query="ИСТОРИЧЕСКАЯ",
                cursor=None,
            )
        ).goals
        scopes: list[tuple[str, ChatProductScope]] = [
            ("foreign-owner", "mana"),
            ("postgres-history-owner", "360rec"),
        ]
        for owner, product in scopes:
            with pytest.raises(ChatError):
                await repository.saved_task(owner, topic.topic_id, product, ids[0], before=before)
    finally:
        await database.dispose()


async def test_postgres_goal_claim_controls_fencing_and_recovery() -> None:
    assert POSTGRES_URL is not None
    databases = [OperationDatabase(POSTGRES_URL), OperationDatabase(POSTGRES_URL)]
    clock = Clock()
    chats = SqlAlchemyChatRepository(databases[0], hourly_limit=20, daily_limit=200)
    await chats.initialize()
    repos = [SqlAlchemyGoalRepository(db, clock, events_enabled=True) for db in databases]
    try:
        topic = await chats.create(
            "postgres-goal-owner",
            TopicCreate(
                agent_id="retention-agent", product="mana", title="Durable PostgreSQL goal"
            ),
        )
        request = GoalCreate(
            request_id=uuid4(),
            objective="Analyze retention using saved aggregate evidence.",
            execution_mode="agent",
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
        steered = await repos[1].command(
            "postgres-goal-owner",
            held.goal_id,
            GoalCommand(
                request_id=uuid4(),
                command="steer",
                expected_revision=held.revision,
                message="Only parent activity; keep payment records separate.",
            ),
        )
        assert steered.status == "running" and steered.lease_until == held.lease_until
        assert await repos[0].claim() is None
        assert not await repos[0].save(
            "postgres-goal-owner", held, held.model_copy(update={"result": "obsolete response"})
        )
        with_tool = steered.model_copy(
            update={
                "tools": [
                    AgentToolRecord(
                        call_id="pg-native-tool",
                        call=AgentToolCall(name="inspect_sources"),
                        status="started",
                        started_at=clock.now(),
                    )
                ]
            }
        )
        assert await repos[0].save("postgres-goal-owner", steered, with_tool)
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
        assert recovered.instructions == ["Only parent activity; keep payment records separate."]
        assert recovered.tools[0].status == "unknown"
        resumed = await repos[1].command(
            "postgres-goal-owner",
            held.goal_id,
            GoalCommand(request_id=uuid4(), command="resume", expected_revision=recovered.revision),
        )
        assert resumed.status == "queued" and resumed.steps_used == 1
        page = await SqlAlchemyWorkspaceEvents(databases[1]).page(
            "postgres-goal-owner", topic.topic_id, 0
        )
        assert [event.revision for event in page.items] == list(range(resumed.revision + 1))
        assert len({event.event_id for event in page.items}) == len(page.items)
        assert page.items[-1].status == resumed.status
        assert page.items[-1].tools[0].status == "unknown"
        assert (
            await SqlAlchemyWorkspaceEvents(databases[0]).page(
                "postgres-goal-owner", topic.topic_id, page.next_cursor
            )
        ).items == []
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


async def test_postgres_action_intent_fences_independent_connections(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.core.config import get_settings
    from app.main import create_app
    from tests.test_operation_agent_workspace import configure_workspace
    from tests.test_workspace_actions import action_topic, decision, proposals

    assert POSTGRES_URL is not None
    configure_workspace(monkeypatch, tmp_path / "legacy-only.db")
    monkeypatch.setenv("OPERATION_DATABASE_URL", POSTGRES_URL)
    monkeypatch.setenv("OPERATION_DRY_RUN", "false")
    get_settings.cache_clear()
    app = create_app()
    second = OperationDatabase(POSTGRES_URL)
    try:
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            await proposals(client)
            topic, turn = await action_topic(app)
            first = app.state.operation_workspace_actions
            other = WorkspaceActionService(
                admin=app.state.operation_admin_service,
                chats=app.state.operation_chat_service.repository,
                store=SqlAlchemyWorkspaceActions(second),
                clock=first._clock,
                enabled=True,
                allow_self_approval=False,
            )
            page = await first.page("alice", topic, turn)
            proposal = page.items[0]
            payload = WorkspaceActionDecision.model_validate(decision(proposal.model_dump()))
            outcomes = await asyncio.gather(
                *[
                    (first if index % 2 else other).decide(
                        ActorContext("alice", UserRole.ADMIN),
                        topic,
                        turn,
                        proposal.proposal_id,
                        payload,
                    )
                    for index in range(12)
                ],
                return_exceptions=True,
            )
            assert any(not isinstance(item, BaseException) for item in outcomes)
            assert all(
                not isinstance(item, BaseException)
                or isinstance(item, ChatError)
                and item.status == 409
                for item in outcomes
            )
            assert app.state.operation_experiment_platform.dispatch_count == 1
            observed = await other.page("alice", topic, turn)
            assert observed.items[0].verification_status == "verified"
            assert observed.items[0].receipt is not None
            assert observed.items[0].receipt.state == "resolved"
            replay = await other.decide(
                ActorContext("alice", UserRole.ADMIN), topic, turn, proposal.proposal_id, payload
            )
            assert replay.verification_status == "verified"
            assert app.state.operation_experiment_platform.dispatch_count == 1
    finally:
        await second.dispose()
        get_settings.cache_clear()
