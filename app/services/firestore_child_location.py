"""One projected exact document GET; precise coordinates never leave this adapter."""

import asyncio
import hashlib
import json
import math
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.child_location import ChildLocationFacts
from app.services.firestore_child_battery import FirestoreReadToken, _timestamp

LOCATION_FIELDS = (
    "coords.latitude",
    "coords.longitude",
    "coords.accuracy",
    "location.timestamp",
    "location.mock",
    "location.sample",
    "location.isMoving",
)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate location response field")
        result[key] = value
    return result


def _number(value: object) -> float:
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError("Invalid coordinate value")
    kind, raw = next(iter(value.items()))
    if kind == "integerValue":
        if not isinstance(raw, str) or not re.fullmatch(r"-?[0-9]{1,20}", raw):
            raise ValueError("Invalid integer coordinate")
        number = float(raw)
    elif kind == "doubleValue" and type(raw) in {float, int}:
        number = float(raw)
    else:
        raise ValueError("Invalid coordinate type")
    if not math.isfinite(number):
        raise ValueError("Invalid finite coordinate")
    return 0.0 if number == 0 else number


def _fields(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"mapValue"}:
        raise ValueError("Invalid projected location map")
    nested = value["mapValue"]
    if not isinstance(nested, dict) or set(nested) != {"fields"}:
        raise ValueError("Invalid projected location fields")
    result = nested["fields"]
    if not isinstance(result, dict):
        raise ValueError("Invalid projected location fields")
    return result


def _boolean(fields: dict[str, Any], name: str) -> bool | None:
    if name not in fields:
        return None
    value = fields[name]
    if (
        not isinstance(value, dict)
        or set(value) != {"booleanValue"}
        or type(value["booleanValue"]) is not bool
    ):
        raise ValueError("Invalid location quality flag")
    return bool(value["booleanValue"])


class FirestoreChildLocationSource:
    def __init__(
        self,
        client: httpx.AsyncClient,
        auth: FirestoreReadToken,
        *,
        project_id: str,
        database_id: str = "(default)",
        clock: Callable[[], datetime],
        timeout_seconds: float = 30,
        maximum_response_bytes: int = 65536,
    ) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{3,62}", project_id) or not re.fullmatch(
            r"(?:\(default\)|[a-z][a-z0-9-]{3,62})", database_id
        ):
            raise ValueError("Explicit Firestore project/database identity is required")
        if not 1 <= timeout_seconds <= 60 or not 1024 <= maximum_response_bytes <= 65536:
            raise ValueError("Invalid location request limits")
        self._client, self._auth, self._clock = client, auth, clock
        self._timeout, self._maximum = timeout_seconds, maximum_response_bytes
        self._prefix = f"projects/{project_id}/databases/{database_id}/documents/children_location/"
        self._url = (
            "https://firestore.googleapis.com/v1/projects/"
            + quote(project_id, safe="")
            + "/databases/"
            + quote(database_id, safe="")
            + "/documents/children_location/"
        )

    async def read(self, child_id: int) -> ChildLocationFacts:
        if type(child_id) is not int or not 0 < child_id <= 2**63 - 1:
            raise ValueError("A canonical child ID is required")
        if self._clock().utcoffset() is None:
            raise ValueError("An aware source clock is required")
        async with asyncio.timeout(self._timeout):
            token = await self._auth.token()
            if not token or len(token) > 8192 or "\n" in token or "\r" in token:
                raise ParentChatError("family_source_auth_denied", 503)
            async with self._client.stream(
                "GET",
                self._url + str(child_id),
                params=[("mask.fieldPaths", field) for field in LOCATION_FIELDS],
                headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "identity"},
                follow_redirects=False,
            ) as response:
                if response.status_code == 404:
                    return ChildLocationFacts(
                        child_id=child_id,
                        status="missing",
                        collected_at=self._clock(),
                        quality="no_observation",
                    )
                if response.status_code in {401, 403}:
                    raise ParentChatError("family_source_auth_denied", 503)
                if response.status_code in {400, 422}:
                    raise ParentChatError("family_source_query_invalid", 503)
                if response.status_code != 200:
                    raise ParentChatError("family_source_unavailable", 503)
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ValueError("Compressed location responses are not admitted")
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    data.extend(chunk)
                    if len(data) > self._maximum:
                        raise ValueError("Location response exceeds its byte ceiling")
                payload = json.loads(data, object_pairs_hook=_unique)
        return self._facts(child_id, payload)

    def _facts(self, child_id: int, payload: object) -> ChildLocationFacts:
        now = self._clock().astimezone(UTC)
        if not isinstance(payload, dict) or payload.get("name") != self._prefix + str(child_id):
            raise ValueError("A location must match the exact verified child document")
        fields = payload.get("fields")
        if not isinstance(fields, dict) or set(fields) != {"coords", "location"}:
            raise ValueError("Invalid projected location document")
        coords, location = _fields(fields["coords"]), _fields(fields["location"])
        if set(coords) - {"latitude", "longitude", "accuracy"} or set(location) - {
            "timestamp",
            "mock",
            "sample",
            "isMoving",
        }:
            raise ValueError("Unexpected unprojected location fields")
        latitude, longitude = _number(coords.get("latitude")), _number(coords.get("longitude"))
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("Coordinates are outside their valid ranges")
        if "accuracy" in coords and _number(coords["accuracy"]) < 0:
            raise ValueError("Invalid reported accuracy")
        updated = _timestamp(payload.get("updateTime"))
        if updated is None or updated > now:
            raise ValueError("Invalid location server update")
        date = location.get("timestamp", {})
        if (
            not isinstance(date, dict)
            or len(date) > 1
            or set(date) - {"timestampValue", "stringValue"}
        ):
            raise ValueError("Invalid location measurement field")
        observed = _timestamp(date.get("timestampValue", date.get("stringValue")))
        if observed is not None and observed > updated:
            observed = None
        position = hashlib.sha256(json.dumps([latitude, longitude]).encode()).hexdigest()
        return ChildLocationFacts(
            child_id=child_id,
            status="available",
            position_fingerprint=position,
            observed_at=observed,
            source_updated_at=updated,
            collected_at=now,
            quality="dated" if observed is not None else "unknown_measurement_time",
            mock=_boolean(location, "mock"),
            sample=_boolean(location, "sample"),
            is_moving=_boolean(location, "isMoving"),
            accuracy_reported="accuracy" in coords,
        )
