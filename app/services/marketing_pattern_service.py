from collections import defaultdict
from datetime import UTC, date, datetime

from app.schemas.marketing import (
    MarketingKpiRow,
    MarketingKpiSummary,
    MarketingPattern,
    MarketingPatternsRequest,
    MarketingPatternsResponse,
)
from app.services.marketing_metrics import MarketingMetricsBuilder
from app.services.marketing_repository import MarketingRepository


class MarketingPatternService:
    def __init__(
        self,
        *,
        repository: MarketingRepository,
        metrics_builder: MarketingMetricsBuilder,
    ) -> None:
        self._repository = repository
        self._metrics_builder = metrics_builder

    async def detect(self, request: MarketingPatternsRequest) -> MarketingPatternsResponse:
        records, _ = await self._repository.list_raw_records(
            account_ids=request.account_ids,
            entity_types=["insight"],
            date_start=request.date_start,
            date_stop=request.date_stop,
            limit=request.max_records,
            offset=0,
        )
        rows = self._metrics_builder.build_rows(records)
        summary = self._metrics_builder.summarize(rows)
        patterns = detect_marketing_patterns(
            rows=rows,
            summary=summary,
            max_patterns=request.max_patterns,
            min_spend=request.min_spend,
            spend_concentration_threshold=request.spend_concentration_threshold,
            outlier_multiplier=request.outlier_multiplier,
        )
        return MarketingPatternsResponse(
            generated_at=datetime.now(UTC),
            source_record_count=len(records),
            kpi_summary=summary,
            patterns=patterns,
        )


def detect_marketing_patterns(
    *,
    rows: list[MarketingKpiRow],
    summary: MarketingKpiSummary,
    max_patterns: int,
    min_spend: float,
    spend_concentration_threshold: float,
    outlier_multiplier: float,
) -> list[MarketingPattern]:
    if not rows:
        return [
            MarketingPattern(
                type="data_quality",
                direction="neutral",
                title="No insight KPI rows available",
                explanation="No stored Meta insight rows matched the selected filters.",
                entity_id=None,
                entity_name=None,
                level=None,
                metric="record_count",
                value=0,
                benchmark=None,
                confidence="high",
                evidence_record_ids=[],
                suggested_raw_queries=[
                    "Sync Meta insights for the target date range.",
                    "Upload raw insight exports through /api/v1/marketing/raw.",
                ],
                dimensions={},
            ),
        ]

    patterns: list[MarketingPattern] = []
    spend_rows = [row for row in rows if row.spend >= min_spend]
    total_spend = summary.total_spend

    if total_spend > 0 and len(spend_rows) > 1:
        top_row = max(spend_rows, key=lambda row: row.spend)
        spend_share = top_row.spend / total_spend
        if spend_share >= spend_concentration_threshold:
            patterns.append(
                _pattern(
                    pattern_type="spend_concentration",
                    direction="neutral",
                    title="Spend is concentrated in one entity",
                    explanation=(
                        f"{_row_label(top_row)} accounts for {spend_share:.1%} of selected "
                        "spend. This can be healthy if it is the clear winner, but it needs "
                        "audit against CPA/ROAS before scaling."
                    ),
                    row=top_row,
                    metric="spend_share",
                    value=spend_share,
                    benchmark=spend_concentration_threshold,
                    confidence="medium",
                    suggested_raw_queries=[
                        "Compare this entity against sibling campaigns/adsets/ads by CPA and ROAS.",
                        "Pull breakdowns for age, gender, platform, and placement if available.",
                    ],
                ),
            )

    patterns.extend(
        _wasted_spend_patterns(rows=spend_rows, min_spend=min_spend, total_spend=total_spend),
    )
    patterns.extend(
        _efficiency_opportunity_patterns(rows=spend_rows, summary=summary, total_spend=total_spend),
    )
    patterns.extend(
        _cost_outlier_patterns(
            rows=spend_rows,
            summary=summary,
            outlier_multiplier=outlier_multiplier,
        ),
    )
    patterns.extend(
        _engagement_outlier_patterns(
            rows=spend_rows,
            summary=summary,
            outlier_multiplier=outlier_multiplier,
        ),
    )
    patterns.extend(
        _dimension_segment_patterns(
            rows=spend_rows,
            summary=summary,
            min_spend=min_spend,
        ),
    )
    patterns.extend(_trend_patterns(rows=rows))
    patterns.extend(_data_quality_patterns(rows=rows))

    return sorted(patterns, key=_pattern_sort_key, reverse=True)[:max_patterns]


