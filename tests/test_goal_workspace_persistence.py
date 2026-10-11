import asyncio
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.agent_tools import AgentToolCall, AgentToolRecord
from app.mana_operation_ai.domain.chat import ChatTopic, MessageCreate, TopicCreate
from app.mana_operation_ai.domain.goals import (
    GoalCommand,
    GoalConversationTurn,
    GoalCreate,
    GoalStatus,
)
from app.mana_operation_ai.infrastructure.persistence.chat_repository import (
    SqlAlchemyChatRepository,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import ChatBudgetRow, GoalRow
from tests.legacy_goal_contract import LegacyGoal
from tests.test_operation_cost_ledger import Clock


async def topic(database: OperationDatabase) -> ChatTopic:
    chats = SqlAlchemyChatRepository(database, hourly_limit=20, daily_limit=200)
    await chats.initialize()
    return await chats.create(
        "owner", TopicCreate(agent_id="operations-orchestrator", product="mana", title="Test task")
    )


@pytest.mark.parametrize(
    "status", ["queued", "running", "paused", "waiting", "completed", "cancelled"]
)
async def test_native_checkpoint_has_closed_legacy_projection_and_lossless_restart(
    tmp_path: Path, status: GoalStatus
) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'native.db'}"
    db = OperationDatabase(url)
    await db.create_schema()
    clock = Clock()
    repository = SqlAlchemyGoalRepository(db, clock)
    native_topic = await topic(db)
    request = GoalCreate(
        request_id=uuid4(),
        objective="Analyze MANA parent retention, not children's activity.",
        execution_mode="agent",
        conversation_history=[
            GoalConversationTurn(user="Do not contact clients.", assistant="Understood.")
        ],
        older_turns_omitted=2,
    )
    created = await repository.create("owner", native_topic, request)
    changed = created.model_copy(
        update={
            "status": status,
            "lease_until": clock.now() + timedelta(minutes=5) if status == "running" else None,
            "steps_used": 2,
            "accounted_microusd": 70_000,
            "instructions": ["Payments need independent evidence."],
            "requested_capability": "retention.parents.analyze",
            "tools": [
                AgentToolRecord(
                    call_id="native-parent-approval",
                    call=AgentToolCall(
                        name="request_source_read", capability="retention.parents.analyze"
                    ),
                    status="awaiting_approval",
                    started_at=clock.now(),
                    result="Approval pending; source has not been read.",
                )
            ],
        }
    )
    assert await repository.save("owner", created, changed)
    saved = await repository.get("owner", created.goal_id)
    async with db.session_factory() as session:
        row = await session.get(GoalRow, created.goal_id)
        legacy_status = "completed" if status == "completed" else "cancelled"
        assert row is not None and row.workspace_status == status and row.status == legacy_status
        legacy = LegacyGoal.model_validate(row.payload)
        assert legacy.status == legacy_status and legacy.lease_until is None
        assert legacy.requested_capability is None and legacy.approved_capability is None
        assert legacy.accounted_microusd == saved.accounted_microusd == 70_000
        assert legacy.instructions == saved.instructions
        assert "история сохранена" in legacy.waiting_reason
        # Both prior worker recovery and queue claims exclude this closed row.
        assert not list(
            await session.scalars(
                select(GoalRow).where(GoalRow.status.in_(("queued", "running", "paused")))
            )
        )
        # Prior command implementations reject terminal states before applying controls.
        assert legacy.status in ("completed", "cancelled")
    await db.dispose()
    restarted = OperationDatabase(url)
    try:
        restored = await SqlAlchemyGoalRepository(restarted, clock).get("owner", created.goal_id)
        assert restored == saved
        assert restored.request == request and restored.tools == changed.tools
    finally:
        await restarted.dispose()


async def test_native_and_legacy_queues_keep_capacity_singleflight_and_command_fences(
    tmp_path: Path,
) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'claims.db'}")
    await db.create_schema()
    clock = Clock()
    repository = SqlAlchemyGoalRepository(db, clock)
    try:
        native_topic = await topic(db)
        native = await repository.create(
            "owner",
            native_topic,
            GoalCreate(
                request_id=uuid4(), objective="Analyze parent retention.", execution_mode="agent"
            ),
        )
        with pytest.raises(ChatError, match="незавершённая"):
            await repository.create(
                "owner", native_topic, GoalCreate(request_id=uuid4(), objective="An ordinary task.")
            )
        assert (await repository.create("owner", native_topic, native.request)) == native
        legacy = await repository.create(
            "owner", await topic(db), GoalCreate(request_id=uuid4(), objective="An ordinary task.")
        )
        async with db.session_factory() as session:
            row = await session.get(GoalRow, legacy.goal_id)
            assert row is not None and row.workspace_payload is None
            assert row.workspace_status is None and row.status == "queued"
            assert LegacyGoal.model_validate(row.payload).status == "queued"
        claims = await asyncio.gather(repository.claim(), repository.claim(), repository.claim())
        assert {item[1].goal_id for item in claims if item} == {native.goal_id, legacy.goal_id}
        held = await repository.get("owner", native.goal_id)
        paused = await repository.command(
            "owner",
            native.goal_id,
            GoalCommand(request_id=uuid4(), command="pause", expected_revision=held.revision),
        )
        assert paused.status == "paused"
        assert not await repository.save(
            "owner", held, held.model_copy(update={"status": "completed"})
        )
        assert (await repository.list("owner", native_topic.topic_id))[0] == paused
        with pytest.raises(ChatError, match="не найдена"):
            await repository.get("other-owner", native.goal_id)
    finally:
        await db.dispose()


