from pydantic import JsonValue

INSIGHT_DIMENSION_KEYS = {
    "age",
    "gender",
    "country",
    "region",
    "dma",
    "impression_device",
    "device_platform",
    "publisher_platform",
    "platform_position",
    "placement",
    "product_id",
    "hourly_stats_aggregated_by_advertiser_time_zone",
    "hourly_stats_aggregated_by_audience_time_zone",
    "skan_conversion_id",
}


def extract_insight_dimensions(payload: dict[str, JsonValue]) -> dict[str, str]:
    dimensions: dict[str, str] = {}
    for key in sorted(INSIGHT_DIMENSION_KEYS):
        value = payload.get(key)
        if isinstance(value, str | int | float) and not isinstance(value, bool):
            dimensions[key] = str(value)
    return dimensions
