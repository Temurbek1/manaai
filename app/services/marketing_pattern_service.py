from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime

from app.schemas.marketing import (
    MarketingKpiRow,
    MarketingKpiSummary,
    MarketingPattern,
    MarketingPatternsRequest,
    MarketingPatternsResponse,
    RawMarketingRecord,
)
from app.services.marketing_metrics import MarketingMetricsBuilder
from app.services.marketing_payload import json_str, nested_id
from app.services.marketing_repository import MarketingRepository
from app.services.marketing_targeting import targeting_custom_audiences

DELIVERY_STATUS_ISSUE_VALUES = {
    "ACCOUNT_DISABLED",
    "ADSET_PAUSED",
    "ARCHIVED",
    "CAMPAIGN_PAUSED",
    "DELETED",
    "DISAPPROVED",
    "IN_PROCESS",
    "PAUSED",
    "PENDING_BILLING_INFO",
    "PENDING_REVIEW",
    "REJECTED",
    "WITH_ISSUES",
}
ACTIVE_ACCOUNT_STATUS_VALUES = {"1", "ACTIVE"}


@dataclass(frozen=True)
class CreativePerformanceContext:
    ad_to_creative_id: dict[str, str]
    creative_names: dict[str, str]
    creative_record_ids: dict[str, str]


@dataclass(frozen=True)
class AudiencePerformanceContext:
    ad_to_adset_id: dict[str, str]
    adset_to_audience_ids: dict[str, list[str]]
    audience_names: dict[str, str]
    audience_record_ids: dict[str, str]
    adset_record_ids: dict[str, str]


@dataclass(frozen=True)
class HierarchyPerformanceContext:
    ad_to_adset_id: dict[str, str]
    ad_to_campaign_id: dict[str, str]
    adset_to_campaign_id: dict[str, str]
    adset_names: dict[str, str]
    campaign_names: dict[str, str]
    adset_record_ids: dict[str, str]
    campaign_record_ids: dict[str, str]


@dataclass(frozen=True)
class ActionSignalContext:
    configured_conversion_action_types: set[str]
    action_totals: dict[str, float]
    action_record_ids: dict[str, list[str]]


@dataclass(frozen=True)
class MeasurementAssetStatus:
    entity_type: str
    entity_id: str
    entity_name: str
    record_id: str
    parent_pixel_id: str | None
    last_fired_at: datetime | None
    is_unavailable: bool
    is_archived: bool


@dataclass(frozen=True)
class MeasurementHealthContext:
    pixels: list[MeasurementAssetStatus]
    custom_conversions: list[MeasurementAssetStatus]


@dataclass(frozen=True)
class DeliveryEntityStatus:
    entity_type: str
    entity_id: str
    entity_name: str
    record_id: str
    status: str | None
    effective_status: str | None
    account_status: str | None


@dataclass(frozen=True)
class DeliveryStatusContext:
    entity_statuses: dict[tuple[str, str], DeliveryEntityStatus]


class MarketingPatternService:
    def __init__(
        self,
        *,
        repository: MarketingRepository,
        metrics_builder: MarketingMetricsBuilder,
        measurement_stale_after_days: int,
    ) -> None:
        self._repository = repository
        self._metrics_builder = metrics_builder
        self._measurement_stale_after_days = measurement_stale_after_days

    async def detect(self, request: MarketingPatternsRequest) -> MarketingPatternsResponse:
        records, _ = await self._repository.list_raw_records(
            account_ids=request.account_ids,
            entity_types=["insight"],
            date_start=request.date_start,
            date_stop=request.date_stop,
            limit=request.max_records,
            offset=0,
        )
        structure_records, _ = await self._repository.list_raw_records(
            account_ids=request.account_ids,
            entity_types=[
                "ad_account",
                "campaign",
                "adset",
                "ad",
                "creative",
                "custom_audience",
                "pixel",
                "custom_conversion",
            ],
            limit=request.max_records,
            offset=0,
        )
        if request.account_ids:
            global_pixel_records, _ = await self._repository.list_raw_records(
                entity_types=["pixel"],
                limit=request.max_records,
                offset=0,
            )
            structure_records = _dedupe_records([*structure_records, *global_pixel_records])
        rows = self._metrics_builder.build_rows(records)
        summary = self._metrics_builder.summarize(rows)
        creative_context = build_creative_performance_context(structure_records)
        audience_context = build_audience_performance_context([*records, *structure_records])
        hierarchy_context = build_hierarchy_performance_context([*records, *structure_records])
        patterns = detect_marketing_patterns(
            rows=rows,
            summary=summary,
            creative_context=creative_context,
            audience_context=audience_context,
            hierarchy_context=hierarchy_context,
            action_signal_context=build_action_signal_context(
                records=records,
                configured_conversion_action_types=self._metrics_builder.conversion_action_types,
            ),
            delivery_context=build_delivery_status_context(structure_records),
            measurement_context=build_measurement_health_context(structure_records),
            measurement_stale_after_days=self._measurement_stale_after_days,
            max_patterns=request.max_patterns,
            min_spend=request.min_spend,
            spend_concentration_threshold=request.spend_concentration_threshold,
            outlier_multiplier=request.outlier_multiplier,
            frequency_fatigue_threshold=request.frequency_fatigue_threshold,
        )
        source_record_ids = {record.id for record in [*records, *structure_records]}
        return MarketingPatternsResponse(
            generated_at=datetime.now(UTC),
            source_record_count=len(source_record_ids),
            kpi_summary=summary,
            patterns=patterns,
        )


