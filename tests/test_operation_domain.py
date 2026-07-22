from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.mana_operation_ai.application.marketing.analytics import MarketingAnalyticsEngine
from app.mana_operation_ai.application.marketing.metrics import build_metrics
from app.mana_operation_ai.application.policy import budget_policy_violation
from app.mana_operation_ai.application.scheduling import next_cron_occurrence
from app.mana_operation_ai.domain.enums import ActionType, AgentRunStatus, DataAvailability
from app.mana_operation_ai.domain.marketing import MarketingAgentConfiguration
from app.mana_operation_ai.domain.models import BudgetActionParameters, Recommendation
from app.mana_operation_ai.domain.state_machine import (
    RUN_TRANSITIONS,
    InvalidStateTransition,
    require_transition,
)
from app.mana_operation_ai.infrastructure.ads.fake_meta import (
    FakeMetaAdsAdapter,
    build_demo_snapshot,
)


class SequentialIds:
    def __init__(self) -> None:
        self._next = 0

    def new(self) -> str:
        self._next += 1
        return f"id-{self._next}"


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def test_financial_metrics_are_decimal_and_unavailable_is_explicit() -> None:
    metrics = build_metrics(
        spend=Decimal("20"),
        impressions=Decimal("400"),
        reach=Decimal("200"),
        clicks=Decimal("20"),
        link_clicks=Decimal("16"),
        conversions=Decimal("4"),
        leads=Decimal("0"),
        revenue=None,
    )

    assert metrics.ctr.value == Decimal("5.00")
    assert metrics.cpc.value == Decimal("1")
    assert metrics.cpa.value == Decimal("5")
    assert metrics.frequency.value == Decimal("2")
    assert metrics.cpl.availability is DataAvailability.UNAVAILABLE
    assert metrics.cpl.value is None
    assert metrics.roas.reason == "ROAS denominator unavailable"


def test_marketing_configuration_validates_objective_and_financial_limits() -> None:
    with pytest.raises(ValidationError):
        MarketingAgentConfiguration(primary_objective="custom")
    with pytest.raises(ValidationError):
        MarketingAgentConfiguration(maximum_budget_increase_factor=Decimal("0.9"))

    configuration = MarketingAgentConfiguration(
        primary_objective="custom",
        custom_conversion_action="qualified_lead",
        maximum_absolute_daily_budget_change=Decimal("25.00"),
    )
    assert configuration.custom_conversion_action == "qualified_lead"
    assert configuration.maximum_absolute_daily_budget_change == Decimal("25.00")


def test_state_machine_rejects_arbitrary_transitions() -> None:
    require_transition(
        AgentRunStatus.QUEUED,
        AgentRunStatus.COLLECTING,
        RUN_TRANSITIONS,
    )
    with pytest.raises(InvalidStateTransition, match="queued -> reporting"):
        require_transition(
            AgentRunStatus.QUEUED,
            AgentRunStatus.REPORTING,
            RUN_TRANSITIONS,
        )


def test_analytics_respects_thresholds_and_emits_typed_recommendations() -> None:
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    snapshot = build_demo_snapshot(now)
    engine = MarketingAnalyticsEngine(ids=SequentialIds())
    bundle = engine.analyze(
        run_id="run-1",
        snapshot_id="snapshot-1",
        snapshot=snapshot,
        configuration=MarketingAgentConfiguration(),
        now=now,
    )
    finding_types = {finding.finding_type for finding in bundle.findings}
    actions = {recommendation.action_type for recommendation in bundle.recommendations}

    assert {"best_creative", "weak_creative", "cheap_audience", "expensive_audience"} <= (
        finding_types
    )
    assert {
        ActionType.MAINTAIN,
        ActionType.PAUSE,
        ActionType.SCALE_AUDIENCE,
        ActionType.DISABLE_AUDIENCE,
        ActionType.INCREASE_BUDGET,
        ActionType.DECREASE_BUDGET,
    } <= actions
    assert all(
        recommendation.parameters.kind is recommendation.action_type
        for recommendation in bundle.recommendations
    )

    strict_bundle = engine.analyze(
        run_id="run-2",
        snapshot_id="snapshot-2",
        snapshot=snapshot,
        configuration=MarketingAgentConfiguration(minimum_spend=Decimal("1000")),
        now=now,
    )
    assert "best_creative" not in {item.finding_type for item in strict_bundle.findings}


