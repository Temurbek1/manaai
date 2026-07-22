import asyncio
import hashlib
from datetime import timedelta
from decimal import Decimal
from typing import cast

from pydantic import BaseModel, ConfigDict, JsonValue

from app.mana_operation_ai.application.policy import PolicyService
from app.mana_operation_ai.application.ports import (
    Clock,
    IdGenerator,
    OperationRepository,
    ProviderObjectNotFoundError,
    ProviderPermanentError,
    ProviderTransientError,
    WriteOperationForbidden,
)
from app.mana_operation_ai.application.registry import AdsPlatformRegistry
from app.mana_operation_ai.domain.enums import (
    ActionStatus,
    ActionType,
    ApprovalStatus,
    AuditEventType,
    ExecutionStatus,
    PolicyDecision,
    ProviderMode,
    UserRole,
    VerificationStatus,
)
from app.mana_operation_ai.domain.marketing import AdEntityType, ProviderObjectState
from app.mana_operation_ai.domain.models import (
    ActionExecution,
    ActionPolicyConfiguration,
    ActionProposal,
    ActionVerification,
    ApprovalDecision,
    ApprovalRequest,
    AudienceActionParameters,
    AuditEvent,
    BudgetActionParameters,
    Recommendation,
    StatusActionParameters,
)
from app.mana_operation_ai.domain.state_machine import ACTION_TRANSITIONS, require_transition


class ApprovalPermissionError(PermissionError):
    """Raised for an invalid actor or approval state."""


class StaleProposalError(RuntimeError):
    """Raised after provider state diverges from the approved proposal."""


class ActionSafetyError(RuntimeError):
    """Raised when a current safeguard prevents execution."""


class ActionReconciliationRequiredError(RuntimeError):
    """Raised when a dispatched write must be reconciled before any retry."""


class ProposalCreation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal: ActionProposal
    approval: ApprovalRequest | None = None


class ActionLifecycleResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal: ActionProposal
    approval_decision: ApprovalDecision | None = None
    execution: ActionExecution | None = None
    verification: ActionVerification | None = None