def _wasted_spend_patterns(
    *,
    rows: list[MarketingKpiRow],
    min_spend: float,
    total_spend: float,
) -> list[MarketingPattern]:
    spend_floor = max(min_spend, total_spend * 0.05)
    candidates = [
        row
        for row in rows
        if row.spend >= spend_floor and row.conversions == 0 and row.clicks > 0
    ]
    return [
        _pattern(
            pattern_type="wasted_spend",
            direction="negative",
            title="Spend with clicks but no tracked conversions",
            explanation=(
                f"{_row_label(row)} spent {row.spend:.2f} and generated {row.clicks} clicks "
                "without tracked conversions in the selected data."
            ),
            row=row,
            metric="spend_without_conversions",
            value=row.spend,
            benchmark=spend_floor,
            confidence="high",
            suggested_raw_queries=[
                "Inspect actions/action_values for the entity and verify conversion mapping.",
                "Pull landing page, placement, and creative raw data before pausing spend.",
            ],
        )
        for row in sorted(candidates, key=lambda item: item.spend, reverse=True)[:5]
    ]


def _efficiency_opportunity_patterns(
    *,
    rows: list[MarketingKpiRow],
    summary: MarketingKpiSummary,
    total_spend: float,
) -> list[MarketingPattern]:
    if summary.cpa is None and summary.roas is None:
        return []

    patterns: list[MarketingPattern] = []
    for row in rows:
        if row.conversions <= 0:
            continue
        spend_share = row.spend / total_spend if total_spend else 0.0
        efficient_cpa = (
            summary.cpa is not None
            and row.cpa is not None
            and row.cpa <= summary.cpa * 0.7
        )
        efficient_roas = (
            summary.roas is not None
            and row.roas is not None
            and row.roas >= summary.roas * 1.3
        )
        if spend_share <= 0.25 and (efficient_cpa or efficient_roas):
            patterns.append(
                _pattern(
                    pattern_type="efficiency_opportunity",
                    direction="positive",
                    title="Efficient entity may deserve more budget",
                    explanation=(
                        f"{_row_label(row)} has better efficiency than the selected average "
                        "while using a limited share of spend."
                    ),
                    row=row,
                    metric="efficiency_gap",
                    value=row.cpa if row.cpa is not None else row.roas,
                    benchmark=summary.cpa if row.cpa is not None else summary.roas,
                    confidence="medium",
                    suggested_raw_queries=[
                        "Validate volume stability across more days before scaling.",
                        "Compare audience saturation, frequency, and placement breakdowns.",
                    ],
                ),
            )
    return patterns[:5]


def _cost_outlier_patterns(
    *,
    rows: list[MarketingKpiRow],
    summary: MarketingKpiSummary,
    outlier_multiplier: float,
) -> list[MarketingPattern]:
    if summary.cpc is None:
        return []

    candidates = [
        row
        for row in rows
        if row.cpc is not None and row.cpc >= summary.cpc * outlier_multiplier and row.clicks > 0
    ]
    return [
        _pattern(
            pattern_type="cost_outlier",
            direction="negative",
            title="CPC is materially above selected average",
            explanation=(
                f"{_row_label(row)} has CPC {row.cpc:.4f}, above the selected average "
                f"of {summary.cpc:.4f}."
            ),
            row=row,
            metric="cpc",
            value=row.cpc,
            benchmark=summary.cpc,
            confidence="medium",
            suggested_raw_queries=[
                "Pull placement/device breakdowns to isolate expensive inventory.",
                "Compare creative quality and audience overlap for this entity.",
            ],
        )
        for row in sorted(candidates, key=lambda item: item.cpc or 0, reverse=True)[:5]
    ]


def _engagement_outlier_patterns(
    *,
    rows: list[MarketingKpiRow],
    summary: MarketingKpiSummary,
    outlier_multiplier: float,
) -> list[MarketingPattern]:
    if summary.ctr is None:
        return []

    low_ctr_threshold = summary.ctr / outlier_multiplier
    candidates = [
        row
        for row in rows
        if row.ctr is not None and row.ctr <= low_ctr_threshold and row.impressions > 0
    ]
    return [
        _pattern(
            pattern_type="engagement_outlier",
            direction="negative",
            title="CTR is materially below selected average",
            explanation=(
                f"{_row_label(row)} has CTR {row.ctr:.4f}, below the selected average "
                f"of {summary.ctr:.4f}."
            ),
            row=row,
            metric="ctr",
            value=row.ctr,
            benchmark=summary.ctr,
            confidence="medium",
            suggested_raw_queries=[
                "Inspect ad creative, hook, format, and placement raw records.",
                "Pull age/gender/platform breakdowns for engagement concentration.",
            ],
        )
        for row in sorted(candidates, key=lambda item: item.spend, reverse=True)[:5]
    ]


