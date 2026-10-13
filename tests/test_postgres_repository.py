import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import func, select

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
from app.mana_operation_ai.domain.goals import GoalCommand, GoalCreate, GoalModelFeedback
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
from app.mana_operation_ai.infrastructure.persistence.models import AgentScheduleRow, ChatTurnRow
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


async def test_postgres_saved_report_catalog_keyset_json_literal_and_scope_fences() -> None:
    from app.mana_operation_ai.application.report_catalog import catalog_cursor
    from tests.test_saved_report_catalog import NOW, catalog_agents, catalog_report, search

    assert POSTGRES_URL is not None
    database = OperationDatabase(POSTGRES_URL)
    repository = SqlAlchemyOperationRepository(database)
    prefix = f"cat-{uuid4()}"
    query = search(query=prefix + " %_", scope_id=prefix)
    try:
        await catalog_agents(repository)
        for index in range(23):
            await catalog_report(repository, f"{prefix}-{index:03}", text=prefix + " %_")
        await catalog_report(repository, prefix + "-foreign", product="360rec", text=prefix + " %_")
        await catalog_report(repository, prefix + "-new", created_at=NOW, text=prefix + " %_")
        await catalog_report(repository, prefix + "-wildcard", text=prefix + " abcXYZ")
        first = await repository.page_report_candidates(query)
        assert first.next_cursor is not None
        second = await repository.page_report_candidates(query, cursor=first.next_cursor)
        assert second.next_cursor is not None
        third = await repository.page_report_candidates(query, cursor=second.next_cursor)
        ids = [item.report_id for page in (first, second, third) for item in page.reports]
        assert ids == [f"{prefix}-{index:03}" for index in range(22, -1, -1)]
        assert third.next_cursor is None
        assert await repository.page_report_candidates(query, cursor=first.next_cursor) == second
        with pytest.raises(ChatError, match="Курсор"):
            await repository.page_report_candidates(
                query.model_copy(update={"product": "360rec"}), cursor=first.next_cursor
            )
        forged = catalog_cursor(
            query, report_id=f"{prefix}-002", created_at=NOW - timedelta(seconds=4)
        )
        with pytest.raises(ChatError, match="Позиция"):
            await repository.page_report_candidates(query, cursor=forged)
    finally:
        await database.dispose()


