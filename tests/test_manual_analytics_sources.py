"""Actual metered HTTP adapters, fake transports only. Never contact live sources."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from app.core.config import Settings
from app.mana_operation_ai.application.cost_control import CostBudgetExceeded
from app.mana_operation_ai.application.ports import ProviderPermanentError, ProviderTransientError
from app.mana_operation_ai.application.retention.analytics_evidence import render_analytics
from app.mana_operation_ai.domain.cost_control import (
    CostAttribution,
    CostLimits,
    DataRateCard,
    ProductScope,
    ResourceUsage,
)
from app.mana_operation_ai.domain.first_party_analytics import (
    PARENT_ACTIVITY_CAPABILITY,
    PARENT_LABEL_MAX_LENGTH,
    ParentAnalyticsBreakdown,
    ParentBreakdownRow,
)
from app.mana_operation_ai.infrastructure.metered_http import MeteredReadHttp
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.retention.analytics_http import AnalyticsReadHttp
from app.mana_operation_ai.infrastructure.retention.firestore_child_telemetry import (
    FirestoreChildTelemetryAdapter,
)
from app.mana_operation_ai.infrastructure.retention.ga4_parent_analytics import (
    Ga4ParentAnalyticsAdapter,
)
from tests.test_operation_cost_ledger import Clock

STREAM = "99"
PRIVATE = "PRIVATE-profile-token-and-location"


class Token:
    async def access_token(self) -> str:
        return "fixture-token"


def report(
    dimensions: list[str], metrics: list[str], rows: list[tuple[list[str], list[str]]]
) -> dict[str, Any]:
    return {
        "dimensionHeaders": [{"name": name} for name in dimensions],
        "metricHeaders": [{"name": name} for name in metrics],
        "rowCount": len(rows),
        "metadata": {"timeZone": "Etc/GMT-5"},
        "rows": [
            {
                "dimensionValues": [{"value": value} for value in dims],
                "metricValues": [{"value": value} for value in values],
            }
            for dims, values in rows
        ],
        "ignored_private_field": PRIVATE,
    }


def ga4_payload(request: httpx.Request) -> dict[str, Any]:
    body = json.loads(request.content)
    if request.url.path.endswith(":batchRunReports"):
        assert set(body) == {"requests"}
        result = []
        for item in body["requests"]:
            filtered = item["dimensionFilter"]
            if "andGroup" in filtered:
                expressions = filtered["andGroup"]["expressions"]
                assert expressions[1]["filter"]["stringFilter"]["value"] == "notification_open"
                filtered = expressions[0]
            assert filtered["filter"]["stringFilter"]["value"] == STREAM
            dims = [value["name"] for value in item["dimensions"]]
            metrics = [value["name"] for value in item["metrics"]]
            if "cohortSpec" in item:
                assert "dateRanges" not in item and item["limit"] == "31"
                name = item["cohortSpec"]["cohorts"][0]["name"]
                rows = [
                    ([name, f"{day:04}", STREAM], [str(100 if day == 0 else 10), "100"])
                    for day in range(31)
                ]
            elif "eventName" in dims:
                rows = [([STREAM, "button_click"], ["350"]), ([STREAM, "screen_view"], ["750"])]
            elif "unifiedScreenName" in dims:
                assert item["limit"] == "10"
                rows = [([STREAM, "Home", "HomeActivity"], ["500", "125.5"])]
            elif "mobileDeviceModel" in dims:
                assert len(dims) == 8 and item["limit"] == "10"
                rows = [
                    (
                        [STREAM, "Pixel 8", "Google", "Android", "14", "1.2.3", "uz", "mobile"],
                        ["3", "750"],
                    )
                ]
            elif "country" in dims:
                rows = [([STREAM, "Uzbekistan", "Tashkent", "Tashkent"], ["3", "750"])]
            elif "firstUserSource" in dims:
                rows = [
                    (
                        [
                            STREAM,
                            "instagram",
                            "social",
                            "Parent launch",
                            "Manual",
                            "Organic Social",
                        ],
                        ["2", "3", "750"],
                    )
                ]
            elif "dayOfWeek" in dims:
                rows = [([STREAM, "0", "23"], ["3", "6", "750"])]
            elif "dateHourMinute" in dims:
                assert "andGroup" in item["dimensionFilter"]
                assert item["orderBys"][0]["dimension"]["dimensionName"] == "dateHourMinute"
                rows = [([STREAM, "202610112354"], ["5"])]
            else:
                assert item["dateRanges"][0]["endDate"] == "2026-10-11"
                rows = [([STREAM], ["3", "6", "4", "150.25"])]
            result.append(report(dims, metrics, rows))
        return {"reports": result}
    assert request.url.path.endswith(":runFunnelReport") and body["limit"] == "3"
    assert body["funnel"]["isOpenFunnel"] is False
    for index, step in enumerate(body["funnel"]["steps"]):
        assert (
            step["filterExpression"]["andGroup"]["expressions"][1]["funnelFieldFilter"][
                "stringFilter"
            ]["value"]
            == STREAM
        )
        if index:
            assert step["withinDurationFromPriorStep"] == "86400s"
    table = report(
        ["funnelStepName"],
        [
            "activeUsers",
            "funnelStepCompletionRate",
            "funnelStepAbandonments",
            "funnelStepAbandonmentRate",
        ],
        [
            (["1. notification_receive"], ["100", "0.5", "50", "0.5"]),
            (["2. notification_open"], ["50", "0.5", "25", "0.5"]),
            (["3. button_click"], ["25", "1", "0", "0"]),
        ],
    )
    # Match the duplicated-header shape observed in the real diagnostic.
    table["metricHeaders"] *= 2
    return {"funnelTable": table}


def firestore_payload(request: httpx.Request, clock: Clock) -> dict[str, Any]:
    fields: list[dict[str, Any]]
    assert request.method == "GET" and request.url.params["pageSize"] == "100"
    assert request.url.params["orderBy"] == "__name__ asc"
    assert "pageToken" not in request.url.params
    collection = request.url.path.rsplit("/", 1)[-1]
    assert collection in {"battery", "children_location"}
    prefix = f"projects/fake-project/databases/(default)/documents/{collection}/"
    now = clock.now()
    if collection == "battery":
        assert set(request.url.params.get_list("mask.fieldPaths")) == {"percent", "created_at"}
        fields = [
            {
                "percent": {"stringValue": value},
                "created_at": {"stringValue": "2026-10-12T14:00:00"},
            }
            for value in ["20%", "101", "NaN", "0"]
        ]
    else:
        assert "coords.latitude" in request.url.params.get_list("mask.fieldPaths")
        fields = []
        for accuracy, mock, stamp, lat in [
            (6.76, False, now - timedelta(minutes=1), 41.123456),
            (1830.64, False, now - timedelta(minutes=1), 41.123456),
            (6.76, True, now - timedelta(minutes=1), 41.123456),
            (6.76, False, datetime(2037, 1, 1, tzinfo=UTC), 41.123456),
            (6.76, False, now - timedelta(minutes=1), 91),
        ]:
            fields.append(
                {
                    "coords": {
                        "mapValue": {
                            "fields": {
                                "latitude": {"doubleValue": lat},
                                "longitude": {"doubleValue": 69.987654},
                                "accuracy": {"doubleValue": accuracy},
                            }
                        }
                    },
                    "location": {
                        "mapValue": {
                            "fields": {
                                "mock": {"booleanValue": mock},
                                "timestamp": {"stringValue": stamp.isoformat()},
                            }
                        }
                    },
                }
            )
    return {
        "documents": [
            {
                "name": prefix + f"private-child-{index}",
                "updateTime": (now - timedelta(minutes=1)).isoformat(),
                "fields": value,
                "private_unused": PRIVATE,
            }
            for index, value in enumerate(fields)
        ],
        "nextPageToken": "PRIVATE-NEXT-PAGE-DO-NOT-FOLLOW",
    }


@dataclass
class Harness:
    clock: Clock
    database: OperationDatabase
    ledger: SqlAlchemyCostLedger

    def meter(self, *, documents: bool = False, maximum_bytes: int = 1_048_576) -> MeteredReadHttp:
        return MeteredReadHttp(
            ledger=self.ledger,
            attribution=CostAttribution(
                product=ProductScope.MANA,
                source="fixture",
                agent_id="retention-agent",
                capability_key=PARENT_ACTIVITY_CAPABILITY,
            ),
            maximum_response_bytes=maximum_bytes,
            rates=DataRateCard(document_usd_per_100k=Decimal("0.06") if documents else 0),
        )


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncIterator[Harness]:
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'analytics.db'}")
    await database.create_schema()
    clock = Clock(datetime(2026, 10, 12, 10, tzinfo=UTC))
    limits = ResourceUsage(
        provider_requests=10, document_reads=200, response_bytes=20_000_000, data_microusd=2000
    )
    ledger = SqlAlchemyCostLedger(
        database, clock=clock, limits=CostLimits(daily=limits, monthly=limits)
    )
    try:
        yield Harness(clock, database, ledger)
    finally:
        await database.dispose()


async def test_parent_reports_are_independent_scoped_complete_and_minimized(
    harness: Harness,
) -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "analyticsdata.googleapis.com"
        return httpx.Response(200, json=ga4_payload(request))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = Ga4ParentAnalyticsAdapter(
            http=AnalyticsReadHttp(client, Token(), harness.meter()),
            clock=harness.clock,
            property_id="123",
            stream_id=STREAM,
            timezone="Etc/GMT-5",
        )
        facts = await source.collect()
    assert len(requests) == 5
    assert [window.days for window in facts.windows] == [1, 7, 30]
    assert all(cohort.quality == "complete" and len(cohort.days) == 31 for cohort in facts.cohorts)
    assert facts.notification_funnel and facts.notification_funnel.users == (100, 50, 25)
    assert facts.event_counts == {"button_click": 350, "screen_view": 750}
    assert len(facts.breakdowns) == 6 and all(row.quality == "complete" for row in facts.breakdowns)
    assert facts.breakdowns[0].rows[0].measures["engagement_seconds"] == Decimal("125.5")
    assert facts.breakdowns[-1].rows[0].labels == {"date_minute": "202610112354"}
    assert PRIVATE not in facts.model_dump_json() and PRIVATE not in render_analytics(facts)
    assert "не платёж" in render_analytics(facts)
    assert (await harness.ledger.periods())[0].usage.provider_requests == 5
    maximal = []
    for breakdown in facts.breakdowns:
        maximal.append(
            ParentAnalyticsBreakdown(
                kind=breakdown.kind,
                total_groups=10,
                quality="complete",
                rows=[
                    ParentBreakdownRow(
                        labels={
                            name: "x" * (PARENT_LABEL_MAX_LENGTH - 1) + str(index)
                            for name in breakdown.rows[0].labels
                        },
                        measures={name: Decimal("1e18") for name in breakdown.rows[0].measures},
                    )
                    for index in range(10)
                ],
            )
        )
    largest = facts.model_copy(update={"breakdowns": maximal})
    assert len(render_analytics(largest)) <= 32000
    assert "x" * PARENT_LABEL_MAX_LENGTH not in render_analytics(largest)


@pytest.mark.parametrize(
    "failure",
    [
        "foreign_stream",
        "wrong_timezone",
        "fractional_count",
        "missing_metric",
        "unstable_cohort",
        "duplicate_cohort",
        "inconsistent_funnel",
        "inconsistent_repeated_metrics",
    ],
)
async def test_invalid_ga4_contracts_stop_without_retries(harness: Harness, failure: str) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = ga4_payload(request)
        if calls == 1:
            row = payload["reports"][0]
            if failure == "foreign_stream":
                row["rows"][0]["dimensionValues"][0]["value"] = "360"
            if failure == "wrong_timezone":
                row["metadata"]["timeZone"] = "UTC"
            if failure == "fractional_count":
                row["rows"][0]["metricValues"][0]["value"] = "1.5"
            if failure == "missing_metric":
                row["rows"][0]["metricValues"].pop()
        if calls == 2:
            row = payload["reports"][0]
            if failure == "unstable_cohort":
                row["rows"][1]["metricValues"][1]["value"] = "99"
            if failure == "duplicate_cohort":
                row["rows"][1]["dimensionValues"][1]["value"] = "0000"
        if calls == 3:
            table = payload["funnelTable"]
            if failure == "inconsistent_funnel":
                table["rows"][0]["metricValues"][1]["value"] = "0.4"
            if failure == "inconsistent_repeated_metrics":
                values = table["rows"][0]["metricValues"]
                table["rows"][0]["metricValues"] = values + [{"value": "999"}] * 4
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = Ga4ParentAnalyticsAdapter(
            http=AnalyticsReadHttp(client, Token(), harness.meter()),
            clock=harness.clock,
            property_id="123",
            stream_id=STREAM,
            timezone="Etc/GMT-5",
        )
        with pytest.raises(ProviderPermanentError):
            await source.collect()
    assert calls == (
        1
        if failure in {"foreign_stream", "wrong_timezone", "fractional_count", "missing_metric"}
        else 2
        if "cohort" in failure
        else 3
    )
    assert (await harness.ledger.periods())[0].usage.provider_requests == calls


@pytest.mark.parametrize(
    "shape",
    [
        "truncated",
        "not_set",
        "private",
        "long_label",
        "absent",
        "sampled",
        "thresholded",
        "data_loss",
    ],
)
async def test_ga4_dimension_coverage_and_privacy_are_explicit(
    harness: Harness, shape: str
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        payload = ga4_payload(request)
        body = json.loads(request.content)
        first = body.get("requests", [{}])[0]
        if first.get("dimensions", [{}])[1:] == [
            {"name": "unifiedScreenName"},
            {"name": "unifiedScreenClass"},
        ]:
            row = payload["reports"][0]
            if shape == "truncated":
                row["rowCount"] = 20
            elif shape == "not_set":
                row["rows"][0]["dimensionValues"][1]["value"] = "(not set)"
            elif shape == "private":
                row["rows"][0]["dimensionValues"][1]["value"] = "private-parent@example.invalid"
            elif shape == "long_label":
                row["rows"][0]["dimensionValues"][1]["value"] = "L" * 81
            elif shape == "absent":
                row["rows"], row["rowCount"] = [], 0
            elif shape == "sampled":
                row["metadata"]["samplingMetadatas"] = [
                    {"samplesReadCount": "1", "samplingSpaceSize": "100"}
                ]
            elif shape == "thresholded":
                row["metadata"]["subjectToThresholding"] = True
            else:
                row["metadata"]["dataLossFromOtherRow"] = True
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = Ga4ParentAnalyticsAdapter(
            http=AnalyticsReadHttp(client, Token(), harness.meter()),
            clock=harness.clock,
            property_id="123",
            stream_id=STREAM,
            timezone="Etc/GMT-5",
        )
        facts = await source.collect()
    breakdown = facts.breakdowns[0]
    assert breakdown.quality == (
        shape
        if shape in {"sampled", "thresholded"}
        else "missing"
        if shape == "absent"
        else "partial"
    )
    if shape in {"private", "long_label"}:
        assert breakdown.rows == [] and breakdown.withheld_rows == 1
        assert "example.invalid" not in facts.model_dump_json()
    if shape == "not_set":
        assert breakdown.rows[0].labels["screen_name"] is None
    if shape == "truncated":
        assert len(breakdown.rows) == 1 and breakdown.total_groups == 20
    assert (await harness.ledger.periods())[0].usage.provider_requests == 5


@pytest.mark.parametrize(
    "shape",
    [
        "foreign_stream",
        "duplicate_group",
        "negative_metric",
        "bad_hour",
        "future_minute",
        "missing_metric",
    ],
)
async def test_invalid_ga4_dimensions_stop_at_the_known_attempt(
    harness: Harness, shape: str
) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = ga4_payload(request)
        if calls == 4:
            row = payload["reports"][0]
            if shape == "foreign_stream":
                row["rows"][0]["dimensionValues"][0]["value"] = "360"
            if shape == "duplicate_group":
                row["rows"].append(row["rows"][0])
                row["rowCount"] = 2
            if shape == "negative_metric":
                row["rows"][0]["metricValues"][0]["value"] = "-1"
            if shape == "missing_metric":
                row["rows"][0]["metricValues"].pop()
            if shape == "bad_hour":
                payload["reports"][4]["rows"][0]["dimensionValues"][2]["value"] = "24"
        if calls == 5 and shape == "future_minute":
            payload["reports"][0]["rows"][0]["dimensionValues"][1]["value"] = "203701012359"
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = Ga4ParentAnalyticsAdapter(
            http=AnalyticsReadHttp(client, Token(), harness.meter()),
            clock=harness.clock,
            property_id="123",
            stream_id=STREAM,
            timezone="Etc/GMT-5",
        )
        with pytest.raises(ProviderPermanentError):
            await source.collect()
    assert calls == (5 if shape == "future_minute" else 4)


@pytest.mark.parametrize("shape", ["absent", "sampled", "thresholded"])
async def test_missing_and_qualified_cohorts_are_not_zero_retention(
    harness: Harness, shape: str
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        payload = ga4_payload(request)
        body = json.loads(request.content)
        if body.get("requests", [{}])[0].get("cohortSpec"):
            for row in payload["reports"]:
                if shape == "absent":
                    row["rows"], row["rowCount"] = row["rows"][:1], 1
                if shape == "sampled":
                    row["metadata"]["samplingMetadatas"] = [
                        {"samplesReadCount": "10", "samplingSpaceSize": "20"}
                    ]
                if shape == "thresholded":
                    row["metadata"]["subjectToThresholding"] = True
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = Ga4ParentAnalyticsAdapter(
            http=AnalyticsReadHttp(client, Token(), harness.meter()),
            clock=harness.clock,
            property_id="123",
            stream_id=STREAM,
            timezone="Etc/GMT-5",
        )
        facts = await source.collect()
    assert all(cohort.quality != "complete" for cohort in facts.cohorts)
    assert "D1:" not in render_analytics(facts)
    if shape == "absent":
        assert all(len(cohort.days) == 1 for cohort in facts.cohorts)


async def test_child_samples_validate_time_precision_and_never_page_or_keep_gps(
    harness: Harness,
) -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=firestore_payload(request, harness.clock))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = FirestoreChildTelemetryAdapter(
            http=AnalyticsReadHttp(client, Token(), harness.meter(documents=True)),
            clock=harness.clock,
            project_id="fake-project",
        )
        facts = await source.collect()
    assert len(requests) == 2
    battery, gps = facts.samples
    assert (
        battery.sampled_documents,
        battery.valid_observations,
        battery.invalid_observations,
    ) == (4, 2, 2)
    assert battery.low_battery_observations == 2 and battery.unknown_client_timezone == 4
    assert gps.valid_observations == 4 and gps.invalid_observations == 1
    assert gps.precise_location_observations == 1 and gps.future_client_dates == 1
    assert gps.mock_location_observations == 1
    assert all(item.more_documents for item in facts.samples)
    for raw in [PRIVATE, "private-child", "41.123456", "69.987654", "NEXT-PAGE"]:
        assert raw not in facts.model_dump_json() and raw not in render_analytics(facts)
    usage = (await harness.ledger.periods())[0].usage
    assert usage.document_reads == 9 and usage.provider_requests == 2


@pytest.mark.parametrize(
    "kind",
    [
        "timeout",
        "403",
        "oversized",
        "excess_documents",
        "foreign_collection",
        "duplicate",
        "future_server_time",
    ],
)
async def test_firestore_failures_are_one_attempt_and_unknown_usage_stays_reserved(
    harness: Harness, kind: str
) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if kind == "timeout":
            raise httpx.ReadTimeout(PRIVATE, request=request)
        if kind == "403":
            return httpx.Response(403, json={"error": PRIVATE})
        if kind == "oversized":
            return httpx.Response(200, content=b"x" * 4096)
        payload = firestore_payload(request, harness.clock)
        if kind == "excess_documents":
            payload["documents"] = payload["documents"] * 30
        if kind == "foreign_collection":
            payload["documents"][0]["name"] = (
                "projects/other/databases/(default)/documents/users/private"
            )
        if kind == "duplicate":
            payload["documents"][1] = payload["documents"][0]
        if kind == "future_server_time":
            payload["documents"][0]["updateTime"] = "2037-01-01T00:00:00Z"
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = FirestoreChildTelemetryAdapter(
            http=AnalyticsReadHttp(
                client,
                Token(),
                harness.meter(
                    documents=True, maximum_bytes=2048 if kind == "oversized" else 1_048_576
                ),
            ),
            clock=harness.clock,
            project_id="fake-project",
        )
        with pytest.raises(
            ProviderPermanentError if kind != "timeout" else ProviderTransientError
        ) as error:
            await source.collect()
    assert calls == 1 and PRIVATE not in str(error.value)
    usage = (await harness.ledger.periods())[0].usage
    assert usage.provider_requests == 1
    if kind in {"timeout", "403", "oversized"}:
        assert usage.document_reads == 100
    if kind == "excess_documents":
        assert usage.document_reads == 120


async def test_budget_is_admitted_before_http(harness: Harness) -> None:
    await harness.ledger.reserve(
        ResourceUsage(provider_requests=10),
        attribution=CostAttribution(
            product=ProductScope.MANA,
            source="fixture",
            agent_id="retention-agent",
            capability_key=PARENT_ACTIVITY_CAPABILITY,
        ),
    )

    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Exhausted source budget must not dispatch HTTP")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(CostBudgetExceeded):
            await FirestoreChildTelemetryAdapter(
                http=AnalyticsReadHttp(client, Token(), harness.meter(documents=True)),
                clock=harness.clock,
                project_id="fake-project",
            ).collect()


@pytest.mark.parametrize(
    "flag", ["operation_parent_analytics_enabled", "operation_child_telemetry_enabled"]
)
def test_manual_sources_require_explicit_readable_approved_bindings(flag: str) -> None:
    with pytest.raises(ValueError, match="requires an approved"):
        Settings(
            _env_file=None,
            openai_api_key="fake-test-key",
            mana_telegram_auth_enabled=False,
            **cast(dict[str, Any], {flag: True}),
        )


def test_defaults_are_disabled_and_unknown_timezone_is_rejected() -> None:
    settings = Settings(
        _env_file=None, openai_api_key="fake-test-key", mana_telegram_auth_enabled=False
    )
    assert (
        not settings.operation_parent_analytics_enabled
        and not settings.operation_child_telemetry_enabled
    )
    with pytest.raises(ValueError, match="explicit IANA"):
        Settings(
            _env_file=None,
            openai_api_key="fake-test-key",
            mana_telegram_auth_enabled=False,
            ga4_parent_property_timezone="Not/A-Timezone",
        )