def _dimension_segment_patterns(
    *,
    rows: list[MarketingKpiRow],
    summary: MarketingKpiSummary,
    min_spend: float,
) -> list[MarketingPattern]:
    grouped: dict[tuple[str, str], list[MarketingKpiRow]] = defaultdict(list)
    for row in rows:
        for dimension_key, dimension_value in row.dimensions.items():
            grouped[(dimension_key, dimension_value)].append(row)

    if not grouped:
        return []

    spend_floor = max(min_spend, summary.total_spend * 0.05)
    patterns: list[MarketingPattern] = []
    for (dimension_key, dimension_value), segment_rows in grouped.items():
        segment_summary = _aggregate_rows(segment_rows)
        if segment_summary.total_spend < spend_floor:
            continue

        dimensions = {dimension_key: dimension_value}
        evidence_record_ids = [row.record_id for row in segment_rows[:20]]
        if segment_summary.total_conversions == 0 and segment_summary.total_clicks > 0:
            patterns.append(
                MarketingPattern(
                    type="segment_waste",
                    direction="negative",
                    title="Breakdown segment spends without tracked conversions",
                    explanation=(
                        f"Segment {dimension_key}={dimension_value} spent "
                        f"{segment_summary.total_spend:.2f} and generated "
                        f"{segment_summary.total_clicks} clicks without tracked conversions."
                    ),
                    entity_id=None,
                    entity_name=f"{dimension_key}={dimension_value}",
                    level="segment",
                    metric="segment_spend_without_conversions",
                    value=segment_summary.total_spend,
                    benchmark=spend_floor,
                    confidence="high" if len(segment_rows) > 1 else "medium",
                    evidence_record_ids=evidence_record_ids,
                    suggested_raw_queries=[
                        f"Filter raw insights where {dimension_key}={dimension_value}.",
                        "Compare the same segment by campaign, ad set, ad, and creative.",
                    ],
                    dimensions=dimensions,
                ),
            )

        efficient_cpa = (
            summary.cpa is not None
            and segment_summary.cpa is not None
            and segment_summary.cpa <= summary.cpa * 0.7
        )
        efficient_roas = (
            summary.roas is not None
            and segment_summary.roas is not None
            and segment_summary.roas >= summary.roas * 1.3
        )
        if segment_summary.total_conversions > 0 and (efficient_cpa or efficient_roas):
            metric = "segment_cpa" if efficient_cpa else "segment_roas"
            value = segment_summary.cpa if efficient_cpa else segment_summary.roas
            benchmark = summary.cpa if efficient_cpa else summary.roas
            patterns.append(
                MarketingPattern(
                    type="segment_efficiency_opportunity",
                    direction="positive",
                    title="Breakdown segment is more efficient than average",
                    explanation=(
                        f"Segment {dimension_key}={dimension_value} has stronger efficiency "
                        "than the selected average and should be checked for scalable volume."
                    ),
                    entity_id=None,
                    entity_name=f"{dimension_key}={dimension_value}",
                    level="segment",
                    metric=metric,
                    value=value,
                    benchmark=benchmark,
                    confidence="medium",
                    evidence_record_ids=evidence_record_ids,
                    suggested_raw_queries=[
                        f"Filter raw insights where {dimension_key}={dimension_value}.",
                        "Check frequency, audience saturation, and creative mix before scaling.",
                    ],
                    dimensions=dimensions,
                ),
            )

    return sorted(patterns, key=_pattern_sort_key, reverse=True)[:10]


def _trend_patterns(rows: list[MarketingKpiRow]) -> list[MarketingPattern]:
    by_date: dict[date, list[MarketingKpiRow]] = defaultdict(list)
    for row in rows:
        if row.date_start is not None:
            by_date[row.date_start].append(row)

    ordered_dates = sorted(by_date)
    if len(ordered_dates) < 2:
        return []

    first_date = ordered_dates[0]
    last_date = ordered_dates[-1]
    first = _aggregate_rows(by_date[first_date])
    last = _aggregate_rows(by_date[last_date])

    spend_change = _safe_change(first.total_spend, last.total_spend)
    conversions_change = _safe_change(first.total_conversions, last.total_conversions)
    if spend_change is None:
        return []

    if spend_change >= 0.25 and (conversions_change is None or conversions_change <= 0):
        return [
            MarketingPattern(
                type="trend",
                direction="negative",
                title="Spend increased without conversion growth",
                explanation=(
                    f"Spend rose from {first.total_spend:.2f} on {first_date.isoformat()} "
                    f"to {last.total_spend:.2f} on {last_date.isoformat()}, while conversions "
                    "did not grow in the same direction."
                ),
                entity_id=None,
                entity_name=None,
                level=None,
                metric="spend_change",
                value=spend_change,
                benchmark=conversions_change,
                confidence="medium",
                evidence_record_ids=[
                    row.record_id for row in [*by_date[first_date], *by_date[last_date]][:20]
                ],
                suggested_raw_queries=[
                    "Compare budget changes against campaign/adset delivery status by day.",
                    "Pull daily conversion action breakdowns for the same date range.",
                ],
                dimensions={},
            ),
        ]

    if conversions_change is not None and conversions_change >= 0.25:
        return [
            MarketingPattern(
                type="trend",
                direction="positive",
                title="Conversions increased over the selected window",
                explanation=(
                    f"Conversions rose from {first.total_conversions:.2f} on "
                    f"{first_date.isoformat()} to {last.total_conversions:.2f} on "
                    f"{last_date.isoformat()}."
                ),
                entity_id=None,
                entity_name=None,
                level=None,
                metric="conversions_change",
                value=conversions_change,
                benchmark=spend_change,
                confidence="medium",
                evidence_record_ids=[
                    row.record_id for row in [*by_date[first_date], *by_date[last_date]][:20]
                ],
                suggested_raw_queries=[
                    "Identify which campaigns/adsets drove the daily conversion lift.",
                    "Check whether conversion quality/value moved with volume.",
                ],
                dimensions={},
            ),
        ]

    return []