@pytest.mark.parametrize("snapshots", [False, True])
async def test_postgres_catalog_capture_cursor_restart_and_legacy_projection(
    snapshots: bool,
) -> None:
    from app.mana_operation_ai.domain.agent_tools import AgentToolCall, AgentToolRecord
    from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
        SqlAlchemyGoalRepository,
    )
    from app.mana_operation_ai.infrastructure.persistence.models import GoalRow
    from tests.legacy_goal_contract import LegacyGoal

    assert POSTGRES_URL is not None
    database = OperationDatabase(POSTGRES_URL)
    clock = Clock()
    repository = SqlAlchemyGoalRepository(
        database,
        clock,
        report_discovery_enabled=True,
        limit_extensions_enabled=True,
        snapshot_replacement_enabled=snapshots,
    )
    chats = SqlAlchemyChatRepository(database, hourly_limit=20, daily_limit=200)
    owner = f"catalog-owner-{uuid4()}"
    try:
        await chats.initialize()
        topic = await chats.create(
            owner, TopicCreate(agent_id="operations-orchestrator", product="mana", title="Catalog")
        )
        goal = await repository.create(
            owner,
            topic,
            GoalCreate(
                request_id=uuid4(),
                objective="Keep the original MANA parent analysis",
                execution_mode="agent",
            ),
        )
        before = SqlAlchemyGoalRepository._storage(goal)
        assert before["workspace_payload"] is not None and before["workspace_payload"][
            "version"
        ] == (12 if snapshots else 11)
        changed = goal.model_copy(
            update={
                "tools": [
                    AgentToolRecord(
                        call_id="pg-catalog",
                        call=AgentToolCall(
                            name="find_saved_reports",
                            query="",
                            cursor="synthetic-position-" + "x" * 280,
                            catalog_capability="retention.parent_activity.analyze",
                        ),
                        status="completed",
                        started_at=clock.now(),
                        completed_at=clock.now(),
                        result="References only; no new source read",
                    )
                ],
                "accounted_microusd": 50000,
                "unsettled_microusd": 50000,
                "status": "waiting",
            }
        )
        if snapshots:
            import json

            from app.mana_operation_ai.infrastructure.goal_continuation import (
                finish_continuation,
                prepare_continuation,
            )

            prepared = prepare_continuation(
                context=json.dumps(
                    {"goal": changed.model_dump(mode="json", exclude={"model_continuation"})}
                ),
                owner=owner,
                state=None,
                model="synthetic-pg-model",
                maximum_bytes=192000,
            )
            changed.model_continuation = finish_continuation(
                prepared, [], model="synthetic-pg-model", call=None, maximum_bytes=192000
            )
        assert await repository.save(owner, goal, changed)
        restored = await SqlAlchemyGoalRepository(database, clock).get(owner, goal.goal_id)
        assert restored.report_discovery_enabled and restored.request == goal.request
        assert restored.snapshot_replacement_enabled == snapshots
        if snapshots:
            assert restored.model_continuation is not None
            assert changed.model_continuation is not None
            assert restored.model_continuation == changed.model_continuation
            assert len(restored.model_continuation.runtime_snapshots) == 1
        assert restored.tools[0].call.cursor == changed.tools[0].call.cursor
        assert restored.requested_capability is None and not restored.read_attempted
        assert restored.unsettled_microusd == restored.accounted_microusd == 50000
        with pytest.raises(ChatError):
            await repository.save(
                owner, restored, restored.model_copy(update={"report_discovery_enabled": False})
            )
        async with database.session_factory() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row is not None and row.workspace_payload is not None
            assert (
                row.workspace_payload["version"] == (12 if snapshots else 11)
                and "report_discovery_enabled" not in row.payload
                and "snapshot_replacement_enabled" not in row.payload
            )
            assert LegacyGoal.model_validate(row.payload).status == "cancelled"
    finally:
        await database.dispose()