def test_paused_efficient_ad_set_produces_resume_recommendation() -> None:
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    snapshot = build_demo_snapshot(now)
    snapshot = snapshot.model_copy(
        update={
            "ad_sets": [
                item.model_copy(update={"status": "PAUSED", "effective_status": "PAUSED"})
                if item.provider_id == "set_cheap"
                else item
                for item in snapshot.ad_sets
            ],
        },
    )
    bundle = MarketingAnalyticsEngine(ids=SequentialIds()).analyze(
        run_id="run-resume",
        snapshot_id="snapshot-resume",
        snapshot=snapshot,
        configuration=MarketingAgentConfiguration(),
        now=now,
    )

    resume = next(item for item in bundle.recommendations if item.action_type is ActionType.RESUME)
    assert resume.provider_object_id == "set_cheap"
    assert resume.parameters.kind is ActionType.RESUME


def test_scheduler_cron_respects_explicit_timezone() -> None:
    after = datetime(2026, 7, 22, 20, 30, tzinfo=UTC)
    occurrence = next_cron_occurrence("0 2 * * *", "Asia/Samarkand", after)
    assert occurrence == datetime(2026, 7, 22, 21, 0, tzinfo=UTC)


def test_budget_policy_enforces_factor_and_absolute_limits() -> None:
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    recommendation = Recommendation(
        recommendation_id="recommendation-1",
        run_id="run-1",
        finding_ids=[],
        object_type="ad_set",
        provider_object_id="set-1",
        action_type=ActionType.INCREASE_BUDGET,
        parameters=BudgetActionParameters(
            kind=ActionType.INCREASE_BUDGET,
            currency="USD",
            current_daily_budget=Decimal("100"),
            proposed_daily_budget=Decimal("130"),
        ),
        evidence=[],
        reasoning="Deterministic efficiency signal",
        confidence=Decimal("0.9"),
        expected_effect="Scale within limits",
        risks=["Efficiency may change"],
        missing_data=[],
        expires_at=now,
        created_at=now,
    )
    configuration = MarketingAgentConfiguration(
        maximum_budget_increase_factor=Decimal("1.2"),
        maximum_absolute_daily_budget_change=Decimal("100"),
    )
    assert (
        budget_policy_violation(
            recommendation,
            configuration.action_policy_configuration(),
        )
        == "The budget increase factor exceeds the configured limit."
    )


def test_budget_policy_enforces_absolute_delta_independently_of_factor() -> None:
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    recommendation = Recommendation(
        recommendation_id="absolute-delta",
        run_id="run-absolute",
        finding_ids=[],
        object_type="ad_set",
        provider_object_id="set-absolute",
        action_type=ActionType.INCREASE_BUDGET,
        parameters=BudgetActionParameters(
            kind=ActionType.INCREASE_BUDGET,
            currency="USD",
            current_daily_budget=Decimal("100"),
            proposed_daily_budget=Decimal("115"),
        ),
        evidence=[],
        reasoning="Deterministic signal",
        confidence=Decimal("0.9"),
        expected_effect="Bounded scale",
        risks=[],
        missing_data=[],
        expires_at=now,
        created_at=now,
    )
    configuration = MarketingAgentConfiguration(
        maximum_budget_increase_factor=Decimal("1.2"),
        maximum_absolute_daily_budget_change=Decimal("10"),
    )

    assert (
        budget_policy_violation(
            recommendation,
            configuration.action_policy_configuration(),
        )
        == "The absolute daily budget change exceeds the configured limit."
    )


async def test_fake_provider_action_idempotency_prevents_duplicate_budget_change() -> None:
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    adapter = FakeMetaAdsAdapter(clock=FixedClock(now))
    parameters = BudgetActionParameters(
        kind=ActionType.INCREASE_BUDGET,
        currency="USD",
        current_daily_budget=Decimal("60"),
        proposed_daily_budget=Decimal("72"),
    )
    first = await adapter.execute(
        object_type="ad_set",
        provider_object_id="set_cheap",
        parameters=parameters,
        idempotency_key="stable-action-key",
    )
    duplicate = await adapter.execute(
        object_type="ad_set",
        provider_object_id="set_cheap",
        parameters=parameters,
        idempotency_key="stable-action-key",
    )
    state = await adapter.get_object_state("ad_set", "set_cheap")

    assert duplicate.provider_request_id == first.provider_request_id
    assert state.daily_budget == Decimal("72")