def detect_marketing_patterns(
    *,
    rows: list[MarketingKpiRow],
    summary: MarketingKpiSummary,
    creative_context: CreativePerformanceContext | None = None,
    audience_context: AudiencePerformanceContext | None = None,
    hierarchy_context: HierarchyPerformanceContext | None = None,
    action_signal_context: ActionSignalContext | None = None,
    delivery_context: DeliveryStatusContext | None = None,
    measurement_context: MeasurementHealthContext | None = None,
    measurement_stale_after_days: int = 14,
    max_patterns: int,
    min_spend: float,
    spend_concentration_threshold: float,
    outlier_multiplier: float,
    frequency_fatigue_threshold: float,
) -> list[MarketingPattern]:
    if not rows:
        empty_patterns = [
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
        if measurement_context is not None:
            empty_patterns.extend(
                _measurement_health_patterns(
                    measurement_context=measurement_context,
                    now=datetime.now(UTC),
                    stale_after_days=measurement_stale_after_days,
                ),
            )
        return sorted(empty_patterns, key=_pattern_sort_key, reverse=True)[:max_patterns]

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
        _frequency_fatigue_patterns(
            rows=spend_rows,
            summary=summary,
            min_spend=min_spend,
            frequency_threshold=frequency_fatigue_threshold,
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
    if creative_context is not None:
        patterns.extend(
            _creative_rollup_patterns(
                rows=spend_rows,
                summary=summary,
                min_spend=min_spend,
                creative_context=creative_context,
            ),
        )
    if hierarchy_context is not None:
        patterns.extend(
            _hierarchy_rollup_patterns(
                rows=spend_rows,
                summary=summary,
                min_spend=min_spend,
                hierarchy_context=hierarchy_context,
            ),
        )
    if delivery_context is not None:
        patterns.extend(
            _delivery_status_patterns(
                rows=spend_rows,
                summary=summary,
                min_spend=min_spend,
                delivery_context=delivery_context,
                hierarchy_context=hierarchy_context,
            ),
        )
    patterns.extend(_trend_patterns(rows=rows))
    if audience_context is not None:
        patterns.extend(
            _audience_rollup_patterns(
                rows=spend_rows,
                summary=summary,
                min_spend=min_spend,
                audience_context=audience_context,
            ),
        )
    if action_signal_context is not None:
        patterns.extend(
            _unmapped_action_signal_patterns(
                rows=rows,
                action_signal_context=action_signal_context,
            ),
        )
    if measurement_context is not None:
        patterns.extend(
            _measurement_health_patterns(
                measurement_context=measurement_context,
                now=datetime.now(UTC),
                stale_after_days=measurement_stale_after_days,
            ),
        )
    patterns.extend(_data_quality_patterns(rows=rows))

    return sorted(patterns, key=_pattern_sort_key, reverse=True)[:max_patterns]


def build_creative_performance_context(
    records: list[RawMarketingRecord],
) -> CreativePerformanceContext:
    ad_to_creative_id: dict[str, str] = {}
    creative_names: dict[str, str] = {}
    creative_record_ids: dict[str, str] = {}

    for record in records:
        payload = record.payload
        if record.entity_type == "ad":
            ad_id = json_str(payload.get("id")) or record.provider_record_id
            creative_id = nested_id(payload.get("creative")) or json_str(payload.get("creative_id"))
            if ad_id is not None and creative_id is not None and ad_id not in ad_to_creative_id:
                ad_to_creative_id[ad_id] = creative_id

        if record.entity_type == "creative":
            creative_id = json_str(payload.get("id")) or record.provider_record_id
            if creative_id is None:
                continue
            creative_names.setdefault(creative_id, _creative_label(record=record))
            creative_record_ids.setdefault(creative_id, record.id)

    return CreativePerformanceContext(
        ad_to_creative_id=ad_to_creative_id,
        creative_names=creative_names,
        creative_record_ids=creative_record_ids,
    )


def build_audience_performance_context(
    records: list[RawMarketingRecord],
) -> AudiencePerformanceContext:
    ad_to_adset_id: dict[str, str] = {}
    adset_to_audience_ids: dict[str, list[str]] = defaultdict(list)
    audience_names: dict[str, str] = {}
    audience_record_ids: dict[str, str] = {}
    adset_record_ids: dict[str, str] = {}

    for record in records:
        payload = record.payload
        if record.entity_type == "ad":
            ad_id = json_str(payload.get("id")) or record.provider_record_id
            adset_id = json_str(payload.get("adset_id")) or record.parent_id
            if ad_id is not None and adset_id is not None and ad_id not in ad_to_adset_id:
                ad_to_adset_id[ad_id] = adset_id

        if record.entity_type == "insight":
            ad_id = json_str(payload.get("ad_id"))
            adset_id = json_str(payload.get("adset_id"))
            if ad_id is not None and adset_id is not None and ad_id not in ad_to_adset_id:
                ad_to_adset_id[ad_id] = adset_id

        if record.entity_type == "adset":
            adset_id = json_str(payload.get("id")) or record.provider_record_id
            if adset_id is None:
                continue
            adset_record_ids.setdefault(adset_id, record.id)
            targeting = payload.get("targeting")
            if not isinstance(targeting, dict):
                continue
            for audience in targeting_custom_audiences(targeting, roles={"included"}):
                if audience.id not in adset_to_audience_ids[adset_id]:
                    adset_to_audience_ids[adset_id].append(audience.id)
                if audience.name is not None:
                    audience_names.setdefault(audience.id, audience.name)

        if record.entity_type == "custom_audience":
            audience_id = json_str(payload.get("id")) or record.provider_record_id
            if audience_id is None:
                continue
            audience_names.setdefault(audience_id, _audience_label(record=record))
            audience_record_ids.setdefault(audience_id, record.id)

    return AudiencePerformanceContext(
        ad_to_adset_id=ad_to_adset_id,
        adset_to_audience_ids=dict(adset_to_audience_ids),
        audience_names=audience_names,
        audience_record_ids=audience_record_ids,
        adset_record_ids=adset_record_ids,
    )


def build_hierarchy_performance_context(
    records: list[RawMarketingRecord],
) -> HierarchyPerformanceContext:
    ad_to_adset_id: dict[str, str] = {}
    ad_to_campaign_id: dict[str, str] = {}
    adset_to_campaign_id: dict[str, str] = {}
    adset_names: dict[str, str] = {}
    campaign_names: dict[str, str] = {}
    adset_record_ids: dict[str, str] = {}
    campaign_record_ids: dict[str, str] = {}

    for record in records:
        payload = record.payload
        if record.entity_type == "campaign":
            campaign_id = json_str(payload.get("id")) or record.provider_record_id
            if campaign_id is None:
                continue
            campaign_names.setdefault(campaign_id, _hierarchy_label(record=record))
            campaign_record_ids.setdefault(campaign_id, record.id)

        if record.entity_type == "adset":
            adset_id = json_str(payload.get("id")) or record.provider_record_id
            campaign_id = json_str(payload.get("campaign_id")) or record.parent_id
            if adset_id is None:
                continue
            adset_names.setdefault(adset_id, _hierarchy_label(record=record))
            adset_record_ids.setdefault(adset_id, record.id)
            if campaign_id is not None and adset_id not in adset_to_campaign_id:
                adset_to_campaign_id[adset_id] = campaign_id

        if record.entity_type == "ad":
            ad_id = json_str(payload.get("id")) or record.provider_record_id
            adset_id = json_str(payload.get("adset_id")) or record.parent_id
            campaign_id = json_str(payload.get("campaign_id"))
            if ad_id is None:
                continue
            if adset_id is not None and ad_id not in ad_to_adset_id:
                ad_to_adset_id[ad_id] = adset_id
            if campaign_id is not None and ad_id not in ad_to_campaign_id:
                ad_to_campaign_id[ad_id] = campaign_id

        if record.entity_type == "insight":
            ad_id = json_str(payload.get("ad_id"))
            adset_id = json_str(payload.get("adset_id"))
            campaign_id = json_str(payload.get("campaign_id"))
            if ad_id is not None:
                if adset_id is not None and ad_id not in ad_to_adset_id:
                    ad_to_adset_id[ad_id] = adset_id
                if campaign_id is not None and ad_id not in ad_to_campaign_id:
                    ad_to_campaign_id[ad_id] = campaign_id
            if adset_id is not None:
                adset_name = json_str(payload.get("adset_name"))
                if adset_name is not None:
                    adset_names.setdefault(adset_id, adset_name)
                if campaign_id is not None and adset_id not in adset_to_campaign_id:
                    adset_to_campaign_id[adset_id] = campaign_id
            if campaign_id is not None:
                campaign_name = json_str(payload.get("campaign_name"))
                if campaign_name is not None:
                    campaign_names.setdefault(campaign_id, campaign_name)

    return HierarchyPerformanceContext(
        ad_to_adset_id=ad_to_adset_id,
        ad_to_campaign_id=ad_to_campaign_id,
        adset_to_campaign_id=adset_to_campaign_id,
        adset_names=adset_names,
        campaign_names=campaign_names,
        adset_record_ids=adset_record_ids,
        campaign_record_ids=campaign_record_ids,
    )


def build_action_signal_context(
    *,
    records: list[RawMarketingRecord],
    configured_conversion_action_types: set[str],
) -> ActionSignalContext:
    action_totals: dict[str, float] = defaultdict(float)
    action_record_ids: dict[str, list[str]] = defaultdict(list)

    for record in records:
        if record.entity_type != "insight":
            continue
        actions = record.payload.get("actions")
        if not isinstance(actions, list):
            continue
        for item in actions:
            if not isinstance(item, dict):
                continue
            action_type = json_str(item.get("action_type"))
            if action_type is None:
                continue
            action_totals[action_type] += _float_value(item.get("value"))
            if record.id not in action_record_ids[action_type]:
                action_record_ids[action_type].append(record.id)

    return ActionSignalContext(
        configured_conversion_action_types=set(configured_conversion_action_types),
        action_totals=dict(action_totals),
        action_record_ids={key: value[:20] for key, value in action_record_ids.items()},
    )


def build_measurement_health_context(
    records: list[RawMarketingRecord],
) -> MeasurementHealthContext:
    pixels: list[MeasurementAssetStatus] = []
    custom_conversions: list[MeasurementAssetStatus] = []

    for record in records:
        payload = record.payload
        if record.entity_type == "pixel":
            pixel_id = json_str(payload.get("id")) or record.provider_record_id
            if pixel_id is None:
                continue
            pixels.append(
                MeasurementAssetStatus(
                    entity_type="pixel",
                    entity_id=pixel_id,
                    entity_name=_measurement_label(record=record),
                    record_id=record.id,
                    parent_pixel_id=None,
                    last_fired_at=_datetime_value(payload.get("last_fired_time")),
                    is_unavailable=_bool_value(payload.get("is_unavailable")),
                    is_archived=False,
                ),
            )

        if record.entity_type == "custom_conversion":
            custom_conversion_id = json_str(payload.get("id")) or record.provider_record_id
            if custom_conversion_id is None:
                continue
            custom_conversions.append(
                MeasurementAssetStatus(
                    entity_type="custom_conversion",
                    entity_id=custom_conversion_id,
                    entity_name=_measurement_label(record=record),
                    record_id=record.id,
                    parent_pixel_id=(
                        nested_id(payload.get("pixel"))
                        or json_str(payload.get("pixel_id"))
                        or record.parent_id
                    ),
                    last_fired_at=_datetime_value(payload.get("last_fired_time")),
                    is_unavailable=False,
                    is_archived=_bool_value(payload.get("is_archived")),
                ),
            )

    return MeasurementHealthContext(
        pixels=pixels,
        custom_conversions=custom_conversions,
    )


def build_delivery_status_context(
    records: list[RawMarketingRecord],
) -> DeliveryStatusContext:
    entity_statuses: dict[tuple[str, str], DeliveryEntityStatus] = {}

    for record in records:
        if record.entity_type not in {"ad_account", "campaign", "adset", "ad"}:
            continue
        entity_id = _delivery_entity_id(record)
        if entity_id is None:
            continue
        key = (record.entity_type, entity_id)
        if key in entity_statuses:
            continue
        payload = record.payload
        entity_statuses[key] = DeliveryEntityStatus(
            entity_type=record.entity_type,
            entity_id=entity_id,
            entity_name=_delivery_label(record=record),
            record_id=record.id,
            status=_status_value(payload.get("status")),
            effective_status=_status_value(payload.get("effective_status")),
            account_status=_status_value(payload.get("account_status")),
        )

    return DeliveryStatusContext(entity_statuses=entity_statuses)


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


def _frequency_fatigue_patterns(
    *,
    rows: list[MarketingKpiRow],
    summary: MarketingKpiSummary,
    min_spend: float,
    frequency_threshold: float,
    outlier_multiplier: float,
) -> list[MarketingPattern]:
    spend_floor = max(min_spend, summary.total_spend * 0.05)
    low_ctr_threshold = summary.ctr / outlier_multiplier if summary.ctr is not None else None
    candidates: list[MarketingKpiRow] = []

    for row in rows:
        if row.frequency is None or row.frequency < frequency_threshold:
            continue
        if row.spend < spend_floor:
            continue
        conversion_issue = row.conversions == 0 and row.clicks > 0
        ctr_issue = (
            low_ctr_threshold is not None
            and row.ctr is not None
            and row.ctr <= low_ctr_threshold
        )
        if conversion_issue or ctr_issue:
            candidates.append(row)

    return [
        _pattern(
            pattern_type="frequency_fatigue",
            direction="negative",
            title="High frequency may indicate audience or creative fatigue",
            explanation=(
                f"{_row_label(row)} has frequency {row.frequency:.2f}, above the configured "
                f"{frequency_threshold:.2f} threshold, with weak conversion or CTR evidence."
            ),
            row=row,
            metric="frequency",
            value=row.frequency,
            benchmark=frequency_threshold,
            confidence="medium",
            suggested_raw_queries=[
                "Compare frequency by placement, device, audience, and creative.",
                "Inspect recent creative refreshes and audience saturation before scaling.",
            ],
        )
        for row in sorted(candidates, key=lambda item: item.frequency or 0, reverse=True)[:5]
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


def _hierarchy_rollup_patterns(
    *,
    rows: list[MarketingKpiRow],
    summary: MarketingKpiSummary,
    min_spend: float,
    hierarchy_context: HierarchyPerformanceContext,
) -> list[MarketingPattern]:
    patterns: list[MarketingPattern] = []
    native_adset_ids = {row.entity_id for row in rows if row.level == "adset" and row.entity_id}
    native_campaign_ids = {
        row.entity_id for row in rows if row.level == "campaign" and row.entity_id
    }

    adset_groups: dict[str, list[MarketingKpiRow]] = defaultdict(list)
    ad_rows = [row for row in rows if row.level == "ad" and row.entity_id is not None]
    for row in ad_rows:
        adset_id = hierarchy_context.ad_to_adset_id.get(str(row.entity_id))
        if adset_id is not None and adset_id not in native_adset_ids:
            adset_groups[adset_id].append(row)

    patterns.extend(
        _parent_rollup_patterns(
            grouped=adset_groups,
            parent_level="adset",
            summary=summary,
            min_spend=min_spend,
            parent_names=hierarchy_context.adset_names,
            parent_record_ids=hierarchy_context.adset_record_ids,
        ),
    )

    campaign_rows = ad_rows if ad_rows else [
        row for row in rows if row.level == "adset" and row.entity_id is not None
    ]
    campaign_groups: dict[str, list[MarketingKpiRow]] = defaultdict(list)
    for row in campaign_rows:
        campaign_id = _row_campaign_id(row=row, hierarchy_context=hierarchy_context)
        if campaign_id is not None and campaign_id not in native_campaign_ids:
            campaign_groups[campaign_id].append(row)

    patterns.extend(
        _parent_rollup_patterns(
            grouped=campaign_groups,
            parent_level="campaign",
            summary=summary,
            min_spend=min_spend,
            parent_names=hierarchy_context.campaign_names,
            parent_record_ids=hierarchy_context.campaign_record_ids,
        ),
    )

    return sorted(patterns, key=_pattern_sort_key, reverse=True)[:10]


def _parent_rollup_patterns(
    *,
    grouped: dict[str, list[MarketingKpiRow]],
    parent_level: str,
    summary: MarketingKpiSummary,
    min_spend: float,
    parent_names: dict[str, str],
    parent_record_ids: dict[str, str],
) -> list[MarketingPattern]:
    if not grouped:
        return []

    spend_floor = max(min_spend, summary.total_spend * 0.05)
    patterns: list[MarketingPattern] = []
    for parent_id, child_rows in grouped.items():
        parent_summary = _aggregate_rows(child_rows)
        if parent_summary.total_spend < spend_floor:
            continue

        parent_name = parent_names.get(parent_id) or parent_id
        evidence_record_ids = _parent_evidence_record_ids(
            parent_id=parent_id,
            rows=child_rows,
            parent_record_ids=parent_record_ids,
        )
        dimensions = {"rollup_level": parent_level, f"{parent_level}_id": parent_id}

        if parent_summary.total_conversions == 0 and parent_summary.total_clicks > 0:
            patterns.append(
                MarketingPattern(
                    type=f"{parent_level}_rollup_waste",
                    direction="negative",
                    title=f"{parent_level.title()} rollup spends without conversions",
                    explanation=(
                        f"{parent_level.title()} {parent_name} aggregates "
                        f"{len(child_rows)} lower-level KPI row(s), spent "
                        f"{parent_summary.total_spend:.2f}, and generated "
                        f"{parent_summary.total_clicks} clicks without tracked conversions."
                    ),
                    entity_id=parent_id,
                    entity_name=parent_name,
                    level=parent_level,
                    metric=f"{parent_level}_rollup_spend_without_conversions",
                    value=parent_summary.total_spend,
                    benchmark=spend_floor,
                    confidence="high" if len(child_rows) > 1 else "medium",
                    evidence_record_ids=evidence_record_ids,
                    suggested_raw_queries=[
                        f"Search raw records by provider_record_id={parent_id}.",
                        f"Compare child rows inside this {parent_level} before budget changes.",
                    ],
                    dimensions=dimensions,
                ),
            )

        efficient_cpa = (
            summary.cpa is not None
            and parent_summary.cpa is not None
            and parent_summary.cpa <= summary.cpa * 0.7
        )
        efficient_roas = (
            summary.roas is not None
            and parent_summary.roas is not None
            and parent_summary.roas >= summary.roas * 1.3
        )
        if parent_summary.total_conversions > 0 and (efficient_cpa or efficient_roas):
            metric = f"{parent_level}_rollup_cpa" if efficient_cpa else (
                f"{parent_level}_rollup_roas"
            )
            value = parent_summary.cpa if efficient_cpa else parent_summary.roas
            benchmark = summary.cpa if efficient_cpa else summary.roas
            patterns.append(
                MarketingPattern(
                    type=f"{parent_level}_rollup_efficiency_opportunity",
                    direction="positive",
                    title=f"{parent_level.title()} rollup is more efficient than average",
                    explanation=(
                        f"{parent_level.title()} {parent_name} aggregates "
                        f"{len(child_rows)} lower-level KPI row(s) with stronger efficiency "
                        "than the selected average."
                    ),
                    entity_id=parent_id,
                    entity_name=parent_name,
                    level=parent_level,
                    metric=metric,
                    value=value,
                    benchmark=benchmark,
                    confidence="medium",
                    evidence_record_ids=evidence_record_ids,
                    suggested_raw_queries=[
                        f"Search raw records by provider_record_id={parent_id}.",
                        f"Validate child ads/ad sets inside this {parent_level} before scaling.",
                    ],
                    dimensions=dimensions,
                ),
            )

    return sorted(patterns, key=_pattern_sort_key, reverse=True)[:10]


def _delivery_status_patterns(
    *,
    rows: list[MarketingKpiRow],
    summary: MarketingKpiSummary,
    min_spend: float,
    delivery_context: DeliveryStatusContext,
    hierarchy_context: HierarchyPerformanceContext | None,
) -> list[MarketingPattern]:
    if not delivery_context.entity_statuses:
        return []

    grouped: dict[tuple[str, str], list[MarketingKpiRow]] = defaultdict(list)
    for row in rows:
        for status in _delivery_statuses_for_row(
            row=row,
            delivery_context=delivery_context,
            hierarchy_context=hierarchy_context,
        ):
            if _is_delivery_status_issue(status):
                grouped[(status.entity_type, status.entity_id)].append(row)

    if not grouped:
        return []

    spend_floor = max(min_spend, summary.total_spend * 0.05)
    patterns: list[MarketingPattern] = []
    for key, impacted_rows in grouped.items():
        impacted_summary = _aggregate_rows(impacted_rows)
        if impacted_summary.total_spend < spend_floor:
            continue

        status = delivery_context.entity_statuses[key]
        status_label = _delivery_status_label(status)
        patterns.append(
            MarketingPattern(
                type="delivery_status_issue",
                direction="neutral",
                title="Spend is tied to a non-active delivery status",
                explanation=(
                    f"{status.entity_type.replace('_', ' ').title()} {status.entity_name} "
                    f"has {status_label}. Selected KPI rows connected to this object spent "
                    f"{impacted_summary.total_spend:.2f}. Validate current delivery state "
                    "before scaling, pausing, or judging performance."
                ),
                entity_id=status.entity_id,
                entity_name=status.entity_name,
                level=status.entity_type,
                metric="impacted_spend_with_status_issue",
                value=impacted_summary.total_spend,
                benchmark=spend_floor,
                confidence="high" if status.effective_status is not None else "medium",
                evidence_record_ids=_delivery_evidence_record_ids(
                    status=status,
                    rows=impacted_rows,
                ),
                suggested_raw_queries=[
                    f"Search raw records by provider_record_id={status.entity_id}.",
                    "Compare status/effective_status with the selected insight date range.",
                ],
                dimensions=_delivery_dimensions(status=status, impacted_rows=impacted_rows),
            ),
        )

    return sorted(patterns, key=_pattern_sort_key, reverse=True)[:10]


def _creative_rollup_patterns(
    *,
    rows: list[MarketingKpiRow],
    summary: MarketingKpiSummary,
    min_spend: float,
    creative_context: CreativePerformanceContext,
) -> list[MarketingPattern]:
    if not creative_context.ad_to_creative_id:
        return []

    grouped: dict[str, list[MarketingKpiRow]] = defaultdict(list)
    for row in rows:
        if row.level != "ad" or row.entity_id is None:
            continue
        creative_id = creative_context.ad_to_creative_id.get(row.entity_id)
        if creative_id is not None:
            grouped[creative_id].append(row)

    if not grouped:
        return []

    spend_floor = max(min_spend, summary.total_spend * 0.05)
    patterns: list[MarketingPattern] = []
    for creative_id, creative_rows in grouped.items():
        creative_summary = _aggregate_rows(creative_rows)
        if creative_summary.total_spend < spend_floor:
            continue

        evidence_record_ids = _creative_evidence_record_ids(
            creative_id=creative_id,
            rows=creative_rows,
            creative_context=creative_context,
        )
        creative_name = creative_context.creative_names.get(creative_id) or creative_id
        dimensions = {"creative_id": creative_id}

        if creative_summary.total_conversions == 0 and creative_summary.total_clicks > 0:
            patterns.append(
                MarketingPattern(
                    type="creative_waste",
                    direction="negative",
                    title="Creative rollup spends without tracked conversions",
                    explanation=(
                        f"Creative {creative_name} is mapped to {len(creative_rows)} ad KPI "
                        f"row(s), spent {creative_summary.total_spend:.2f}, and generated "
                        f"{creative_summary.total_clicks} clicks without tracked conversions."
                    ),
                    entity_id=creative_id,
                    entity_name=creative_name,
                    level="creative",
                    metric="creative_spend_without_conversions",
                    value=creative_summary.total_spend,
                    benchmark=spend_floor,
                    confidence="high" if len(creative_rows) > 1 else "medium",
                    evidence_record_ids=evidence_record_ids,
                    suggested_raw_queries=[
                        f"Search raw records by provider_record_id={creative_id}.",
                        "Inspect the ads mapped to this creative before pausing it.",
                    ],
                    dimensions=dimensions,
                ),
            )

        efficient_cpa = (
            summary.cpa is not None
            and creative_summary.cpa is not None
            and creative_summary.cpa <= summary.cpa * 0.7
        )
        efficient_roas = (
            summary.roas is not None
            and creative_summary.roas is not None
            and creative_summary.roas >= summary.roas * 1.3
        )
        if creative_summary.total_conversions > 0 and (efficient_cpa or efficient_roas):
            metric = "creative_cpa" if efficient_cpa else "creative_roas"
            value = creative_summary.cpa if efficient_cpa else creative_summary.roas
            benchmark = summary.cpa if efficient_cpa else summary.roas
            patterns.append(
                MarketingPattern(
                    type="creative_efficiency_opportunity",
                    direction="positive",
                    title="Creative rollup is more efficient than average",
                    explanation=(
                        f"Creative {creative_name} is mapped to {len(creative_rows)} ad KPI "
                        "row(s) and has stronger efficiency than the selected average."
                    ),
                    entity_id=creative_id,
                    entity_name=creative_name,
                    level="creative",
                    metric=metric,
                    value=value,
                    benchmark=benchmark,
                    confidence="medium",
                    evidence_record_ids=evidence_record_ids,
                    suggested_raw_queries=[
                        f"Search raw records by provider_record_id={creative_id}.",
                        "Compare delivery volume, placement mix, and sibling ads before scaling.",
                    ],
                    dimensions=dimensions,
                ),
            )

    return sorted(patterns, key=_pattern_sort_key, reverse=True)[:10]


def _audience_rollup_patterns(
    *,
    rows: list[MarketingKpiRow],
    summary: MarketingKpiSummary,
    min_spend: float,
    audience_context: AudiencePerformanceContext,
) -> list[MarketingPattern]:
    if not audience_context.adset_to_audience_ids:
        return []

    grouped: dict[str, list[MarketingKpiRow]] = defaultdict(list)
    for row in rows:
        adset_id = _row_adset_id(row=row, audience_context=audience_context)
        if adset_id is None:
            continue
        for audience_id in audience_context.adset_to_audience_ids.get(adset_id, []):
            grouped[audience_id].append(row)

    if not grouped:
        return []

    spend_floor = max(min_spend, summary.total_spend * 0.05)
    patterns: list[MarketingPattern] = []
    for audience_id, audience_rows in grouped.items():
        audience_summary = _aggregate_rows(audience_rows)
        if audience_summary.total_spend < spend_floor:
            continue

        evidence_record_ids = _audience_evidence_record_ids(
            audience_id=audience_id,
            rows=audience_rows,
            audience_context=audience_context,
        )
        audience_name = audience_context.audience_names.get(audience_id) or audience_id
        dimensions = {"custom_audience_id": audience_id, "targeting_role": "included"}

        if audience_summary.total_conversions == 0 and audience_summary.total_clicks > 0:
            patterns.append(
                MarketingPattern(
                    type="audience_waste",
                    direction="negative",
                    title="Included custom audience rollup spends without conversions",
                    explanation=(
                        f"Ad sets that include custom audience {audience_name} produced "
                        f"{len(audience_rows)} KPI row(s), spent "
                        f"{audience_summary.total_spend:.2f}, and generated "
                        f"{audience_summary.total_clicks} clicks without tracked conversions. "
                        "This is a targeting rollup, not exclusive causal attribution."
                    ),
                    entity_id=audience_id,
                    entity_name=audience_name,
                    level="custom_audience",
                    metric="audience_spend_without_conversions",
                    value=audience_summary.total_spend,
                    benchmark=spend_floor,
                    confidence="high" if len(audience_rows) > 1 else "medium",
                    evidence_record_ids=evidence_record_ids,
                    suggested_raw_queries=[
                        f"Search raw records by provider_record_id={audience_id}.",
                        "Inspect ad sets that include this audience before changing targeting.",
                    ],
                    dimensions=dimensions,
                ),
            )

        efficient_cpa = (
            summary.cpa is not None
            and audience_summary.cpa is not None
            and audience_summary.cpa <= summary.cpa * 0.7
        )
        efficient_roas = (
            summary.roas is not None
            and audience_summary.roas is not None
            and audience_summary.roas >= summary.roas * 1.3
        )
        if audience_summary.total_conversions > 0 and (efficient_cpa or efficient_roas):
            metric = "audience_cpa" if efficient_cpa else "audience_roas"
            value = audience_summary.cpa if efficient_cpa else audience_summary.roas
            benchmark = summary.cpa if efficient_cpa else summary.roas
            patterns.append(
                MarketingPattern(
                    type="audience_efficiency_opportunity",
                    direction="positive",
                    title="Included custom audience rollup is more efficient than average",
                    explanation=(
                        f"Ad sets that include custom audience {audience_name} produced "
                        f"{len(audience_rows)} KPI row(s) with stronger efficiency than the "
                        "selected average. Validate overlap and scale before budget changes."
                    ),
                    entity_id=audience_id,
                    entity_name=audience_name,
                    level="custom_audience",
                    metric=metric,
                    value=value,
                    benchmark=benchmark,
                    confidence="medium",
                    evidence_record_ids=evidence_record_ids,
                    suggested_raw_queries=[
                        f"Search raw records by provider_record_id={audience_id}.",
                        "Compare audience overlap, exclusions, frequency, and placement mix.",
                    ],
                    dimensions=dimensions,
                ),
            )

    return sorted(patterns, key=_pattern_sort_key, reverse=True)[:10]


def _unmapped_action_signal_patterns(
    *,
    rows: list[MarketingKpiRow],
    action_signal_context: ActionSignalContext,
) -> list[MarketingPattern]:
    unmapped_totals = {
        action_type: total
        for action_type, total in action_signal_context.action_totals.items()
        if action_type not in action_signal_context.configured_conversion_action_types
        and total > 0
    }
    if not unmapped_totals:
        return []

    top_actions = sorted(unmapped_totals.items(), key=lambda item: item[1], reverse=True)[:5]
    top_action_type, top_action_total = top_actions[0]
    evidence_record_ids: list[str] = []
    for action_type, _ in top_actions:
        for record_id in action_signal_context.action_record_ids.get(action_type, []):
            if record_id not in evidence_record_ids:
                evidence_record_ids.append(record_id)
            if len(evidence_record_ids) >= 20:
                break
        if len(evidence_record_ids) >= 20:
            break

    action_label = ", ".join(
        f"{action_type}={total:g}" for action_type, total in top_actions
    )
    return [
        MarketingPattern(
            type="unmapped_action_signal",
            direction="neutral",
            title="Meta action signals are not mapped as conversions",
            explanation=(
                "Stored insight rows contain Meta action values that are not included in "
                "MARKETING_CONVERSION_ACTION_TYPES. Waste and CPA findings may be overstated "
                f"until mapping is verified. Top unmapped action values: {action_label}."
            ),
            entity_id=None,
            entity_name=None,
            level=None,
            metric="unmapped_action_value",
            value=top_action_total,
            benchmark=float(len(rows)),
            confidence="high",
            evidence_record_ids=evidence_record_ids,
            suggested_raw_queries=[
                "Review MARKETING_CONVERSION_ACTION_TYPES for the observed action types.",
                "Inspect raw insight actions before pausing spend as non-converting.",
            ],
            dimensions={
                "action_type": top_action_type,
                "configured_conversion_action_types": str(
                    len(action_signal_context.configured_conversion_action_types),
                ),
            },
        ),
    ]


def _measurement_health_patterns(
    *,
    measurement_context: MeasurementHealthContext,
    now: datetime,
    stale_after_days: int,
) -> list[MarketingPattern]:
    patterns: list[MarketingPattern] = []

    for pixel in measurement_context.pixels:
        if pixel.is_unavailable:
            patterns.append(
                MarketingPattern(
                    type="pixel_unavailable",
                    direction="negative",
                    title="Meta pixel is marked unavailable",
                    explanation=(
                        f"Pixel {pixel.entity_name} is stored with is_unavailable=true. "
                        "Conversion tracking and optimization signals may be incomplete until "
                        "the pixel status is resolved."
                    ),
                    entity_id=pixel.entity_id,
                    entity_name=pixel.entity_name,
                    level="pixel",
                    metric="pixel_unavailable",
                    value=1,
                    benchmark=0,
                    confidence="high",
                    evidence_record_ids=[pixel.record_id],
                    suggested_raw_queries=[
                        f"Search raw records by provider_record_id={pixel.entity_id}.",
                        "Check Meta Events Manager status before changing conversion budgets.",
                    ],
                    dimensions={"measurement_entity_type": "pixel"},
                ),
            )
        stale_pattern = _measurement_stale_pattern(
            asset=pixel,
            now=now,
            stale_after_days=stale_after_days,
        )
        if stale_pattern is not None:
            patterns.append(stale_pattern)

    for custom_conversion in measurement_context.custom_conversions:
        if custom_conversion.is_archived:
            patterns.append(
                MarketingPattern(
                    type="custom_conversion_archived",
                    direction="negative",
                    title="Custom conversion is archived",
                    explanation=(
                        f"Custom conversion {custom_conversion.entity_name} is stored with "
                        "is_archived=true. CPA and ROAS conclusions can be incomplete if this "
                        "conversion is still expected in reporting."
                    ),
                    entity_id=custom_conversion.entity_id,
                    entity_name=custom_conversion.entity_name,
                    level="custom_conversion",
                    metric="custom_conversion_archived",
                    value=1,
                    benchmark=0,
                    confidence="high",
                    evidence_record_ids=[custom_conversion.record_id],
                    suggested_raw_queries=[
                        f"Search raw records by provider_record_id={custom_conversion.entity_id}.",
                        "Verify active conversion rules before judging campaigns by CPA or ROAS.",
                    ],
                    dimensions=_measurement_dimensions(custom_conversion),
                ),
            )
        stale_pattern = _measurement_stale_pattern(
            asset=custom_conversion,
            now=now,
            stale_after_days=stale_after_days,
        )
        if stale_pattern is not None:
            patterns.append(stale_pattern)

    return sorted(patterns, key=_pattern_sort_key, reverse=True)[:10]


def _measurement_stale_pattern(
    *,
    asset: MeasurementAssetStatus,
    now: datetime,
    stale_after_days: int,
) -> MarketingPattern | None:
    if asset.last_fired_at is None:
        return None

    days_since_last_fired = (now - asset.last_fired_at).days
    if days_since_last_fired <= stale_after_days:
        return None

    return MarketingPattern(
        type="measurement_event_stale",
        direction="negative",
        title="Measurement event has not fired recently",
        explanation=(
            f"{asset.entity_type.replace('_', ' ').title()} {asset.entity_name} last fired "
            f"{days_since_last_fired} day(s) ago, above the configured "
            f"{stale_after_days}-day freshness threshold. Validate tracking freshness before "
            "using CPA or ROAS as final evidence."
        ),
        entity_id=asset.entity_id,
        entity_name=asset.entity_name,
        level=asset.entity_type,
        metric="days_since_last_fired",
        value=float(days_since_last_fired),
        benchmark=float(stale_after_days),
        confidence="medium",
        evidence_record_ids=[asset.record_id],
        suggested_raw_queries=[
            f"Search raw records by provider_record_id={asset.entity_id}.",
            "Compare last_fired_time against recent insight action timestamps.",
        ],
        dimensions=_measurement_dimensions(asset),
    )


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


def _creative_evidence_record_ids(
    *,
    creative_id: str,
    rows: list[MarketingKpiRow],
    creative_context: CreativePerformanceContext,
) -> list[str]:
    evidence_record_ids: list[str] = []
    creative_record_id = creative_context.creative_record_ids.get(creative_id)
    if creative_record_id is not None:
        evidence_record_ids.append(creative_record_id)

    for row in rows:
        if row.record_id not in evidence_record_ids:
            evidence_record_ids.append(row.record_id)
        if len(evidence_record_ids) >= 20:
            break

    return evidence_record_ids


def _audience_evidence_record_ids(
    *,
    audience_id: str,
    rows: list[MarketingKpiRow],
    audience_context: AudiencePerformanceContext,
) -> list[str]:
    evidence_record_ids: list[str] = []
    audience_record_id = audience_context.audience_record_ids.get(audience_id)
    if audience_record_id is not None:
        evidence_record_ids.append(audience_record_id)

    adset_ids = [
        adset_id
        for row in rows
        if (adset_id := _row_adset_id(row=row, audience_context=audience_context)) is not None
    ]
    for adset_id in adset_ids:
        adset_record_id = audience_context.adset_record_ids.get(adset_id)
        if adset_record_id is not None and adset_record_id not in evidence_record_ids:
            evidence_record_ids.append(adset_record_id)
        if len(evidence_record_ids) >= 20:
            return evidence_record_ids

    for row in rows:
        if row.record_id not in evidence_record_ids:
            evidence_record_ids.append(row.record_id)
        if len(evidence_record_ids) >= 20:
            break

    return evidence_record_ids


def _parent_evidence_record_ids(
    *,
    parent_id: str,
    rows: list[MarketingKpiRow],
    parent_record_ids: dict[str, str],
) -> list[str]:
    evidence_record_ids: list[str] = []
    parent_record_id = parent_record_ids.get(parent_id)
    if parent_record_id is not None:
        evidence_record_ids.append(parent_record_id)

    for row in rows:
        if row.record_id not in evidence_record_ids:
            evidence_record_ids.append(row.record_id)
        if len(evidence_record_ids) >= 20:
            break

    return evidence_record_ids


def _row_adset_id(
    *,
    row: MarketingKpiRow,
    audience_context: AudiencePerformanceContext,
) -> str | None:
    if row.level == "adset":
        return row.entity_id
    if row.level == "ad" and row.entity_id is not None:
        return audience_context.ad_to_adset_id.get(row.entity_id)
    return None


def _row_campaign_id(
    *,
    row: MarketingKpiRow,
    hierarchy_context: HierarchyPerformanceContext,
) -> str | None:
    if row.level == "campaign":
        return row.entity_id
    if row.level == "adset" and row.entity_id is not None:
        return hierarchy_context.adset_to_campaign_id.get(row.entity_id)
    if row.level == "ad" and row.entity_id is not None:
        campaign_id = hierarchy_context.ad_to_campaign_id.get(row.entity_id)
        if campaign_id is not None:
            return campaign_id
        adset_id = hierarchy_context.ad_to_adset_id.get(row.entity_id)
        if adset_id is not None:
            return hierarchy_context.adset_to_campaign_id.get(adset_id)
    return None


def _delivery_statuses_for_row(
    *,
    row: MarketingKpiRow,
    delivery_context: DeliveryStatusContext,
    hierarchy_context: HierarchyPerformanceContext | None,
) -> list[DeliveryEntityStatus]:
    keys: list[tuple[str, str]] = []
    row_level = str(row.level)

    if row.account_id is not None:
        keys.append(("ad_account", row.account_id))

    if row.entity_id is not None:
        if row_level in {"campaign", "adset", "ad"}:
            keys.append((row_level, row.entity_id))
        if row_level == "account":
            keys.append(("ad_account", row.entity_id))

    if hierarchy_context is not None and row.entity_id is not None:
        if row_level == "ad":
            adset_id = hierarchy_context.ad_to_adset_id.get(row.entity_id)
            if adset_id is not None:
                keys.append(("adset", adset_id))
            campaign_id = _row_campaign_id(row=row, hierarchy_context=hierarchy_context)
            if campaign_id is not None:
                keys.append(("campaign", campaign_id))

        if row_level == "adset":
            campaign_id = hierarchy_context.adset_to_campaign_id.get(row.entity_id)
            if campaign_id is not None:
                keys.append(("campaign", campaign_id))

    statuses: list[DeliveryEntityStatus] = []
    seen: set[tuple[str, str]] = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        status = delivery_context.entity_statuses.get(key)
        if status is not None:
            statuses.append(status)
    return statuses


def _is_delivery_status_issue(status: DeliveryEntityStatus) -> bool:
    if status.effective_status in DELIVERY_STATUS_ISSUE_VALUES:
        return True
    if status.status in DELIVERY_STATUS_ISSUE_VALUES:
        return True
    return (
        status.account_status is not None
        and status.account_status not in ACTIVE_ACCOUNT_STATUS_VALUES
    )


def _delivery_evidence_record_ids(
    *,
    status: DeliveryEntityStatus,
    rows: list[MarketingKpiRow],
) -> list[str]:
    evidence_record_ids = [status.record_id]
    for row in rows:
        if row.record_id not in evidence_record_ids:
            evidence_record_ids.append(row.record_id)
        if len(evidence_record_ids) >= 20:
            break
    return evidence_record_ids


def _delivery_dimensions(
    *,
    status: DeliveryEntityStatus,
    impacted_rows: list[MarketingKpiRow],
) -> dict[str, str]:
    dimensions = {
        "delivery_entity_type": status.entity_type,
        "impacted_kpi_rows": str(len(impacted_rows)),
    }
    if status.status is not None:
        dimensions["status"] = status.status
    if status.effective_status is not None:
        dimensions["effective_status"] = status.effective_status
    if status.account_status is not None:
        dimensions["account_status"] = status.account_status
    return dimensions


def _delivery_status_label(status: DeliveryEntityStatus) -> str:
    values: list[str] = []
    if status.status is not None:
        values.append(f"status={status.status}")
    if status.effective_status is not None:
        values.append(f"effective_status={status.effective_status}")
    if status.account_status is not None:
        values.append(f"account_status={status.account_status}")
    return ", ".join(values) if values else "no stored delivery status"


def _creative_label(*, record: RawMarketingRecord) -> str:
    for key in ("name", "title", "body"):
        value = json_str(record.payload.get(key))
        if value is not None:
            return value
    return record.provider_record_id or record.id


def _hierarchy_label(*, record: RawMarketingRecord) -> str:
    value = json_str(record.payload.get("name"))
    if value is not None:
        return value
    return record.provider_record_id or record.id


def _audience_label(*, record: RawMarketingRecord) -> str:
    for key in ("name", "description", "subtype"):
        value = json_str(record.payload.get(key))
        if value is not None:
            return value
    return record.provider_record_id or record.id


def _measurement_label(*, record: RawMarketingRecord) -> str:
    for key in ("name", "description", "custom_event_type"):
        value = json_str(record.payload.get(key))
        if value is not None:
            return value
    return record.provider_record_id or record.id


def _delivery_label(*, record: RawMarketingRecord) -> str:
    value = json_str(record.payload.get("name"))
    if value is not None:
        return value
    return record.provider_record_id or record.account_id or record.id


def _delivery_entity_id(record: RawMarketingRecord) -> str | None:
    if record.entity_type == "ad_account":
        return json_str(record.payload.get("id")) or record.provider_record_id or record.account_id
    return json_str(record.payload.get("id")) or record.provider_record_id


def _measurement_dimensions(asset: MeasurementAssetStatus) -> dict[str, str]:
    dimensions = {"measurement_entity_type": asset.entity_type}
    if asset.parent_pixel_id is not None:
        dimensions["pixel_id"] = asset.parent_pixel_id
    return dimensions


def _dedupe_records(records: list[RawMarketingRecord]) -> list[RawMarketingRecord]:
    deduped: list[RawMarketingRecord] = []
    seen: set[str] = set()
    for record in records:
        if record.id in seen:
            continue
        seen.add(record.id)
        deduped.append(record)
    return deduped


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
        frequency=_safe_ratio(total_impressions, total_reach),
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


def _float_value(value: object | None) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _bool_value(value: object | None) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"true", "1", "yes", "y"}
    return False


def _status_value(value: object | None) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        return normalized.upper()
    return str(value)


def _datetime_value(value: object | None) -> datetime | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, datetime):
        return _utc_datetime(value)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, int | float):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        try:
            return datetime.fromtimestamp(timestamp, UTC)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            return _utc_datetime(datetime.fromisoformat(normalized))
        except ValueError:
            return None
    return None


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)
