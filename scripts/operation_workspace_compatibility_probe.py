"""Synthetic SQLite probe shared by current code and the supported legacy image.

Only run through operation_workspace_compatibility_audit.sh: that script supplies
an isolated database and pins the legacy process to a local, networkless container.
"""

import argparse
import asyncio
import hashlib
import json
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


async def probe(
    path: Path,
    *,
    stage: str,
    paused: bool,
    catalog: bool = False,
    snapshots: bool = False,
    pages: bool = False,
    verdicts: bool = False,
) -> None:
    if snapshots and not catalog:
        raise ValueError("Snapshot compatibility auditing requires the captured catalog contract")
    if pages and not snapshots:
        raise ValueError("Page compatibility auditing requires captured snapshot replacement")
    if verdicts and not pages:
        raise ValueError("Review compatibility auditing requires the paged-catalog contract")
    if stage == "setup" and path.exists():
        raise RuntimeError("Synthetic compatibility setup requires a nonexistent database file")
    database = OperationDatabase(f"sqlite+aiosqlite:///{path}")
    clock = SystemClock()
    chats = SqlAlchemyChatRepository(database, hourly_limit=20, daily_limit=200)
    repository = (
        SqlAlchemyGoalRepository(database, clock)
        if stage == "legacy"
        else SqlAlchemyGoalRepository(
            database,
            clock,
            events_enabled=True,
            limit_extensions_enabled=True,
            **({"report_discovery_enabled": True} if catalog else {}),
            **({"snapshot_replacement_enabled": True} if snapshots else {}),
            **({"page_projection_enabled": True} if pages else {}),
            **({"review_verdict_enabled": True} if verdicts else {}),
        )
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
            from app.mana_operation_ai.domain.goals import (
                GoalConversationTurn,
                GoalEvidence,
                GoalLimitGrant,
                GoalModelFeedback,
                ReportReadProgress,
            )
            from app.mana_operation_ai.domain.session import SessionMemory, SessionUserContext
            from app.mana_operation_ai.domain.workspace_actions import WorkspaceActionHistory

            await database.create_schema()
            await chats.initialize()
            for title in ("Native queued", "Native lost", "Native manual", "Legacy"):
                topic = await chats.create(
                    OWNER,
                    TopicCreate(agent_id="operations-orchestrator", product="mana", title=title),
                )
                native = title != "Legacy"
                capability = (
                    "retention.parent_activity.analyze"
                    if title == "Native manual"
                    else "retention.parents.analyze"
                )
                request = GoalCreate(
                    request_id=uuid4(),
                    objective="Synthetic compatibility task; no customer data or provider I/O.",
                    execution_mode="agent" if native else "analysis",
                    analysis_scope="saved_snapshot" if title == "Native queued" else "current",
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
                                also_kinds=["instruction"],
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
                    # New preview fields remain outside the old strict chat JSON.
                    chats._stream_events_enabled = True
                    assert await chats.preview(
                        OWNER, topic.topic_id, turn.turn_id, "Synthetic draft 🧒"
                    )
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
                    from app.mana_operation_ai.infrastructure.goal_continuation import (
                        finish_continuation,
                        prepare_continuation,
                    )

                    prepared = prepare_continuation(
                        context=goal.model_dump_json().join(('{"goal":', "}")),
                        owner=OWNER,
                        state=None,
                        model="compatibility-fake",
                        maximum_bytes=192000,
                    )
                    continuation = finish_continuation(
                        prepared,
                        [
                            {
                                "type": "reasoning" if snapshots else "compaction",
                                "id": "cmp_compat",
                                "encrypted_content": "test-compat-private-model-state",
                                **({"summary": []} if snapshots else {}),
                            },
                            {
                                "type": "function_call",
                                "id": "fc_compat",
                                "call_id": "call_compat",
                                "name": "request_source_read",
                                "arguments": '{"capability":"' + capability + '"}',
                            },
                        ],
                        model="compatibility-fake",
                        call=AgentToolCall(name="request_source_read", capability=capability),
                        maximum_bytes=192000,
                    )
                    updated = goal.model_copy(
                        update={
                            "status": "running" if lost else "queued",
                            "lease_until": clock.now() - timedelta(minutes=1) if lost else None,
                            "steps_used": 1,
                            "accounted_microusd": 90_000,
                            "unsettled_microusd": 90_000 if lost else 0,
                            "limit_grants": []
                            if lost
                            else [
                                GoalLimitGrant(
                                    request_id=uuid4(),
                                    at=clock.now(),
                                    max_steps=12,
                                    budget_microusd=goal.request.budget_microusd,
                                )
                            ],
                            "read_attempted": lost,
                            "model_continuation": continuation,
                            "model_feedback": GoalModelFeedback(
                                code="invalid_decision",
                                message="Synthetic known-output correction.",
                            )
                            if not lost
                            else None,
                            "model_recoveries": 1 if not lost else 0,
                            "requested_capability": None if lost else capability,
                            "approved_capability": None if lost else capability,
                            "tools": [
                                AgentToolRecord(
                                    call_id=f"synthetic-{title}",
                                    call=AgentToolCall(
                                        name="request_source_read",
                                        capability=capability,
                                    ),
                                    status="started" if lost else "awaiting_approval",
                                    started_at=clock.now(),
                                )
                            ],
                        }
                    )
                    if verdicts:
                        from app.mana_operation_ai.domain.goal_review import (
                            GoalReviewCheck,
                            GoalReviewVerdictBody,
                        )
                        from app.mana_operation_ai.domain.goals import GoalTask

                        updated.plan = [
                            GoalTask(title="Complete independent full review", status="active")
                        ]
                        updated.result = (
                            "Synthetic complete draft, never current business evidence."
                        )
                        updated.review_receipt = GoalReviewVerdictBody(
                            input_sha256="a" * 64,
                            draft_sha256=hashlib.sha256(updated.result.encode()).hexdigest(),
                            checks=[
                                GoalReviewCheck(
                                    target=target,
                                    quote=getattr(updated.request, target),
                                    status="not_checked",
                                    finding="Historical synthetic review only.",
                                )
                                for target in ("objective", "success_criteria")
                                if getattr(updated.request, target)
                            ],
                            checked_plan_positions=[0],
                            conditions_checked=False,
                            evidence_checked=False,
                            evidence_ids=[],
                            disposition="waiting",
                            feedback="Synthetic scope preserved; no new authority.",
                        )
                    if not lost:
                        text = "Synthetic complete report: " + "x" * 5200 + " EXACT FOOTER \t\n"
                        digest = hashlib.sha256(text.encode()).hexdigest()
                        updated.evidence = [
                            GoalEvidence(
                                report_id="synthetic-paged-report",
                                capability_key="retention.engagement.analyze",
                                product="mana",
                                collected_at=clock.now() - timedelta(days=1),
                                fresh_until=None,
                                refresh_status="unknown",
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
                        ]
                    if catalog:
                        updated.tools.append(
                            AgentToolRecord(
                                call_id=f"synthetic-catalog-{title}",
                                call=AgentToolCall(
                                    name="find_saved_reports",
                                    query="synthetic",
                                    cursor="synthetic-position-" + "x" * 280,
                                    catalog_capability="retention.parent_activity.analyze",
                                ),
                                status="completed",
                                started_at=clock.now(),
                                completed_at=clock.now(),
                                result="References only; no collection.",
                            )
                        )
                    if pages and not lost:
                        source = updated.evidence[0]
                        page_call = AgentToolCall(
                            name="read_saved_report_page", report_id=source.report_id, offset=0
                        )
                        page_pending = finish_continuation(
                            prepare_continuation(
                                context=json.dumps(
                                    {
                                        "goal": updated.model_dump(
                                            mode="json", exclude={"model_continuation"}
                                        )
                                    }
                                ),
                                owner=OWNER,
                                state=None,
                                model="compatibility-fake",
                                maximum_bytes=192000,
                            ),
                            [
                                {
                                    "type": "function_call",
                                    "id": "fc_page",
                                    "call_id": "call_page",
                                    "name": page_call.name,
                                    "arguments": json.dumps(
                                        {"report_id": source.report_id, "offset": 0}
                                    ),
                                }
                            ],
                            model="compatibility-fake",
                            call=page_call,
                            maximum_bytes=192000,
                        )
                        updated.tools.append(
                            AgentToolRecord(
                                call_id="synthetic-page",
                                call=page_call,
                                status="completed",
                                started_at=clock.now(),
                                result=json.dumps(
                                    {
                                        "report_id": source.report_id,
                                        "offset": 0,
                                        "text": source.summary[:4000],
                                        "total_characters": len(source.summary),
                                        "next_offset": 4000,
                                        "loaded_into_evidence": True,
                                        "reading_not_population_coverage": True,
                                    },
                                    ensure_ascii=False,
                                ),
                            )
                        )
                        updated.model_continuation = finish_continuation(
                            prepare_continuation(
                                context=json.dumps(
                                    {
                                        "goal": updated.model_dump(
                                            mode="json", exclude={"model_continuation"}
                                        )
                                    }
                                ),
                                owner=OWNER,
                                state=page_pending,
                                model="compatibility-fake",
                                maximum_bytes=192000,
                            ),
                            [
                                {
                                    "type": "reasoning",
                                    "id": "rs_page",
                                    "summary": [],
                                    "encrypted_content": "test-compat-private-model-state",
                                }
                            ],
                            model="compatibility-fake",
                            call=None,
                            maximum_bytes=192000,
                        )
                    assert await repository.save(OWNER, goal, updated)
            return

        topics = await chats.topics(OWNER)
        assert len(topics) == 4
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
                if topic.title == "Native queued":
                    assert len(goal.evidence[0].summary) == 5000
                    assert goal.evidence[0].shortened
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
                assert goal.limit_tracking
                assert getattr(goal, "report_discovery_enabled", False) == catalog
                assert getattr(goal, "snapshot_replacement_enabled", False) == snapshots
                assert getattr(goal, "page_projection_enabled", False) == pages
                assert getattr(goal, "review_verdict_enabled", False) == verdicts
                if verdicts:
                    assert goal.review_receipt is not None
                    assert (
                        goal.review_receipt.draft_sha256
                        == hashlib.sha256(goal.result.encode()).hexdigest()
                    )
                    assert "no new authority" in goal.review_receipt.feedback
                if catalog:
                    assert goal.tools[1].call.name == "find_saved_reports"
                    assert (
                        goal.tools[1].call.catalog_capability == "retention.parent_activity.analyze"
                    )
                    assert goal.tools[1].result == "References only; no collection."
                assert goal.unsettled_microusd == (90_000 if lost else 0)
                assert len(goal.limit_grants) == (0 if lost else 1)
                assert goal.execution_limits.max_steps == (6 if lost else 12)
                journal = await SqlAlchemyWorkspaceEvents(database).page(OWNER, topic.topic_id, 0)
                assert len(journal.items) == 2
                assert [event.revision for event in journal.items] == [0, 1]
                assert journal.items[-1].tools[0].status == (
                    "started" if lost else "awaiting_approval"
                )
                turns = await chats.turns(OWNER, topic.topic_id)
                assert len(turns) == 1
                assert turns[0].next_action == "start_goal" and turns[0].execution_mode == "agent"
                assert turns[0].session_memory is None
                original = await chats.turn(OWNER, topic.topic_id, turns[0].turn_id)
                assert original.preview == "Synthetic draft 🧒" and original.preview_revision == 2
                assert original.session_memory is not None and goal.session_memory is not None
                assert bool(goal.session_memory.actions) is (topic.title == "Native queued")
                assert original.session_memory.actions == goal.session_memory.actions
                assert original.session_memory.user_context[0].text == "Do not contact clients."
                assert goal.session_memory.user_context[0].text == "Do not contact clients."
                assert goal.status == ("paused" if paused else "running" if lost else "queued")
                assert goal.request.execution_mode == "agent"
                assert goal.request.analysis_scope == (
                    "saved_snapshot" if topic.title == "Native queued" else "current"
                )
                assert goal.request.conversation_history[0].user == "Do not contact clients."
                assert goal.steps_used == 1 and goal.accounted_microusd == 90_000
                assert goal.read_attempted == lost
                assert goal.model_continuation is not None
                assert "test-compat-private-model-state" in goal.model_continuation.payload
                assert goal.model_continuation.compactions == (0 if snapshots else 1)
                if snapshots:
                    assert goal.model_continuation.protocol == (
                        "goal-model-continuation-v5"
                        if verdicts
                        else "goal-model-continuation-v4"
                        if pages
                        else "goal-model-continuation-v3"
                    )
                    assert len(goal.model_continuation.runtime_snapshots) == 1
                    assert goal.model_continuation.runtime_snapshots[0].position == (
                        2 if pages and not lost else 0
                    )
                if pages and not lost:
                    assert len(goal.model_continuation.page_outputs) == 1
                    assert goal.model_continuation.page_outputs[0].position == 1
                    assert goal.model_continuation.page_outputs[0].tool_position == 2
                    assert (
                        json.loads(goal.tools[2].result)["text"] == goal.evidence[0].summary[:4000]
                    )
                if not lost:
                    assert goal.evidence[0].summary.endswith("EXACT FOOTER \t\n")
                    assert len(goal.evidence[0].summary) > 5000
                    assert goal.evidence[0].report_read_progress is not None
                    assert not goal.evidence[0].shortened
                    assert (
                        goal.model_feedback is not None
                        and goal.model_feedback.code == "invalid_decision"
                    )
                    assert goal.model_recoveries == 1
                assert goal.tools[0].status == (
                    "unknown" if lost and paused else "started" if lost else "awaiting_approval"
                )
                assert goal.approved_capability == (
                    None
                    if paused or lost
                    else "retention.parent_activity.analyze"
                    if topic.title == "Native manual"
                    else "retention.parents.analyze"
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
    parser.add_argument("--catalog", action="store_true")
    parser.add_argument("--snapshots", action="store_true")
    parser.add_argument("--pages", action="store_true")
    parser.add_argument("--verdicts", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        probe(
            args.database_file.resolve(),
            stage=args.stage,
            paused=args.paused,
            catalog=args.catalog,
            snapshots=args.snapshots,
            pages=args.pages,
            verdicts=args.verdicts,
        )
    )


if __name__ == "__main__":
    main()
