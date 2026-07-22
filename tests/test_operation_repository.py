import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.mana_operation_ai.domain.enums import (
    ActionStatus,
    ActionType,
    AgentRunStatus,
    AgentStatus,
    ApprovalStatus,
    ExecutionStatus,
    PolicyDecision,
    TriggerType,
    UserRole,
)
from app.mana_operation_ai.domain.models import (
    ActionExecution,
    ActionPolicy,
    ActionProposal,
    AgentConfiguration,
    AgentDefinition,
    AgentRun,
    AgentSchedule,
    ApprovalRequest,
    StatusActionParameters,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.repository import (
    SqlAlchemyOperationRepository,
)


async def test_repository_versions_configurations_idempotent_runs_and_locks(
    tmp_path: Path,
) -> None:
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'operation.db'}")
    await database.create_schema()
    repository = SqlAlchemyOperationRepository(database)
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    definition = AgentDefinition(
        agent_id="test-agent",
        display_name="Test Agent",
        description="Repository integration test agent",
        version="1.0.0",
        status=AgentStatus.ENABLED,
        capabilities=[],
        configuration_schema={"type": "object"},
        registered_at=now,
    )
    await repository.register_agent(definition)
    await repository.save_configuration(
        AgentConfiguration(
            configuration_id="config-1",
            agent_id="test-agent",
            version=1,
            values={"threshold": 1},
            created_at=now,
            created_by="tester",
        ),
    )
    await repository.save_configuration(
        AgentConfiguration(
            configuration_id="config-2",
            agent_id="test-agent",
            version=2,
            values={"threshold": 2},
            created_at=now + timedelta(seconds=1),
            created_by="tester",
        ),
    )

    configurations = await repository.list_configurations("test-agent")
    assert [item.version for item in configurations] == [2, 1]
    assert configurations[0].active is True
    assert configurations[1].active is False

    run = AgentRun(
        run_id="run-1",
        agent_id="test-agent",
        correlation_id="correlation-1",
        trigger=TriggerType.API,
        initiated_by="tester",
        status=AgentRunStatus.QUEUED,
        configuration_version=2,
        idempotency_key="same-run-key",
        started_at=now,
        updated_at=now,
    )
    first = await repository.create_run(run)
    duplicate = await repository.create_run(run.model_copy(update={"run_id": "run-2"}))
    assert first.run_id == "run-1"
    assert duplicate.run_id == "run-1"

    assert await repository.acquire_lock(
        key="agent-run:test-agent",
        owner_id="owner-1",
        now=now,
        expires_at=now + timedelta(minutes=5),
    )
    assert not await repository.acquire_lock(
        key="agent-run:test-agent",
        owner_id="owner-2",
        now=now + timedelta(minutes=1),
        expires_at=now + timedelta(minutes=6),
    )
    assert await repository.acquire_lock(
        key="agent-run:test-agent",
        owner_id="owner-2",
        now=now + timedelta(minutes=6),
        expires_at=now + timedelta(minutes=7),
    )
    await repository.release_lock(key="agent-run:test-agent", owner_id="owner-2")
    await database.dispose()


