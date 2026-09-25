from datetime import UTC, datetime
from typing import Protocol

from pydantic import JsonValue

from app.mana_operation_ai.application.policy import PolicyService
from app.mana_operation_ai.application.ports import Clock, IdGenerator, OperationRepository
from app.mana_operation_ai.domain.enums import GrowthActionType, PolicyDecision
from app.mana_operation_ai.domain.growth import GrowthFunnelConfiguration
from app.mana_operation_ai.domain.models import (
    ActionPolicy,
    ActionPolicyConfiguration,
    CreateExperimentActionParameters,
    Recommendation,
    StopExperimentActionParameters,
)


class ActionPolicyEvaluator(Protocol):
    @property
    def action_family(self) -> str: ...

    async def evaluate(
        self,
        *,
        agent_id: str,
        recommendation: Recommendation,
        configuration: dict[str, JsonValue],
        configuration_version: int,
        exclude_proposal_id: str | None = None,
    ) -> ActionPolicy: ...


class ActionPolicyRegistry:
    def __init__(self) -> None:
        self._evaluators: dict[str, ActionPolicyEvaluator] = {}

    def register(self, evaluator: ActionPolicyEvaluator) -> None:
        if evaluator.action_family in self._evaluators:
            raise ValueError(
                f"Policy evaluator {evaluator.action_family!r} is already registered",
            )
        self._evaluators[evaluator.action_family] = evaluator

    def get(self, action_family: str) -> ActionPolicyEvaluator:
        try:
            return self._evaluators[action_family]
        except KeyError as exc:
            raise LookupError(
                f"No policy evaluator is registered for action family {action_family!r}",
            ) from exc


class AdvertisingPolicyEvaluator:
    action_family = "advertising"

    def __init__(self, policy: PolicyService) -> None:
        self._policy = policy

    async def evaluate(
        self,
        *,
        agent_id: str,
        recommendation: Recommendation,
        configuration: dict[str, JsonValue],
        configuration_version: int,
        exclude_proposal_id: str | None = None,
    ) -> ActionPolicy:
        return await self._policy.evaluate(
            agent_id=agent_id,
            recommendation=recommendation,
            configuration=ActionPolicyConfiguration.model_validate(configuration),
            configuration_version=configuration_version,
            exclude_proposal_id=exclude_proposal_id,
        )


class GrowthExperimentPolicyEvaluator:
    action_family = "growth_experiment"

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
        configuration: dict[str, JsonValue],
        configuration_version: int,
        exclude_proposal_id: str | None = None,
    ) -> ActionPolicy:
        del exclude_proposal_id
        typed = GrowthFunnelConfiguration.model_validate(configuration)
        reasons: list[str] = []
        denied = False
        if typed.experiment_mode != "sandbox":
            reasons.append("Experiment writes are disabled while the capability is in shadow mode.")
            denied = True
        if recommendation.action_type not in {
            GrowthActionType.CREATE_EXPERIMENT,
            GrowthActionType.STOP_EXPERIMENT,
        }:
            reasons.append("The action is not supported by the Growth experiment policy.")
            denied = True
        if recommendation.confidence < typed.minimum_completeness:
            reasons.append("Evidence completeness is below the configured minimum.")
            denied = True
        if isinstance(recommendation.parameters, CreateExperimentActionParameters):
            if recommendation.parameters.allocation_percent > typed.experiment_allocation_percent:
                reasons.append("Experiment allocation exceeds the configured sandbox limit.")
                denied = True
        elif not isinstance(recommendation.parameters, StopExperimentActionParameters):
            reasons.append("Experiment action parameters are invalid for this policy.")
            denied = True

        day_start = datetime.combine(self._clock.now().date(), datetime.min.time(), tzinfo=UTC)
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

        decision = PolicyDecision.DENY if denied else PolicyDecision.REQUIRE_APPROVAL
        if not denied:
            reasons.append("Sandbox experiment actions always require explicit approval.")
        return ActionPolicy(
            policy_id=self._ids.new(),
            agent_id=agent_id,
            capability_key=recommendation.capability_key,
            action_family=recommendation.action_family,
            action_type=recommendation.action_type,
            decision=decision,
            reasons=reasons,
            checked_at=self._clock.now(),
            configuration_version=configuration_version,
        )
