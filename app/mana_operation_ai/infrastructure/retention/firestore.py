import asyncio
import re
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from urllib.parse import quote

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
_TAXONOMY_PATTERN = r"^[a-z][a-z0-9_.-]{0,63}$"


@dataclass(frozen=True)
class _MobileActivityEvent:
    event_type: ActivityEventType
    occurred_at: datetime
    sequence_number: int
    subject_id: str
    session_id: str
    duration_ms: int
    screen: str | None
    previous_screen: str | None
    button: str | None
    feature: str | None
    form: str | None
    file_type: str | None
    query_length: int
    filter_count: int
    sort_used: bool


class FirestoreMobileActivityAdapter:
    """Reads the canonical mobile activity collection and persists aggregate facts only."""

    integration_id = "firebase_app_activity"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        project_id: str,
        database_id: str,
        collection_id: str,
        token_provider: GoogleAccessTokenProvider,
        clock: Clock,
        max_documents: int,
        max_retries: int,
        retry_backoff_seconds: float,
    ) -> None:
        self._client = client
        self._project_id = project_id
        self._database_id = database_id
        self._collection_id = collection_id
        self._token_provider = token_provider
        self._clock = clock
        self._max_documents = max_documents
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        encoded_project = quote(project_id, safe="")
        encoded_database = quote(database_id, safe="")
        self._database_path = f"projects/{encoded_project}/databases/{encoded_database}"
        self._base_url = f"https://firestore.googleapis.com/v1/{self._database_path}"

    async def collect_activity(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
    ) -> MobileActivityFacts:
        if period_end <= period_start:
            raise ValueError("Activity period end must be after its start")
        response = await self._request(
            "POST",
            f"{self._base_url}/documents:runQuery",
            json=_query_payload(
                collection_id=self._collection_id,
                period_start=period_start,
                period_end=period_end,
                limit=self._max_documents,
            ),
        )
        payload = _json_payload(response, operation="Firestore activity query")
        if not isinstance(payload, list):
            raise ProviderPermanentError("Firestore activity query returned a non-list payload")

        event_counts = {event_type: 0 for event_type in ActivityEventType}
        dimension_counts: dict[str, Counter[str]] = {
            "screen_views": Counter(),
            "button_clicks": Counter(),
            "feature_uses": Counter(),
            "navigation": Counter(),
            "forms_completed": Counter(),
            "uploads_by_type": Counter(),
            "search_usage": Counter(),
        }
        screen_time_ms_by_screen: Counter[str] = Counter()
        events_by_session: dict[str, list[_MobileActivityEvent]] = {}
        subject_ids: set[str] = set()
        session_ids: set[str] = set()
        screen_time_milliseconds = 0
        valid_documents = 0
        invalid_documents = 0
        read_times: list[str] = []
        for row in payload:
            if not isinstance(row, Mapping):
                invalid_documents += 1
                continue
            read_time = row.get("readTime")
            if isinstance(read_time, str):
                read_times.append(read_time)
            document = row.get("document")
            if document is None:
                continue
            parsed = _parse_activity_document(document, period_start, period_end)
            if parsed is None:
                invalid_documents += 1
                continue
            valid_documents += 1
            event_counts[parsed.event_type] += 1
            subject_ids.add(parsed.subject_id)
            session_ids.add(parsed.session_id)
            events_by_session.setdefault(parsed.session_id, []).append(parsed)
            _record_dimensions(parsed, dimension_counts, screen_time_ms_by_screen)
            if parsed.event_type is ActivityEventType.SCREEN_TIME:
                screen_time_milliseconds += parsed.duration_ms

        documents_scanned = valid_documents + invalid_documents
        completeness = (
            Decimal(valid_documents) / Decimal(documents_scanned)
            if documents_scanned
            else Decimal("1")
        )
        limitations: list[str] = []
        if invalid_documents:
            limitations.append(
                f"Firestore returned {invalid_documents} invalid activity document(s); they were "
                "excluded from aggregates.",
            )
        if documents_scanned >= self._max_documents:
            completeness = min(completeness, Decimal("0.99"))
            limitations.append(
                "The configured Firestore document limit was reached; the window may be partial.",
            )
        request_ids = _unique_nonempty(
            [
                response.headers.get("x-guploader-uploadid"),
                response.headers.get("x-request-id"),
                *read_times[-1:],
            ],
        )
        sequence_counts = _sequence_counts(events_by_session)
        normalized_dimensions = {
            category: dict(sorted(counts.items()))
            for category, counts in dimension_counts.items()
            if counts
        }
        if screen_time_ms_by_screen:
            normalized_dimensions["screen_time_seconds_by_screen"] = {
                screen: milliseconds // 1_000
                for screen, milliseconds in sorted(screen_time_ms_by_screen.items())
            }
        return MobileActivityFacts(
            source=self.integration_id,
            period_start=period_start,
            period_end=period_end,
            collected_at=self._clock.now(),
            event_counts=event_counts,
            dimension_counts=normalized_dimensions,
            sequence_counts=dict(sorted(sequence_counts.items())),
            active_subjects=len(subject_ids),
            sessions=len(session_ids),
            screen_time_seconds=screen_time_milliseconds // 1_000,
            documents_scanned=documents_scanned,
            invalid_documents=invalid_documents,
            completeness=completeness,
            source_request_ids=request_ids,
            limitations=limitations,
        )

    async def health(self) -> IntegrationHealth:
        started = time.monotonic()
        checked_at = self._clock.now()
        try:
            response = await self._request("GET", self._base_url)
        except (ProviderPermanentError, ProviderTransientError) as exc:
            return IntegrationHealth(
                integration_id=self.integration_id,
                status=IntegrationStatus.UNHEALTHY,
                checked_at=checked_at,
                latency_ms=_latency_ms(started),
                message=f"Firestore read check failed ({type(exc).__name__})",
                diagnostics={"mode": "live_read_only"},
            )
        return IntegrationHealth(
            integration_id=self.integration_id,
            status=IntegrationStatus.HEALTHY,
            checked_at=checked_at,
            last_success_at=self._clock.now(),
            latency_ms=_latency_ms(started),
            message="Firestore mobile activity read access is healthy",
            provider_request_id=(
                response.headers.get("x-guploader-uploadid") or response.headers.get("x-request-id")
            ),
            diagnostics={
                "mode": "live_read_only",
                "collection": self._collection_id,
            },
        )

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            token = await self._token_provider.access_token()
            headers = dict(cast(Mapping[str, str], kwargs.pop("headers", {})))
            headers["Authorization"] = f"Bearer {token}"
            try:
                response = await self._client.request(method, url, headers=headers, **kwargs)
            except httpx.RequestError as exc:
                if attempt >= self._max_retries:
                    raise ProviderTransientError("Firestore network request failed") from exc
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
                continue
            if response.status_code not in _RETRYABLE_STATUSES or attempt >= self._max_retries:
                _raise_for_status(response, operation="Firestore read")
                return response
            await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
        raise ProviderTransientError("Firestore retry budget was exhausted")