async def test_postgres_v13_page_receipts_and_unknown_hold_restart() -> None:
    import json

    from app.mana_operation_ai.infrastructure.goal_continuation import (
        finish_continuation,
        prepare_continuation,
    )
    from tests.legacy_goal_contract import LegacyGoal
    from tests.test_page_projection import TEXT, page_goal

    assert POSTGRES_URL is not None
    database = OperationDatabase(POSTGRES_URL)
    clock = Clock()
    owner = f"page-owner-{uuid4()}"
    repository = SqlAlchemyGoalRepository(
        database,
        clock,
        limit_extensions_enabled=True,
        report_discovery_enabled=True,
        snapshot_replacement_enabled=True,
        page_projection_enabled=True,
    )
    chats = SqlAlchemyChatRepository(database, hourly_limit=20, daily_limit=200)
    try:
        await chats.initialize()
        topic = await chats.create(
            owner,
            TopicCreate(
                agent_id="operations-orchestrator", product="mana", title="Page references"
            ),
        )
        original = await repository.create(
            owner,
            topic,
            GoalCreate(
                request_id=uuid4(),
                objective="Keep the complete original parent analysis",
                execution_mode="agent",
            ),
        )
        fixture = page_goal()
        changed = original.model_copy(
            update={
                "tools": fixture.tools,
                "evidence": fixture.evidence,
                "accounted_microusd": 50000,
                "unsettled_microusd": 50000,
                "status": "waiting",
            }
        )
        before = changed.model_copy(update={"tools": []})
        prepared = prepare_continuation(
            context=json.dumps(
                {"goal": before.model_dump(mode="json", exclude={"model_continuation"})}
            ),
            owner=owner,
            state=None,
            model="fake-pg",
            maximum_bytes=192000,
        )
        call = changed.tools[0].call
        pending = finish_continuation(
            prepared,
            [
                {
                    "type": "function_call",
                    "id": "pg-fc",
                    "call_id": "pg-call",
                    "name": call.name,
                    "arguments": json.dumps({"report_id": call.report_id, "offset": call.offset}),
                }
            ],
            model="fake-pg",
            call=call,
            maximum_bytes=192000,
        )
        ready = prepare_continuation(
            context=json.dumps(
                {"goal": changed.model_dump(mode="json", exclude={"model_continuation"})}
            ),
            owner=owner,
            state=pending,
            model="fake-pg",
            maximum_bytes=192000,
        )
        changed.model_continuation = finish_continuation(
            ready, [], model="fake-pg", call=None, maximum_bytes=192000
        )
        assert await repository.save(owner, original, changed)
        restored = await SqlAlchemyGoalRepository(database, clock).get(owner, original.goal_id)
        assert restored.model_continuation == changed.model_continuation
        assert (
            restored.model_continuation is not None
            and len(restored.model_continuation.page_outputs) == 1
        )
        assert (
            restored.tools[0].result == fixture.tools[0].result
            and restored.evidence[0].summary == TEXT
        )
        assert (
            restored.request == original.request
            and restored.accounted_microusd == restored.unsettled_microusd == 50000
        )
        storage = repository._storage(restored)
        assert (
            storage["workspace_payload"] is not None
            and storage["workspace_payload"]["version"] == 13
        )
        assert "page_outputs" not in json.dumps(storage["payload"])
        assert LegacyGoal.model_validate(storage["payload"]).status == "cancelled"
    finally:
        await database.dispose()


async def test_postgres_limit_grant_v10_atomic_replay_unknown_hold_and_read_fence() -> None:
    from app.mana_operation_ai.domain.first_party_analytics import CHILD_TELEMETRY_CAPABILITY
    from app.mana_operation_ai.infrastructure.persistence.models import GoalRow
    from tests.legacy_goal_contract import LegacyGoal

    assert POSTGRES_URL is not None
    databases = [OperationDatabase(POSTGRES_URL), OperationDatabase(POSTGRES_URL)]
    clock = Clock()
    chats = SqlAlchemyChatRepository(databases[0], hourly_limit=100, daily_limit=1000)
    repositories = [
        SqlAlchemyGoalRepository(db, clock, limit_extensions_enabled=True) for db in databases
    ]
    owner = f"limits-{uuid4()}"
    try:
        await chats.initialize()
        topic = await chats.create(
            owner,
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Long task"),
        )
        goal = await repositories[0].create(
            owner,
            topic,
            GoalCreate(
                request_id=uuid4(),
                objective="Complete the same synthetic analysis.",
                execution_mode="agent",
            ),
        )
        stopped = goal.model_copy(
            update={
                "status": "waiting",
                "limit_stop": "steps",
                "steps_used": 6,
                "accounted_microusd": 10000,
                "read_attempted": True,
                "tools": [
                    AgentToolRecord(
                        call_id="already-consumed-read",
                        call=AgentToolCall(
                            name="request_source_read", capability=CHILD_TELEMETRY_CAPABILITY
                        ),
                        status="completed",
                        started_at=clock.now(),
                        completed_at=clock.now(),
                        result='{"report_id":"synthetic-saved"}',
                    )
                ],
            }
        )
        assert await repositories[0].save(owner, goal, stopped)
        stopped = await repositories[0].get(owner, goal.goal_id)
        grant = GoalCommand(
            request_id=uuid4(),
            command="extend_limits",
            expected_revision=stopped.revision,
            max_steps=12,
            budget_microusd=500000,
        )
        expanded = await asyncio.gather(
            *[repository.command(owner, goal.goal_id, grant) for repository in repositories]
        )
        assert expanded[0] == expanded[1] and len(expanded[0].limit_grants) == 1
        assert expanded[0].request == stopped.request
        assert expanded[0].read_attempted and expanded[0].approved_capability is None
        assert not await repositories[1].save(
            owner, stopped, stopped.model_copy(update={"result": "late"})
        )
        held = expanded[0].model_copy(
            update={
                "status": "running",
                "lease_until": clock.now() - timedelta(minutes=1),
                "accounted_microusd": 30000,
                "unsettled_microusd": 20000,
            }
        )
        assert await repositories[0].save(owner, expanded[0], held)
        await repositories[1].claim()
        recovered = await repositories[1].get(owner, goal.goal_id)
        assert recovered.status == "waiting" and recovered.unsettled_microusd == 20000
        assert recovered.accounted_microusd == 30000 and recovered.read_attempted
        with pytest.raises(ChatError):
            await repositories[1].command(
                owner,
                goal.goal_id,
                GoalCommand(
                    request_id=uuid4(), command="resume", expected_revision=recovered.revision
                ),
            )
        async with databases[0].session_factory() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row and row.workspace_payload and row.workspace_payload["version"] == 10
            assert LegacyGoal.model_validate(row.payload).status == "cancelled"
    finally:
        for database in databases:
            await database.dispose()


