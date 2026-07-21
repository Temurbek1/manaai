from collections.abc import Sequence

from pydantic import JsonValue

from app.schemas.marketing import MarketingEntityType, RawMarketingRecord
from app.services.marketing_payload import json_str, nested_id, nested_name

OPERATIONAL_CONTEXT_ENTITY_TYPES: list[MarketingEntityType] = [
    "app",
    "business",
    "ad_account",
    "pixel",
    "custom_conversion",
    "custom_audience",
    "insights_job",
]
GLOBAL_OPERATIONAL_CONTEXT_ENTITY_TYPES: list[MarketingEntityType] = [
    "app",
    "business",
    "pixel",
]

_CONTEXT_ATTRIBUTE_KEYS = [
    "status",
    "effective_status",
    "account_status",
    "disable_reason",
    "currency",
    "timezone_name",
    "publication_status",
    "app_review_status",
    "business_verification_status",
    "technology_provider_status",
    "use_cases",
    "permissions",
    "required_actions",
    "developer_console_urls",
    "api_version",
    "async_status",
    "async_percent_completion",
    "custom_event_type",
    "event_source_type",
    "last_fired_time",
    "is_archived",
    "is_unavailable",
    "subtype",
    "delivery_status",
    "operation_status",
    "permission_for_actions",
    "approximate_count",
    "retention_days",
    "time_content_updated",
]


def build_operational_context(
    records: Sequence[RawMarketingRecord],
) -> list[dict[str, JsonValue]]:
    return [_context_item(record) for record in records[:50]]


def dedupe_raw_records(records: Sequence[RawMarketingRecord]) -> list[RawMarketingRecord]:
    deduped: list[RawMarketingRecord] = []
    seen: set[str] = set()
    for record in records:
        if record.id in seen:
            continue
        seen.add(record.id)
        deduped.append(record)
    return deduped


def _context_item(record: RawMarketingRecord) -> dict[str, JsonValue]:
    entity_id = record.provider_record_id or _payload_id(record.payload)
    item: dict[str, JsonValue] = {
        "source_record_id": record.id,
        "source": record.source,
        "entity_type": record.entity_type,
    }
    if entity_id is not None:
        item["entity_id"] = entity_id
    if record.account_id is not None:
        item["account_id"] = record.account_id
    if record.parent_id is not None:
        item["parent_id"] = record.parent_id

    name = _record_name(record.payload)
    if name is not None:
        item["name"] = name

    business_id = _business_id(record.payload)
    if business_id is not None:
        item["business_id"] = business_id
    business_name = _business_name(record.payload)
    if business_name is not None:
        item["business_name"] = business_name

    attributes = _context_attributes(record.payload)
    if attributes:
        item["attributes"] = attributes
    return item


def _payload_id(payload: dict[str, JsonValue]) -> str | None:
    return json_str(payload.get("id")) or json_str(payload.get("app_id"))


def _record_name(payload: dict[str, JsonValue]) -> str | None:
    return (
        json_str(payload.get("name"))
        or json_str(payload.get("app_name"))
        or json_str(payload.get("business_name"))
        or json_str(payload.get("account_name"))
    )


def _business_id(payload: dict[str, JsonValue]) -> str | None:
    return (
        nested_id(payload.get("business"))
        or json_str(payload.get("business_id"))
        or json_str(payload.get("_meta_business_id"))
    )


def _business_name(payload: dict[str, JsonValue]) -> str | None:
    return (
        nested_name(payload.get("business"))
        or json_str(payload.get("business_name"))
        or json_str(payload.get("_meta_business_name"))
    )


def _context_attributes(payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        key: value
        for key in _CONTEXT_ATTRIBUTE_KEYS
        if (value := payload.get(key)) is not None
    }