def _data_quality_patterns(rows: list[MarketingKpiRow]) -> list[MarketingPattern]:
    rows_with_conversions_without_value = [
        row for row in rows if row.conversions > 0 and row.conversion_value == 0
    ]
    if not rows_with_conversions_without_value:
        return []

    return [
        MarketingPattern(
            type="data_quality",
            direction="neutral",
            title="Conversions exist without conversion value",
            explanation=(
                "Some rows contain tracked conversions but no conversion value. ROAS analysis "
                "will be incomplete until value action mapping is verified."
            ),
            entity_id=None,
            entity_name=None,
            level=None,
            metric="rows_with_conversions_without_value",
            value=float(len(rows_with_conversions_without_value)),
            benchmark=float(len(rows)),
            confidence="high",
            evidence_record_ids=[row.record_id for row in rows_with_conversions_without_value[:20]],
            suggested_raw_queries=[
                "Verify MARKETING_VALUE_ACTION_TYPES against Meta action_values.action_type.",
                "Pull action_values for purchase and offsite conversion events.",
            ],
            dimensions={},
        ),
    ]


def _aggregate_rows(rows: list[MarketingKpiRow]) -> MarketingKpiSummary:
    total_spend = sum(row.spend for row in rows)
    total_impressions = sum(row.impressions for row in rows)
    total_reach = sum(row.reach for row in rows)
    total_clicks = sum(row.clicks for row in rows)
    total_inline_link_clicks = sum(row.inline_link_clicks for row in rows)
    total_conversions = sum(row.conversions for row in rows)
    total_conversion_value = sum(row.conversion_value for row in rows)
    return MarketingKpiSummary(
        total_spend=total_spend,
        total_impressions=total_impressions,
        total_reach=total_reach,
        total_clicks=total_clicks,
        total_inline_link_clicks=total_inline_link_clicks,
        total_conversions=total_conversions,
        total_conversion_value=total_conversion_value,
        ctr=_safe_ratio(total_clicks, total_impressions),
        cpc=_safe_ratio(total_spend, total_clicks),
        cpm=_safe_ratio(total_spend * 1000, total_impressions),
        cpa=_safe_ratio(total_spend, total_conversions),
        roas=_safe_ratio(total_conversion_value, total_spend),
    )


def _pattern(
    *,
    pattern_type: str,
    direction: str,
    title: str,
    explanation: str,
    row: MarketingKpiRow,
    metric: str,
    value: float | None,
    benchmark: float | None,
    confidence: str,
    suggested_raw_queries: list[str],
) -> MarketingPattern:
    return MarketingPattern(
        type=pattern_type,
        direction=direction,
        title=title,
        explanation=explanation,
        entity_id=row.entity_id,
        entity_name=row.entity_name,
        level=row.level,
        metric=metric,
        value=value,
        benchmark=benchmark,
        confidence=confidence,
        evidence_record_ids=[row.record_id],
        suggested_raw_queries=suggested_raw_queries,
        dimensions=row.dimensions,
    )


def _pattern_sort_key(pattern: MarketingPattern) -> tuple[float, float]:
    confidence_weight = {"high": 3.0, "medium": 2.0, "low": 1.0}[pattern.confidence]
    value_weight = abs(pattern.value or 0.0)
    return confidence_weight, value_weight


def _row_label(row: MarketingKpiRow) -> str:
    name = row.entity_name or row.entity_id or "selected entity"
    if not row.dimensions:
        return f"{row.level} {name}"

    dimension_label = ", ".join(f"{key}={value}" for key, value in row.dimensions.items())
    return f"{row.level} {name} ({dimension_label})"


def _safe_change(first: float, last: float) -> float | None:
    if first == 0:
        return None
    return round((last - first) / first, 6)


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)