async def test_postgres_atomic_chat_stream_stop_recovery_and_bounds() -> None:
    from tests.test_chat_text_stream import assert_stream_atomicity

    assert POSTGRES_URL is not None
    await assert_stream_atomicity(POSTGRES_URL)


async def test_postgres_manual_read_v9_pending_and_unknown_restart_fences() -> None:
    from app.mana_operation_ai.domain.first_party_analytics import CHILD_TELEMETRY_CAPABILITY
    from app.mana_operation_ai.infrastructure.persistence.models import GoalRow
    from tests.legacy_goal_contract import LegacyGoal

    assert POSTGRES_URL is not None
    databases = [OperationDatabase(POSTGRES_URL), OperationDatabase(POSTGRES_URL)]
    clock = Clock()
    chats = SqlAlchemyChatRepository(databases[0], hourly_limit=100, daily_limit=1000)
    repositories = [SqlAlchemyGoalRepository(db, clock) for db in databases]
    owner = f"manual-{uuid4()}"
    try:
        await chats.initialize()
        topic = await chats.create(
            owner,
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Manual read"),
        )
        goal = await repositories[0].create(
            owner,
            topic,
            GoalCreate(
                request_id=uuid4(),
                objective="Synthetic source read; no provider I/O.",
                execution_mode="agent",
            ),
        )
        pending = goal.model_copy(
            update={
                "status": "waiting",
                "requested_capability": CHILD_TELEMETRY_CAPABILITY,
                "tools": [
                    AgentToolRecord(
                        call_id="pg-manual-read",
                        call=AgentToolCall(
                            name="request_source_read", capability=CHILD_TELEMETRY_CAPABILITY
                        ),
                        status="awaiting_approval",
                        started_at=clock.now(),
                    )
                ],
            }
        )
        assert await repositories[0].save(owner, goal, pending)
        reloaded = await repositories[1].get(owner, goal.goal_id)
        async with databases[1].session_factory() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row and row.workspace_payload and row.workspace_payload["version"] == 9
            assert LegacyGoal.model_validate(row.payload).requested_capability is None
            original_payload = row.workspace_payload
        approved = await repositories[1].command(
            owner,
            goal.goal_id,
            GoalCommand(
                request_id=uuid4(), command="approve_read", expected_revision=reloaded.revision
            ),
        )
        consumed = approved.model_copy(
            deep=True,
            update={
                "status": "running",
                "requested_capability": None,
                "approved_capability": None,
                "read_attempted": True,
                "accounted_microusd": 90000,
                "lease_until": clock.now() - timedelta(minutes=1),
            },
        )
        consumed.tools[0].status = "started"
        assert await repositories[0].save(owner, approved, consumed)
        assert await repositories[1].claim() is None
        lost = await repositories[0].get(owner, goal.goal_id)
        assert lost.status == "waiting" and lost.read_attempted
        assert lost.tools[0].status == "unknown" and lost.accounted_microusd == 90000
        async with databases[1].session_factory.begin() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row and row.workspace_payload and row.workspace_payload["version"] == 9
            row.workspace_payload = {**row.workspace_payload, "version": 8}
        with pytest.raises(ChatError, match="совместимости"):
            await repositories[0].get(owner, goal.goal_id)
        # Restore the isolated fixture before later archive checks inspect it.
        async with databases[1].session_factory.begin() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row and row.workspace_payload
            row.workspace_payload = {
                **row.workspace_payload,
                "version": original_payload["version"],
            }
    finally:
        await asyncio.gather(*(db.dispose() for db in databases))


