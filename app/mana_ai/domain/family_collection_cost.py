"""Offline upper bounds, not provider invoices or permission to activate a source."""

from decimal import Decimal

from app.mana_ai.domain.family_collection import FamilyCollectionPolicy
from app.mana_ai.domain.family_sources import FamilySourceLimits


def family_collection_forecast(
    *,
    parents: int,
    connected_links: int,
    include_app_usage: bool,
    read_price_per_100000: Decimal,
    policy: FamilyCollectionPolicy | None = None,
    source_limits: FamilySourceLimits | None = None,
) -> dict[str, object]:
    if (
        type(parents) is not int
        or type(connected_links) is not int
        or not 0 <= parents <= 100000000
        or not 0 <= connected_links <= parents * 20
    ):
        raise ValueError("Canonical nonnegative MANA population counts are required")
    if (
        not isinstance(read_price_per_100000, Decimal)
        or not read_price_per_100000.is_finite()
        or not 0 <= read_price_per_100000 <= 1000
    ):
        raise ValueError("Supply a finite explicit USD price per 100,000 Firestore reads")
    selected, limits = policy or FamilyCollectionPolicy(), source_limits or FamilySourceLimits()
    source_count = 2 if include_app_usage else 1
    pages = max(1, (parents + selected.page_size - 1) // selected.page_size)
    target_reads = connected_links * source_count
    firestore_units = connected_links * 2 * 2
    request_cap = min(limits.requests_per_24h, selected.reads_per_window * 2)
    inventory_page_cap = min(
        selected.pages_per_window * 2, selected.inventory_attempts_per_24h // 2
    )
    firestore_cap = min(limits.document_units_per_24h, request_cap * 2)
    full_price = Decimal(firestore_units) * read_price_per_100000 / Decimal(100000)
    capped_price = Decimal(firestore_cap) * read_price_per_100000 / Decimal(100000)
    sufficient = (
        target_reads <= selected.reads_per_window
        and target_reads * 2 <= limits.requests_per_24h
        and firestore_units <= limits.document_units_per_24h
        and pages <= selected.pages_per_window
        and pages * 4 <= selected.inventory_attempts_per_24h
    )
    return {
        "scope": "MANA parent-child links; battery and optionally app-counter first pages",
        "windows_local": ["09:00", "15:00"],
        "timezone": selected.timezone,
        "parents_input": parents,
        "connected_links_input": connected_links,
        "full_population_requirement": {
            "inventory_pages_per_day": pages * 2,
            "inventory_http_attempts_upper_per_day": pages * 4,
            "source_admissions_per_day": target_reads * 2,
            "firestore_document_units_upper_per_day": firestore_units,
            "source_http_attempts_upper_per_day": target_reads * 2 * 4,
            "firestore_read_usd_per_day": str(full_price),
            "firestore_read_usd_per_30_days": str(full_price * 30),
            "firestore_read_usd_per_365_days": str(full_price * 365),
        },
        "current_ceiling": {
            "source_admissions_per_rolling_24h": request_cap,
            "inventory_pages_per_rolling_24h": inventory_page_cap,
            "firestore_units_per_rolling_24h": firestore_cap,
            "response_payload_bytes_upper_per_rolling_24h": inventory_page_cap * (262144 + 65536)
            + request_cap * 4 * 65536,
            "firestore_read_usd_per_24h_upper": str(capped_price),
            "firestore_read_usd_per_30_days_upper": str(capped_price * 30),
            "firestore_read_usd_per_365_days_upper": str(capped_price * 365),
        },
        "capacity_arithmetic_sufficient": sufficient,
        "throughput_or_complete_coverage_verified": False,
        "read_price_per_100000_usd_input": str(read_price_per_100000),
        "excluded_or_unpriced": [
            "No shared free allowance is assumed. This is not the total Firebase/account bill.",
            "Existing storage, indexes beyond the fixed equality-query contract, "
            "network/wire overhead and other applications.",
            "Manakids backend compute/database/network costs have no supplied rate card.",
            "Model inference, contact delivery and other separately enabled "
            "consumers are not priced here.",
            "Scoped reads may hit cache; required population/latency and changing "
            "pagination need separate verification.",
            "Targeted reads share the same source ceiling; no limit is raised by this forecast.",
        ],
    }
