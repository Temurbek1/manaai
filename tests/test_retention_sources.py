import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx

from app.mana_operation_ai.application.runtime import SystemClock
from app.mana_operation_ai.domain.enums import ActivityEventType, IntegrationStatus
from app.mana_operation_ai.infrastructure.retention.firestore import (
    FirestoreMobileActivityAdapter,
)
from app.mana_operation_ai.infrastructure.retention.firestore_operational import (
    FirestoreOperationalTelemetryAdapter,
)
from app.mana_operation_ai.infrastructure.retention.ga4 import Ga4MobileActivityAdapter
from app.mana_operation_ai.infrastructure.retention.manakids import (
    ManakidsAdminActivityAdapter,
)
from app.mana_operation_ai.infrastructure.retention.unavailable import (
    UnavailableMobileActivityAdapter,
)


class StaticTokenProvider:
    async def access_token(self) -> str:
        return "firebase-test-token"


async def test_ga4_adapter_collects_real_aggregate_product_analytics_without_identifiers() -> None:
    observed: list[dict[str, object]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer firebase-test-token"
        body = json.loads(request.content)
        observed.append(body)
        dimensions = [item["name"] for item in body.get("dimensions", [])]
        metrics = [item["name"] for item in body["metrics"]]
        if dimensions == ["eventName"]:
            event_rows = [
                ("screen_view", "976291"),
                ("button_click", "187922"),
                ("session_start", "159526"),
                ("first_open", "35887"),
                ("app_exception", "2944340"),
                ("notification_receive", "358521"),
                ("unknown_provider_event", "99"),
            ]
            return httpx.Response(
                200,
                headers={"x-request-id": "ga4-events"},
                json={
                    "dimensionHeaders": [{"name": "eventName"}],
                    "metricHeaders": [{"name": "eventCount", "type": "TYPE_INTEGER"}],
                    "rows": [
                        {
                            "dimensionValues": [{"value": event_name}],
                            "metricValues": [{"value": count}],
                        }
                        for event_name, count in event_rows
                    ],
                    "rowCount": len(event_rows),
                },
            )
        if dimensions:
            dimension = dimensions[0]
            values = {
                "unifiedScreenName": "Home Screen",
                "appVersion": "1.1.88",
                "operatingSystemWithVersion": "Android 15",
                "mobileDeviceBranding": "Samsung",
                "mobileDeviceModel": "SM-A556E",
                "language": "uz-uz",
                "country": "Uzbekistan",
                "region": "Tashkent Region",
                "city": "Tashkent",
            }
            metric = metrics[0]
            return httpx.Response(
                200,
                headers={"x-request-id": f"ga4-{dimension}"},
                json={
                    "dimensionHeaders": [{"name": dimension}],
                    "metricHeaders": [{"name": metric, "type": "TYPE_INTEGER"}],
                    "rows": [
                        {
                            "dimensionValues": [{"value": values[dimension]}],
                            "metricValues": [{"value": "42"}],
                        },
                    ],
                    "rowCount": 1,
                },
            )
        if len(metrics) > 1:
            values = {
                "activeUsers": "38007",
                "sessions": "159526",
                "engagedSessions": "120000",
                "newUsers": "35887",
                "userEngagementDuration": "1460000.5",
            }
        else:
            date_range = body["dateRanges"][0]
            start = datetime.fromisoformat(date_range["startDate"])
            end = datetime.fromisoformat(date_range["endDate"])
            days = (end - start).days + 1
            values = {"activeUsers": str({1: 4800, 7: 27000, 30: 46000}[days])}
        return httpx.Response(
            200,
            headers={"x-request-id": f"ga4-summary-{len(observed)}"},
            json={
                "metricHeaders": [{"name": metric, "type": "TYPE_INTEGER"} for metric in metrics],
                "rows": [
                    {"metricValues": [{"value": values[metric]} for metric in metrics]},
                ],
                "rowCount": 1,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = Ga4MobileActivityAdapter(
            client=client,
            property_id="123456789",
            token_provider=StaticTokenProvider(),
            clock=SystemClock(),
            api_base_url="https://analyticsdata.googleapis.test/v1beta",
            dimension_limit=50,
            max_concurrency=5,
            max_retries=0,
            retry_backoff_seconds=0.01,
        )
        facts = await adapter.collect_activity(
            period_start=datetime(2026, 8, 26, tzinfo=UTC),
            period_end=datetime(2026, 9, 25, tzinfo=UTC),
        )

    assert facts.event_counts[ActivityEventType.SCREEN_VIEW] == 976_291
    assert facts.event_counts[ActivityEventType.BUTTON_CLICK] == 187_922
    assert facts.event_counts[ActivityEventType.APP_EXCEPTION] == 2_944_340
    assert facts.event_counts[ActivityEventType.NOTIFICATION_RECEIVE] == 358_521
    assert facts.active_subjects == 38_007
    assert facts.active_users_by_window == {"1d": 4_800, "7d": 27_000, "30d": 46_000}
    assert facts.sessions == 159_526
    assert facts.engaged_sessions == 120_000
    assert facts.new_users == 35_887
    assert facts.screen_time_seconds == 1_460_000
    assert facts.dimension_counts["screen_views"] == {"home_screen": 42}
    assert facts.dimension_counts["app_versions"] == {"v_1.1.88": 42}
    assert facts.dimension_counts["device_models"] == {"sm-a556e": 42}
    assert facts.dimension_counts["regions"] == {"tashkent_region": 42}
    serialized = facts.model_dump_json()
    assert "user_id" not in serialized
    assert "session_id" not in serialized
    assert "unknown_provider_event" not in serialized
    assert len(observed) == 14


async def test_ga4_health_retries_throttling_without_leaking_provider_body() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": "secret-provider-detail"})
        return httpx.Response(
            200,
            headers={"x-request-id": "ga4-health"},
            json={
                "metricHeaders": [{"name": "activeUsers", "type": "TYPE_INTEGER"}],
                "rows": [{"metricValues": [{"value": "1"}]}],
                "rowCount": 1,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = Ga4MobileActivityAdapter(
            client=client,
            property_id="123456789",
            token_provider=StaticTokenProvider(),
            clock=SystemClock(),
            api_base_url="https://analyticsdata.googleapis.test/v1beta",
            dimension_limit=50,
            max_concurrency=5,
            max_retries=1,
            retry_backoff_seconds=0.001,
        )
        health = await adapter.health()

    assert attempts == 2
    assert health.status is IntegrationStatus.HEALTHY
    assert health.provider_request_id == "ga4-health"
    assert "secret-provider-detail" not in health.model_dump_json()


async def test_firestore_operational_adapter_aggregates_and_discards_sensitive_fields() -> None:
    def value(raw: object) -> dict[str, object]:
        if isinstance(raw, bool):
            return {"booleanValue": raw}
        if isinstance(raw, int):
            return {"integerValue": str(raw)}
        if isinstance(raw, float):
            return {"doubleValue": raw}
        if isinstance(raw, dict):
            return {
                "mapValue": {
                    "fields": {key: value(item) for key, item in raw.items()},
                },
            }
        return {"stringValue": str(raw)}

    def document(collection: str, document_id: str, fields: dict[str, object]) -> dict[str, object]:
        return {
            "name": (f"projects/test/databases/(default)/documents/{collection}/{document_id}"),
            "fields": {key: value(item) for key, item in fields.items()},
        }

    collections = {
        "battery": [
            document(
                "battery",
                "private-device-1",
                {"childId": 11, "percent": "55", "is_silent": True},
            ),
            document(
                "battery",
                "private-device-2",
                {"childId": 12, "percent": "", "is_silent": False},
            ),
        ],
        "children_location": [
            document(
                "children_location",
                "private-device-1",
                {
                    "activity": {"type": "still"},
                    "coords": {"latitude": 41.2, "longitude": 69.1, "speed": 0},
                },
            ),
            document(
                "children_location",
                "private-device-2",
                {
                    "activity": {"type": "walking"},
                    "coords": {"latitude": 40.7, "longitude": 72.3, "speed": 1.2},
                },
            ),
        ],
        "internet": [
            document("internet", "private-device-1", {"childId": 11}),
            document("internet", "private-device-2", {"childId": 12}),
        ],
        "monitoring": [
            document("monitoring", "private-device-1", {"enabled": True}),
            document("monitoring", "private-device-2", {"enabled": False}),
        ],
        "screen-commands": [
            document("screen-commands", "private-device-1", {"command": "start"}),
            document("screen-commands", "private-device-2", {"command": "STOP"}),
        ],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer firebase-test-token"
        collection = request.url.path.rsplit("/", 1)[-1]
        masks = request.url.params.get_list("mask.fieldPaths")
        assert "coords.latitude" not in masks
        assert "coords.longitude" not in masks
        if collection == "children_location":
            assert masks == ["childId", "activity.type", "coords.speed"]
        return httpx.Response(
            200,
            headers={"x-request-id": f"firestore-{collection}"},
            json={"documents": collections[collection]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = FirestoreOperationalTelemetryAdapter(
            client=client,
            project_id="bosstracker-dev",
            database_id="(default)",
            token_provider=StaticTokenProvider(),
            clock=SystemClock(),
            max_documents_per_collection=100,
            max_retries=0,
            retry_backoff_seconds=0.01,
        )
        facts = await adapter.collect_telemetry()

    assert facts.battery_devices == 2
    assert facts.battery_percent_available == 1
    assert facts.silent_devices == 1
    assert facts.located_devices == 2
    assert facts.moving_devices == 1
    assert facts.internet_records == 2
    assert facts.monitoring_enabled == 1
    assert facts.monitoring_disabled == 1
    assert facts.screen_command_counts == {"start": 1, "stop": 1}
    assert facts.documents_scanned == 10
    serialized = facts.model_dump_json()
    for forbidden in ("private-device", "latitude", "longitude", "41.2", "69.1"):
        assert forbidden not in serialized


async def test_firestore_operational_adapter_supports_explicit_public_reads() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"documents": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = FirestoreOperationalTelemetryAdapter(
            client=client,
            project_id="bosstracker-dev",
            database_id="(default)",
            token_provider=None,
            clock=SystemClock(),
            max_documents_per_collection=100,
            max_retries=0,
            retry_backoff_seconds=0.01,
        )
        facts = await adapter.collect_telemetry()
        health = await adapter.health()

    assert facts.documents_scanned == 0
    assert any("public project rules" in item for item in facts.limitations)
    assert health.status is IntegrationStatus.HEALTHY
    assert health.diagnostics["authentication"] == "public_rules"


async def test_unavailable_mobile_adapter_never_invents_activity() -> None:
    adapter = UnavailableMobileActivityAdapter(clock=SystemClock())
    period_end = datetime(2026, 9, 5, 12, tzinfo=UTC)
    facts = await adapter.collect_activity(
        period_start=period_end - timedelta(days=1),
        period_end=period_end,
    )
    health = await adapter.health()

    assert facts.event_counts == {}
    assert facts.active_subjects == 0
    assert facts.sessions == 0
    assert facts.completeness == Decimal("0")
    assert any("unavailable data" in item for item in facts.limitations)
    assert health.status is IntegrationStatus.UNCONFIGURED
    assert health.diagnostics["synthetic_data"] is False


async def test_manakids_adapter_translates_documented_endpoints_to_aggregates() -> None:
    observed: list[tuple[str, str, dict[str, str]]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        query = dict(request.url.params)
        observed.append((request.method, request.url.path, query))
        if request.url.path.endswith("/admin-panel-auth/login/"):
            assert json.loads(request.content) == {
                "username": "service-user",
                "password": "test-password-fixture",
            }
            return httpx.Response(200, json={"access": "admin-token"})
        assert request.headers["Authorization"] == "Bearer admin-token"
        if request.url.path.endswith("/admin-panel-common/account/"):
            count = 13 if query.get("role") == "PARENT" else 17
            return httpx.Response(
                200,
                headers={"x-request-id": f"request-{len(observed)}"},
                json={"count": count, "results": []},
            )
        elif request.url.path.endswith("/admin-panel-child/child-list/"):
            return httpx.Response(
                200,
                headers={"x-request-id": f"request-{len(observed)}"},
                json={"count": 120, "results": []},
            )
        elif request.url.path.endswith("/admin-panel-child/app-usage-statistics/"):
            results: list[dict[str, object]] = [
                {
                    "id": "private-child-1",
                    "fullname": "Must Not Persist",
                    "app_usage_statistics": {
                        "total_count": 4,
                        "results": [{"application": "private-app-usage"}],
                    },
                },
                {
                    "id": "private-child-2",
                    "app_usage_statistics": {"total_count": 2, "results": []},
                },
                {
                    "id": "private-child-3",
                    "app_usage_statistics": {"total_count": 0, "results": []},
                },
            ]
        elif request.url.path.endswith("/admin-panel-child/camera-audio-usage-logs/"):
            results = [
                {
                    "id": "private-child-1",
                    "camera_audio_usage_logs": [{"kind": "private-camera-log"}],
                },
                {"id": "private-child-2", "camera_audio_usage_logs": []},
            ]
        else:
            raise AssertionError(f"Unexpected request path {request.url.path}")
        return httpx.Response(
            200,
            headers={"x-request-id": f"request-{len(observed)}"},
            json={
                "success": True,
                "total_count": len(results),
                "current_page": 1,
                "page_count": 1,
                "per_page": 10,
                "results": results,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ManakidsAdminActivityAdapter(
            client=client,
            base_url="https://api.manakids.test",
            username="service-user",
            password="test-password-fixture",
            clock=SystemClock(),
            max_retries=0,
            retry_backoff_seconds=0.01,
            max_pages=10,
        )
        period_end = datetime(2026, 9, 5, 12, tzinfo=UTC)
        facts = await adapter.collect_activity(
            period_start=period_end - timedelta(days=7),
            period_end=period_end,
        )

    assert facts.parent_accounts_joined == 13
    assert facts.child_accounts_joined == 17
    assert facts.total_children == 120
    assert facts.children_with_app_usage == 2
    assert facts.children_with_realtime_feature_usage == 1
    assert facts.completeness == Decimal("1")
    serialized = facts.model_dump_json()
    assert "Must Not Persist" not in serialized
    assert "private-child" not in serialized
    assert "private-app-usage" not in serialized
    assert "private-camera-log" not in serialized
    assert sum(path.endswith("/admin-panel-auth/login/") for _, path, _ in observed) == 1
    account_queries = [query for _, path, query in observed if path.endswith("/account/")]
    assert {query["role"] for query in account_queries} == {"PARENT", "CHILD"}
    assert {query["date_joined_gte"] for query in account_queries} == {"2026-08-29"}
    assert {query["date_joined_lt"] for query in account_queries} == {"2026-09-06"}


async def test_manakids_health_sanitizes_failed_authentication() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/admin-panel-auth/login/")
        return httpx.Response(400, json={"password": "[REDACTED]"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ManakidsAdminActivityAdapter(
            client=client,
            base_url="https://api.manakids.test",
            username="service-user",
            password="test-password-fixture",
            clock=SystemClock(),
            max_retries=0,
            retry_backoff_seconds=0.01,
            max_pages=10,
        )
        health = await adapter.health()

    assert health.status is IntegrationStatus.UNHEALTHY
    assert health.message is not None
    assert "secret" not in health.message
    assert "test-password-fixture" not in health.message


async def test_manakids_adapter_reports_bounded_activity_scan_coverage() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/admin-panel-auth/login/"):
            return httpx.Response(200, json={"access": "admin-token"})
        if request.url.path.endswith("/admin-panel-common/account/"):
            return httpx.Response(200, json={"count": 1, "results": []})
        if request.url.path.endswith("/admin-panel-child/child-list/"):
            return httpx.Response(200, json={"count": 50, "results": []})
        page = int(request.url.params["page"])
        is_app_usage = request.url.path.endswith("/app-usage-statistics/")
        row_count = 3 if is_app_usage and page == 2 else 10
        if is_app_usage:
            results = [
                {
                    "id": index,
                    "app_usage_statistics": {
                        "total_count": 1,
                        "results": [{"event": "fixture"}],
                    },
                }
                for index in range(row_count)
            ]
            total_count = 13
            page_count = 2
        else:
            results = [
                {"id": index, "camera_audio_usage_logs": [{"event": "fixture"}]}
                for index in range(row_count)
            ]
            total_count = 25
            page_count = 3
        return httpx.Response(
            200,
            json={
                "total_count": total_count,
                "current_page": page,
                "page_count": page_count,
                "per_page": 10,
                "results": results,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = ManakidsAdminActivityAdapter(
            client=client,
            base_url="https://api.manakids.test",
            username="service-user",
            password="test-password-fixture",
            clock=SystemClock(),
            max_retries=0,
            retry_backoff_seconds=0.01,
            max_pages=2,
        )
        period_end = datetime(2026, 9, 5, 12, tzinfo=UTC)
        facts = await adapter.collect_activity(
            period_start=period_end - timedelta(days=7),
            period_end=period_end,
        )

    assert facts.children_with_app_usage == 13
    assert facts.children_with_realtime_feature_usage == 20
    assert facts.completeness == Decimal("0.8")
    assert any("20 of 25" in limitation for limitation in facts.limitations)
    assert any("not an extrapolated global count" in item for item in facts.limitations)


async def test_firestore_adapter_aggregates_and_discards_mobile_identifiers() -> None:
    period_start = datetime(2026, 9, 1, tzinfo=UTC)
    period_end = datetime(2026, 9, 6, tzinfo=UTC)
    observed_query: dict[str, object] = {}

    def document(
        event_type: str,
        *,
        occurred_at: str = "2026-09-03T10:00:00Z",
        duration_ms: int = 0,
    ) -> dict[str, object]:
        return {
            "document": {
                "name": "projects/test/databases/(default)/documents/app_activity_events/id",
                "fields": {
                    "schema_version": {"stringValue": "app-activity-v1"},
                    "subject_id": {"stringValue": "private-child-id"},
                    "session_id": {"stringValue": "private-session-id"},
                    "event_type": {"stringValue": event_type},
                    "occurred_at": {"timestampValue": occurred_at},
                    "duration_ms": {"integerValue": str(duration_ms)},
                    "sequence_number": {"integerValue": "1"},
                    "screen": {"stringValue": "dashboard"},
                    "previous_screen": {"stringValue": "login"},
                    "button": {"stringValue": "open_dashboard"},
                    "feature": {"stringValue": "app_usage"},
                    "form": {"stringValue": "registration"},
                    "file_type": {"stringValue": "image"},
                    "query_length": {"integerValue": "12"},
                    "filter_count": {"integerValue": "2"},
                    "sort_used": {"booleanValue": True},
                    "search_query": {"stringValue": "raw search must be discarded"},
                },
            },
            "readTime": "2026-09-05T12:00:00Z",
        }

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer firebase-test-token"
        if request.method == "GET":
            return httpx.Response(200, headers={"x-request-id": "firebase-health"}, json={})
        observed_query.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"x-guploader-uploadid": "firebase-query-1"},
            json=[
                document("app_open"),
                document("screen_time", duration_ms=2_500),
                document("screen_view"),
                document("button_click"),
                document("search"),
                document("navigation"),
                document("form_completed"),
                document("file_uploaded"),
                document("feature_used"),
                document("unknown_event"),
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = FirestoreMobileActivityAdapter(
            client=client,
            project_id="bosstracker-dev",
            database_id="(default)",
            collection_id="app_activity_events",
            token_provider=StaticTokenProvider(),
            clock=SystemClock(),
            max_documents=100,
            max_retries=0,
            retry_backoff_seconds=0.01,
        )
        facts = await adapter.collect_activity(
            period_start=period_start,
            period_end=period_end,
        )
        health = await adapter.health()

    assert facts.event_counts[ActivityEventType.APP_OPEN] == 1
    assert facts.event_counts[ActivityEventType.SCREEN_TIME] == 1
    assert facts.active_subjects == 1
    assert facts.sessions == 1
    assert facts.screen_time_seconds == 2
    assert facts.dimension_counts["screen_time_seconds_by_screen"] == {"dashboard": 2}
    assert facts.sequence_counts["app_open>screen_time"] == 1
    assert facts.dimension_counts["screen_views"] == {"dashboard": 1}
    assert facts.dimension_counts["button_clicks"] == {"open_dashboard": 1}
    assert facts.dimension_counts["feature_uses"] == {"app_usage": 1}
    assert facts.dimension_counts["navigation"] == {"login>dashboard": 1}
    assert facts.dimension_counts["forms_completed"] == {"registration": 1}
    assert facts.dimension_counts["uploads_by_type"] == {"image": 1}
    assert facts.dimension_counts["search_usage"] == {
        "with_filters": 1,
        "with_query": 1,
        "with_sort": 1,
    }
    assert facts.documents_scanned == 10
    assert facts.invalid_documents == 1
    assert facts.completeness == Decimal("0.9")
    serialized = facts.model_dump_json()
    assert "private-child-id" not in serialized
    assert "private-session-id" not in serialized
    assert "raw search" not in serialized
    assert health.status is IntegrationStatus.HEALTHY
    query = observed_query["structuredQuery"]
    assert isinstance(query, dict)
    assert query["from"] == [{"collectionId": "app_activity_events"}]
