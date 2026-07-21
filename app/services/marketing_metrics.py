from datetime import date

from pydantic import JsonValue

from app.schemas.marketing import MarketingKpiRow, MarketingKpiSummary, RawMarketingRecord
from app.services.marketing_dimensions import extract_insight_dimensions


class MarketingMetricsBuilder:
    def __init__(
        self,
        *,
        conversion_action_types: list[str],
        value_action_types: list[str],
    ) -> None:
        self._conversion_action_types = set(conversion_action_types)
        self._value_action_types = set(value_action_types)

    @property
    def conversion_action_types(self) -> set[str]:
        return set(self._conversion_action_types)

    @property
    def value_action_types(self) -> set[str]:
        return set(self._value_action_types)

    def build_rows(self, records: list[RawMarketingRecord]) -> list[MarketingKpiRow]:
        rows: list[MarketingKpiRow] = []
        for record in records:
            if record.entity_type != "insight":
                continue
            payload = record.payload
            spend = _float_value(payload.get("spend"))
            impressions = _int_value(payload.get("impressions"))
            reach = _int_value(payload.get("reach"))
            clicks = _int_value(payload.get("clicks"))
            inline_link_clicks = _int_value(payload.get("inline_link_clicks"))
            conversions = _sum_action_values(
                payload.get("actions"),
                action_types=self._conversion_action_types,
            )
            conversion_value = _sum_action_values(
                payload.get("action_values"),
                action_types=self._value_action_types,
            )
            rows.append(
                MarketingKpiRow(
                    record_id=record.id,
                    level=str(payload.get("_meta_level") or _infer_level(payload)),
                    entity_id=_entity_id(payload),
                    entity_name=_entity_name(payload),
                    account_id=_optional_str(payload.get("account_id")) or record.account_id,
                    date_start=_date_value(payload.get("date_start")),
                    date_stop=_date_value(payload.get("date_stop")),
                    spend=spend,
                    impressions=impressions,
                    reach=reach,
                    clicks=clicks,
                    inline_link_clicks=inline_link_clicks,
                    conversions=conversions,
                    conversion_value=conversion_value,
                    ctr=_safe_ratio(clicks, impressions),
                    frequency=_safe_ratio(impressions, reach),
                    cpc=_safe_ratio(spend, clicks),
                    cpm=_safe_ratio(spend * 1000, impressions),
                    cpa=_safe_ratio(spend, conversions),
                    roas=_safe_ratio(conversion_value, spend),
                    dimensions=extract_insight_dimensions(payload),
                ),
            )
        return rows

    def summarize(self, rows: list[MarketingKpiRow]) -> MarketingKpiSummary:
        total_spend = sum(row.spend for row in rows)
        total_impressions = sum(row.impressions for row in rows)
        total_reach = sum(row.reach for row in rows)
        total_clicks = sum(row.clicks for row in rows)
        total_inline_link_clicks = sum(row.inline_link_clicks for row in rows)
        total_conversions = sum(row.conversions for row in rows)
        total_conversion_value = sum(row.conversion_value for row in rows)

        return MarketingKpiSummary(
            total_spend=round(total_spend, 6),
            total_impressions=total_impressions,
            total_reach=total_reach,
            total_clicks=total_clicks,
            total_inline_link_clicks=total_inline_link_clicks,
            total_conversions=round(total_conversions, 6),
            total_conversion_value=round(total_conversion_value, 6),
            ctr=_safe_ratio(total_clicks, total_impressions),
            frequency=_safe_ratio(total_impressions, total_reach),
            cpc=_safe_ratio(total_spend, total_clicks),
            cpm=_safe_ratio(total_spend * 1000, total_impressions),
            cpa=_safe_ratio(total_spend, total_conversions),
            roas=_safe_ratio(total_conversion_value, total_spend),
        )


def _entity_id(payload: dict[str, JsonValue]) -> str | None:
    for key in ("ad_id", "adset_id", "campaign_id", "account_id"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def _entity_name(payload: dict[str, JsonValue]) -> str | None:
    for key in ("ad_name", "adset_name", "campaign_name", "account_name"):
        value = payload.get(key)
        if value is not None:
            return str(value)
    return None


def _infer_level(payload: dict[str, JsonValue]) -> str:
    if payload.get("ad_id") is not None:
        return "ad"
    if payload.get("adset_id") is not None:
        return "adset"
    if payload.get("campaign_id") is not None:
        return "campaign"
    return "account"


def _sum_action_values(value: JsonValue | None, *, action_types: set[str]) -> float:
    if not isinstance(value, list):
        return 0.0

    total = 0.0
    for item in value:
        if not isinstance(item, dict):
            continue
        action_type = item.get("action_type")
        if action_type not in action_types:
            continue
        total += _float_value(item.get("value"))
    return total


def _date_value(value: JsonValue | None) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _optional_str(value: JsonValue | None) -> str | None:
    return str(value) if value is not None else None


def _int_value(value: JsonValue | None) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value:
        try:
            return int(float(value))
        except ValueError:
            return 0
    return 0


def _float_value(value: JsonValue | None) -> float:
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


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)
