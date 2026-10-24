"""Exact offline rate arithmetic and declared coverage, never provider requests."""

from decimal import Decimal

import pytest

from app.mana_ai.domain.family_collection_cost import family_collection_forecast


def test_full_fleet_demand_and_current_caps_are_independent() -> None:
    result = family_collection_forecast(
        parents=50000,
        connected_links=50000,
        include_app_usage=True,
        read_price_per_100000=Decimal("0.06"),
    )
    full = result["full_population_requirement"]
    cap = result["current_ceiling"]
    assert isinstance(full, dict) and isinstance(cap, dict)
    assert full["source_admissions_per_day"] == 200000
    assert full["firestore_document_units_upper_per_day"] == 200000
    assert full["firestore_read_usd_per_day"] == "0.12"
    assert full["firestore_read_usd_per_30_days"] == "3.60"
    assert full["firestore_read_usd_per_365_days"] == "43.80"
    assert cap["firestore_units_per_rolling_24h"] == 200
    assert cap["firestore_read_usd_per_24h_upper"] == "0.00012"
    assert cap["firestore_read_usd_per_365_days_upper"] == "0.04380"
    assert (
        not result["capacity_arithmetic_sufficient"]
        and not result["throughput_or_complete_coverage_verified"]
    )


def test_zero_population_still_needs_one_inventory_page_in_each_window() -> None:
    result = family_collection_forecast(
        parents=0, connected_links=0, include_app_usage=False, read_price_per_100000=Decimal("0.06")
    )
    full = result["full_population_requirement"]
    assert isinstance(full, dict) and full["inventory_pages_per_day"] == 2
    assert full["firestore_document_units_upper_per_day"] == 0
    assert result["capacity_arithmetic_sufficient"]


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-1"])
async def test_invalid_price_cannot_enable_or_price_a_collection(price: str) -> None:
    with pytest.raises(ValueError):
        family_collection_forecast(
            parents=1,
            connected_links=1,
            include_app_usage=True,
            read_price_per_100000=Decimal(price),
        )