class ActionLifecycleService:
    def __init__(
        self,
        *,
        repository: OperationRepository,
        platforms: AdsPlatformRegistry,
        policy: PolicyService,
        clock: Clock,
        ids: IdGenerator,
        dry_run: bool,
        allow_self_approval: bool,
        global_kill_switch_default: bool,
        lock_timeout_seconds: int,
        verification_attempts: int = 4,
        verification_delay_seconds: float = 1.0,
    ) -> None:
        self._repository = repository
        self._platforms = platforms
        self._policy = policy
        self._clock = clock
        self._ids = ids
        self._dry_run = dry_run
        self._allow_self_approval = allow_self_approval
        self._global_kill_switch_default = global_kill_switch_default
        self._lock_timeout_seconds = lock_timeout_seconds
        self._verification_attempts = verification_attempts
        self._verification_delay_seconds = verification_delay_seconds

    async def create_proposal(
        self,
        *,
        agent_id: str,
        provider_name: str,
        run_id: str,
        correlation_id: str,
        recommendation: Recommendation,
        configuration: ActionPolicyConfiguration,
        configuration_version: int,
        requested_by: str,
    ) -> ProposalCreation | None:
        if recommendation.action_type in {
            ActionType.MAINTAIN,
            ActionType.OBSERVE,
            ActionType.PROPOSE_TEST,
        }:
            return None
        platform = self._platforms.get(provider_name)
        current = (
            _advisory_object_state(recommendation, provider_name)
            if platform.provider_mode is ProviderMode.LIVE_READ_ONLY
            else await platform.get_object_state(
                recommendation.object_type,
                recommendation.provider_object_id,
            )
        )
        policy = await self._policy.evaluate(
            agent_id=agent_id,
            recommendation=recommendation,
            configuration=configuration,
            configuration_version=configuration_version,
        )
        if policy.decision is PolicyDecision.DENY:
            status = ActionStatus.POLICY_REJECTED
        elif policy.decision is PolicyDecision.REQUIRE_APPROVAL:
            status = ActionStatus.AWAITING_APPROVAL
        else:
            status = ActionStatus.APPROVED
        proposal = ActionProposal(
            proposal_id=self._ids.new(),
            run_id=run_id,
            recommendation_id=recommendation.recommendation_id,
            agent_id=agent_id,
            provider=provider_name,
            provider_mode=platform.provider_mode,
            execution_forbidden=platform.provider_mode is ProviderMode.LIVE_READ_ONLY,
            object_type=recommendation.object_type,
            provider_object_id=recommendation.provider_object_id,
            action_type=recommendation.action_type,
            parameters=recommendation.parameters,
            evidence=recommendation.evidence,
            reasoning=recommendation.reasoning,
            confidence=recommendation.confidence,
            expected_effect=recommendation.expected_effect,
            risks=recommendation.risks,
            missing_data=recommendation.missing_data,
            manual_action_instructions=_manual_action_instructions(recommendation),
            policy=policy,
            status=status,
            idempotency_key=_action_key(recommendation, current),
            current_state_hash=current.state_hash,
            expires_at=recommendation.expires_at,
            created_at=self._clock.now(),
        )
        approval = (
            ApprovalRequest(
                approval_id=self._ids.new(),
                proposal_id=proposal.proposal_id,
                requested_at=self._clock.now(),
                expires_at=proposal.expires_at,
                requested_by=requested_by,
                required_role=UserRole.APPROVER,
                status=ApprovalStatus.PENDING,
            )
            if status is ActionStatus.AWAITING_APPROVAL
            else None
        )
        persisted_proposal, persisted_approval = await self._repository.create_action_request(
            proposal,
            approval,
        )
        if persisted_proposal.proposal_id != proposal.proposal_id:
            return ProposalCreation(
                proposal=persisted_proposal,
                approval=persisted_approval,
            )
        await self._audit(
            correlation_id=correlation_id,
            proposal=proposal,
            event_type=AuditEventType.ACTION_PROPOSED,
            actor_id=requested_by,
            actor_role=UserRole.OPERATOR,
            summary=f"Action proposal created with status {proposal.status.value}",
            details={"policy_decision": policy.decision.value},
        )
        return ProposalCreation(proposal=persisted_proposal, approval=persisted_approval)

    async def decide(
        self,
        *,
        proposal_id: str,
        approve: bool,
        actor_id: str,
        actor_role: UserRole,
        reason: str,
        correlation_id: str,
    ) -> ActionLifecycleResult:
        if actor_role not in {UserRole.APPROVER, UserRole.ADMIN}:
            raise ApprovalPermissionError("Approver or admin role is required")
        proposal = await self._required_proposal(proposal_id)
        approval = await self._repository.get_approval_for_proposal(proposal_id)
        if approval is None or approval.status is not ApprovalStatus.PENDING:
            raise ApprovalPermissionError("No pending approval exists for this proposal")
        if not self._allow_self_approval and approval.requested_by == actor_id:
            raise ApprovalPermissionError("Self-approval is disabled")
        now = self._clock.now()
        if approval.expires_at <= now or proposal.expires_at <= now:
            expired_request = approval.model_copy(update={"status": ApprovalStatus.EXPIRED})
            require_transition(proposal.status, ActionStatus.EXPIRED, ACTION_TRANSITIONS)
            expired_proposal = proposal.model_copy(update={"status": ActionStatus.EXPIRED})
            decision = ApprovalDecision(
                approval_id=approval.approval_id,
                proposal_id=proposal_id,
                status=ApprovalStatus.EXPIRED,
                decided_at=now,
                decided_by=actor_id,
                reason="Proposal expired before the decision.",
            )
            await self._repository.apply_approval_decision(
                expired_request,
                decision,
                expired_proposal,
            )
            return ActionLifecycleResult(
                proposal=expired_proposal,
                approval_decision=decision,
            )

        approval_status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        target_status = ActionStatus.APPROVED if approve else ActionStatus.REJECTED
        require_transition(proposal.status, target_status, ACTION_TRANSITIONS)
        updated_approval = approval.model_copy(update={"status": approval_status})
        updated_proposal = proposal.model_copy(update={"status": target_status})
        decision = ApprovalDecision(
            approval_id=approval.approval_id,
            proposal_id=proposal_id,
            status=approval_status,
            decided_at=now,
            decided_by=actor_id,
            reason=reason,
        )
        await self._repository.apply_approval_decision(
            updated_approval,
            decision,
            updated_proposal,
        )
        await self._audit(
            correlation_id=correlation_id,
            proposal=updated_proposal,
            event_type=AuditEventType.APPROVAL_DECIDED,
            actor_id=actor_id,
            actor_role=actor_role,
            summary=f"Action proposal {approval_status.value}",
            details={"reason": reason},
        )
        if not approve:
            return ActionLifecycleResult(
                proposal=updated_proposal,
                approval_decision=decision,
            )
        if updated_proposal.execution_forbidden:
            return ActionLifecycleResult(
                proposal=updated_proposal,
                approval_decision=decision,
            )
        executed = await self.execute_proposal(
            proposal=updated_proposal,
            actor_id=actor_id,
            actor_role=actor_role,
            correlation_id=correlation_id,
        )
        return executed.model_copy(update={"approval_decision": decision})

    async def execute_proposal(
        self,
        *,
        proposal: ActionProposal,
        actor_id: str,
        actor_role: UserRole,
        correlation_id: str,
    ) -> ActionLifecycleResult:
        platform = self._platforms.get(proposal.provider)
        if proposal.execution_forbidden or platform.provider_mode is ProviderMode.LIVE_READ_ONLY:
            await self._audit(
                correlation_id=correlation_id,
                proposal=proposal,
                event_type=AuditEventType.WRITE_FORBIDDEN,
                actor_id=actor_id,
                actor_role=actor_role,
                summary="LIVE Meta write attempt blocked before provider dispatch",
                details={
                    "provider_mode": ProviderMode.LIVE_READ_ONLY.value,
                    "action_type": proposal.action_type.value,
                    "provider_request_sent": False,
                },
            )
            raise WriteOperationForbidden(
                "LIVE Meta is read-only; execution is forbidden and no provider request was sent",
            )
        if proposal.status is not ActionStatus.APPROVED:
            raise ActionSafetyError("Only approved proposals can be executed")
        previous = await self._repository.get_execution_by_idempotency(proposal.idempotency_key)
        if previous is not None:
            return ActionLifecycleResult(proposal=proposal, execution=previous)

        lock_key = ":".join(
            (
                "provider-action",
                proposal.provider,
                proposal.object_type,
                proposal.provider_object_id,
            ),
        )
        owner_id = self._ids.new()
        now = self._clock.now()
        acquired = await self._repository.acquire_lock(
            key=lock_key,
            owner_id=owner_id,
            now=now,
            expires_at=now + timedelta(seconds=self._lock_timeout_seconds),
        )
        if not acquired:
            raise ActionSafetyError(
                "Another approved action is already executing for this provider object",
            )
        try:
            return await self._execute_proposal_locked(
                proposal=proposal,
                actor_id=actor_id,
                actor_role=actor_role,
                correlation_id=correlation_id,
            )
        finally:
            await self._repository.release_lock(key=lock_key, owner_id=owner_id)

    async def _execute_proposal_locked(
        self,
        *,
        proposal: ActionProposal,
        actor_id: str,
        actor_role: UserRole,
        correlation_id: str,
    ) -> ActionLifecycleResult:
        platform = self._platforms.get(proposal.provider)
        if proposal.execution_forbidden or platform.provider_mode is ProviderMode.LIVE_READ_ONLY:
            raise WriteOperationForbidden(
                "LIVE Meta is read-only; execution is forbidden and no provider request was sent",
            )
        if proposal.status is not ActionStatus.APPROVED:
            raise ActionSafetyError("Only approved proposals can be executed")
        previous = await self._repository.get_execution_by_idempotency(proposal.idempotency_key)
        if previous is not None:
            return ActionLifecycleResult(proposal=proposal, execution=previous)
        if proposal.expires_at <= self._clock.now():
            require_transition(proposal.status, ActionStatus.EXPIRED, ACTION_TRANSITIONS)
            expired = proposal.model_copy(update={"status": ActionStatus.EXPIRED})
            await self._repository.update_proposal(expired)
            await self._audit(
                correlation_id=correlation_id,
                proposal=expired,
                event_type=AuditEventType.ACTION_EXECUTED,
                actor_id=actor_id,
                actor_role=actor_role,
                summary="Approved action expired before provider execution",
                details={"execution_status": "not_executed"},
            )
            raise ActionSafetyError("The proposal has expired")
        await self._require_safety(proposal)
        try:
            before = await platform.get_object_state(
                proposal.object_type,
                proposal.provider_object_id,
            )
        except ProviderObjectNotFoundError as exc:
            failed = await self._failed_execution(
                proposal=proposal,
                before=None,
                message="The provider object no longer exists or is inaccessible.",
                error_code="provider_object_not_found",
            )
            raise StaleProposalError(
                failed.error_message or "Provider object was not found",
            ) from exc
        except ProviderPermanentError as exc:
            failed = await self._failed_execution(
                proposal=proposal,
                before=None,
                message="The provider rejected the pre-execution state check.",
                error_code="provider_permanent_error",
            )
            raise ActionSafetyError(failed.error_message or "Provider state check failed") from exc
        except ProviderTransientError as exc:
            raise ActionSafetyError(
                "The provider state is temporarily unavailable; the approved action was not sent",
            ) from exc
        if before.state_hash != proposal.current_state_hash:
            failed = await self._failed_execution(
                proposal=proposal,
                before=before,
                message="The provider object changed after the proposal was created.",
            )
            raise StaleProposalError(failed.error_message or "Proposal is stale")
        if (state_violation := provider_state_violation(proposal, before)) is not None:
            failed = await self._failed_execution(
                proposal=proposal,
                before=before,
                message=state_violation,
                error_code="provider_state_not_executable",
            )
            raise StaleProposalError(failed.error_message or "Provider state is not executable")

        now = self._clock.now()
        requested_change = cast(
            dict[str, JsonValue],
            proposal.parameters.model_dump(mode="json"),
        )
        pending = ActionExecution(
            execution_id=self._ids.new(),
            proposal_id=proposal.proposal_id,
            run_id=proposal.run_id,
            idempotency_key=proposal.idempotency_key,
            status=ExecutionStatus.PENDING,
            attempted_at=now,
            before_state=before.raw_safe,
            requested_change=requested_change,
            provider_response={},
        )
        pending = await self._repository.save_execution(pending)
        if self._dry_run:
            require_transition(proposal.status, ActionStatus.DRY_RUN, ACTION_TRANSITIONS)
            dry_proposal = proposal.model_copy(update={"status": ActionStatus.DRY_RUN})
            dry_execution = pending.model_copy(
                update={"status": ExecutionStatus.DRY_RUN, "completed_at": now},
            )
            await self._repository.finalize_action_state(
                proposal=dry_proposal,
                execution=dry_execution,
            )
            await self._audit(
                correlation_id=correlation_id,
                proposal=dry_proposal,
                event_type=AuditEventType.ACTION_EXECUTED,
                actor_id=actor_id,
                actor_role=actor_role,
                summary="Action completed as a dry run; provider state was not changed",
                details={"execution_status": ExecutionStatus.DRY_RUN.value},
            )
            return ActionLifecycleResult(proposal=dry_proposal, execution=dry_execution)

        require_transition(proposal.status, ActionStatus.EXECUTING, ACTION_TRANSITIONS)
        executing_proposal = proposal.model_copy(update={"status": ActionStatus.EXECUTING})
        executing = pending.model_copy(update={"status": ExecutionStatus.EXECUTING})
        await self._repository.finalize_action_state(
            proposal=executing_proposal,
            execution=executing,
        )
        try:
            result = await platform.execute(
                object_type=proposal.object_type,
                provider_object_id=proposal.provider_object_id,
                parameters=proposal.parameters,
                idempotency_key=proposal.idempotency_key,
            )
        except ProviderPermanentError as exc:
            failed_execution = executing.model_copy(
                update={
                    "status": ExecutionStatus.FAILED,
                    "completed_at": self._clock.now(),
                    "error_code": "provider_permanent_error",
                    "error_message": "The provider rejected the action.",
                },
            )
            failed_proposal = executing_proposal.model_copy(update={"status": ActionStatus.FAILED})
            await self._repository.finalize_action_state(
                proposal=failed_proposal,
                execution=failed_execution,
            )
            raise ActionSafetyError("The provider rejected the action") from exc
        except Exception as exc:
            uncertain = executing.model_copy(
                update={
                    "error_code": "write_outcome_uncertain",
                    "error_message": (
                        "The write outcome is uncertain; reconciliation is required before retry."
                    ),
                },
            )
            await self._repository.finalize_action_state(
                proposal=executing_proposal,
                execution=uncertain,
            )
            await self._audit(
                correlation_id=correlation_id,
                proposal=executing_proposal,
                event_type=AuditEventType.ACTION_EXECUTED,
                actor_id=actor_id,
                actor_role=actor_role,
                summary="Provider write outcome is uncertain; reconciliation required",
                details={"execution_status": ExecutionStatus.EXECUTING.value},
            )
            raise ActionReconciliationRequiredError(
                "The action may have been applied; do not retry while reconciliation is pending",
            ) from exc

        if not result.accepted:
            failed_execution = executing.model_copy(
                update={
                    "status": ExecutionStatus.FAILED,
                    "completed_at": self._clock.now(),
                    "provider_request_id": result.provider_request_id,
                    "provider_response": result.model_dump(mode="json"),
                    "error_code": "provider_not_accepted",
                    "error_message": "The provider did not accept the action.",
                },
            )
            failed_proposal = executing_proposal.model_copy(update={"status": ActionStatus.FAILED})
            await self._repository.finalize_action_state(
                proposal=failed_proposal,
                execution=failed_execution,
            )
            raise ActionSafetyError("The provider did not accept the action")

        expected = expected_state(proposal, before)
        after: ProviderObjectState | None = None
        differences: list[str] = []
        verification_error: Exception | None = None
        for attempt in range(self._verification_attempts):
            try:
                after = await platform.get_object_state(
                    proposal.object_type,
                    proposal.provider_object_id,
                )
                differences = state_differences(expected, after)
                verification_error = None
                if not differences:
                    break
            except Exception as exc:
                verification_error = exc
            if attempt + 1 < self._verification_attempts:
                await asyncio.sleep(self._verification_delay_seconds)

        if after is None or verification_error is not None:
            uncertain = executing.model_copy(
                update={
                    "provider_request_id": result.provider_request_id,
                    "provider_response": result.model_dump(mode="json"),
                    "error_code": "verification_unavailable",
                    "error_message": (
                        "The provider accepted the action, but its resulting state is unavailable."
                    ),
                },
            )
            await self._repository.finalize_action_state(
                proposal=executing_proposal,
                execution=uncertain,
            )
            raise ActionReconciliationRequiredError(
                "The provider accepted the action, but verification requires reconciliation",
            ) from verification_error
        verification_status = (
            VerificationStatus.VERIFIED if not differences else VerificationStatus.MISMATCH
        )
        execution_status = (
            ExecutionStatus.SUCCEEDED if not differences else ExecutionStatus.PARTIALLY_APPLIED
        )
        proposal_status = (
            ActionStatus.SUCCEEDED if not differences else ActionStatus.PARTIALLY_APPLIED
        )
        completed = executing.model_copy(
            update={
                "status": execution_status,
                "completed_at": self._clock.now(),
                "provider_request_id": result.provider_request_id,
                "provider_response": result.model_dump(mode="json"),
            },
        )
        completed_proposal = executing_proposal.model_copy(update={"status": proposal_status})
        verification = ActionVerification(
            verification_id=self._ids.new(),
            execution_id=completed.execution_id,
            status=verification_status,
            checked_at=self._clock.now(),
            expected_state=expected,
            observed_state=after.raw_safe,
            differences=differences,
        )
        await self._repository.finalize_action_state(
            proposal=completed_proposal,
            execution=completed,
            verification=verification,
        )
        await self._audit(
            correlation_id=correlation_id,
            proposal=completed_proposal,
            event_type=AuditEventType.ACTION_EXECUTED,
            actor_id=actor_id,
            actor_role=actor_role,
            summary=f"Action execution: {completed.status.value}",
            details={"provider_request_id": completed.provider_request_id},
        )
        await self._audit(
            correlation_id=correlation_id,
            proposal=completed_proposal,
            event_type=AuditEventType.ACTION_VERIFIED,
            actor_id=actor_id,
            actor_role=actor_role,
            summary=f"Action verification: {verification.status.value}",
            details={"differences": cast(list[JsonValue], differences)},
        )
        return ActionLifecycleResult(
            proposal=completed_proposal,
            execution=completed,
            verification=verification,
        )

    async def _require_safety(self, proposal: ActionProposal) -> None:
        if await self._repository.get_control(
            "global_kill_switch",
            default=self._global_kill_switch_default,
        ):
            raise ActionSafetyError("The global kill switch is enabled")
        if await self._repository.get_control(f"agent_kill_switch:{proposal.agent_id}"):
            raise ActionSafetyError("The agent kill switch is enabled")
        configuration_record = await self._repository.latest_configuration(proposal.agent_id)
        if configuration_record is None:
            raise ActionSafetyError("No active configuration exists")
        configuration = ActionPolicyConfiguration.model_validate(configuration_record.values)
        recommendation = Recommendation(
            recommendation_id=proposal.recommendation_id,
            run_id=proposal.run_id,
            finding_ids=[],
            object_type=proposal.object_type,
            provider_object_id=proposal.provider_object_id,
            action_type=proposal.action_type,
            parameters=proposal.parameters,
            evidence=proposal.evidence,
            reasoning=proposal.reasoning,
            confidence=proposal.confidence,
            expected_effect=proposal.expected_effect,
            risks=proposal.risks,
            missing_data=proposal.missing_data,
            expires_at=proposal.expires_at,
            created_at=proposal.created_at,
        )
        current_policy = await self._policy.evaluate(
            agent_id=proposal.agent_id,
            recommendation=recommendation,
            configuration=configuration,
            configuration_version=configuration_record.version,
            exclude_proposal_id=proposal.proposal_id,
        )
        if current_policy.decision is PolicyDecision.DENY:
            raise ActionSafetyError(" ".join(current_policy.reasons))

    async def _required_proposal(self, proposal_id: str) -> ActionProposal:
        proposal = await self._repository.get_proposal(proposal_id)
        if proposal is None:
            raise LookupError(f"Proposal {proposal_id!r} was not found")
        return proposal

    async def _failed_execution(
        self,
        *,
        proposal: ActionProposal,
        before: ProviderObjectState | None,
        message: str,
        error_code: str = "stale_proposal",
    ) -> ActionExecution:
        now = self._clock.now()
        require_transition(proposal.status, ActionStatus.EXECUTING, ACTION_TRANSITIONS)
        executing_proposal = proposal.model_copy(update={"status": ActionStatus.EXECUTING})
        require_transition(executing_proposal.status, ActionStatus.FAILED, ACTION_TRANSITIONS)
        failed_proposal = executing_proposal.model_copy(update={"status": ActionStatus.FAILED})
        execution = ActionExecution(
            execution_id=self._ids.new(),
            proposal_id=proposal.proposal_id,
            run_id=proposal.run_id,
            idempotency_key=proposal.idempotency_key,
            status=ExecutionStatus.FAILED,
            attempted_at=now,
            completed_at=now,
            before_state=before.raw_safe if before is not None else {},
            requested_change=cast(
                dict[str, JsonValue],
                proposal.parameters.model_dump(mode="json"),
            ),
            provider_response={},
            error_code=error_code,
            error_message=message,
        )
        await self._repository.finalize_action_state(
            proposal=failed_proposal,
            execution=execution,
        )
        return execution

    async def _audit(
        self,
        *,
        correlation_id: str,
        proposal: ActionProposal,
        event_type: AuditEventType,
        actor_id: str,
        actor_role: UserRole,
        summary: str,
        details: dict[str, JsonValue],
    ) -> None:
        await self._repository.save_audit_event(
            AuditEvent(
                event_id=self._ids.new(),
                correlation_id=correlation_id,
                agent_id=proposal.agent_id,
                run_id=proposal.run_id,
                event_type=event_type,
                actor_id=actor_id,
                actor_role=actor_role,
                occurred_at=self._clock.now(),
                summary=summary,
                details=details,
            ),
        )


