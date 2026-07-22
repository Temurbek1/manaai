from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.mana_operation_ai.domain.enums import DataAvailability
from app.mana_operation_ai.domain.marketing import (
    AccountCalibration,
    AdsSnapshot,
    InsightRow,
    MarketingObjective,
    MarketingThresholdOverrides,
    Metric,
)


class CalibrationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calibration: AccountCalibration
    base_row_count: int = Field(ge=0)
    represented_days: int = Field(ge=0)
    unavailable_thresholds: list[str]


def calibrate_account(
    *,
    snapshot: AdsSnapshot,
    source_snapshot_id: str,
    objective: MarketingObjective,
    calibrated_at: datetime,
) -> CalibrationSummary:
    if len(snapshot.accounts) != 1:
        raise ValueError("Account calibration requires exactly one ad account")
    rows = [row for row in snapshot.insights if row.dimensions.get("_query_scope") == "base"]
    days = len({row.date_stop for row in rows})
    if not rows:
        account = snapshot.accounts[0]
        return CalibrationSummary(
            calibration=AccountCalibration(
                account_id=account.provider_id,
                provider=snapshot.provider,
                source_snapshot_id=source_snapshot_id,
                calibrated_at=calibrated_at,
                thresholds=MarketingThresholdOverrides(),
                rationale=[
                    "No normalized ad-level base rows were available in the completed period.",
                    "Every account threshold therefore inherits its applicable "
                    "lower-layer default.",
                    "Re-run calibration after sufficient completed delivery data is available.",
                ],
            ),
            base_row_count=0,
            represented_days=0,
            unavailable_thresholds=sorted(MarketingThresholdOverrides.model_fields),
        )
    unavailable: list[str] = []

    def threshold(
        name: str,
        extractor: Callable[[InsightRow], Decimal | None],
        quantile: Decimal,
    ) -> Decimal | None:
        value = _quantile(_positive_values(rows, extractor), quantile)
        if value is None:
            unavailable.append(name)
        return value

    minimum_spend = threshold(
        "minimum_spend",
        lambda row: _value(row.metrics.spend),
        Decimal("0.25"),
    )
    minimum_impressions_decimal = threshold(
        "minimum_impressions",
        lambda row: _value(row.metrics.impressions),
        Decimal("0.25"),
    )
    minimum_clicks_decimal = threshold(
        "minimum_clicks",
        lambda row: _value(row.metrics.clicks),
        Decimal("0.25"),
    )
    result_metric = (
        (lambda row: _value(row.metrics.leads))
        if objective is MarketingObjective.LEADS
        else (lambda row: _value(row.metrics.conversions))
    )
    minimum_conversions = threshold(
        "minimum_conversions",
        result_metric,
        Decimal("0.25"),
    )
    cost_metric = (
        (lambda row: _value(row.metrics.cpl))
        if objective is MarketingObjective.LEADS
        else (lambda row: _value(row.metrics.cpa))
    )
    costs = _positive_values(rows, cost_metric)
    acceptable_cost = _quantile(costs, Decimal("0.50"))
    if acceptable_cost is None:
        unavailable.append("acceptable_cpl_cpa")
    roas = _quantile(
        _positive_values(rows, lambda row: _value(row.metrics.roas)),
        Decimal("0.50"),
    )
    if roas is None:
        unavailable.append("target_roas")
    maximum_frequency = _quantile(
        _positive_values(rows, lambda row: _value(row.metrics.frequency)),
        Decimal("0.75"),
    )
    if maximum_frequency is None:
        unavailable.append("maximum_frequency")
    ctr_variation = _relative_iqr(
        _positive_values(rows, lambda row: _value(row.metrics.ctr)),
    )
    cost_variation = _relative_iqr(costs)
    quality = _metric_completeness(rows)
    baseline_days = max(1, min(14, days // 2)) if days else 1
    comparison_days = max(1, min(7, days - baseline_days)) if days else 1
    thresholds = MarketingThresholdOverrides(
        minimum_spend=minimum_spend,
        minimum_impressions=(
            max(int(minimum_impressions_decimal), 1)
            if minimum_impressions_decimal is not None
            else None
        ),
        minimum_clicks=(
            max(int(minimum_clicks_decimal), 1) if minimum_clicks_decimal is not None else None
        ),
        minimum_conversions=minimum_conversions,
        baseline_period_days=baseline_days,
        comparison_period_days=comparison_days,
        acceptable_cpl_cpa=acceptable_cost,
        target_roas=roas,
        maximum_frequency=maximum_frequency,
        ctr_decline_threshold=_bounded(ctr_variation, Decimal("0.05"), Decimal("0.75")),
        cpl_cpa_increase_threshold=_bounded(
            cost_variation,
            Decimal("0.05"),
            Decimal("2"),
        ),
        anomaly_threshold=_bounded(
            Decimal("1") + cost_variation,
            Decimal("1"),
            Decimal("4"),
        ),
        minimum_confidence=_bounded(
            Decimal("0.50") + quality * Decimal("0.40"),
            Decimal("0.50"),
            Decimal("0.90"),
        ),
        data_completeness_threshold=_bounded(
            quality,
            Decimal("0.50"),
            Decimal("0.95"),
        ),
    )
    rationale = [
        "Provisional thresholds use only normalized ad-level base rows from the source snapshot.",
        "Volume floors use the 25th percentile; targets use medians; frequency uses the "
        "75th percentile.",
        "Relative interquartile ranges calibrate change and anomaly sensitivity.",
        f"Observed {len(rows)} base rows across {days} completed reporting days.",
    ]
    if unavailable:
        rationale.append(
            "Unavailable source metrics retained the applicable lower-layer defaults: "
            + ", ".join(sorted(unavailable))
            + ".",
        )
    account = snapshot.accounts[0]
    return CalibrationSummary(
        calibration=AccountCalibration(
            account_id=account.provider_id,
            provider=snapshot.provider,
            source_snapshot_id=source_snapshot_id,
            calibrated_at=calibrated_at,
            thresholds=thresholds,
            rationale=rationale,
        ),
        base_row_count=len(rows),
        represented_days=days,
        unavailable_thresholds=sorted(unavailable),
    )


def _value(metric: Metric) -> Decimal | None:
    return metric.value if metric.availability is DataAvailability.AVAILABLE else None


def _positive_values(
    rows: Sequence[InsightRow],
    extractor: Callable[[InsightRow], Decimal | None],
) -> list[Decimal]:
    return sorted(value for row in rows if (value := extractor(row)) is not None and value > 0)


def _quantile(values: Sequence[Decimal], probability: Decimal) -> Decimal | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = probability * Decimal(len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - Decimal(lower)
    return values[lower] + (values[upper] - values[lower]) * fraction


def _relative_iqr(values: Sequence[Decimal]) -> Decimal:
    median = _quantile(values, Decimal("0.50"))
    lower = _quantile(values, Decimal("0.25"))
    upper = _quantile(values, Decimal("0.75"))
    if median is None or lower is None or upper is None or median == 0:
        return Decimal("0.25")
    return abs(upper - lower) / median


def _metric_completeness(rows: Sequence[InsightRow]) -> Decimal:
    if not rows:
        return Decimal("0")
    metric_names = ("spend", "impressions", "clicks", "conversions", "ctr", "cpa")
    available = sum(
        1
        for row in rows
        for name in metric_names
        if getattr(row.metrics, name).availability is DataAvailability.AVAILABLE
    )
    return Decimal(available) / Decimal(len(rows) * len(metric_names))


def _bounded(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
    return min(max(value, minimum), maximum).quantize(Decimal("0.0001"))
