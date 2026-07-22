from decimal import Decimal


def calculate_reference_metrics(
    *,
    spend: Decimal | None,
    impressions: Decimal | None,
    reach: Decimal | None,
    clicks: Decimal | None,
    link_clicks: Decimal | None,
    conversions: Decimal | None,
    leads: Decimal | None,
    revenue: Decimal | None,
) -> dict[str, Decimal | None]:
    valid_spend = non_negative(spend)
    valid_impressions = non_negative(impressions)
    valid_reach = non_negative(reach)
    valid_clicks = non_negative(clicks)
    valid_link_clicks = non_negative(link_clicks)
    valid_conversions = non_negative(conversions)
    valid_leads = non_negative(leads)
    return {
        "spend": valid_spend,
        "impressions": valid_impressions,
        "reach": valid_reach,
        "clicks": valid_clicks,
        "link_clicks": valid_link_clicks,
        "conversions": valid_conversions,
        "leads": valid_leads,
        "revenue": revenue,
        "ctr": divide(valid_clicks, valid_impressions, Decimal("100")),
        "cpc": divide(valid_spend, valid_clicks),
        "cpm": divide(valid_spend, valid_impressions, Decimal("1000")),
        "cpl": divide(valid_spend, valid_leads),
        "cpa": divide(valid_spend, valid_conversions),
        "roas": divide(revenue, valid_spend),
        "frequency": divide(valid_impressions, valid_reach),
    }


def non_negative(value: Decimal | None) -> Decimal | None:
    if value is None or value < Decimal("0"):
        return None
    return value


def divide(
    numerator: Decimal | None,
    denominator: Decimal | None,
    multiplier: Decimal = Decimal("1"),
) -> Decimal | None:
    if numerator is None or denominator is None or denominator == Decimal("0"):
        return None
    return numerator / denominator * multiplier
