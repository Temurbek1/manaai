from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

from app.mana_operation_ai.application.ports import Clock, IdGenerator, OperationRepository
from app.mana_operation_ai.domain.enums import ActionStatus, ActionType, PolicyDecision
from app.mana_operation_ai.domain.models import (
    ActionPolicy,
    ActionPolicyConfiguration,
    AudienceActionParameters,
    BudgetActionParameters,
    Recommendation,
)


class PolicyService:
    def __init__(
        self,
        *,
        repository: OperationRepository,
        clock: Clock,
        ids: IdGenerator,
        global_execution_limit_per_day: int,
        agent_execution_limit_per_day: int,
    ) -> None:
        self._repository = repository
        self._clock = clock
        self._ids = ids
        self._global_execution_limit = global_execution_limit_per_day
        self._agent_execution_limit = agent_execution_limit_per_day

    async def evaluate(
        self,
        *,
        agent_id: str,
        recommendation: Recommendation,
        configuration: ActionPolicyConfiguration,
        configuration_version: int,
        exclude_proposal_id: str | None = None,
    ) -> ActionPolicy:
        reasons: list[str] = []
        denied = False
        if recommendation.action_type not in configuration.allowed_action_types:
            reasons.append("Action type is not allowed by the active configuration.")
            denied = True
        if recommendation.confidence < configuration.minimum_confidence:
            reasons.append("Recommendation confidence is below the configured minimum.")
            denied = True
        budget_reason = budget_policy_violation(recommendation, configuration)
        if budget_reason is not None:
            reasons.append(budget_reason)
            denied = True

        now = self._clock.now()
        day_start = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
        _, global_count = await self._repository.list_executions(since=day_start, limit=1)
        _, agent_count = await self._repository.list_executions(
            agent_id=agent_id,
            since=day_start,
            limit=1,
        )
        if global_count >= self._global_execution_limit:
            reasons.append("The global daily execution limit has been reached.")
            denied = True
        if agent_count >= self._agent_execution_limit:
            reasons.append("The agent daily execution limit has been reached.")
            denied = True

        recent_proposals, _ = await self._repository.list_proposals(limit=1_000)
        cooldown_cutoff = now - timedelta(hours=configuration.cooldown_hours)
        if any(
            item.provider_object_id == recommendation.provider_object_id
            and item.proposal_id != exclude_proposal_id
            and item.run_id != recommendation.run_id
            and item.created_at >= cooldown_cutoff
            and item.action_type in {ActionType.INCREASE_BUDGET, ActionType.SCALE_AUDIENCE}
            and item.status
            in {
                ActionStatus.AWAITING_APPROVAL,
                ActionStatus.APPROVED,
                ActionStatus.EXECUTING,
                ActionStatus.SUCCEEDED,
                ActionStatus.PARTIALLY_APPLIED,
            }
            for item in recent_proposals
        ):
            reasons.append("A recent scaling action is still inside the configured cooldown.")
            denied = True

        if denied:
            decision = PolicyDecision.DENY
        elif configuration.approval_required.get(
            cast(ActionType, recommendation.action_type),
            True,
        ):
            decision = PolicyDecision.REQUIRE_APPROVAL
            reasons.append("The action type requires an approver decision.")
        else:
            decision = PolicyDecision.ALLOW
            reasons.append("The action satisfies the configured policy limits.")
        return ActionPolicy(
            policy_id=self._ids.new(),
            agent_id=agent_id,
            capability_key=recommendation.capability_key,
            action_family=recommendation.action_family,
            action_type=recommendation.action_type,
            decision=decision,
            reasons=reasons,
            checked_at=now,
            configuration_version=configuration_version,
        )


def budget_policy_violation(
    recommendation: Recommendation,
    configuration: ActionPolicyConfiguration,
) -> str | None:
    parameters = recommendation.parameters
    budget: BudgetActionParameters | None = None
    if isinstance(parameters, BudgetActionParameters):
        budget = parameters
    elif isinstance(parameters, AudienceActionParameters):
        budget = parameters.budget_change
    if budget is None:
        return None

    currency = budget.currency.upper()
    if currency not in configuration.allowed_currencies:
        return "The proposal currency is not allowed by the active configuration."
    minimum_budget = configuration.minimum_daily_budget_by_currency.get(currency)
    if minimum_budget is None:
        return "The proposal currency has no configured minimum daily budget."
    if budget.proposed_daily_budget < minimum_budget:
        return "The proposed daily budget is below the configured currency minimum."

    change = budget.proposed_daily_budget - budget.current_daily_budget
    if abs(change) > configuration.maximum_absolute_daily_budget_change:
        return "The absolute daily budget change exceeds the configured limit."
    if change > 0:
        if budget.current_daily_budget == 0:
            return "A zero budget cannot be increased without an explicit baseline."
        factor = budget.proposed_daily_budget / budget.current_daily_budget
        if factor > configuration.maximum_budget_increase_factor:
            return "The budget increase factor exceeds the configured limit."
    elif change < 0 and budget.current_daily_budget > 0:
        decrease = abs(change) / budget.current_daily_budget
        if decrease > configuration.maximum_budget_decrease:
            return "The budget decrease exceeds the configured limit."
    if budget.proposed_daily_budget <= Decimal("0"):
        return "The proposed daily budget must remain positive."
    return None
