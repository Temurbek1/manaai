from decimal import Decimal

from app.mana_operation_ai.domain.enums import DataAvailability
from app.mana_operation_ai.domain.marketing import Metric, PerformanceMetrics

ZERO = Decimal("0")
HUNDRED = Decimal("100")
THOUSAND = Decimal("1000")


def available(value: Decimal) -> Metric:
    return Metric(value=value, availability=DataAvailability.AVAILABLE)


def unavailable(reason: str) -> Metric:
    return Metric(value=None, availability=DataAvailability.UNAVAILABLE, reason=reason)


def ratio(
    numerator: Decimal | None,
    denominator: Decimal | None,
    *,
    multiplier: Decimal = Decimal("1"),
    reason: str,
) -> Metric:
    if numerator is None or denominator is None or denominator == ZERO:
        return unavailable(reason)
    return available((numerator / denominator) * multiplier)


def build_metrics(
    *,
    spend: Decimal | None,
    impressions: Decimal | None,
    reach: Decimal | None,
    clicks: Decimal | None,
    link_clicks: Decimal | None,
    conversions: Decimal | None,
    leads: Decimal | None,
    revenue: Decimal | None,
) -> PerformanceMetrics:
    valid_spend = non_negative_or_none(spend)
    valid_impressions = non_negative_or_none(impressions)
    valid_reach = non_negative_or_none(reach)
    valid_clicks = non_negative_or_none(clicks)
    valid_leads = non_negative_or_none(leads)
    valid_conversions = non_negative_or_none(conversions)
    return PerformanceMetrics(
        spend=_non_negative(spend, "spend is absent", "spend is negative"),
        impressions=_non_negative(
            impressions,
            "impressions are absent",
            "impressions are negative",
        ),
        reach=_non_negative(reach, "reach is absent", "reach is negative"),
        clicks=_non_negative(clicks, "clicks are absent", "clicks are negative"),
        link_clicks=_non_negative(
            link_clicks,
            "link clicks are absent",
            "link clicks are negative",
        ),
        conversions=_non_negative(
            conversions,
            "conversions are absent",
            "conversions are negative",
        ),
        leads=_non_negative(leads, "leads are absent", "leads are negative"),
        revenue=_base(revenue, "purchase value is absent"),
        ctr=ratio(
            valid_clicks,
            valid_impressions,
            multiplier=HUNDRED,
            reason="CTR denominator unavailable",
        ),
        cpc=ratio(valid_spend, valid_clicks, reason="CPC denominator unavailable"),
        cpm=ratio(
            valid_spend,
            valid_impressions,
            multiplier=THOUSAND,
            reason="CPM denominator unavailable",
        ),
        cpl=ratio(valid_spend, valid_leads, reason="CPL denominator unavailable"),
        cpa=ratio(valid_spend, valid_conversions, reason="CPA denominator unavailable"),
        roas=ratio(revenue, valid_spend, reason="ROAS denominator unavailable"),
        frequency=ratio(
            valid_impressions,
            valid_reach,
            reason="frequency denominator unavailable",
        ),
    )


def _base(value: Decimal | None, reason: str) -> Metric:
    return available(value) if value is not None else unavailable(reason)


def _non_negative(value: Decimal | None, absent_reason: str, negative_reason: str) -> Metric:
    if value is None:
        return unavailable(absent_reason)
    if value < ZERO:
        return unavailable(negative_reason)
    return available(value)


def non_negative_or_none(value: Decimal | None) -> Decimal | None:
    return value if value is not None and value >= ZERO else None