def _query_payload(
    *,
    collection_id: str,
    period_start: datetime,
    period_end: datetime,
    limit: int,
) -> dict[str, object]:
    return {
        "structuredQuery": {
            "from": [{"collectionId": collection_id}],
            "where": {
                "compositeFilter": {
                    "op": "AND",
                    "filters": [
                        {
                            "fieldFilter": {
                                "field": {"fieldPath": "occurred_at"},
                                "op": "GREATER_THAN_OR_EQUAL",
                                "value": {"timestampValue": _utc_iso(period_start)},
                            },
                        },
                        {
                            "fieldFilter": {
                                "field": {"fieldPath": "occurred_at"},
                                "op": "LESS_THAN",
                                "value": {"timestampValue": _utc_iso(period_end)},
                            },
                        },
                    ],
                },
            },
            "orderBy": [
                {"field": {"fieldPath": "occurred_at"}, "direction": "ASCENDING"},
            ],
            "limit": limit,
        },
    }


def _parse_activity_document(
    raw_document: object,
    period_start: datetime,
    period_end: datetime,
) -> _MobileActivityEvent | None:
    if not isinstance(raw_document, Mapping):
        return None
    fields = raw_document.get("fields")
    if not isinstance(fields, Mapping):
        return None
    schema_version = _string_field(fields, "schema_version")
    subject_id = _string_field(fields, "subject_id")
    session_id = _string_field(fields, "session_id")
    event_value = _string_field(fields, "event_type")
    occurred_value = _timestamp_field(fields, "occurred_at")
    if (
        schema_version != "app-activity-v1"
        or not subject_id
        or not session_id
        or event_value is None
        or occurred_value is None
    ):
        return None
    try:
        event_type = ActivityEventType(event_value)
    except ValueError:
        return None
    occurred_at = _parse_timestamp(occurred_value)
    if occurred_at is None or not (period_start <= occurred_at < period_end):
        return None
    duration_ms = _integer_field(fields, "duration_ms") or 0
    sequence_number = _integer_field(fields, "sequence_number") or 0
    query_length = _integer_field(fields, "query_length") or 0
    filter_count = _integer_field(fields, "filter_count") or 0
    if duration_ms < 0 or sequence_number < 0 or query_length < 0 or filter_count < 0:
        return None
    return _MobileActivityEvent(
        event_type=event_type,
        occurred_at=occurred_at,
        sequence_number=sequence_number,
        subject_id=subject_id,
        session_id=session_id,
        duration_ms=duration_ms,
        screen=_taxonomy_field(fields, "screen"),
        previous_screen=_taxonomy_field(fields, "previous_screen"),
        button=_taxonomy_field(fields, "button"),
        feature=_taxonomy_field(fields, "feature"),
        form=_taxonomy_field(fields, "form"),
        file_type=_taxonomy_field(fields, "file_type"),
        query_length=query_length,
        filter_count=filter_count,
        sort_used=_boolean_field(fields, "sort_used") or False,
    )


