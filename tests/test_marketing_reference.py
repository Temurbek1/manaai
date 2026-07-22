from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.mana_operation_ai.application.marketing.analytics import (
    MarketingAnalyticsEngine,
    aggregate_metrics,
)
from app.mana_operation_ai.application.marketing.metrics import build_metrics
from app.mana_operation_ai.application.scheduling import next_cron_occurrence
from app.mana_operation_ai.domain.marketing import MarketingAgentConfiguration
from app.mana_operation_ai.infrastructure.ads.fake_meta import build_demo_snapshot
from tests.reference_marketing_calculator import calculate_reference_metrics


class SequentialIds:
    def __init__(self) -> None:
        self._value = 0

    def new(self) -> str:
        self._value += 1
        return f"reference-{self._value}"


@pytest.mark.parametrize(
    ("inputs"),
    [
        {
            "spend": Decimal("10.01"),
            "impressions": Decimal("333"),
            "reach": Decimal("222"),
            "clicks": Decimal("7"),
            "link_clicks": Decimal("5"),
            "conversions": Decimal("3"),
            "leads": Decimal("2"),
            "revenue": Decimal("31.25"),
        },
        {
            "spend": Decimal("0"),
            "impressions": Decimal("0"),
            "reach": Decimal("0"),
            "clicks": Decimal("0"),
            "link_clicks": None,
            "conversions": None,
            "leads": Decimal("0"),
            "revenue": None,
        },
        {
            "spend": Decimal("-1"),
            "impressions": Decimal("100"),
            "reach": Decimal("80"),
            "clicks": Decimal("-2"),
            "link_clicks": Decimal("-1"),
            "conversions": Decimal("-1"),
            "leads": Decimal("-1"),
            "revenue": Decimal("-5"),
        },
    ],
)
def test_metric_engine_matches_independent_decimal_reference(
    inputs: dict[str, Decimal | None],
) -> None:
    expected = calculate_reference_metrics(**inputs)
    actual = build_metrics(**inputs)

    for name, expected_value in expected.items():
        assert getattr(actual, name).value == expected_value


def test_aggregation_avoids_breakdown_duplicates_and_non_additive_reach() -> None:
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    row = build_demo_snapshot(now).insights[0]
    base = row.model_copy(
        update={"row_id": "base", "dimensions": {"_query_scope": "base"}},
        deep=True,
    )
    breakdown = row.model_copy(
        update={"row_id": "region", "dimensions": {"_query_scope": "region"}},
        deep=True,
    )
    base_metrics = aggregate_metrics([base, breakdown, base])
    shared_creative = aggregate_metrics(
        [
            base,
            base.model_copy(update={"row_id": "second-ad", "ad_id": "ad-2"}),
        ],
    )

    assert base_metrics.spend.value == row.metrics.spend.value
    assert base_metrics.impressions.value == row.metrics.impressions.value
    assert row.metrics.spend.value is not None
    assert shared_creative.spend.value == row.metrics.spend.value * 2
    assert shared_creative.reach.value is None
    assert shared_creative.frequency.value is None


def test_mixed_currency_and_attribution_data_fail_closed() -> None:
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    snapshot = build_demo_snapshot(now)
    first = snapshot.insights[0].model_copy(
        update={"row_id": "usd", "dimensions": {"_query_scope": "base"}},
    )
    eur = snapshot.insights[1].model_copy(
        update={
            "row_id": "eur",
            "currency": "EUR",
            "dimensions": {"_query_scope": "base"},
        },
    )
    other_window = first.model_copy(
        update={"row_id": "other-window", "attribution_window": "1d_click"},
    )

    currency_metrics = aggregate_metrics([first, eur])
    attribution_metrics = aggregate_metrics([first, other_window])

    assert currency_metrics.spend.value is None
    assert currency_metrics.cpa.value is None
    assert all(
        getattr(attribution_metrics, name).value is None
        for name in type(attribution_metrics).model_fields
    )


def test_delayed_conversions_and_incomplete_periods_suppress_actions() -> None:
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    bundle = MarketingAnalyticsEngine(ids=SequentialIds()).analyze(
        run_id="lagged-run",
        snapshot_id="lagged-snapshot",
        snapshot=build_demo_snapshot(now),
        configuration=MarketingAgentConfiguration(
            comparison_period_days=1,
            conversion_lag_days=1,
        ),
        now=now,
    )

    assert {finding.finding_type for finding in bundle.findings} == {"insufficient_data"}
    assert all(
        item.action_type.value in {"observe", "propose_test"} for item in bundle.recommendations
    )


def test_cron_occurrence_is_stable_across_daylight_saving_boundaries() -> None:
    spring = next_cron_occurrence(
        "30 2 * * *",
        "America/New_York",
        datetime(2026, 3, 7, 12, tzinfo=UTC),
    )
    fall = next_cron_occurrence(
        "30 2 * * *",
        "America/New_York",
        datetime(2026, 10, 31, 12, tzinfo=UTC),
    )

    assert spring == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)
    assert fall == datetime(2026, 11, 1, 7, 30, tzinfo=UTC)
