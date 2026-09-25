import asyncio
import hashlib
import re
import time
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import httpx

from app.mana_operation_ai.application.ports import (
    Clock,
    ProviderPermanentError,
    ProviderTransientError,
)
from app.mana_operation_ai.domain.enums import ActivityEventType, IntegrationStatus
from app.mana_operation_ai.domain.models import IntegrationHealth
from app.mana_operation_ai.domain.retention import MobileActivityFacts
from app.mana_operation_ai.infrastructure.google_auth import GoogleAccessTokenProvider

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_DIMENSION_REPORTS: tuple[tuple[str, str, str], ...] = (
    ("unifiedScreenName", "screenPageViews", "screen_views"),
    ("appVersion", "activeUsers", "app_versions"),
    ("operatingSystemWithVersion", "activeUsers", "operating_system_versions"),
    ("mobileDeviceBranding", "activeUsers", "device_brands"),
    ("mobileDeviceModel", "activeUsers", "device_models"),
    ("language", "activeUsers", "languages"),
    ("country", "activeUsers", "countries"),
    ("region", "activeUsers", "regions"),
    ("city", "activeUsers", "cities"),
)


class Ga4MobileActivityAdapter:
    """Read privacy-minimized aggregate mobile analytics through the GA4 Data API."""

    integration_id = "google_analytics_4"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        property_id: str,
        token_provider: GoogleAccessTokenProvider,
        clock: Clock,
        api_base_url: str,
        dimension_limit: int,
        max_concurrency: int,
        max_retries: int,
        retry_backoff_seconds: float,
    ) -> None:
        self._client = client
        self._property_id = property_id
        self._token_provider = token_provider
        self._clock = clock
        self._api_base_url = api_base_url.rstrip("/")
        self._dimension_limit = dimension_limit
        self._request_semaphore = asyncio.Semaphore(max_concurrency)
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._run_report_url = f"{self._api_base_url}/properties/{self._property_id}:runReport"

    async def collect_activity(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> MobileActivityFacts:
        if period_end <= period_start:
            raise ValueError("Activity period end must be after its start")
        start_date, end_date = _inclusive_date_range(period_start, period_end)
        summary_task = self._run_report(
            start_date=start_date,
            end_date=end_date,
            metrics=[
                "activeUsers",
                "sessions",
                "engagedSessions",
                "newUsers",
                "userEngagementDuration",
            ],
        )
        events_task = self._run_report(
            start_date=start_date,
            end_date=end_date,
            dimensions=["eventName"],
            metrics=["eventCount"],
            limit=1_000,
        )
        active_window_tasks = [
            self._active_users_for_window(period_end=period_end, days=days) for days in (1, 7, 30)
        ]
        dimension_tasks = [
            self._run_report(
                start_date=start_date,
                end_date=end_date,
                dimensions=[dimension],
                metrics=[metric],
                limit=self._dimension_limit,
                order_by_metric=metric,
            )
            for dimension, metric, _ in _DIMENSION_REPORTS
        ]
        responses = await asyncio.gather(
            summary_task,
            events_task,
            *active_window_tasks,
            *dimension_tasks,
        )
        summary, events = responses[:2]
        active_windows = responses[2:5]
        dimension_responses = responses[5:]

        summary_metrics = _single_metric_row(summary.payload)
        event_counts = {event_type: 0 for event_type in ActivityEventType}
        for dimensions, metrics in _report_rows(events.payload):
            event_name = dimensions.get("eventName")
            if event_name is None:
                continue
            try:
                event_type = ActivityEventType(event_name)
            except ValueError:
                continue
            event_counts[event_type] = _metric_int(metrics, "eventCount")

        dimension_counts: dict[str, dict[str, int]] = {}
        limitations: list[str] = []
        completeness = Decimal("1")
        for (_, metric_name, category), response in zip(
            _DIMENSION_REPORTS,
            dimension_responses,
            strict=True,
        ):
            counts: dict[str, int] = {}
            for dimensions, metrics in _report_rows(response.payload):
                raw_value = next(iter(dimensions.values()), None)
                if raw_value is None or raw_value in {"", "(not set)"}:
                    continue
                value = _safe_dimension_value(raw_value)
                counts[value] = counts.get(value, 0) + _metric_int(metrics, metric_name)
            if counts:
                dimension_counts[category] = dict(sorted(counts.items()))
            if _report_is_truncated(response.payload, self._dimension_limit):
                completeness = min(completeness, Decimal("0.99"))
                limitations.append(
                    f"GA4 {category} retains only the top {self._dimension_limit} values.",
                )

        active_users_by_window: dict[Literal["1d", "7d", "30d"], int] = {}
        windows: tuple[tuple[int, Literal["1d", "7d", "30d"]], ...] = (
            (1, "1d"),
            (7, "7d"),
            (30, "30d"),
        )
        for (_, window), response in zip(windows, active_windows, strict=True):
            active_users_by_window[window] = _metric_int(
                _single_metric_row(response.payload),
                "activeUsers",
            )
        request_ids = _unique_nonempty(
            [response.request_id for response in responses if response.request_id],
        )
        return MobileActivityFacts(
            source=self.integration_id,
            period_start=period_start,
            period_end=period_end,
            collected_at=self._clock.now(),
            event_counts=event_counts,
            dimension_counts=dimension_counts,
            sequence_counts={},
            active_subjects=_metric_int(summary_metrics, "activeUsers"),
            active_users_by_window=active_users_by_window,
            sessions=_metric_int(summary_metrics, "sessions"),
            engaged_sessions=_metric_int(summary_metrics, "engagedSessions"),
            new_users=_metric_int(summary_metrics, "newUsers"),
            screen_time_seconds=_metric_int(summary_metrics, "userEngagementDuration"),
            documents_scanned=len(_report_rows(events.payload)),
            invalid_documents=0,
            completeness=completeness,
            source_request_ids=request_ids,
            limitations=[
                "GA4 provides aggregate analytics; raw user identifiers and individual timelines "
                "are deliberately not collected by Operation AI.",
                "Action sequences require an approved GA4 BigQuery export and are unavailable "
                "through this aggregate adapter.",
                *limitations,
            ],
        )

    async def health(self) -> IntegrationHealth:
        started = time.monotonic()
        checked_at = self._clock.now()
        day = checked_at.astimezone(UTC).date().isoformat()
        try:
            response = await self._run_report(
                start_date=day,
                end_date=day,
                metrics=["activeUsers"],
            )
        except (ProviderPermanentError, ProviderTransientError) as exc:
            return IntegrationHealth(
                integration_id=self.integration_id,
                status=IntegrationStatus.UNHEALTHY,
                checked_at=checked_at,
                latency_ms=_latency_ms(started),
                message=f"GA4 aggregate read check failed ({type(exc).__name__})",
                diagnostics={"mode": "live_read_only"},
            )
        return IntegrationHealth(
            integration_id=self.integration_id,
            status=IntegrationStatus.HEALTHY,
            checked_at=checked_at,
            last_success_at=self._clock.now(),
            latency_ms=_latency_ms(started),
            message="GA4 aggregate read access is healthy",
            provider_request_id=response.request_id,
            diagnostics={"mode": "live_read_only", "property_id": self._property_id},
        )

    async def _active_users_for_window(
        self,
        *,
        period_end: datetime,
        days: int,
    ) -> "_Ga4Response":
        end_date = period_end.astimezone(UTC).date()
        start_date = end_date - timedelta(days=days - 1)
        return await self._run_report(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            metrics=["activeUsers"],
        )

    async def _run_report(
        self,
        *,
        start_date: str,
        end_date: str,
        metrics: list[str],
        dimensions: list[str] | None = None,
        limit: int | None = None,
        order_by_metric: str | None = None,
    ) -> "_Ga4Response":
        body: dict[str, Any] = {
            "dateRanges": [{"startDate": start_date, "endDate": end_date}],
            "metrics": [{"name": item} for item in metrics],
            "keepEmptyRows": False,
            "returnPropertyQuota": True,
        }
        if dimensions:
            body["dimensions"] = [{"name": item} for item in dimensions]
        if limit is not None:
            body["limit"] = str(limit)
        if order_by_metric is not None:
            body["orderBys"] = [
                {"metric": {"metricName": order_by_metric}, "desc": True},
            ]
        response = await self._request(body)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderPermanentError("GA4 returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise ProviderPermanentError("GA4 returned a non-object report")
        request_id = response.headers.get("x-request-id") or response.headers.get(
            "x-guploader-uploadid",
        )
        return _Ga4Response(payload=payload, request_id=request_id)

    async def _request(self, body: dict[str, Any]) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            token = await self._token_provider.access_token()
            try:
                async with self._request_semaphore:
                    response = await self._client.post(
                        self._run_report_url,
                        headers={"Authorization": f"Bearer {token}"},
                        json=body,
                    )
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise ProviderTransientError("GA4 request failed") from exc
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
                continue
            if response.status_code < 400:
                return response
            if response.status_code in _RETRYABLE_STATUSES:
                if attempt >= self._max_retries:
                    raise ProviderTransientError(
                        f"GA4 request failed with status {response.status_code}",
                    )
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
                continue
            raise ProviderPermanentError(
                f"GA4 request was rejected with status {response.status_code}",
            )
        raise AssertionError("GA4 retry loop exited unexpectedly")


class _Ga4Response:
    def __init__(self, *, payload: Mapping[str, Any], request_id: str | None) -> None:
        self.payload = payload
        self.request_id = request_id


def _inclusive_date_range(period_start: datetime, period_end: datetime) -> tuple[str, str]:
    start = period_start.astimezone(UTC).date()
    exclusive_end = period_end.astimezone(UTC)
    inclusive_end = (exclusive_end - timedelta(microseconds=1)).date()
    return start.isoformat(), inclusive_end.isoformat()


def _report_rows(
    payload: Mapping[str, Any],
) -> list[tuple[dict[str, str], dict[str, str]]]:
    raw_dimension_headers = payload.get("dimensionHeaders", [])
    raw_metric_headers = payload.get("metricHeaders", [])
    raw_rows = payload.get("rows", [])
    if not isinstance(raw_dimension_headers, list) or not isinstance(raw_metric_headers, list):
        raise ProviderPermanentError("GA4 report headers are invalid")
    if not isinstance(raw_rows, list):
        raise ProviderPermanentError("GA4 report rows are invalid")
    dimension_headers: list[str] = []
    for item in raw_dimension_headers:
        if isinstance(item, Mapping) and isinstance(item.get("name"), str):
            dimension_headers.append(item["name"])
    metric_headers: list[str] = []
    for item in raw_metric_headers:
        if isinstance(item, Mapping) and isinstance(item.get("name"), str):
            metric_headers.append(item["name"])
    parsed: list[tuple[dict[str, str], dict[str, str]]] = []
    for row in raw_rows:
        if not isinstance(row, Mapping):
            continue
        dimensions = _values_by_header(dimension_headers, row.get("dimensionValues", []))
        metrics = _values_by_header(metric_headers, row.get("metricValues", []))
        parsed.append((dimensions, metrics))
    return parsed


def _values_by_header(headers: list[str], values: object) -> dict[str, str]:
    if not isinstance(values, list):
        return {}
    result: dict[str, str] = {}
    for header, value in zip(headers, values, strict=False):
        if isinstance(value, Mapping) and isinstance(value.get("value"), str):
            result[header] = value["value"]
    return result


def _single_metric_row(payload: Mapping[str, Any]) -> dict[str, str]:
    rows = _report_rows(payload)
    return rows[0][1] if rows else {}


def _metric_int(metrics: Mapping[str, str], name: str) -> int:
    raw = metrics.get(name, "0")
    try:
        return max(int(Decimal(raw)), 0)
    except (InvalidOperation, ValueError):
        return 0


def _safe_dimension_value(raw: str) -> str:
    normalized = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9_.-]+", "_", normalized.lower()).strip("_.-")
    if not slug:
        slug = f"value_{hashlib.sha256(raw.encode()).hexdigest()[:10]}"
    if not slug[0].isalpha():
        slug = f"v_{slug}"
    return slug[:64]


def _report_is_truncated(payload: Mapping[str, Any], limit: int) -> bool:
    row_count = payload.get("rowCount")
    return isinstance(row_count, int) and row_count > limit


def _unique_nonempty(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _latency_ms(started: float) -> int:
    return max(int((time.monotonic() - started) * 1000), 0)
