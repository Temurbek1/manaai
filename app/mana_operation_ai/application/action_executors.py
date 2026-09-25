import hashlib
import json
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from app.mana_operation_ai.application.ports import (
    AdsPlatform,
    ExperimentPlatform,
    ProviderPermanentError,
)
from app.mana_operation_ai.domain.enums import ProviderMode
from app.mana_operation_ai.domain.growth import ExperimentTargetState
from app.mana_operation_ai.domain.marketing import AdEntityType, ProviderObjectState
from app.mana_operation_ai.domain.models import (
    ActionProposal,
    AudienceActionParameters,
    BudgetActionParameters,
    CreateExperimentActionParameters,
    Recommendation,
    StatusActionParameters,
    StopExperimentActionParameters,
)


class ActionTargetState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    object_type: str
    provider_object_id: str
    state_hash: str
    raw_safe: dict[str, JsonValue]


class ActionDispatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_request_id: str
    state: ActionTargetState
    raw_safe: dict[str, JsonValue]


class ActionExecutor(Protocol):
    @property
    def action_family(self) -> str: ...

    @property
    def provider_name(self) -> str: ...

    @property
    def provider_mode(self) -> ProviderMode: ...

    async def state_for_recommendation(
        self, recommendation: Recommendation
    ) -> ActionTargetState: ...

    async def state_for_proposal(self, proposal: ActionProposal) -> ActionTargetState: ...

    def state_violation(self, proposal: ActionProposal, state: ActionTargetState) -> str | None: ...

    def expected_state(
        self,
        proposal: ActionProposal,
        before: ActionTargetState,
    ) -> dict[str, JsonValue]: ...

    def differences(
        self,
        expected: dict[str, JsonValue],
        observed: ActionTargetState,
    ) -> list[str]: ...

    async def dispatch(self, proposal: ActionProposal) -> ActionDispatchResult: ...


class DuplicateActionExecutorError(ValueError):
    """Raised when two executors claim the same action family and provider."""


class ActionExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[tuple[str, str], ActionExecutor] = {}

    def register(self, executor: ActionExecutor) -> None:
        key = (executor.action_family, executor.provider_name)
        if key in self._executors:
            raise DuplicateActionExecutorError(f"Action executor {key!r} is already registered")
        self._executors[key] = executor

    def get(self, action_family: str, provider_name: str) -> ActionExecutor:
        try:
            return self._executors[(action_family, provider_name)]
        except KeyError as exc:
            raise LookupError(
                f"No executor is registered for {action_family!r} on {provider_name!r}",
            ) from exc


class AdvertisingActionExecutor:
    action_family = "advertising"

    def __init__(self, platform: AdsPlatform) -> None:
        self._platform = platform

    @property
    def provider_name(self) -> str:
        return self._platform.provider_name

    @property
    def provider_mode(self) -> ProviderMode:
        return self._platform.provider_mode

    async def state_for_recommendation(self, recommendation: Recommendation) -> ActionTargetState:
        state = (
            _advisory_ad_state(recommendation, self.provider_name)
            if self.provider_mode is ProviderMode.LIVE_READ_ONLY
            else await self._platform.get_object_state(
                recommendation.object_type,
                recommendation.provider_object_id,
            )
        )
        return _advertising_state(state)

    async def state_for_proposal(self, proposal: ActionProposal) -> ActionTargetState:
        state = await self._platform.get_object_state(
            proposal.object_type,
            proposal.provider_object_id,
        )
        return _advertising_state(state)

    def state_violation(self, proposal: ActionProposal, state: ActionTargetState) -> str | None:
        effective_status = str(
            state.raw_safe.get("effective_status", state.raw_safe.get("status", "UNKNOWN")),
        ).upper()
        if effective_status in {"ARCHIVED", "DELETED", "PENDING_DELETE"}:
            return f"Provider object is not executable in status {effective_status}."
        budget: BudgetActionParameters | None = None
        if isinstance(proposal.parameters, BudgetActionParameters):
            budget = proposal.parameters
        elif isinstance(proposal.parameters, AudienceActionParameters):
            budget = proposal.parameters.budget_change
        if budget is None:
            return None
        currency = state.raw_safe.get("currency")
        if currency is None:
            return "Provider currency is unavailable; a financial action cannot be verified."
        if str(currency).upper() != budget.currency.upper():
            return (
                f"Proposal currency {budget.currency.upper()} does not match provider currency "
                f"{str(currency).upper()}."
            )
        current_budget = state.raw_safe.get("daily_budget")
        if current_budget is None or str(current_budget) != str(budget.current_daily_budget):
            return "Proposal budget baseline does not match the current provider budget."
        minimum_budget = state.raw_safe.get("minimum_daily_budget")
        if minimum_budget is not None and budget.proposed_daily_budget < _decimal(minimum_budget):
            return "The proposed daily budget is below the provider account minimum."
        return None

    def expected_state(
        self,
        proposal: ActionProposal,
        before: ActionTargetState,
    ) -> dict[str, JsonValue]:
        parameters = proposal.parameters
        if isinstance(parameters, BudgetActionParameters):
            return {"daily_budget": str(parameters.proposed_daily_budget)}
        if isinstance(parameters, StatusActionParameters):
            return {"status": parameters.proposed_status}
        if isinstance(parameters, AudienceActionParameters):
            expected: dict[str, JsonValue] = {"status": parameters.proposed_status}
            if parameters.budget_change is not None:
                expected["daily_budget"] = str(
                    parameters.budget_change.proposed_daily_budget,
                )
            return expected
        return before.raw_safe

    def differences(
        self,
        expected: dict[str, JsonValue],
        observed: ActionTargetState,
    ) -> list[str]:
        return _raw_differences(expected, observed.raw_safe)

    async def dispatch(self, proposal: ActionProposal) -> ActionDispatchResult:
        result = await self._platform.execute(
            object_type=proposal.object_type,
            provider_object_id=proposal.provider_object_id,
            parameters=proposal.parameters,
            idempotency_key=proposal.idempotency_key,
        )
        if not result.accepted:
            raise ProviderPermanentError("The advertising provider did not accept the action")
        if result.applied_state is None:
            raise ProviderPermanentError("The advertising provider omitted the applied state")
        state = _advertising_state(result.applied_state)
        return ActionDispatchResult(
            provider_request_id=result.provider_request_id or "",
            state=state,
            raw_safe=result.model_dump(mode="json"),
        )


