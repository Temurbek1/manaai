"""One read-only, equality-filtered Firestore query for a verified own child."""

import asyncio
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from urllib.parse import quote

import httpx

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.family_sources import ChildBatteryFacts


class FirestoreReadToken(Protocol):
    async def token(self) -> str: ...


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(UTC) if result.utcoffset() is not None else None


class FirestoreChildBatterySource:
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
            raise ValueError("Invalid Firestore request limits")
        self._client, self._auth, self._clock = client, auth, clock
        self._timeout, self._maximum = timeout_seconds, maximum_response_bytes
        self._prefix = f"projects/{project_id}/databases/{database_id}/documents/battery/"
        self._url = (
            "https://firestore.googleapis.com/v1/projects/"
            + quote(project_id, safe="")
            + "/databases/"
            + quote(database_id, safe="")
            + "/documents:runQuery"
        )

    async def read(self, child_id: int) -> ChildBatteryFacts:
        if type(child_id) is not int or not 0 < child_id <= 2**63 - 1:
            raise ValueError("A canonical child ID is required")
        if self._clock().utcoffset() is None:
            raise ValueError("An aware source clock is required")
        # POST runQuery is a read, not a document mutation. No list, offset,
        # pagination, field discovery, listener or arbitrary provider payload.
        query = {
            "structuredQuery": {
                "select": {
                    "fields": [
                        {"fieldPath": field} for field in ("childId", "percent", "created_at")
                    ]
                },
                "from": [{"collectionId": "battery", "allDescendants": False}],
                "where": {
                    "fieldFilter": {
                        "field": {"fieldPath": "childId"},
                        "op": "EQUAL",
                        "value": {"integerValue": str(child_id)},
                    }
                },
                "limit": 2,
            }
        }
        async with asyncio.timeout(self._timeout):
            token = await self._auth.token()
            if not token or len(token) > 8192 or "\n" in token or "\r" in token:
                raise ParentChatError("family_source_auth_denied", 503)
            async with self._client.stream(
                "POST",
                self._url,
                json=query,
                headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "identity"},
                follow_redirects=False,
            ) as response:
                if response.status_code in {401, 403}:
                    raise ParentChatError("family_source_auth_denied", 503)
                if response.status_code in {400, 404, 422}:
                    raise ParentChatError("family_source_query_invalid", 503)
                if response.status_code != 200:
                    raise ParentChatError("family_source_unavailable", 503)
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ValueError("Compressed source responses are not admitted")
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    data.extend(chunk)
                    if len(data) > self._maximum:
                        raise ValueError("Firestore response exceeds its byte ceiling")
                payload = json.loads(data)
        return self._facts(child_id, payload)

    def _facts(self, child_id: int, payload: object) -> ChildBatteryFacts:
        now = self._clock().astimezone(UTC)
        if not isinstance(payload, list) or not 1 <= len(payload) <= 3:
            raise ValueError("Firestore query returned an invalid result list")
        documents = []
        seen: set[str] = set()
        for row in payload:
            if not isinstance(row, dict) or any(
                field in row for field in ("transaction", "explainMetrics", "skippedResults")
            ):
                raise ValueError("Unexpected Firestore query result")
            read_at = _timestamp(row.get("readTime"))
            if read_at is None or read_at > now:
                raise ValueError("Invalid Firestore query read time")
            document = row.get("document")
            if document is None:
                if set(row) - {"readTime", "done"}:
                    raise ValueError("Invalid empty Firestore result")
                continue
            if not isinstance(document, dict):
                raise ValueError("Invalid Firestore document")
            name, fields = document.get("name"), document.get("fields")
            if (
                not isinstance(name, str)
                or not name.startswith(self._prefix)
                or not name[len(self._prefix) :]
                or "/" in name[len(self._prefix) :]
                or name in seen
                or not isinstance(fields, dict)
                or fields.get("childId") != {"integerValue": str(child_id)}
            ):
                raise ValueError("Foreign or ambiguous Firestore family document")
            seen.add(name)
            updated = _timestamp(document.get("updateTime"))
            if updated is None or updated > read_at:
                raise ValueError("Invalid Firestore server update")
            percent_value = fields.get("percent")
            if not isinstance(percent_value, dict) or len(percent_value) != 1:
                raise ValueError("Invalid battery percent")
            kind, raw_percent = next(iter(percent_value.items()))
            if kind not in {"integerValue", "doubleValue", "stringValue"} or (
                type(raw_percent) not in {int, float, str} or len(str(raw_percent)) > 16
            ):
                raise ValueError("Invalid battery percent")
            try:
                percent = Decimal(str(raw_percent).strip().removesuffix("%").strip())
            except InvalidOperation as exc:
                raise ValueError("Invalid battery percent") from exc
            if not percent.is_finite() or not 0 <= percent <= 100 or percent != int(percent):
                raise ValueError("Invalid battery percent")
            created = fields.get("created_at", {})
            if not isinstance(created, dict):
                raise ValueError("Invalid battery observation field")
            observed = _timestamp(created.get("timestampValue", created.get("stringValue")))
            if observed is not None and observed > updated:
                observed = None  # Never reinterpret future or naive device dates as current.
            documents.append((int(percent), observed, updated))
        if len(documents) > 2:
            raise ValueError("Firestore exceeded its document ceiling")
        if len(documents) != 1:
            return ChildBatteryFacts(
                child_id=child_id,
                status="ambiguous" if documents else "missing",
                collected_at=now,
                quality="no_observation",
            )
        selected_percent, observed, updated = documents[0]
        return ChildBatteryFacts(
            child_id=child_id,
            status="available",
            percent=selected_percent,
            observed_at=observed,
            source_updated_at=updated,
            collected_at=now,
            quality="dated" if observed else "unknown_measurement_time",
        )