async def test_rollback_inspection_is_readonly_live_work_blocks_and_unknown_costs_are_retained(
    tmp_path: Path,
) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'rollback.db'}")
    await db.create_schema()
    clock = Clock()
    repository = SqlAlchemyGoalRepository(db, clock)
    try:
        native = await repository.create(
            "owner",
            await topic(db),
            GoalCreate(
                request_id=uuid4(), objective="Analyze parent retention.", execution_mode="agent"
            ),
        )
        # Queue tie-breaking uses UUIDs; give this fixture a deterministic first arrival.
        clock.value += timedelta(seconds=1)
        queued = await repository.create(
            "owner",
            await topic(db),
            GoalCreate(
                request_id=uuid4(), objective="Analyze parent funnels.", execution_mode="agent"
            ),
        )
        claim = await repository.claim()
        assert claim is not None and claim[1].goal_id == native.goal_id
        held = claim[1]
        assert await repository.save(
            "owner",
            held,
            held.model_copy(
                update={
                    "steps_used": 1,
                    "accounted_microusd": 90_000,
                    "read_attempted": True,
                    "tools": [
                        AgentToolRecord(
                            call_id="lost-read",
                            call=AgentToolCall(
                                name="request_source_read", capability="retention.parents.analyze"
                            ),
                            status="started",
                            started_at=clock.now(),
                        )
                    ],
                }
            ),
        )
        held = await repository.get("owner", native.goal_id)
        async with db.session_factory() as session:
            before_lock = await session.get(ChatBudgetRow, "global")
            assert before_lock is not None
            lock_revision = before_lock.revision
        dry = await repository.workspace_rollback()
        assert dry.active_goals == 2 and dry.live_leases == 1 and dry.paused_goals == 0
        assert await repository.get("owner", native.goal_id) == held
        async with db.session_factory() as session:
            after_lock = await session.get(ChatBudgetRow, "global")
            assert after_lock is not None and after_lock.revision == lock_revision
        with pytest.raises(ChatError, match="активных шагов"):
            await repository.workspace_rollback(apply_pause=True)
        assert (await repository.get("owner", queued.goal_id)).status == "queued"
        clock.value += timedelta(minutes=6)
        applied = await repository.workspace_rollback(apply_pause=True)
        assert applied.active_goals == applied.paused_goals == 2 and applied.live_leases == 0
        restored = await repository.get("owner", native.goal_id)
        assert restored.status == "paused" and restored.lease_until is None
        assert restored.steps_used == 1 and restored.accounted_microusd == 90_000
        assert restored.read_attempted and restored.tools[0].status == "unknown"
        assert await repository.claim() is None
        assert (await repository.workspace_rollback(apply_pause=True)).paused_goals == 0
        resumed = await repository.command(
            "owner",
            restored.goal_id,
            GoalCommand(request_id=uuid4(), command="resume", expected_revision=restored.revision),
        )
        assert resumed.status == "queued" and resumed.read_attempted
        assert resumed.accounted_microusd == 90_000
    finally:
        await db.dispose()


