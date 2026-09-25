import hashlib
import json
from datetime import datetime
from decimal import Decimal

from app.mana_operation_ai.application.ports import (
    Clock,
    ProviderPermanentError,
    ProviderWriteUncertainError,
)
from app.mana_operation_ai.domain.enums import GrowthActionType, IntegrationStatus, ProviderMode
from app.mana_operation_ai.domain.growth import (
    AttributionChannelFacts,
    AttributionFacts,
    BillingFunnelFacts,
    ExperimentDispatchResult,
    ExperimentTargetState,
    ProductAnalyticsFacts,
)
from app.mana_operation_ai.domain.models import (
    ActionParameters,
    CreateExperimentActionParameters,
    IntegrationHealth,
    StopExperimentActionParameters,
)


class FakeProductAnalyticsAdapter:
    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    async def collect_funnel(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> ProductAnalyticsFacts:
        return ProductAnalyticsFacts(
            source="fake_product_analytics",
            period_start=period_start,
            period_end=period_end,
            collected_at=self._clock.now(),
            visitors=10_000,
            signups=3_000,
            activated_users=1_050,
            completeness=Decimal("0.98"),
            source_request_id="fake-product-funnel-v1",
        )


class FakeBillingReadAdapter:
    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    async def collect_funnel(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> BillingFunnelFacts:
        return BillingFunnelFacts(
            source="fake_billing",
            period_start=period_start,
            period_end=period_end,
            collected_at=self._clock.now(),
            activated_users=1_050,
            trials_started=420,
            paid_subscriptions=63,
            recognized_revenue=Decimal("945.00"),
            currency="USD",
            completeness=Decimal("0.97"),
            source_request_id="fake-billing-funnel-v1",
        )


class FakeAttributionAdapter:
    def __init__(self, *, clock: Clock) -> None:
        self._clock = clock

    async def collect_funnel(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> AttributionFacts:
        return AttributionFacts(
            source="fake_attribution",
            period_start=period_start,
            period_end=period_end,
            collected_at=self._clock.now(),
            channels=[
                AttributionChannelFacts(
                    channel="meta",
                    visitors=4_000,
                    paid_subscriptions=32,
                ),
                AttributionChannelFacts(
                    channel="organic",
                    visitors=3_500,
                    paid_subscriptions=22,
                ),
                AttributionChannelFacts(
                    channel="referral",
                    visitors=2_000,
                    paid_subscriptions=9,
                ),
            ],
            completeness=Decimal("0.95"),
            source_request_id="fake-attribution-funnel-v1",
        )


class FakeExperimentAdapter:
    provider_name = "fake_experiments"
    provider_mode = ProviderMode.FAKE_EXECUTABLE

    def __init__(self, *, clock: Clock, uncertain_once: bool = False) -> None:
        self._clock = clock
        self._states: dict[str, dict[str, object]] = {}
        self._idempotency: dict[str, ExperimentDispatchResult] = {}
        self._uncertain_once = uncertain_once
        self._uncertain_dispatched = False
        self._dispatch_count = 0

    @property
    def dispatch_count(self) -> int:
        return self._dispatch_count

    def simulate_uncertain_response_once(self) -> None:
        """Make the next applied sandbox write lose its response for recovery tests."""
        self._uncertain_once = True
        self._uncertain_dispatched = False

    async def get_state(self, experiment_key: str) -> ExperimentTargetState:
        raw = self._states.get(
            experiment_key,
            {"status": "ABSENT", "allocation_percent": None},
        )
        return _state(self.provider_name, experiment_key, raw)

    async def execute(
        self,
        *,
        experiment_key: str,
        parameters: ActionParameters,
        idempotency_key: str,
    ) -> ExperimentDispatchResult:
        previous = self._idempotency.get(idempotency_key)
        if previous is not None:
            return previous
        self._dispatch_count += 1
        current = await self.get_state(experiment_key)
        if isinstance(parameters, CreateExperimentActionParameters):
            if current.status != "ABSENT":
                raise ProviderPermanentError("Experiment already exists")
            raw: dict[str, object] = {
                "status": "DRAFT",
                "allocation_percent": parameters.allocation_percent,
                "primary_metric": parameters.primary_metric,
                "audience_segment": parameters.audience_segment,
                "duration_days": parameters.duration_days,
                "hypothesis": parameters.hypothesis,
            }
        elif isinstance(parameters, StopExperimentActionParameters):
            if current.status not in {"DRAFT", "RUNNING"}:
                raise ProviderPermanentError("Only an active experiment can be stopped")
            raw = dict(current.raw_safe)
            raw["status"] = "STOPPED"
        else:
            raise ProviderPermanentError(
                f"Unsupported experiment action {parameters.kind.value!r}",
            )
        self._states[experiment_key] = raw
        result = ExperimentDispatchResult(
            provider_request_id=f"fake-experiment-{len(self._idempotency) + 1}",
            state=_state(self.provider_name, experiment_key, raw),
        )
        self._idempotency[idempotency_key] = result
        if self._uncertain_once and not self._uncertain_dispatched:
            self._uncertain_dispatched = True
            raise ProviderWriteUncertainError("Experiment write response was lost")
        return result

    async def health(self) -> IntegrationHealth:
        return IntegrationHealth(
            integration_id=self.provider_name,
            status=IntegrationStatus.HEALTHY,
            checked_at=self._clock.now(),
            last_success_at=self._clock.now(),
            latency_ms=0,
            message="Deterministic in-memory experiment sandbox is ready",
            diagnostics={"write_mode": GrowthActionType.CREATE_EXPERIMENT.value},
        )


def _state(
    provider: str,
    experiment_key: str,
    raw: dict[str, object],
) -> ExperimentTargetState:
    serialized = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str)
    return ExperimentTargetState(
        provider=provider,
        experiment_key=experiment_key,
        status=str(raw["status"]),
        allocation_percent=(
            int(str(raw["allocation_percent"]))
            if raw.get("allocation_percent") is not None
            else None
        ),
        state_hash=hashlib.sha256(serialized.encode()).hexdigest(),
        raw_safe=raw,
    )
