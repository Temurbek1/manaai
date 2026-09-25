import asyncio
import re
import time
from collections import Counter
from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx

from app.mana_operation_ai.application.ports import (
    Clock,
    ProviderPermanentError,
    ProviderTransientError,
)
from app.mana_operation_ai.domain.enums import IntegrationStatus
from app.mana_operation_ai.domain.models import IntegrationHealth
from app.mana_operation_ai.domain.retention import OperationalTelemetryFacts
from app.mana_operation_ai.infrastructure.google_auth import GoogleAccessTokenProvider

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_COLLECTIONS = (
    "battery",
    "children_location",
    "internet",
    "monitoring",
    "screen-commands",
)
_FIELD_MASKS: dict[str, tuple[str, ...]] = {
    "battery": ("childId", "percent", "is_silent"),
    "children_location": ("childId", "activity.type", "coords.speed"),
    "internet": ("childId",),
    "monitoring": ("childId", "enabled"),
    "screen-commands": ("childId", "command"),
}


class FirestoreOperationalTelemetryAdapter:
    """Aggregate operational Firestore state while discarding IDs, GPS, and raw documents."""

    integration_id = "firebase_operational_telemetry"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        project_id: str,
        database_id: str,
        token_provider: GoogleAccessTokenProvider,
        clock: Clock,
        max_documents_per_collection: int,
        max_retries: int,
        retry_backoff_seconds: float,
    ) -> None:
        self._client = client
        self._token_provider = token_provider
        self._clock = clock
        self._max_documents_per_collection = max_documents_per_collection
        self._max_retries = max_retries
        self._retry_backoff_seconds = retry_backoff_seconds
        encoded_project = quote(project_id, safe="")
        encoded_database = quote(database_id, safe="")
        self._documents_url = (
            "https://firestore.googleapis.com/v1/projects/"
            f"{encoded_project}/databases/{encoded_database}/documents"
        )

    async def collect_telemetry(self) -> OperationalTelemetryFacts:
        results = await asyncio.gather(
            *(self._list_collection(collection) for collection in _COLLECTIONS),
        )
        by_collection = dict(zip(_COLLECTIONS, results, strict=True))
        battery_subjects: set[str] = set()
        percent_available = 0
        silent_devices = 0
        for document in by_collection["battery"].documents:
            fields = _document_fields(document)
            subject = _subject_key(document, fields)
            if subject:
                battery_subjects.add(subject)
            if _numeric_value(fields.get("percent")) is not None:
                percent_available += 1
            if fields.get("is_silent") is True:
                silent_devices += 1

        located_subjects: set[str] = set()
        moving_subjects: set[str] = set()
        for document in by_collection["children_location"].documents:
            fields = _document_fields(document)
            subject = _subject_key(document, fields)
            if subject:
                located_subjects.add(subject)
            activity = fields.get("activity")
            coordinates = fields.get("coords")
            activity_type = activity.get("type") if isinstance(activity, Mapping) else None
            speed = coordinates.get("speed") if isinstance(coordinates, Mapping) else None
            movement_speed = _numeric_value(speed) or 0
            if subject and (activity_type not in {None, "still"} or movement_speed > 0):
                moving_subjects.add(subject)

        monitoring_enabled = 0
        monitoring_disabled = 0
        for document in by_collection["monitoring"].documents:
            enabled = _document_fields(document).get("enabled")
            monitoring_enabled += enabled is True
            monitoring_disabled += enabled is False

        command_counts: Counter[str] = Counter()
        for document in by_collection["screen-commands"].documents:
            command = _document_fields(document).get("command")
            if isinstance(command, str):
                normalized = _taxonomy(command)
                if normalized:
                    command_counts[normalized] += 1

        documents_scanned = sum(len(result.documents) for result in results)
        truncated = [result.collection for result in results if result.truncated]
        completeness = Decimal("0.99") if truncated else Decimal("1")
        limitations = [
            "Exact child IDs, device IDs, coordinates, timestamps, and raw Firestore documents "
            "are discarded after in-memory aggregation.",
            "Firestore operational collections are current-state signals, not product-event "
            "sessions or ordered user timelines.",
        ]
        if truncated:
            limitations.append(
                "The configured document limit was reached for: " + ", ".join(sorted(truncated)),
            )
        return OperationalTelemetryFacts(
            source=self.integration_id,
            collected_at=self._clock.now(),
            battery_devices=len(battery_subjects),
            battery_percent_available=percent_available,
            silent_devices=silent_devices,
            located_devices=len(located_subjects),
            moving_devices=len(moving_subjects),
            internet_records=len(by_collection["internet"].documents),
            monitoring_enabled=monitoring_enabled,
            monitoring_disabled=monitoring_disabled,
            screen_command_counts=dict(sorted(command_counts.items())),
            documents_scanned=documents_scanned,
            completeness=completeness,
            source_request_ids=_unique_nonempty(
                [request_id for result in results for request_id in result.request_ids],
            ),
            limitations=limitations,
        )

    async def health(self) -> IntegrationHealth:
        started = time.monotonic()
        checked_at = self._clock.now()
        try:
            result = await self._list_collection("battery", limit=1)
        except (ProviderPermanentError, ProviderTransientError) as exc:
            return IntegrationHealth(
                integration_id=self.integration_id,
                status=IntegrationStatus.UNHEALTHY,
                checked_at=checked_at,
                latency_ms=_latency_ms(started),
                message=f"Firestore operational read check failed ({type(exc).__name__})",
                diagnostics={"mode": "live_read_only"},
            )
        return IntegrationHealth(
            integration_id=self.integration_id,
            status=IntegrationStatus.HEALTHY,
            checked_at=checked_at,
            last_success_at=self._clock.now(),
            latency_ms=_latency_ms(started),
            message="Firestore operational aggregate read access is healthy",
            provider_request_id=next(iter(result.request_ids), None),
            diagnostics={"mode": "live_read_only", "collections": list(_COLLECTIONS)},
        )

    async def _list_collection(
        self,
        collection: str,
        *,
        limit: int | None = None,
    ) -> "_CollectionResult":
        document_limit = limit or self._max_documents_per_collection
        documents: list[Mapping[str, Any]] = []
        request_ids: list[str] = []
        page_token: str | None = None
        while len(documents) < document_limit:
            page_size = min(document_limit - len(documents), 1_000)
            params: list[tuple[str, str | int | float | bool | None]] = [
                ("pageSize", str(page_size)),
            ]
            params.extend(("mask.fieldPaths", field) for field in _FIELD_MASKS[collection])
            if page_token:
                params.append(("pageToken", page_token))
            response = await self._request(
                f"{self._documents_url}/{quote(collection, safe='')}",
                params=params,
            )
            payload = _json_object(response)
            raw_documents = payload.get("documents", [])
            if not isinstance(raw_documents, list):
                raise ProviderPermanentError("Firestore documents response is invalid")
            documents.extend(item for item in raw_documents if isinstance(item, Mapping))
            request_ids.extend(
                _unique_nonempty(
                    [
                        response.headers.get("x-request-id"),
                        response.headers.get("x-guploader-uploadid"),
                    ],
                ),
            )
            next_token = payload.get("nextPageToken")
            page_token = next_token if isinstance(next_token, str) and next_token else None
            if page_token is None:
                break
        return _CollectionResult(
            collection=collection,
            documents=documents[:document_limit],
            request_ids=request_ids,
            truncated=page_token is not None or len(documents) > document_limit,
        )

    async def _request(
        self,
        url: str,
        *,
        params: list[tuple[str, str | int | float | bool | None]],
    ) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            token = await self._token_provider.access_token()
            try:
                response = await self._client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                )
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise ProviderTransientError("Firestore operational request failed") from exc
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
                continue
            if response.status_code < 400:
                return response
            if response.status_code in _RETRYABLE_STATUSES:
                if attempt >= self._max_retries:
                    raise ProviderTransientError(
                        f"Firestore operational request failed with status {response.status_code}",
                    )
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
                continue
            raise ProviderPermanentError(
                f"Firestore operational request was rejected with status {response.status_code}",
            )
        raise AssertionError("Firestore operational retry loop exited unexpectedly")


