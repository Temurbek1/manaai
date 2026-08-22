from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from pydantic import BaseModel
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.mana_operation_ai.application.ports import ConcurrentOperationError
from app.mana_operation_ai.domain.enums import (
    ActionStatus,
    AgentRunStatus,
    AgentStatus,
    ApprovalStatus,
)
from app.mana_operation_ai.domain.models import (
    ActionExecution,
    ActionProposal,
    ActionVerification,
    AgentConfiguration,
    AgentDefinition,
    AgentReport,
    AgentRun,
    AgentSchedule,
    Analysis,
    ApprovalDecision,
    ApprovalRequest,
    AuditEvent,
    DataSnapshot,
    Finding,
    IntegrationHealth,
    OutcomeEvaluation,
    Recommendation,
)
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import (
    ActionExecutionRow,
    ActionProposalRow,
    ActionVerificationRow,
    AgentConfigurationRow,
    AgentReportRow,
    AgentRow,
    AgentRunRow,
    AgentScheduleRow,
    AnalysisRow,
    ApprovalDecisionRow,
    ApprovalRequestRow,
    AuditEventRow,
    DataSnapshotRow,
    FindingRow,
    IntegrationHealthRow,
    JobLockRow,
    OutcomeEvaluationRow,
    RecommendationRow,
    SystemControlRow,
)


