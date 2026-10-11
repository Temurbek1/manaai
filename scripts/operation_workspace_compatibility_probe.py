"""Synthetic SQLite probe shared by current code and the supported legacy image.

Only run through operation_workspace_compatibility_audit.sh: that script supplies
an isolated database and pins the legacy process to a local, networkless container.
"""

import argparse
import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path.cwd()))

from app.mana_operation_ai.application.chat_ports import ChatError  # noqa: E402
from app.mana_operation_ai.application.runtime import SystemClock  # noqa: E402
from app.mana_operation_ai.domain.chat import TopicCreate  # noqa: E402
from app.mana_operation_ai.domain.goals import GoalCommand, GoalCreate  # noqa: E402
from app.mana_operation_ai.infrastructure.persistence.chat_repository import (  # noqa: E402
    SqlAlchemyChatRepository,
)
from app.mana_operation_ai.infrastructure.persistence.database import (  # noqa: E402
    OperationDatabase,
)
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (  # noqa: E402
    SqlAlchemyGoalRepository,
)

OWNER = "local-workspace-rollback-audit"


async def probe(path: Path, *, stage: str, paused: bool) -> None:
    if stage == "setup" and path.exists():
        raise RuntimeError("Synthetic compatibility setup requires a nonexistent database file")
    database = OperationDatabase(f"sqlite+aiosqlite:///{path}")
    clock = SystemClock()
    chats = SqlAlchemyChatRepository(database, hourly_limit=20, daily_limit=200)
    repository = (
        SqlAlchemyGoalRepository(database, clock)
        if stage == "legacy"
        else SqlAlchemyGoalRepository(database, clock, events_enabled=True)
    )
    try:
        if stage == "setup":
            from app.mana_operation_ai.domain.agent_tools import AgentToolCall, AgentToolRecord
            from app.mana_operation_ai.domain.chat import MessageCreate
            from app.mana_operation_ai.domain.enums import (
                ActionStatus,
                ExecutionStatus,
                VerificationStatus,
            )
            from app.mana_operation_ai.domain.goals import GoalConversationTurn
            from app.mana_operation_ai.domain.session import SessionMemory, SessionUserContext
            from app.mana_operation_ai.domain.workspace_actions import WorkspaceActionHistory

            await database.create_schema()
            await chats.initialize()
            for title in ("Native queued", "Native lost", "Legacy"):
                topic = await chats.create(
                    OWNER,
                    TopicCreate(agent_id="operations-orchestrator", product="mana", title=title),
                )
                native = title != "Legacy"
                request = GoalCreate(
                    request_id=uuid4(),
                    objective="Synthetic compatibility task; no customer data or provider I/O.",
                    execution_mode="agent" if native else "analysis",
                    conversation_history=[
                        GoalConversationTurn(user="Do not contact clients.", assistant="Confirmed.")
                    ]
                    if native
                    else [],
                )
                memory = (
                    SessionMemory(
                        topic_id=topic.topic_id,
                        product="mana",
                        captured_at=clock.now(),
                        actions=[
                            WorkspaceActionHistory(
                                proposal_id="synthetic-private-proposal",
                                at=clock.now(),
                                status=ActionStatus.SUCCEEDED,
                                execution_status=ExecutionStatus.SUCCEEDED,
                                verification_status=VerificationStatus.VERIFIED,
                                message="Sandbox only; no business outcome measured.",
                            )
                        ]
                        if title == "Native queued"
                        else [],
                        user_context=[
                            SessionUserContext(
                                kind="constraint",
                                text="Do not contact clients.",
                                origin_id="synthetic",
                            )
                        ],
                    )
                    if native
                    else None
                )
                goal = await repository.create(OWNER, topic, request, session_memory=memory)
                if native:
                    turn, created = await chats.reserve(
                        OWNER,
                        topic.topic_id,
                        MessageCreate(
                            request_id=uuid4(),
                            message="Analyze synthetic evidence.",
                            execution_mode="agent",
                        ),
                    )
                    assert created
                    assert await chats.update(
                        turn.model_copy(
                            update={
                                "status": "completed",
                                "next_action": "start_goal",
                                "answer": "Synthetic task started.",
                                "session_memory": memory,
                            }
                        ),
                    )
                    lost = title == "Native lost"
                    updated = goal.model_copy(
                        update={
                            "status": "running" if lost else "queued",
                            "lease_until": clock.now() - timedelta(minutes=1) if lost else None,
                            "steps_used": 1,
                            "accounted_microusd": 90_000,
                            "read_attempted": lost,
                            "requested_capability": None if lost else "retention.parents.analyze",
                            "approved_capability": None if lost else "retention.parents.analyze",
                            "tools": [
                                AgentToolRecord(
                                    call_id=f"synthetic-{title}",
                                    call=AgentToolCall(
                                        name="request_source_read",
                                        capability="retention.parents.analyze",
                                    ),
                                    status="started" if lost else "awaiting_approval",
                                    started_at=clock.now(),
                                )
                            ],
                        }
                    )
                    assert await repository.save(OWNER, goal, updated)
            return

        topics = await chats.topics(OWNER)
        assert len(topics) == 3
        if stage == "legacy":
            # This process imports the real old image's strict models and repository.
            for topic in topics:
                goal = (await repository.list(OWNER, topic.topic_id))[0]
                if topic.title == "Legacy":
                    continue
                turns = await chats.turns(OWNER, topic.topic_id)
                assert len(turns) == 1
                assert turns[0].status == "completed" and turns[0].next_action == "none"
                assert goal.status == "cancelled" and goal.lease_until is None
                assert goal.accounted_microusd == 90_000
                assert goal.requested_capability is None and goal.approved_capability is None
                for command in ("pause", "resume", "cancel", "steer", "approve_read"):
                    try:
                        await repository.command(
                            OWNER,
                            goal.goal_id,
                            GoalCommand(
                                request_id=uuid4(),
                                command=command,
                                expected_revision=goal.revision,
                                message="A legacy control must not change native work.",
                            ),
                        )
                    except ChatError as exc:
                        assert "Цель закрыта" in str(exc)
                    else:
                        raise AssertionError("The legacy API accepted a native Goal control")
            claimed = await repository.claim()
            if not paused:
                assert claimed is not None
                topic = next(topic for topic in topics if topic.title == "Legacy")
                assert claimed[1].topic_id == topic.topic_id
                await repository.command(
                    OWNER,
                    claimed[1].goal_id,
                    GoalCommand(
                        request_id=uuid4(),
                        command="cancel",
                        expected_revision=claimed[1].revision,
                    ),
                )
            else:
                assert claimed is None
            assert await repository.claim() is None
        else:
            from app.mana_operation_ai.infrastructure.persistence.workspace_events import (
                SqlAlchemyWorkspaceEvents,
            )

            for topic in topics:
                goal = (await repository.list(OWNER, topic.topic_id))[0]
                if topic.title == "Legacy":
                    assert goal.status == "cancelled"
                    continue
                lost = topic.title == "Native lost"
                journal = await SqlAlchemyWorkspaceEvents(database).page(OWNER, topic.topic_id, 0)
                assert len(journal.items) == 2
                assert [event.revision for event in journal.items] == [0, 1]
                assert journal.items[-1].tools[0].status == (
                    "started" if lost else "awaiting_approval"
                )
                turns = await chats.turns(OWNER, topic.topic_id)
                assert len(turns) == 1
                assert turns[0].next_action == "start_goal" and turns[0].execution_mode == "agent"
                assert turns[0].session_memory is not None and goal.session_memory is not None
                assert bool(goal.session_memory.actions) is (topic.title == "Native queued")
                assert turns[0].session_memory.actions == goal.session_memory.actions
                assert turns[0].session_memory.user_context[0].text == "Do not contact clients."
                assert goal.session_memory.user_context[0].text == "Do not contact clients."
                assert goal.status == ("paused" if paused else "running" if lost else "queued")
                assert goal.request.execution_mode == "agent"
                assert goal.request.conversation_history[0].user == "Do not contact clients."
                assert goal.steps_used == 1 and goal.accounted_microusd == 90_000
                assert goal.read_attempted == lost
                assert goal.tools[0].status == (
                    "unknown" if lost and paused else "started" if lost else "awaiting_approval"
                )
                assert goal.approved_capability == (
                    None if paused or lost else "retention.parents.analyze"
                )
            if paused:
                assert await repository.claim() is None
        print(f"Workspace compatibility probe passed: {stage}, paused={paused}")
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-file", required=True, type=Path)
    parser.add_argument("--stage", choices=("setup", "legacy", "verify"), required=True)
    parser.add_argument("--paused", action="store_true")
    args = parser.parse_args()
    asyncio.run(probe(args.database_file.resolve(), stage=args.stage, paused=args.paused))


if __name__ == "__main__":
    main()