class _CollectionResult:
    def __init__(
        self,
        *,
        collection: str,
        documents: list[Mapping[str, Any]],
        request_ids: list[str],
        truncated: bool,
    ) -> None:
        self.collection = collection
        self.documents = documents
        self.request_ids = request_ids
        self.truncated = truncated


def _json_object(response: httpx.Response) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderPermanentError("Firestore returned invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ProviderPermanentError("Firestore returned a non-object response")
    return payload


def _document_fields(document: Mapping[str, Any]) -> dict[str, Any]:
    fields = document.get("fields")
    if not isinstance(fields, Mapping):
        return {}
    return {str(key): _firestore_value(value) for key, value in fields.items()}


def _firestore_value(value: object) -> Any:
    if not isinstance(value, Mapping):
        return None
    for key in ("stringValue", "timestampValue", "booleanValue", "doubleValue"):
        if key in value:
            return value[key]
    if "integerValue" in value:
        try:
            return int(str(value["integerValue"]))
        except ValueError:
            return None
    map_value = value.get("mapValue")
    if isinstance(map_value, Mapping):
        fields = map_value.get("fields")
        if isinstance(fields, Mapping):
            return {str(key): _firestore_value(item) for key, item in fields.items()}
    return None


def _subject_key(document: Mapping[str, Any], fields: Mapping[str, Any]) -> str | None:
    child_id = fields.get("childId")
    if isinstance(child_id, str | int):
        return str(child_id)
    name = document.get("name")
    if isinstance(name, str) and "/" in name:
        return name.rsplit("/", 1)[-1]
    return None


def _numeric_value(value: object, default: float | None = None) -> float | None:
    try:
        if isinstance(value, bool) or value is None or value == "":
            return default
        if isinstance(value, str | int | float):
            return float(value)
        return default
    except (TypeError, ValueError):
        return default


def _taxonomy(value: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9_.-]+", "_", value.lower()).strip("_.-")
    if not normalized:
        return None
    if not normalized[0].isalpha():
        normalized = f"command_{normalized}"
    return normalized[:64]


def _unique_nonempty(values: list[str | None]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _latency_ms(started: float) -> int:
    return max(int((time.monotonic() - started) * 1000), 0)