def _manual_action_instructions(recommendation: Recommendation) -> list[str]:
    return [
        (
            "Open the target object in Meta Ads Manager and verify the same account and "
            "attribution context."
        ),
        "Recheck current delivery state, budget, currency, policy limits, and the evidence period.",
        (
            f"If a human independently accepts the risk, apply the typed "
            f"{recommendation.action_type.value} change manually in Ads Manager."
        ),
        "Record the resulting provider state and decision in the MANA audit trail.",
    ]


def _advisory_object_state(
    recommendation: Recommendation,
    provider_name: str,
) -> ProviderObjectState:
    parameters = recommendation.parameters
    status = "UNKNOWN"
    daily_budget: Decimal | None = None
    currency: str | None = None
    if isinstance(parameters, BudgetActionParameters):
        daily_budget = parameters.current_daily_budget
        currency = parameters.currency
    elif isinstance(parameters, StatusActionParameters | AudienceActionParameters):
        status = parameters.current_status
        if (
            isinstance(parameters, AudienceActionParameters)
            and parameters.budget_change is not None
        ):
            daily_budget = parameters.budget_change.current_daily_budget
            currency = parameters.budget_change.currency
    raw_safe: dict[str, JsonValue] = {
        "source": "normalized_live_snapshot",
        "status": status,
        "daily_budget": str(daily_budget) if daily_budget is not None else None,
        "currency": currency,
    }
    state_hash = hashlib.sha256(json_safe(raw_safe).encode()).hexdigest()
    object_type = {
        "campaign": AdEntityType.CAMPAIGN,
        "ad_set": AdEntityType.AD_SET,
        "ad": AdEntityType.AD,
        "creative": AdEntityType.CREATIVE,
        "audience": AdEntityType.AUDIENCE,
    }.get(recommendation.object_type, AdEntityType.AD)
    return ProviderObjectState(
        provider=provider_name,
        object_type=object_type,
        provider_object_id=recommendation.provider_object_id,
        status=status,
        daily_budget=daily_budget,
        currency=currency,
        state_hash=state_hash,
        raw_safe=raw_safe,
    )