@pytest.mark.parametrize("replanning", [False, True])
async def test_postgres_paged_evidence_v8_restart_and_idempotent_control(replanning: bool) -> None:
    import json

    from app.mana_operation_ai.domain.goals import GoalEvidence, ReportReadProgress
    from app.mana_operation_ai.infrastructure.goal_continuation import (
        finish_continuation,
        prepare_continuation,
    )
    from app.mana_operation_ai.infrastructure.persistence.models import GoalRow
    from tests.legacy_goal_contract import LegacyGoal

    assert POSTGRES_URL is not None
    databases = [OperationDatabase(POSTGRES_URL), OperationDatabase(POSTGRES_URL)]
    clock = Clock()
    chats = SqlAlchemyChatRepository(databases[0], hourly_limit=100, daily_limit=1000)
    repositories = [SqlAlchemyGoalRepository(db, clock, events_enabled=True) for db in databases]
    owner = f"pages-{uuid4()}"
    try:
        await chats.initialize()
        topic = await chats.create(
            owner, TopicCreate(agent_id="operations-orchestrator", product="mana", title="Pages")
        )
        goal = await repositories[0].create(
            owner,
            topic,
            GoalCreate(
                request_id=uuid4(),
                objective="Read the complete saved report.",
                execution_mode="agent",
            ),
        )
        text = "Synthetic report " + "x" * 8100 + " EXACT FOOTER"
        digest = hashlib.sha256(text.encode()).hexdigest()
        evidence = GoalEvidence(
            report_id="synthetic-pg-report",
            capability_key="retention.engagement.analyze",
            product="mana",
            collected_at=clock.now(),
            fresh_until=clock.now() + timedelta(hours=1),
            refresh_status="cached",
            summary=text,
            report_read_progress=ReportReadProgress(
                source_fingerprint="b" * 64,
                full_text_sha256=digest,
                loaded_text_sha256=digest,
                total_characters=len(text),
                next_offset=len(text),
                quality_notes_complete=True,
            ),
        )
        changed = goal.model_copy(update={"evidence": [evidence], "accounted_microusd": 90000})
        if replanning:
            prepared = prepare_continuation(
                context=json.dumps({"goal": goal.model_dump(mode="json")}),
                owner=owner,
                state=None,
                model="test-model",
                maximum_bytes=192000,
            )
            call = AgentToolCall(
                name="read_saved_report_page", report_id=evidence.report_id, offset=5000
            )
            changed.model_continuation = finish_continuation(
                prepared,
                [
                    {
                        "type": "function_call",
                        "id": "pg-fc",
                        "call_id": "pg-call",
                        "name": call.name,
                        "arguments": json.dumps({"report_id": evidence.report_id, "offset": 5000}),
                    }
                ],
                model="test-model",
                call=call,
                maximum_bytes=192000,
            )
            changed.model_recoveries = 1
            changed.tools = [
                AgentToolRecord(
                    call_id="pg-local-error",
                    call=call,
                    status="denied",
                    started_at=clock.now(),
                    completed_at=clock.now(),
                    result=json.dumps({"code": "noncontiguous_page", "expected_offset": len(text)}),
                )
            ]
        assert await repositories[0].save(owner, goal, changed)
        restored = await repositories[1].get(owner, goal.goal_id)
        assert restored.evidence[0].summary == text
        assert restored.model_recoveries == int(replanning)
        assert restored.model_continuation == changed.model_continuation
        if replanning:
            acknowledged = prepare_continuation(
                context=json.dumps(
                    {"goal": restored.model_dump(mode="json", exclude={"model_continuation"})}
                ),
                owner=owner,
                state=restored.model_continuation,
                model="test-model",
                maximum_bytes=192000,
            )
            assert "noncontiguous_page" in str(acknowledged.items[-2])
        command = GoalCommand(
            request_id=uuid4(), command="pause", expected_revision=restored.revision
        )
        results = await asyncio.gather(
            *(repo.command(owner, goal.goal_id, command) for repo in repositories)
        )
        assert all(
            result.status == "paused" and result.revision == restored.revision + 1
            for result in results
        )
        assert all(result.accounted_microusd == 90000 for result in results)
        assert all(result.model_recoveries == int(replanning) for result in results)
        async with databases[1].session_factory() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row is not None and row.workspace_payload is not None
            assert row.workspace_payload["version"] == 8
            projection = LegacyGoal.model_validate(row.payload)
            assert projection.status == "cancelled"
            assert projection.evidence[0].shortened and len(projection.evidence[0].summary) == 5000
    finally:
        for db in databases:
            await db.dispose()


