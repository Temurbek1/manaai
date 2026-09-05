import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx

from app.mana_operation_ai.application.runtime import SystemClock
from app.mana_operation_ai.domain.enums import ActivityEventType, IntegrationStatus
from app.mana_operation_ai.infrastructure.retention.firestore import (
    FirestoreMobileActivityAdapter,
)
from app.mana_operation_ai.infrastructure.retention.manakids import (
    ManakidsAdminActivityAdapter,
)


class StaticTokenProvider:
    async def access_token(self) -> str:
        return "firebase-test-token"


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
        elif request.url.path.endswith("/admin-panel-child/child-list/"):
            count = 120
        elif request.url.path.endswith("/admin-panel-child/app-usage-statistics/"):
            count = 81
        elif request.url.path.endswith("/admin-panel-child/camera-audio-usage-logs/"):
            count = 32
        else:
            raise AssertionError(f"Unexpected request path {request.url.path}")
        return httpx.Response(
            200,
            headers={"x-request-id": f"request-{len(observed)}"},
            json={
                "count": count,
                "results": [
                    {
                        "id": "raw-child-id",
                        "fullname": "Must Not Persist",
                        "parent_phone": "+998000000000",
                    },
                ],
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
    assert facts.children_with_app_usage == 81
    assert facts.children_with_realtime_feature_usage == 32
    serialized = facts.model_dump_json()
    assert "Must Not Persist" not in serialized
    assert "+998000000000" not in serialized
    assert "raw-child-id" not in serialized
    assert sum(path.endswith("/admin-panel-auth/login/") for _, path, _ in observed) == 1
    account_queries = [query for _, path, query in observed if path.endswith("/account/")]
    assert {query["role"] for query in account_queries} == {"PARENT", "CHILD"}


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


async def test_manakids_adapter_bounds_unpaginated_activity_responses() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/admin-panel-auth/login/"):
            return httpx.Response(200, json={"access": "admin-token"})
        if request.url.path.endswith("/admin-panel-common/account/"):
            return httpx.Response(200, json={"count": 1, "results": []})
        if request.url.path.endswith("/admin-panel-child/child-list/"):
            return httpx.Response(200, json={"count": 50, "results": []})
        page = int(request.url.params["page"])
        row_count = 3 if request.url.path.endswith("/app-usage-statistics/") and page == 2 else 10
        return httpx.Response(200, json={"results": [{"id": index} for index in range(row_count)]})

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
    assert facts.completeness == Decimal("0.75")
    assert any("page limit" in limitation for limitation in facts.limitations)


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