def _action_key(recommendation: Recommendation, state: ProviderObjectState) -> str:
    source = json_safe(
        {
            "run_id": recommendation.run_id,
            "provider_object_id": recommendation.provider_object_id,
            "action_type": recommendation.action_type.value,
            "parameters": recommendation.parameters.model_dump(mode="json"),
            "state_hash": state.state_hash,
        },
    )
    return hashlib.sha256(source.encode()).hexdigest()


def json_safe(value: object) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def expected_state(
    proposal: ActionProposal,
    before: ProviderObjectState,
) -> dict[str, JsonValue]:
    parameters = proposal.parameters
    if isinstance(parameters, BudgetActionParameters):
        return {"daily_budget": str(parameters.proposed_daily_budget)}
    if isinstance(parameters, StatusActionParameters):
        return {"status": parameters.proposed_status}
    if isinstance(parameters, AudienceActionParameters):
        expected: dict[str, JsonValue] = {"status": parameters.proposed_status}
        if parameters.budget_change is not None:
            expected["daily_budget"] = str(parameters.budget_change.proposed_daily_budget)
        return expected
    return before.raw_safe


def provider_state_violation(
    proposal: ActionProposal,
    state: ProviderObjectState,
) -> str | None:
    effective_status = str(state.raw_safe.get("effective_status", state.status)).upper()
    if effective_status in {"ARCHIVED", "DELETED", "PENDING_DELETE"}:
        return f"Provider object is not executable in status {effective_status}."
    budget: BudgetActionParameters | None = None
    if isinstance(proposal.parameters, BudgetActionParameters):
        budget = proposal.parameters
    elif isinstance(proposal.parameters, AudienceActionParameters):
        budget = proposal.parameters.budget_change
    if budget is None:
        return None
    if state.currency is None:
        return "Provider currency is unavailable; a financial action cannot be verified."
    if state.currency.upper() != budget.currency.upper():
        return (
            f"Proposal currency {budget.currency.upper()} does not match provider currency "
            f"{state.currency.upper()}."
        )
    if state.daily_budget != budget.current_daily_budget:
        return "Proposal budget baseline does not match the current provider budget."
    minimum_budget_raw = state.raw_safe.get("minimum_daily_budget")
    if minimum_budget_raw is not None:
        try:
            minimum_budget = Decimal(str(minimum_budget_raw))
        except (ArithmeticError, ValueError):
            return "Provider minimum daily budget metadata is invalid."
        if budget.proposed_daily_budget < minimum_budget:
            return "The proposed daily budget is below the provider account minimum."
    return None


def state_differences(
    expected: dict[str, JsonValue],
    observed: ProviderObjectState,
) -> list[str]:
    differences: list[str] = []
    for key, expected_value in expected.items():
        if key == "daily_budget":
            try:
                expected_budget = Decimal(str(expected_value))
            except (ArithmeticError, ValueError):
                expected_budget = None
            if observed.daily_budget == expected_budget:
                continue
            observed_value: JsonValue = (
                str(observed.daily_budget) if observed.daily_budget is not None else None
            )
        elif key == "status":
            observed_value = observed.status
        else:
            observed_value = observed.raw_safe.get(key)
        if observed_value != expected_value:
            differences.append(f"{key}: expected {expected_value!r}, observed {observed_value!r}")
    return differences