class ExperimentActionExecutor:
    action_family = "growth_experiment"

    def __init__(self, platform: ExperimentPlatform) -> None:
        self._platform = platform

    @property
    def provider_name(self) -> str:
        return self._platform.provider_name

    @property
    def provider_mode(self) -> ProviderMode:
        return self._platform.provider_mode

    async def state_for_recommendation(self, recommendation: Recommendation) -> ActionTargetState:
        return _experiment_state(
            await self._platform.get_state(recommendation.provider_object_id),
        )

    async def state_for_proposal(self, proposal: ActionProposal) -> ActionTargetState:
        return _experiment_state(await self._platform.get_state(proposal.provider_object_id))

    def state_violation(self, proposal: ActionProposal, state: ActionTargetState) -> str | None:
        status = str(state.raw_safe.get("status"))
        if isinstance(proposal.parameters, CreateExperimentActionParameters):
            return None if status == "ABSENT" else "The experiment already exists."
        if isinstance(proposal.parameters, StopExperimentActionParameters):
            if status != proposal.parameters.current_status:
                return "The experiment status changed after the proposal was created."
            return None
        return "The proposal parameters are not supported by the experiment executor."

    def expected_state(
        self,
        proposal: ActionProposal,
        before: ActionTargetState,
    ) -> dict[str, JsonValue]:
        del before
        if isinstance(proposal.parameters, CreateExperimentActionParameters):
            return {
                "status": proposal.parameters.proposed_status,
                "allocation_percent": proposal.parameters.allocation_percent,
                "primary_metric": proposal.parameters.primary_metric,
                "audience_segment": proposal.parameters.audience_segment,
                "duration_days": proposal.parameters.duration_days,
                "hypothesis": proposal.parameters.hypothesis,
            }
        if isinstance(proposal.parameters, StopExperimentActionParameters):
            return {"status": proposal.parameters.proposed_status}
        return {}

    def differences(
        self,
        expected: dict[str, JsonValue],
        observed: ActionTargetState,
    ) -> list[str]:
        return _raw_differences(expected, observed.raw_safe)

    async def dispatch(self, proposal: ActionProposal) -> ActionDispatchResult:
        result = await self._platform.execute(
            experiment_key=proposal.provider_object_id,
            parameters=proposal.parameters,
            idempotency_key=proposal.idempotency_key,
        )
        state = _experiment_state(result.state)
        return ActionDispatchResult(
            provider_request_id=result.provider_request_id,
            state=state,
            raw_safe=result.model_dump(mode="json"),
        )


def _advertising_state(state: ProviderObjectState) -> ActionTargetState:
    raw = dict(state.raw_safe)
    raw.setdefault("status", state.status)
    raw.setdefault(
        "daily_budget", str(state.daily_budget) if state.daily_budget is not None else None
    )
    raw.setdefault("currency", state.currency)
    return ActionTargetState(
        provider=state.provider,
        object_type=state.object_type.value,
        provider_object_id=state.provider_object_id,
        state_hash=state.state_hash,
        raw_safe=raw,
    )


def _experiment_state(state: ExperimentTargetState) -> ActionTargetState:
    return ActionTargetState(
        provider=state.provider,
        object_type="experiment",
        provider_object_id=state.experiment_key,
        state_hash=state.state_hash,
        raw_safe=state.raw_safe,
    )


def _advisory_ad_state(
    recommendation: Recommendation,
    provider_name: str,
) -> ProviderObjectState:
    parameters = recommendation.parameters
    status = "UNKNOWN"
    daily_budget = None
    currency = None
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
    state_hash = hashlib.sha256(
        json.dumps(raw_safe, sort_keys=True, separators=(",", ":"), default=str).encode(),
    ).hexdigest()
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


def _raw_differences(
    expected: dict[str, JsonValue],
    observed: dict[str, JsonValue],
) -> list[str]:
    differences: list[str] = []
    for key, expected_value in expected.items():
        observed_value = observed.get(key)
        if key == "daily_budget" and observed_value is not None:
            observed_value = str(observed_value)
        if observed_value != expected_value:
            differences.append(f"{key}: expected {expected_value!r}, observed {observed_value!r}")
    return differences


def _decimal(value: JsonValue) -> Decimal:
    return Decimal(str(value))