async def test_postgres_chat_and_goal_share_event_commit_order() -> None:
    from app.mana_operation_ai.application.runtime import SystemClock
    from app.mana_operation_ai.domain.workspace_events import ChatTextEvent, WorkspaceEvent
    from app.mana_operation_ai.infrastructure.persistence.models import GoalRow

    assert POSTGRES_URL is not None
    databases = [OperationDatabase(POSTGRES_URL), OperationDatabase(POSTGRES_URL)]
    chats = SqlAlchemyChatRepository(
        databases[0], hourly_limit=100, daily_limit=1000, stream_events_enabled=True
    )
    goals = SqlAlchemyGoalRepository(databases[0], SystemClock(), events_enabled=True)
    await chats.initialize()
    owner = f"commit-order-{uuid4()}"
    topic = await chats.create(
        owner, TopicCreate(agent_id="operations-orchestrator", product="mana", title="Commit order")
    )
    turn, _ = await chats.reserve(
        owner, topic.topic_id, MessageCreate(request_id=uuid4(), message="Chat")
    )
    goal = await goals.create(
        owner, topic, GoalCreate(request_id=uuid4(), objective="Journal ordering only")
    )
    events = SqlAlchemyWorkspaceEvents(databases[1])
    before = await events.notifications(owner, topic.topic_id, 0)
    other = SqlAlchemyChatRepository(
        databases[1], hourly_limit=100, daily_limit=1000, stream_events_enabled=True
    )
    writer: asyncio.Task[bool] | None = None
    try:
        async with databases[0].session_factory() as session, session.begin():
            await goals._lock(session)
            row = await session.get(GoalRow, goal.goal_id)
            assert row is not None
            goals._store(session, row, goal.model_copy(update={"revision": 1, "status": "paused"}))
            await session.flush()  # Allocate the earlier event ID but do not commit it yet.
            writer = asyncio.create_task(
                other.preview(owner, topic.topic_id, turn.turn_id, "Draft")
            )
            await asyncio.sleep(0.05)
            assert not writer.done()
            assert not (await events.notifications(owner, topic.topic_id, before.next_cursor)).items
        assert await asyncio.wait_for(writer, 3)
        after = await events.notifications(owner, topic.topic_id, before.next_cursor)
        assert len(after.items) == 2
        assert isinstance(after.items[0], WorkspaceEvent) and after.items[0].status == "paused"
        assert isinstance(after.items[1], ChatTextEvent) and after.items[1].delta == "Draft"
        assert after.items[0].event_id < after.items[1].event_id
    finally:
        if writer and not writer.done():
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)
        await asyncio.gather(*(db.dispose() for db in databases))


