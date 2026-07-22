from datetime import timedelta
from typing import cast

from pydantic import JsonValue

from app.mana_operation_ai.application.action_lifecycle import expected_state, state_differences
from app.mana_operation_ai.application.ports import (
    Clock,
    IdGenerator,
    OperationRepository,
    ProviderPermanentError,
    ProviderTransientError,
)
from app.mana_operation_ai.application.registry import AdsPlatformRegistry, AgentRegistry
from app.mana_operation_ai.domain.enums import (
    ActionStatus,
    AuditEventType,
    ExecutionStatus,
    UserRole,
    VerificationStatus,
)
from app.mana_operation_ai.domain.models import ActionVerification, AuditEvent


class OperationMaintenanceService:
    def __init__(
        self,
        *,
        repository: OperationRepository,
        platforms: AdsPlatformRegistry,
        agents: AgentRegistry,
        clock: Clock,
        ids: IdGenerator,
        retention_days: int = 90,
    ) -> None:
        self._repository = repository
        self._platforms = platforms
        self._agents = agents
        self._clock = clock
        self._ids = ids
        self._retention_days = retention_days

    async def reconcile_actions(self) -> int:
        proposals, _ = await self._repository.list_proposals(
            status=ActionStatus.EXECUTING,
            limit=1_000,
        )
        reconciled = 0
        for proposal in proposals:
            execution = await self._repository.get_execution_for_proposal(proposal.proposal_id)
            if execution is None:
                continue
            try:
                observed = await self._platforms.get(proposal.provider).get_object_state(
                    proposal.object_type,
                    proposal.provider_object_id,
                )
            except ProviderTransientError:
                continue
            except ProviderPermanentError as exc:
                verification = ActionVerification(
                    verification_id=self._ids.new(),
                    execution_id=execution.execution_id,
                    status=VerificationStatus.UNAVAILABLE,
                    checked_at=self._clock.now(),
                    expected_state={},
                    observed_state={},
                    differences=["Provider state is permanently unavailable."],
                )
                failed_execution = execution.model_copy(
                    update={
                        "status": ExecutionStatus.FAILED,
                        "completed_at": self._clock.now(),
                        "error_code": "reconciliation_provider_unavailable",
                        "error_message": str(exc),
                    },
                )
                failed_proposal = proposal.model_copy(update={"status": ActionStatus.FAILED})
                await self._repository.finalize_action_state(
                    proposal=failed_proposal,
                    execution=failed_execution,
                    verification=verification,
                )
                await self._agents.get(proposal.agent_id).finalize_after_actions(
                    proposal.run_id,
                )
                reconciled += 1
                continue
            expected = expected_state(proposal, observed)
            differences = state_differences(expected, observed)
            verified = not differences
            verification = ActionVerification(
                verification_id=self._ids.new(),
                execution_id=execution.execution_id,
                status=(VerificationStatus.VERIFIED if verified else VerificationStatus.MISMATCH),
                checked_at=self._clock.now(),
                expected_state=expected,
                observed_state=observed.raw_safe,
                differences=differences,
            )
            updated_execution = execution.model_copy(
                update={
                    "status": (
                        ExecutionStatus.SUCCEEDED if verified else ExecutionStatus.PARTIALLY_APPLIED
                    ),
                    "completed_at": self._clock.now(),
                },
            )
            updated_proposal = proposal.model_copy(
                update={
                    "status": (
                        ActionStatus.SUCCEEDED if verified else ActionStatus.PARTIALLY_APPLIED
                    ),
                },
            )
            await self._repository.finalize_action_state(
                proposal=updated_proposal,
                execution=updated_execution,
                verification=verification,
            )
            await self._repository.save_audit_event(
                AuditEvent(
                    event_id=self._ids.new(),
                    correlation_id=proposal.run_id,
                    agent_id=proposal.agent_id,
                    run_id=proposal.run_id,
                    event_type=AuditEventType.ACTION_VERIFIED,
                    actor_id="reconciliation-job",
                    actor_role=UserRole.ADMIN,
                    occurred_at=self._clock.now(),
                    summary=f"Interrupted action reconciled as {verification.status.value}",
                    details={"differences": cast(list[JsonValue], differences)},
                ),
            )
            await self._agents.get(proposal.agent_id).finalize_after_actions(proposal.run_id)
            reconciled += 1
        return reconciled

    async def cleanup(self) -> dict[str, int]:
        cutoff = self._clock.now() - timedelta(days=self._retention_days)
        return await self._repository.cleanup_before(cutoff)
