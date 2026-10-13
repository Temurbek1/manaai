"""Two bounded collection pages; no listeners, cursors, scans or source writes."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import quote

from app.mana_operation_ai.application.ports import Clock, ProviderPermanentError
from app.mana_operation_ai.domain.first_party_analytics import (
    ChildTelemetryFacts,
    ChildTelemetrySample,
)
from app.mana_operation_ai.infrastructure.retention.analytics_http import AnalyticsReadHttp


def _fields(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderPermanentError("Firestore telemetry has invalid field structure")
    return value


def _numeric(value: object) -> Decimal | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("doubleValue", value.get("integerValue", value.get("stringValue")))
    if isinstance(raw, bool) or not isinstance(raw, int | float | str) or len(str(raw)) > 40:
        return None
    try:
        result = Decimal(str(raw).strip().removesuffix("%").strip())
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _time(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class FirestoreChildTelemetryAdapter:
    def __init__(
        self,
        *,
        http: AnalyticsReadHttp,
        clock: Clock,
        project_id: str,
        database_id: str = "(default)",
        sample_limit: int = 100,
        precise_accuracy_meters: Decimal = Decimal("100"),
    ) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{3,62}", project_id) or not re.fullmatch(
            r"(?:\(default\)|[a-z][a-z0-9-]{3,62})", database_id
        ):
            raise ValueError("Explicit Firestore project/database identity is required")
        if (
            isinstance(sample_limit, bool)
            or not 1 <= sample_limit <= 100
            or not precise_accuracy_meters.is_finite()
            or not (0 < precise_accuracy_meters <= 10000)
        ):
            raise ValueError("Firestore sample and accuracy limits are invalid")
        self._http, self._clock = http, clock
        self._limit, self._accuracy = sample_limit, precise_accuracy_meters
        self._document_prefix = f"projects/{project_id}/databases/{database_id}/documents/"
        self._base = (
            "https://firestore.googleapis.com/v1/projects/"
            + quote(project_id, safe="")
            + "/databases/"
            + quote(database_id, safe="")
            + "/documents/"
        )

    async def collect(self) -> ChildTelemetryFacts:
        if self._clock.now().utcoffset() is None:
            raise ProviderPermanentError("Firestore analytics requires a timezone-aware clock")
        samples = []
        collections: tuple[Literal["battery", "children_location"], ...] = (
            "battery",
            "children_location",
        )
        for collection in collections:
            masks = (
                ["percent", "created_at"]
                if collection == "battery"
                else [
                    "coords.latitude",
                    "coords.longitude",
                    "coords.accuracy",
                    "location.mock",
                    "location.timestamp",
                ]
            )
            parameters: list[tuple[str, str]] = [
                ("pageSize", str(self._limit)),
                ("orderBy", "__name__ asc"),
            ]
            parameters.extend(("mask.fieldPaths", path) for path in masks)
            payload = await self._http.request(
                "GET", self._base + collection, document_limit=self._limit, params=parameters
            )
            samples.append(self._sample(collection, _fields(payload)))
        return ChildTelemetryFacts(
            collected_at=self._clock.now(),
            sample_limit_per_collection=self._limit,
            precise_accuracy_limit_meters=self._accuracy,
            samples=(samples[0], samples[1]),
            limitations=[
                "Two bounded document-ID prefix samples only; neither representative nor "
                "complete child/device population statistics. No continuation pages or scans.",
                "MANA child device records are separate from parent behavioral analytics; "
                "no parent denominator, individual GPS coordinates or identity join is supplied.",
                "Collection time is a database read, not a sensor measurement. Server update "
                "age, missing/naive/future client dates and GPS accuracy are checked separately.",
                "Low-battery counts describe valid stored fields, not confirmed current device "
                "state. Precise-location count requires recent known-time, non-mock observations.",
            ],
        )

    def _sample(
        self, collection: Literal["battery", "children_location"], payload: dict[str, Any]
    ) -> ChildTelemetrySample:
        documents = payload.get("documents", [])
        if not isinstance(documents, list) or len(documents) > self._limit:
            raise ProviderPermanentError("Firestore exceeded its telemetry document limit")
        now = self._clock.now().astimezone(UTC)
        recent_start = now - timedelta(hours=6)
        valid = invalid = recent = future = unknown_timezone = low = precise = mock_count = 0
        updates = []
        seen_names: set[str] = set()
        for raw in documents:
            document = _fields(raw)
            name = document.get("name")
            expected_prefix = self._document_prefix + collection + "/"
            if (
                not isinstance(name, str)
                or not name.startswith(expected_prefix)
                or (
                    "/" in name[len(expected_prefix) :]
                    or not name[len(expected_prefix) :]
                    or name in seen_names
                )
            ):
                raise ProviderPermanentError(
                    "Firestore returned duplicate or foreign document names"
                )
            seen_names.add(name)
            updated = _time(document.get("updateTime"))
            if updated is None or updated.utcoffset() is None or updated > now:
                raise ProviderPermanentError("Firestore server observation time is invalid")
            updates.append(updated.astimezone(UTC))
            server_recent = updated >= recent_start
            recent += server_recent
            fields = _fields(document.get("fields", {}))
            if collection == "battery":
                percent = _numeric(fields.get("percent"))
                usable = percent is not None and 0 <= percent <= 100
                low += usable and percent is not None and percent <= 20
                client_time = _time(_fields(fields.get("created_at", {})).get("stringValue"))
            else:
                coords = _fields(_fields(fields.get("coords", {})).get("mapValue", {})).get(
                    "fields", {}
                )
                coords = _fields(coords)
                lat, lon, accuracy = [
                    _numeric(coords.get(key)) for key in ["latitude", "longitude", "accuracy"]
                ]
                usable = (
                    lat is not None
                    and lon is not None
                    and -90 <= lat <= 90
                    and -180 <= lon <= 180
                    and (lat != 0 or lon != 0)
                )
                location = _fields(_fields(fields.get("location", {})).get("mapValue", {})).get(
                    "fields", {}
                )
                location = _fields(location)
                mock = _fields(location.get("mock", {})).get("booleanValue")
                mock_count += mock is True
                client_time = _time(_fields(location.get("timestamp", {})).get("stringValue"))
                precise += bool(
                    usable
                    and accuracy is not None
                    and 0 <= accuracy <= self._accuracy
                    and mock is False
                    and server_recent
                    and client_time is not None
                    and client_time.utcoffset() is not None
                    and recent_start <= client_time <= now
                )
            valid += usable
            invalid += not usable
            if client_time is None or client_time.utcoffset() is None:
                unknown_timezone += 1
            else:
                future += client_time > now
        # Names, coordinates and all raw fields leave scope here and are never persisted.
        return ChildTelemetrySample(
            collection=collection,
            sampled_documents=len(documents),
            more_documents=bool(payload.get("nextPageToken")),
            valid_observations=valid,
            invalid_observations=invalid,
            source_updated_min=min(updates) if updates else None,
            source_updated_max=max(updates) if updates else None,
            recent_server_updates=recent,
            future_client_dates=future,
            unknown_client_timezone=unknown_timezone,
            low_battery_observations=low if collection == "battery" else None,
            precise_location_observations=precise if collection == "children_location" else None,
            mock_location_observations=mock_count if collection == "children_location" else None,
        )