class SqlAlchemyOperationRepository:
    def __init__(self, database: OperationDatabase) -> None:
        self._database = database

    async def register_agent(self, definition: AgentDefinition) -> None:
        async with self._database.session_factory.begin() as session:
            row = await session.get(AgentRow, definition.agent_id)
            if row is None:
                session.add(
                    AgentRow(
                        agent_id=definition.agent_id,
                        status=definition.status.value,
                        registered_at=definition.registered_at,
                        definition=_payload(definition),
                    ),
                )
            else:
                row.status = definition.status.value
                row.definition = _payload(definition)

    async def get_agent(self, agent_id: str) -> AgentDefinition | None:
        async with self._database.session_factory() as session:
            row = await session.get(AgentRow, agent_id)
        return AgentDefinition.model_validate(row.definition) if row is not None else None

    async def list_agents(self) -> list[AgentDefinition]:
        async with self._database.session_factory() as session:
            rows = list((await session.scalars(select(AgentRow).order_by(AgentRow.agent_id))).all())
        return [AgentDefinition.model_validate(row.definition) for row in rows]

    async def set_agent_status(self, agent_id: str, status: AgentStatus) -> AgentDefinition:
        async with self._database.session_factory.begin() as session:
            row = await session.get(AgentRow, agent_id)
            if row is None:
                raise LookupError(f"Agent {agent_id!r} was not found")
            definition = AgentDefinition.model_validate(row.definition).model_copy(
                update={"status": status},
            )
            row.status = status.value
            row.definition = _payload(definition)
        return definition

    async def save_configuration(self, configuration: AgentConfiguration) -> None:
        try:
            async with self._database.session_factory.begin() as session:
                if configuration.active:
                    active_rows = list(
                        (
                            await session.scalars(
                                select(AgentConfigurationRow).where(
                                    AgentConfigurationRow.agent_id == configuration.agent_id,
                                    AgentConfigurationRow.capability_key
                                    == configuration.capability_key,
                                    AgentConfigurationRow.active.is_(True),
                                ),
                            )
                        ).all(),
                    )
                    for row in active_rows:
                        previous = AgentConfiguration.model_validate(row.payload).model_copy(
                            update={"active": False},
                        )
                        row.active = False
                        row.payload = _payload(previous)
                session.add(
                    AgentConfigurationRow(
                        configuration_id=configuration.configuration_id,
                        agent_id=configuration.agent_id,
                        capability_key=configuration.capability_key,
                        version=configuration.version,
                        active=configuration.active,
                        created_at=configuration.created_at,
                        payload=_payload(configuration),
                    ),
                )
        except IntegrityError as exc:
            async with self._database.session_factory() as session:
                agent_exists = await session.get(AgentRow, configuration.agent_id)
            if agent_exists is None:
                raise
            raise ConcurrentOperationError(
                "The configuration version was created by another request",
            ) from exc

    async def latest_configuration(
        self,
        agent_id: str,
        capability_key: str,
    ) -> AgentConfiguration | None:
        statement = (
            select(AgentConfigurationRow)
            .where(
                AgentConfigurationRow.agent_id == agent_id,
                AgentConfigurationRow.capability_key == capability_key,
            )
            .order_by(AgentConfigurationRow.version.desc())
            .limit(1)
        )
        async with self._database.session_factory() as session:
            row = (await session.scalars(statement)).first()
        return AgentConfiguration.model_validate(row.payload) if row is not None else None

    async def list_configurations(
        self,
        agent_id: str,
        capability_key: str | None = None,
    ) -> list[AgentConfiguration]:
        statement = select(AgentConfigurationRow).where(
            AgentConfigurationRow.agent_id == agent_id,
        )
        if capability_key is not None:
            statement = statement.where(
                AgentConfigurationRow.capability_key == capability_key,
            )
        statement = statement.order_by(
            AgentConfigurationRow.capability_key,
            AgentConfigurationRow.version.desc(),
        )
        async with self._database.session_factory() as session:
            rows = list((await session.scalars(statement)).all())
        return [AgentConfiguration.model_validate(row.payload) for row in rows]

    async def save_schedule(self, schedule: AgentSchedule) -> None:
        async with self._database.session_factory.begin() as session:
            row = await session.get(AgentScheduleRow, schedule.schedule_id)
            if row is None:
                session.add(
                    AgentScheduleRow(
                        schedule_id=schedule.schedule_id,
                        agent_id=schedule.agent_id,
                        capability_key=schedule.capability_key,
                        job_type=schedule.job_type,
                        enabled=schedule.enabled,
                        next_run_at=schedule.next_run_at,
                        payload=_payload(schedule),
                    ),
                )
            else:
                if (
                    row.agent_id != schedule.agent_id
                    or row.capability_key != schedule.capability_key
                    or row.job_type != schedule.job_type
                ):
                    raise ConcurrentOperationError(
                        "Schedule identity fields cannot be changed",
                    )
                row.job_type = schedule.job_type
                row.capability_key = schedule.capability_key
                row.enabled = schedule.enabled
                row.next_run_at = schedule.next_run_at
                row.payload = _payload(schedule)

    async def list_schedules(
        self,
        agent_id: str | None = None,
        capability_key: str | None = None,
    ) -> list[AgentSchedule]:
        statement = select(AgentScheduleRow)
        if agent_id is not None:
            statement = statement.where(AgentScheduleRow.agent_id == agent_id)
        if capability_key is not None:
            statement = statement.where(AgentScheduleRow.capability_key == capability_key)
        statement = statement.order_by(
            AgentScheduleRow.agent_id,
            AgentScheduleRow.capability_key,
            AgentScheduleRow.job_type,
        )
        async with self._database.session_factory() as session:
            rows = list((await session.scalars(statement)).all())
        return [AgentSchedule.model_validate(row.payload) for row in rows]

    async def due_schedules(self, now: datetime) -> list[AgentSchedule]:
        statement = select(AgentScheduleRow).where(
            AgentScheduleRow.enabled.is_(True),
            AgentScheduleRow.next_run_at.is_not(None),
            AgentScheduleRow.next_run_at <= now,
        )
        async with self._database.session_factory() as session:
            rows = list((await session.scalars(statement)).all())
        return [AgentSchedule.model_validate(row.payload) for row in rows]

    async def claim_schedule(
        self,
        *,
        current: AgentSchedule,
        advanced: AgentSchedule,
    ) -> bool:
        if current.schedule_id != advanced.schedule_id:
            raise ValueError("A schedule claim cannot change the schedule ID")
        async with self._database.session_factory.begin() as session:
            result = await session.execute(
                update(AgentScheduleRow)
                .where(
                    AgentScheduleRow.schedule_id == current.schedule_id,
                    AgentScheduleRow.enabled.is_(True),
                    AgentScheduleRow.next_run_at == current.next_run_at,
                )
                .values(
                    enabled=advanced.enabled,
                    next_run_at=advanced.next_run_at,
                    payload=_payload(advanced),
                ),
            )
            return result.rowcount == 1

    async def create_run(self, run: AgentRun) -> AgentRun:
        async with self._database.session_factory() as session:
            try:
                async with session.begin():
                    session.add(
                        AgentRunRow(
                            run_id=run.run_id,
                            agent_id=run.agent_id,
                            capability_key=run.capability_key,
                            correlation_id=run.correlation_id,
                            status=run.status.value,
                            trigger=run.trigger.value,
                            idempotency_key=run.idempotency_key,
                            started_at=run.started_at,
                            updated_at=run.updated_at,
                            payload=_payload(run),
                        ),
                    )
                    await session.flush()
                return run
            except IntegrityError:
                await session.rollback()
                existing = (
                    await session.scalars(
                        select(AgentRunRow).where(
                            AgentRunRow.agent_id == run.agent_id,
                            AgentRunRow.capability_key == run.capability_key,
                            AgentRunRow.idempotency_key == run.idempotency_key,
                        ),
                    )
                ).first()
                if existing is None:
                    raise
                return AgentRun.model_validate(existing.payload)

    async def update_run(self, run: AgentRun) -> None:
        async with self._database.session_factory.begin() as session:
            row = await session.get(AgentRunRow, run.run_id)
            if row is None:
                raise LookupError(f"Run {run.run_id!r} was not found")
            row.status = run.status.value
            row.updated_at = run.updated_at
            row.payload = _payload(run)

    async def get_run(self, run_id: str) -> AgentRun | None:
        async with self._database.session_factory() as session:
            row = await session.get(AgentRunRow, run_id)
        return AgentRun.model_validate(row.payload) if row is not None else None

    async def list_runs(
        self,
        *,
        agent_id: str | None = None,
        capability_key: str | None = None,
        status: AgentRunStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AgentRun], int]:
        filters = []
        if agent_id is not None:
            filters.append(AgentRunRow.agent_id == agent_id)
        if capability_key is not None:
            filters.append(AgentRunRow.capability_key == capability_key)
        if status is not None:
            filters.append(AgentRunRow.status == status.value)
        statement = select(AgentRunRow).where(*filters)
        count_statement = select(func.count()).select_from(AgentRunRow).where(*filters)
        async with self._database.session_factory() as session:
            total = int((await session.scalar(count_statement)) or 0)
            rows = list(
                (
                    await session.scalars(
                        statement.order_by(AgentRunRow.started_at.desc())
                        .limit(limit)
                        .offset(offset),
                    )
                ).all(),
            )
        return [AgentRun.model_validate(row.payload) for row in rows], total

    async def save_snapshot(self, snapshot: DataSnapshot) -> None:
        async with self._database.session_factory.begin() as session:
            session.add(
                DataSnapshotRow(
                    snapshot_id=snapshot.snapshot_id,
                    run_id=snapshot.run_id,
                    agent_id=snapshot.agent_id,
                    collected_at=snapshot.collected_at,
                    checksum=snapshot.checksum,
                    payload=_payload(snapshot),
                ),
            )

    async def list_snapshots(self, run_id: str) -> list[DataSnapshot]:
        statement = (
            select(DataSnapshotRow)
            .where(DataSnapshotRow.run_id == run_id)
            .order_by(DataSnapshotRow.collected_at)
        )
        async with self._database.session_factory() as session:
            rows = list((await session.scalars(statement)).all())
        return [DataSnapshot.model_validate(row.payload) for row in rows]

    async def save_analysis(self, analysis: Analysis) -> None:
        async with self._database.session_factory.begin() as session:
            session.add(
                AnalysisRow(
                    analysis_id=analysis.analysis_id,
                    run_id=analysis.run_id,
                    snapshot_id=analysis.snapshot_id,
                    calculated_at=analysis.calculated_at,
                    payload=_payload(analysis),
                ),
            )

    async def save_findings(self, findings: Sequence[Finding]) -> None:
        async with self._database.session_factory.begin() as session:
            session.add_all(
                [
                    FindingRow(
                        finding_id=item.finding_id,
                        run_id=item.run_id,
                        analysis_id=item.analysis_id,
                        finding_type=item.finding_type,
                        severity=item.severity.value,
                        created_at=item.created_at,
                        payload=_payload(item),
                    )
                    for item in findings
                ],
            )

    async def list_findings(
        self,
        *,
        run_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Finding], int]:
        filters = [FindingRow.run_id == run_id] if run_id is not None else []
        statement = select(FindingRow).where(*filters)
        count_statement = select(func.count()).select_from(FindingRow).where(*filters)
        async with self._database.session_factory() as session:
            total = int((await session.scalar(count_statement)) or 0)
            rows = list(
                (
                    await session.scalars(
                        statement.order_by(FindingRow.created_at.desc())
                        .limit(limit)
                        .offset(offset),
                    )
                ).all(),
            )
        return [Finding.model_validate(row.payload) for row in rows], total

    async def save_recommendations(self, recommendations: Sequence[Recommendation]) -> None:
        async with self._database.session_factory.begin() as session:
            session.add_all(
                [
                    RecommendationRow(
                        recommendation_id=item.recommendation_id,
                        run_id=item.run_id,
                        action_type=item.action_type.value,
                        provider_object_id=item.provider_object_id,
                        expires_at=item.expires_at,
                        created_at=item.created_at,
                        payload=_payload(item),
                    )
                    for item in recommendations
                ],
            )

    async def list_recommendations(
        self,
        *,
        run_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Recommendation], int]:
        filters = [RecommendationRow.run_id == run_id] if run_id is not None else []
        statement = select(RecommendationRow).where(*filters)
        count_statement = select(func.count()).select_from(RecommendationRow).where(*filters)
        async with self._database.session_factory() as session:
            total = int((await session.scalar(count_statement)) or 0)
            rows = list(
                (
                    await session.scalars(
                        statement.order_by(RecommendationRow.created_at.desc())
                        .limit(limit)
                        .offset(offset),
                    )
                ).all(),
            )
        return [Recommendation.model_validate(row.payload) for row in rows], total

    async def create_action_request(
        self,
        proposal: ActionProposal,
        approval: ApprovalRequest | None,
    ) -> tuple[ActionProposal, ApprovalRequest | None]:
        async with self._database.session_factory() as session:
            try:
                async with session.begin():
                    session.add(_proposal_row(proposal))
                    if approval is not None:
                        session.add(_approval_row(approval))
                    await session.flush()
                return proposal, approval
            except IntegrityError:
                await session.rollback()
                existing_row = (
                    await session.scalars(
                        select(ActionProposalRow).where(
                            ActionProposalRow.idempotency_key == proposal.idempotency_key,
                        ),
                    )
                ).one_or_none()
                if existing_row is None:
                    raise
                existing = ActionProposal.model_validate(existing_row.payload)
                approval_row = (
                    await session.scalars(
                        select(ApprovalRequestRow).where(
                            ApprovalRequestRow.proposal_id == existing.proposal_id,
                        ),
                    )
                ).one_or_none()
                existing_approval = (
                    ApprovalRequest.model_validate(approval_row.payload)
                    if approval_row is not None
                    else None
                )
                return existing, existing_approval

    async def update_proposal(self, proposal: ActionProposal) -> None:
        async with self._database.session_factory.begin() as session:
            row = await session.get(ActionProposalRow, proposal.proposal_id)
            if row is None:
                raise LookupError(f"Proposal {proposal.proposal_id!r} was not found")
            row.status = proposal.status.value
            row.payload = _payload(proposal)

    async def get_proposal(self, proposal_id: str) -> ActionProposal | None:
        async with self._database.session_factory() as session:
            row = await session.get(ActionProposalRow, proposal_id)
        return ActionProposal.model_validate(row.payload) if row is not None else None

    async def list_proposals(
        self,
        *,
        run_id: str | None = None,
        status: ActionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ActionProposal], int]:
        filters = []
        if run_id is not None:
            filters.append(ActionProposalRow.run_id == run_id)
        if status is not None:
            filters.append(ActionProposalRow.status == status.value)
        statement = select(ActionProposalRow).where(*filters)
        count_statement = select(func.count()).select_from(ActionProposalRow).where(*filters)
        async with self._database.session_factory() as session:
            total = int((await session.scalar(count_statement)) or 0)
            rows = list(
                (
                    await session.scalars(
                        statement.order_by(ActionProposalRow.created_at.desc())
                        .limit(limit)
                        .offset(offset),
                    )
                ).all(),
            )
        return [ActionProposal.model_validate(row.payload) for row in rows], total

    async def get_approval_for_proposal(self, proposal_id: str) -> ApprovalRequest | None:
        statement = select(ApprovalRequestRow).where(
            ApprovalRequestRow.proposal_id == proposal_id,
        )
        async with self._database.session_factory() as session:
            row = (await session.scalars(statement)).first()
        return ApprovalRequest.model_validate(row.payload) if row is not None else None

    async def apply_approval_decision(
        self,
        request: ApprovalRequest,
        decision: ApprovalDecision,
        proposal: ActionProposal,
    ) -> None:
        try:
            async with self._database.session_factory.begin() as session:
                request_row = (
                    await session.scalars(
                        select(ApprovalRequestRow)
                        .where(ApprovalRequestRow.approval_id == request.approval_id)
                        .with_for_update(),
                    )
                ).one_or_none()
                proposal_row = (
                    await session.scalars(
                        select(ActionProposalRow)
                        .where(ActionProposalRow.proposal_id == proposal.proposal_id)
                        .with_for_update(),
                    )
                ).one_or_none()
                if request_row is None:
                    raise LookupError(f"Approval {request.approval_id!r} was not found")
                if proposal_row is None:
                    raise LookupError(f"Proposal {proposal.proposal_id!r} was not found")
                persisted_request = ApprovalRequest.model_validate(request_row.payload)
                persisted_proposal = ActionProposal.model_validate(proposal_row.payload)
                if persisted_request.status is not ApprovalStatus.PENDING or (
                    persisted_proposal.status is not ActionStatus.AWAITING_APPROVAL
                ):
                    raise ConcurrentOperationError(
                        "The approval or proposal was already decided by another request",
                    )
                request_row.status = request.status.value
                request_row.payload = _payload(request)
                proposal_row.status = proposal.status.value
                proposal_row.payload = _payload(proposal)
                session.add(
                    ApprovalDecisionRow(
                        approval_id=decision.approval_id,
                        proposal_id=decision.proposal_id,
                        status=decision.status.value,
                        decided_by=decision.decided_by,
                        decided_at=decision.decided_at,
                        payload=_payload(decision),
                    ),
                )
        except IntegrityError as exc:
            raise ConcurrentOperationError(
                "The approval was already decided by another request",
            ) from exc

    async def list_approvals(
        self,
        *,
        status: ApprovalStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ApprovalRequest], int]:
        filters = [ApprovalRequestRow.status == status.value] if status is not None else []
        statement = select(ApprovalRequestRow).where(*filters)
        count_statement = select(func.count()).select_from(ApprovalRequestRow).where(*filters)
        async with self._database.session_factory() as session:
            total = int((await session.scalar(count_statement)) or 0)
            rows = list(
                (
                    await session.scalars(
                        statement.order_by(ApprovalRequestRow.requested_at.desc())
                        .limit(limit)
                        .offset(offset),
                    )
                ).all(),
            )
        return [ApprovalRequest.model_validate(row.payload) for row in rows], total

    async def save_execution(self, execution: ActionExecution) -> ActionExecution:
        async with self._database.session_factory() as session:
            try:
                async with session.begin():
                    session.add(
                        ActionExecutionRow(
                            execution_id=execution.execution_id,
                            proposal_id=execution.proposal_id,
                            run_id=execution.run_id,
                            idempotency_key=execution.idempotency_key,
                            status=execution.status.value,
                            attempted_at=execution.attempted_at,
                            payload=_payload(execution),
                        ),
                    )
                    await session.flush()
                return execution
            except IntegrityError:
                await session.rollback()
                existing = (
                    await session.scalars(
                        select(ActionExecutionRow).where(
                            ActionExecutionRow.idempotency_key == execution.idempotency_key,
                        ),
                    )
                ).first()
                if existing is None:
                    raise
                return ActionExecution.model_validate(existing.payload)

    async def finalize_action_state(
        self,
        *,
        proposal: ActionProposal,
        execution: ActionExecution,
        verification: ActionVerification | None = None,
    ) -> None:
        async with self._database.session_factory.begin() as session:
            proposal_row = await session.get(ActionProposalRow, proposal.proposal_id)
            if proposal_row is None:
                raise LookupError(f"Proposal {proposal.proposal_id!r} was not found")
            proposal_row.status = proposal.status.value
            proposal_row.payload = _payload(proposal)

            execution_row = await session.get(ActionExecutionRow, execution.execution_id)
            if execution_row is None:
                execution_row = ActionExecutionRow(
                    execution_id=execution.execution_id,
                    proposal_id=execution.proposal_id,
                    run_id=execution.run_id,
                    idempotency_key=execution.idempotency_key,
                    status=execution.status.value,
                    attempted_at=execution.attempted_at,
                    payload=_payload(execution),
                )
                session.add(execution_row)
            else:
                execution_row.status = execution.status.value
                execution_row.payload = _payload(execution)

            if verification is not None:
                verification_row = (
                    await session.scalars(
                        select(ActionVerificationRow).where(
                            ActionVerificationRow.execution_id == execution.execution_id,
                        ),
                    )
                ).one_or_none()
                if verification_row is None:
                    session.add(
                        ActionVerificationRow(
                            verification_id=verification.verification_id,
                            execution_id=verification.execution_id,
                            status=verification.status.value,
                            checked_at=verification.checked_at,
                            payload=_payload(verification),
                        ),
                    )
                else:
                    verification_row.status = verification.status.value
                    verification_row.checked_at = verification.checked_at
                    verification_row.payload = _payload(verification)

    async def get_execution_by_idempotency(self, key: str) -> ActionExecution | None:
        statement = select(ActionExecutionRow).where(ActionExecutionRow.idempotency_key == key)
        async with self._database.session_factory() as session:
            row = (await session.scalars(statement)).first()
        return ActionExecution.model_validate(row.payload) if row is not None else None

    async def get_execution_for_proposal(self, proposal_id: str) -> ActionExecution | None:
        statement = select(ActionExecutionRow).where(
            ActionExecutionRow.proposal_id == proposal_id,
        )
        async with self._database.session_factory() as session:
            row = (await session.scalars(statement)).first()
        return ActionExecution.model_validate(row.payload) if row is not None else None

    async def get_verification_for_execution(
        self,
        execution_id: str,
    ) -> ActionVerification | None:
        statement = select(ActionVerificationRow).where(
            ActionVerificationRow.execution_id == execution_id,
        )
        async with self._database.session_factory() as session:
            row = (await session.scalars(statement)).one_or_none()
        return ActionVerification.model_validate(row.payload) if row is not None else None

    async def list_executions(
        self,
        *,
        agent_id: str | None = None,
        capability_key: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ActionExecution], int]:
        filters = []
        if since is not None:
            filters.append(ActionExecutionRow.attempted_at >= since)
        if agent_id is not None:
            filters.append(
                ActionExecutionRow.run_id.in_(
                    select(AgentRunRow.run_id).where(AgentRunRow.agent_id == agent_id),
                ),
            )
        if capability_key is not None:
            filters.append(
                ActionExecutionRow.run_id.in_(
                    select(AgentRunRow.run_id).where(
                        AgentRunRow.capability_key == capability_key,
                    ),
                ),
            )
        statement = select(ActionExecutionRow).where(*filters)
        count_statement = select(func.count()).select_from(ActionExecutionRow).where(*filters)
        async with self._database.session_factory() as session:
            total = int((await session.scalar(count_statement)) or 0)
            rows = list(
                (
                    await session.scalars(
                        statement.order_by(ActionExecutionRow.attempted_at.desc())
                        .limit(limit)
                        .offset(offset),
                    )
                ).all(),
            )
        return [ActionExecution.model_validate(row.payload) for row in rows], total

    async def save_report(self, report: AgentReport) -> None:
        async with self._database.session_factory.begin() as session:
            session.add(
                AgentReportRow(
                    report_id=report.report_id,
                    agent_id=report.agent_id,
                    run_id=report.run_id,
                    report_type=report.report_type,
                    created_at=report.created_at,
                    human_readable=report.human_readable,
                    payload=_payload(report),
                ),
            )

    async def get_report(self, report_id: str) -> AgentReport | None:
        async with self._database.session_factory() as session:
            row = await session.get(AgentReportRow, report_id)
        return AgentReport.model_validate(row.payload) if row is not None else None

    async def list_reports(
        self,
        *,
        agent_id: str | None = None,
        capability_key: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AgentReport], int]:
        filters = [AgentReportRow.agent_id == agent_id] if agent_id is not None else []
        if capability_key is not None:
            filters.append(
                AgentReportRow.run_id.in_(
                    select(AgentRunRow.run_id).where(
                        AgentRunRow.capability_key == capability_key,
                    ),
                ),
            )
        statement = select(AgentReportRow).where(*filters)
        count_statement = select(func.count()).select_from(AgentReportRow).where(*filters)
        async with self._database.session_factory() as session:
            total = int((await session.scalar(count_statement)) or 0)
            rows = list(
                (
                    await session.scalars(
                        statement.order_by(AgentReportRow.created_at.desc())
                        .limit(limit)
                        .offset(offset),
                    )
                ).all(),
            )
        return [AgentReport.model_validate(row.payload) for row in rows], total

    async def save_outcome_evaluation(self, evaluation: OutcomeEvaluation) -> None:
        async with self._database.session_factory.begin() as session:
            session.add(
                OutcomeEvaluationRow(
                    evaluation_id=evaluation.evaluation_id,
                    run_id=evaluation.run_id,
                    proposal_id=evaluation.proposal_id,
                    agent_id=evaluation.agent_id,
                    capability_key=evaluation.capability_key,
                    status=evaluation.status.value,
                    evaluated_at=evaluation.evaluated_at,
                    payload=_payload(evaluation),
                ),
            )

    async def list_outcome_evaluations(
        self,
        *,
        run_id: str | None = None,
        proposal_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[OutcomeEvaluation], int]:
        filters = []
        if run_id is not None:
            filters.append(OutcomeEvaluationRow.run_id == run_id)
        if proposal_id is not None:
            filters.append(OutcomeEvaluationRow.proposal_id == proposal_id)
        statement = select(OutcomeEvaluationRow).where(*filters)
        count_statement = select(func.count()).select_from(OutcomeEvaluationRow).where(*filters)
        async with self._database.session_factory() as session:
            total = int((await session.scalar(count_statement)) or 0)
            rows = list(
                (
                    await session.scalars(
                        statement.order_by(OutcomeEvaluationRow.evaluated_at.desc())
                        .limit(limit)
                        .offset(offset),
                    )
                ).all(),
            )
        return [OutcomeEvaluation.model_validate(row.payload) for row in rows], total

    async def save_audit_event(self, event: AuditEvent) -> None:
        async with self._database.session_factory.begin() as session:
            session.add(
                AuditEventRow(
                    event_id=event.event_id,
                    correlation_id=event.correlation_id,
                    agent_id=event.agent_id,
                    capability_key=event.capability_key,
                    run_id=event.run_id,
                    event_type=event.event_type.value,
                    occurred_at=event.occurred_at,
                    actor_id=event.actor_id,
                    payload=_payload(event),
                ),
            )

    async def list_audit_events(
        self,
        *,
        correlation_id: str | None = None,
        run_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[AuditEvent], int]:
        filters = []
        if correlation_id is not None:
            filters.append(AuditEventRow.correlation_id == correlation_id)
        if run_id is not None:
            filters.append(AuditEventRow.run_id == run_id)
        statement = select(AuditEventRow).where(*filters)
        count_statement = select(func.count()).select_from(AuditEventRow).where(*filters)
        async with self._database.session_factory() as session:
            total = int((await session.scalar(count_statement)) or 0)
            rows = list(
                (
                    await session.scalars(
                        statement.order_by(AuditEventRow.occurred_at.desc())
                        .limit(limit)
                        .offset(offset),
                    )
                ).all(),
            )
        return [AuditEvent.model_validate(row.payload) for row in rows], total

    async def save_integration_health(self, health: IntegrationHealth) -> None:
        async with self._database.session_factory.begin() as session:
            row = await session.get(IntegrationHealthRow, health.integration_id)
            if row is None:
                session.add(
                    IntegrationHealthRow(
                        integration_id=health.integration_id,
                        status=health.status.value,
                        checked_at=health.checked_at,
                        payload=_payload(health),
                    ),
                )
            else:
                row.status = health.status.value
                row.checked_at = health.checked_at
                row.payload = _payload(health)

    async def get_integration_health(self, integration_id: str) -> IntegrationHealth | None:
        async with self._database.session_factory() as session:
            row = await session.get(IntegrationHealthRow, integration_id)
        return IntegrationHealth.model_validate(row.payload) if row is not None else None

    async def set_control(
        self,
        *,
        key: str,
        enabled: bool,
        updated_at: datetime,
        updated_by: str,
    ) -> None:
        async with self._database.session_factory.begin() as session:
            row = await session.get(SystemControlRow, key)
            if row is None:
                session.add(
                    SystemControlRow(
                        control_key=key,
                        enabled=enabled,
                        updated_at=updated_at,
                        updated_by=updated_by,
                    ),
                )
            else:
                row.enabled = enabled
                row.updated_at = updated_at
                row.updated_by = updated_by

    async def get_control(self, key: str, *, default: bool = False) -> bool:
        async with self._database.session_factory() as session:
            row = await session.get(SystemControlRow, key)
        return row.enabled if row is not None else default

    async def acquire_lock(
        self,
        *,
        key: str,
        owner_id: str,
        now: datetime,
        expires_at: datetime,
    ) -> bool:
        async with self._database.session_factory.begin() as session:
            claimed = await session.execute(
                update(JobLockRow)
                .where(
                    JobLockRow.lock_key == key,
                    or_(
                        JobLockRow.expires_at <= now,
                        JobLockRow.owner_id == owner_id,
                    ),
                )
                .values(owner_id=owner_id, acquired_at=now, expires_at=expires_at),
            )
            if claimed.rowcount == 1:
                return True
            try:
                async with session.begin_nested():
                    session.add(
                        JobLockRow(
                            lock_key=key,
                            owner_id=owner_id,
                            acquired_at=now,
                            expires_at=expires_at,
                        ),
                    )
                    await session.flush()
            except IntegrityError:
                return False
        return True

    async def release_lock(self, *, key: str, owner_id: str) -> None:
        async with self._database.session_factory.begin() as session:
            await session.execute(
                delete(JobLockRow).where(
                    JobLockRow.lock_key == key,
                    JobLockRow.owner_id == owner_id,
                ),
            )

    async def cleanup_before(self, cutoff: datetime) -> dict[str, int]:
        counts: dict[str, int] = {}
        async with self._database.session_factory.begin() as session:
            stale_snapshot_ids = select(DataSnapshotRow.snapshot_id).where(
                DataSnapshotRow.collected_at < cutoff,
            )
            stale_analysis_ids = select(AnalysisRow.analysis_id).where(
                AnalysisRow.snapshot_id.in_(stale_snapshot_ids),
            )
            await session.execute(
                delete(FindingRow).where(FindingRow.analysis_id.in_(stale_analysis_ids)),
            )
            await session.execute(
                delete(AnalysisRow).where(AnalysisRow.analysis_id.in_(stale_analysis_ids)),
            )
            result = await session.execute(
                delete(DataSnapshotRow).where(DataSnapshotRow.collected_at < cutoff),
            )
            counts["snapshots"] = max(result.rowcount or 0, 0)
            result = await session.execute(
                delete(JobLockRow).where(JobLockRow.expires_at < datetime.now(UTC)),
            )
            counts["locks"] = max(result.rowcount or 0, 0)
        return counts


def _payload(model: BaseModel) -> dict[str, object]:
    return cast(dict[str, object], model.model_dump(mode="json"))


def _proposal_row(proposal: ActionProposal) -> ActionProposalRow:
    return ActionProposalRow(
        proposal_id=proposal.proposal_id,
        run_id=proposal.run_id,
        agent_id=proposal.agent_id,
        provider=proposal.provider,
        provider_object_id=proposal.provider_object_id,
        action_type=proposal.action_type.value,
        status=proposal.status.value,
        idempotency_key=proposal.idempotency_key,
        expires_at=proposal.expires_at,
        created_at=proposal.created_at,
        payload=_payload(proposal),
    )


def _approval_row(approval: ApprovalRequest) -> ApprovalRequestRow:
    return ApprovalRequestRow(
        approval_id=approval.approval_id,
        proposal_id=approval.proposal_id,
        status=approval.status.value,
        requested_by=approval.requested_by,
        requested_at=approval.requested_at,
        expires_at=approval.expires_at,
        payload=_payload(approval),
    )