async def test_postgres_native_transcript_pages_and_frozen_constraints() -> None:
    from datetime import UTC, datetime

    from app.mana_operation_ai.application.chat_ports import ChatError
    from tests.test_chat_transcript import FIRST, seed_transcript

    assert POSTGRES_URL is not None
    database = OperationDatabase(POSTGRES_URL)
    chats = SqlAlchemyChatRepository(
        database, hourly_limit=20, daily_limit=200, topic_message_limit=1000
    )
    await chats.initialize()
    try:
        topic = await chats.create(
            "alice", TopicCreate(agent_id="operations-orchestrator", product="mana", title="Pages")
        )
        saved = await seed_transcript(database, topic)
        observed: list[str] = []
        cursor = None
        while True:
            page = await chats.transcript_page("alice", topic.topic_id, before=cursor, limit=17)
            observed[0:0] = [turn.turn_id for turn in page.turns]
            assert all(turn.session_memory is None for turn in page.turns)
            cursor = page.next_cursor
            if not page.has_more:
                break
        assert observed == [turn.turn_id for turn in saved]
        cutoff = datetime(2021, 1, 1, tzinfo=UTC)
        context = [
            record async for record in chats.user_context("alice", topic.topic_id, before=cutoff)
        ]
        assert len(context) == 110 and context[0].text == FIRST
        recent = await chats.recent_conversation("alice", topic.topic_id, before=cutoff)
        assert len(recent.turns) == 6 and recent.older_turns_omitted == 104
        with pytest.raises(ChatError):
            await chats.transcript_page("foreign-owner", topic.topic_id, before=None)
        assert (await chats.turn("alice", topic.topic_id, saved[0].turn_id)).message == FIRST
    finally:
        await database.dispose()


async def test_postgres_all_closed_goal_conditions_and_scoped_stream() -> None:
    from app.mana_operation_ai.application.session_context import OperationSessionContext
    from app.mana_operation_ai.domain.session import SessionMemory, SessionUserContext

    assert POSTGRES_URL is not None
    database = OperationDatabase(POSTGRES_URL)
    chats = SqlAlchemyChatRepository(database, hourly_limit=200, daily_limit=1000)
    await chats.initialize()
    clock = Clock(datetime(2020, 1, 1, tzinfo=UTC))
    goals = SqlAlchemyGoalRepository(database, clock)
    owner = f"archive-owner-{uuid4()}"
    try:
        topic = await chats.create(
            owner,
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Full archive"),
        )
        for index in range(105):
            goal = await goals.create(
                owner,
                topic,
                GoalCreate(
                    request_id=uuid4(),
                    objective="Historical analysis.",
                    constraints="No customer contact; budget $5." if index == 0 else "",
                ),
                session_memory=SessionMemory(
                    topic_id=topic.topic_id,
                    product="mana",
                    captured_at=clock.now(),
                    user_context=[
                        SessionUserContext(
                            kind="instruction",
                            text="No scheduled Firebase reads.",
                            origin_id="old-user-quote",
                        )
                    ],
                )
                if index == 0
                else None,
            )
            assert await goals.save(
                owner,
                goal,
                goal.model_copy(update={"status": "completed", "result": f"Result {index}"}),
            )
            clock.value += timedelta(seconds=1)
        cutoff = clock.now()
        reader = OperationSessionContext(chats, goals)
        memory = await reader.read(owner, topic.topic_id, before=cutoff)
        assert memory is not None
        assert any("$5" in item.text for item in memory.user_context)
        assert any("Firebase" in item.text for item in memory.user_context)
        assert len(memory.checkpoints) == 3 and memory.older_checkpoints_omitted == 102
        assert not [
            item
            async for item in goals.closed_context(
                "foreign", topic.topic_id, product="mana", before=cutoff
            )
        ]
        assert not [
            item
            async for item in goals.closed_context(
                owner, topic.topic_id, product="360rec", before=cutoff
            )
        ]
        assert not [
            item
            async for item in goals.closed_context(
                owner, topic.topic_id, product="mana", before=datetime(2019, 1, 1, tzinfo=UTC)
            )
        ]
        records = [
            item
            async for item in goals.closed_context(
                owner, topic.topic_id, product="mana", before=cutoff
            )
        ]
        assert (
            len(records) == 105
            and records[-1].request.constraints == "No customer contact; budget $5."
        )
    finally:
        await database.dispose()


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