async def test_additive_migration_preserves_legacy_history_and_refuses_destructive_downgrade(
    tmp_path: Path,
) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'migrated.db'}"
    env = {**os.environ, "OPERATION_DATABASE_URL": url, "OPENAI_API_KEY": "test-key"}

    async def migrate(*arguments: str) -> tuple[int, str]:
        process = await asyncio.create_subprocess_exec(
            ".venv/bin/alembic",
            *arguments,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()
        return process.returncode or 0, output.decode()

    assert (await migrate("upgrade", "b64e9c2f703d"))[0] == 0
    db = OperationDatabase(url)
    clock = Clock()
    try:
        legacy_topic = await topic(db)
        legacy = LegacyGoal(
            goal_id=str(uuid4()),
            topic_id=legacy_topic.topic_id,
            agent_id="operations-orchestrator",
            product="mana",
            request={"request_id": str(uuid4()), "objective": "An existing private analysis."},
            created_at=clock.now(),
            updated_at=clock.now(),
            status="waiting",
            accounted_microusd=75_000,
        )
        raw = legacy.model_dump_json()
        async with db.session_factory() as session, session.begin():
            await session.execute(
                text(
                    "INSERT INTO operation_goals "
                    "(goal_id, topic_id, owner, request_id, status, revision, updated_at, payload) "
                    "VALUES (:id, :topic, 'owner', :request, 'waiting', 0, :updated, :payload)"
                ),
                {
                    "id": legacy.goal_id,
                    "topic": legacy.topic_id,
                    "request": str(legacy.request.request_id),
                    "updated": clock.now().isoformat(),
                    "payload": raw,
                },
            )
        assert (await migrate("upgrade", "head"))[0] == 0
        async with db.session_factory() as session:
            assert (
                await session.scalar(
                    text("SELECT payload FROM operation_goals WHERE goal_id=:id"),
                    {"id": legacy.goal_id},
                )
                == raw
            )
        repository = SqlAlchemyGoalRepository(db, clock)
        restored = await repository.get("owner", legacy.goal_id)
        assert restored.accounted_microusd == 75_000 and restored.status == "waiting"
        native = await repository.create(
            "owner",
            await topic(db),
            GoalCreate(
                request_id=uuid4(), objective="A new private native task.", execution_mode="agent"
            ),
        )
        assert await repository.save(
            "owner", native, native.model_copy(update={"status": "completed"})
        )
        code, output = await migrate("downgrade", "b64e9c2f703d")
        assert code != 0 and "use application-only rollback" in output
        assert (await repository.get("owner", native.goal_id)).status == "completed"
        async with db.session_factory() as session:
            assert (
                await session.scalar(text("SELECT version_num FROM alembic_version"))
                == "d86a1b9f023c"
            )
    finally:
        await db.dispose()


async def test_chat_only_workspace_history_refuses_schema_downgrade(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'chat-migration.db'}"
    env = {**os.environ, "OPERATION_DATABASE_URL": url, "OPENAI_API_KEY": "test-key"}

    async def migrate(*arguments: str) -> tuple[int, str]:
        process = await asyncio.create_subprocess_exec(
            ".venv/bin/alembic",
            *arguments,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await process.communicate()
        return process.returncode or 0, output.decode()

    assert (await migrate("upgrade", "head"))[0] == 0
    db = OperationDatabase(url)
    chats = SqlAlchemyChatRepository(db, hourly_limit=20, daily_limit=200)
    try:
        native_topic = await topic(db)
        turn, _ = await chats.reserve(
            "owner",
            native_topic.topic_id,
            MessageCreate(
                request_id=uuid4(), message="A native conversation", execution_mode="agent"
            ),
        )
        assert await chats.update(
            turn.model_copy(update={"status": "completed", "next_action": "start_goal"})
        )
        before = await chats.turns("owner", native_topic.topic_id)
        code, output = await migrate("downgrade", "c75f0a6e812b")
        assert code != 0 and "use application-only rollback" in output
        assert await chats.turns("owner", native_topic.topic_id) == before
        async with db.session_factory() as session:
            assert (
                await session.scalar(text("SELECT version_num FROM alembic_version"))
                == "d86a1b9f023c"
            )
    finally:
        await db.dispose()


async def test_unknown_workspace_protocol_fails_closed_without_exposing_private_contents(
    tmp_path: Path,
) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'future-protocol.db'}")
    await db.create_schema()
    repository = SqlAlchemyGoalRepository(db, Clock())
    try:
        native = await repository.create(
            "owner",
            await topic(db),
            GoalCreate(
                request_id=uuid4(),
                objective="PRIVATE future protocol task.",
                execution_mode="agent",
            ),
        )
        async with db.session_factory() as session, session.begin():
            row = await session.get(GoalRow, native.goal_id)
            assert row is not None and row.workspace_payload is not None
            row.workspace_payload = {**row.workspace_payload, "version": 999}
        with pytest.raises(ChatError) as error:
            await repository.get("owner", native.goal_id)
        assert error.value.status == 503 and "PRIVATE" not in str(error.value)
        with pytest.raises(ChatError, match="совместимой версии"):
            await repository.claim()
        async with db.session_factory() as session:
            row = await session.get(GoalRow, native.goal_id)
            assert row is not None and row.status == "cancelled"
            assert LegacyGoal.model_validate(row.payload).status == "cancelled"
    finally:
        await db.dispose()