async def test_repository_lock_and_schedule_claim_are_atomic_across_contenders(
    tmp_path: Path,
) -> None:
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'claims.db'}")
    await database.create_schema()
    repository = SqlAlchemyOperationRepository(database)
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    await repository.register_agent(
        AgentDefinition(
            agent_id="claim-agent",
            display_name="Claim Agent",
            description="Exercises distributed database claims",
            version="1.0.0",
            status=AgentStatus.ENABLED,
            capabilities=[],
            configuration_schema={"type": "object"},
            registered_at=now,
        ),
    )
    lock_results = await asyncio.gather(
        *(
            repository.acquire_lock(
                key="provider-action:meta:ad_set:shared",
                owner_id=f"worker-{index}",
                now=now,
                expires_at=now + timedelta(minutes=5),
            )
            for index in range(12)
        ),
    )
    assert lock_results.count(True) == 1
    assert lock_results.count(False) == 11

    schedule = AgentSchedule(
        schedule_id="claim-schedule",
        agent_id="claim-agent",
        job_type="analysis",
        cron_expression="0 */6 * * *",
        timezone="UTC",
        enabled=True,
        next_run_at=now,
    )
    advanced = schedule.model_copy(
        update={
            "last_run_at": now,
            "next_run_at": now + timedelta(hours=6),
        },
    )
    await repository.save_schedule(schedule)
    schedule_results = await asyncio.gather(
        *(repository.claim_schedule(current=schedule, advanced=advanced) for _ in range(12)),
    )
    assert schedule_results.count(True) == 1
    assert schedule_results.count(False) == 11

    run_template = AgentRun(
        run_id="contended-run-0",
        agent_id="claim-agent",
        correlation_id="contended-run",
        trigger=TriggerType.SCHEDULE,
        initiated_by="scheduler",
        status=AgentRunStatus.QUEUED,
        configuration_version=1,
        idempotency_key="one-scheduled-occurrence",
        started_at=now,
        updated_at=now,
    )
    run_results = await asyncio.gather(
        *(
            repository.create_run(
                run_template.model_copy(update={"run_id": f"contended-run-{index}"}),
            )
            for index in range(12)
        ),
    )
    persisted_run_ids = {item.run_id for item in run_results}
    assert len(persisted_run_ids) == 1
    persisted_run_id = next(iter(persisted_run_ids))

    proposal_template = ActionProposal(
        proposal_id="proposal-0",
        run_id=persisted_run_id,
        recommendation_id="recommendation-1",
        agent_id="claim-agent",
        provider="fake_meta",
        object_type="ad_set",
        provider_object_id="set-1",
        action_type=ActionType.PAUSE,
        parameters=StatusActionParameters(
            kind=ActionType.PAUSE,
            current_status="ACTIVE",
            proposed_status="PAUSED",
        ),
        evidence=[],
        reasoning="Deterministic weak-performance signal",
        confidence=Decimal("0.9"),
        expected_effect="Stop inefficient spend",
        risks=[],
        missing_data=[],
        policy=ActionPolicy(
            policy_id="policy-1",
            agent_id="claim-agent",
            action_type=ActionType.PAUSE,
            decision=PolicyDecision.REQUIRE_APPROVAL,
            reasons=["Approval is required."],
            checked_at=now,
            configuration_version=1,
        ),
        status=ActionStatus.AWAITING_APPROVAL,
        idempotency_key="one-action-request",
        current_state_hash="state-1",
        expires_at=now + timedelta(hours=1),
        created_at=now,
    )

    async def create_action(index: int) -> tuple[ActionProposal, ApprovalRequest | None]:
        proposal = proposal_template.model_copy(update={"proposal_id": f"proposal-{index}"})
        return await repository.create_action_request(
            proposal,
            ApprovalRequest(
                approval_id=f"approval-{index}",
                proposal_id=proposal.proposal_id,
                requested_at=now,
                expires_at=proposal.expires_at,
                requested_by="operator",
                required_role=UserRole.APPROVER,
                status=ApprovalStatus.PENDING,
            ),
        )

    action_results = await asyncio.gather(*(create_action(index) for index in range(12)))
    persisted_proposal_ids = {item[0].proposal_id for item in action_results}
    persisted_approval_ids = {item[1].approval_id for item in action_results if item[1] is not None}
    assert len(persisted_proposal_ids) == 1
    assert len(persisted_approval_ids) == 1
    persisted_proposal_id = next(iter(persisted_proposal_ids))

    execution_template = ActionExecution(
        execution_id="execution-0",
        proposal_id=persisted_proposal_id,
        run_id=persisted_run_id,
        idempotency_key="one-action-request",
        status=ExecutionStatus.PENDING,
        attempted_at=now,
        before_state={},
        requested_change={},
        provider_response={},
    )
    execution_results = await asyncio.gather(
        *(
            repository.save_execution(
                execution_template.model_copy(update={"execution_id": f"execution-{index}"}),
            )
            for index in range(12)
        ),
    )
    assert len({item.execution_id for item in execution_results}) == 1
    await database.dispose()


async def test_sqlite_foreign_keys_are_enforced(tmp_path: Path) -> None:
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'foreign-keys.db'}")
    await database.create_schema()
    repository = SqlAlchemyOperationRepository(database)
    with pytest.raises(IntegrityError):
        await repository.save_configuration(
            AgentConfiguration(
                configuration_id="orphan-configuration",
                agent_id="missing-agent",
                version=1,
                values={},
                created_at=datetime(2026, 7, 22, 12, tzinfo=UTC),
                created_by="tester",
            ),
        )
    await database.dispose()