async def test_postgres_private_continuation_checkpoint_and_scope() -> None:
    import json

    from app.mana_operation_ai.infrastructure.goal_continuation import (
        finish_continuation,
        prepare_continuation,
    )

    assert POSTGRES_URL is not None
    database = OperationDatabase(POSTGRES_URL)
    clock = Clock()
    chats = SqlAlchemyChatRepository(database, hourly_limit=20, daily_limit=200)
    repository = SqlAlchemyGoalRepository(database, clock, events_enabled=True)
    try:
        owner = "postgres-continuation-owner"
        topic = await chats.create(
            owner,
            TopicCreate(
                agent_id="operations-orchestrator", product="mana", title="Context checkpoint"
            ),
        )
        goal = await repository.create(
            owner,
            topic,
            GoalCreate(
                request_id=uuid4(),
                objective="Verify a private bounded MANA workspace continuation.",
                execution_mode="agent",
            ),
        )
        prepared = prepare_continuation(
            context=json.dumps({"goal": goal.model_dump(mode="json")}),
            owner=owner,
            state=None,
            model="test-model",
            maximum_bytes=192000,
        )
        state = finish_continuation(
            prepared,
            [{"type": "compaction", "id": "cmp_pg", "encrypted_content": "test-private-pg-state"}],
            model="test-model",
            call=None,
            maximum_bytes=192000,
        )
        changed = goal.model_copy(
            update={
                "model_continuation": state,
                "model_feedback": GoalModelFeedback(
                    code="invalid_decision", message="Synthetic correction only."
                ),
                "model_recoveries": 1,
            }
        )
        assert await repository.save(owner, goal, changed)
        reopened = SqlAlchemyGoalRepository(database, clock)
        saved = await reopened.get(owner, goal.goal_id)
        assert saved.model_continuation == state and saved.model_feedback == changed.model_feedback
        paused = await reopened.command(
            owner,
            saved.goal_id,
            GoalCommand(request_id=uuid4(), command="pause", expected_revision=saved.revision),
        )
        assert paused.model_continuation == state and paused.status == "paused"
        with pytest.raises(ChatError):
            await reopened.get("foreign-owner", goal.goal_id)
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
    # Other integration cases may already have today's synthetic chat rows.
    # Give this concurrency case exactly one remaining global slot, not a clean-DB assumption.
    async with first_db.session_factory() as session:
        used = await session.scalar(
            select(func.count())
            .select_from(ChatTurnRow)
            .where(ChatTurnRow.created_at >= datetime.now(UTC) - timedelta(days=1))
        )
    first = SqlAlchemyChatRepository(first_db, hourly_limit=1, daily_limit=(used or 0) + 1)
    second = SqlAlchemyChatRepository(second_db, hourly_limit=1, daily_limit=(used or 0) + 1)
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