def _sequence_counts(
    events_by_session: Mapping[str, list[_MobileActivityEvent]],
) -> Counter[str]:
    result: Counter[str] = Counter()
    for events in events_by_session.values():
        ordered = sorted(events, key=lambda item: (item.occurred_at, item.sequence_number))
        for previous, current in zip(ordered, ordered[1:], strict=False):
            result[f"{previous.event_type.value}>{current.event_type.value}"] += 1
    return result


def _record_dimensions(
    event: _MobileActivityEvent,
    dimensions: dict[str, Counter[str]],
    screen_time_ms_by_screen: Counter[str],
) -> None:
    if event.event_type is ActivityEventType.SCREEN_VIEW and event.screen:
        dimensions["screen_views"][event.screen] += 1
    if event.event_type is ActivityEventType.BUTTON_CLICK and event.button:
        dimensions["button_clicks"][event.button] += 1
    if event.event_type is ActivityEventType.FEATURE_USED and event.feature:
        dimensions["feature_uses"][event.feature] += 1
    if event.event_type is ActivityEventType.NAVIGATION and event.previous_screen and event.screen:
        dimensions["navigation"][f"{event.previous_screen}>{event.screen}"] += 1
    if event.event_type is ActivityEventType.FORM_COMPLETED and event.form:
        dimensions["forms_completed"][event.form] += 1
    if event.event_type is ActivityEventType.FILE_UPLOADED and event.file_type:
        dimensions["uploads_by_type"][event.file_type] += 1
    if event.event_type is ActivityEventType.SEARCH:
        if event.query_length:
            dimensions["search_usage"]["with_query"] += 1
        if event.filter_count:
            dimensions["search_usage"]["with_filters"] += 1
        if event.sort_used:
            dimensions["search_usage"]["with_sort"] += 1
    if event.event_type is ActivityEventType.SCREEN_TIME and event.screen:
        screen_time_ms_by_screen[event.screen] += event.duration_ms


def _string_field(fields: Mapping[object, object], key: str) -> str | None:
    raw = fields.get(key)
    if not isinstance(raw, Mapping):
        return None
    value = raw.get("stringValue")
    return value if isinstance(value, str) else None


def _taxonomy_field(fields: Mapping[object, object], key: str) -> str | None:
    value = _string_field(fields, key)
    if value is None or re.fullmatch(_TAXONOMY_PATTERN, value) is None:
        return None
    return value


def _timestamp_field(fields: Mapping[object, object], key: str) -> str | None:
    raw = fields.get(key)
    if not isinstance(raw, Mapping):
        return None
    value = raw.get("timestampValue")
    return value if isinstance(value, str) else None


def _integer_field(fields: Mapping[object, object], key: str) -> int | None:
    raw = fields.get(key)
    if not isinstance(raw, Mapping):
        return None
    value = raw.get("integerValue")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _boolean_field(fields: Mapping[object, object], key: str) -> bool | None:
    raw = fields.get(key)
    if not isinstance(raw, Mapping):
        return None
    value = raw.get("booleanValue")
    return value if isinstance(value, bool) else None


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _raise_for_status(response: httpx.Response, *, operation: str) -> None:
    if response.status_code < 400:
        return
    error = f"{operation} failed with HTTP {response.status_code}"
    if response.status_code in _RETRYABLE_STATUSES:
        raise ProviderTransientError(error)
    raise ProviderPermanentError(error)


def _json_payload(response: httpx.Response, *, operation: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderPermanentError(f"{operation} returned invalid JSON") from exc


def _unique_nonempty(values: list[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _latency_ms(started: float) -> int:
    return max(round((time.monotonic() - started) * 1_000), 0)
