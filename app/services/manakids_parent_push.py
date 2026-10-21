"""Bounded documented parent push adapter: one dispatch, no delivery claims."""

import asyncio
import json
import math
import re
import time
from typing import Literal, cast

import httpx

from app.mana_ai.application.parent_notifications import ParentPushRejected, ParentPushUnknown
from app.mana_ai.domain.parent_notifications import ParentPushMessage, ParentPushReceipt

_MAX_RECEIPT_BYTES = 16_384
_AUTH_COOLDOWN_SECONDS = 60
_QUEUE_RECEIPT = re.compile(r"Notification queued for (0|[1-9][0-9]*) devices", flags=re.ASCII)
_ACCESS_TOKEN = re.compile(r"[A-Za-z0-9._~-]{1,8192}", flags=re.ASCII)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Ambiguous provider receipt")
        result[key] = value
    return result


class ManakidsParentPushGateway:
    """The owning service, not this adapter, owns idempotency and recipient policy."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str,
        username: str,
        password: str,
        wall_timeout_seconds: float = 30,
    ) -> None:
        try:
            parsed = httpx.URL(base_url)
        except (ValueError, httpx.InvalidURL):
            raise ValueError("A valid HTTPS push API origin is required") from None
        if (
            parsed.scheme != "https"
            or not parsed.host
            or parsed.userinfo
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("A valid HTTPS push API origin is required")
        if not username or not password:
            raise ValueError("Push API credentials are required")
        if not math.isfinite(wall_timeout_seconds) or not 0 < wall_timeout_seconds <= 120:
            raise ValueError("Push API wall timeout must be between 0 and 120 seconds")
        self._client = client
        self._base = str(parsed).rstrip("/")
        self._username, self._password = username, password
        self._wall_timeout_seconds = wall_timeout_seconds
        self._auth_lock = asyncio.Lock()
        self._auth_retry_at = 0.0

    async def _read_json(self, response: httpx.Response) -> object:
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=4096):
            data.extend(chunk)
            if len(data) > _MAX_RECEIPT_BYTES:
                raise ValueError("Bounded push receipt exceeded")
        payload: object = json.loads(data, object_pairs_hook=_unique_object)
        return payload

    async def _access(self) -> str:
        async with self._auth_lock:
            if time.monotonic() < self._auth_retry_at:
                raise ParentPushUnknown("parent_push_auth_unavailable")
            self._auth_retry_at = time.monotonic() + _AUTH_COOLDOWN_SECONDS
            async with self._client.stream(
                "POST",
                self._base + "/api/v1/admin-panel-auth/login/",
                json={"username": self._username, "password": self._password},
                headers={"User-Agent": "MANA-Parent-Touch/1.0"},
                follow_redirects=False,
            ) as response:
                if response.status_code in {400, 401, 403, 404}:
                    raise ParentPushRejected(
                        "parent_push_auth_rejected",
                        cast(Literal[400, 401, 403, 404], response.status_code),
                    )
                if response.status_code != 200:
                    raise ParentPushUnknown("parent_push_auth_unavailable")
                payload = await self._read_json(response)
            token = payload.get("access") if isinstance(payload, dict) else None
            if not isinstance(token, str) or not _ACCESS_TOKEN.fullmatch(token):
                raise ParentPushUnknown("parent_push_auth_unavailable")
            # Each separately claimed job obtains a fresh token. Its undocumented
            # lifetime must not burn another job's sole permitted write attempt.
            self._auth_retry_at = 0.0
            return token

    async def send(self, message: ParentPushMessage) -> ParentPushReceipt:
        # Revalidate even an unchecked model_copy/model_construct before any provider call.
        admitted = ParentPushMessage.model_validate(message.model_dump(warnings=False))
        dispatched = False
        try:
            async with asyncio.timeout(self._wall_timeout_seconds):
                token = await self._access()
                dispatched = True
                async with self._client.stream(
                    "POST",
                    self._base + f"/api/v1/parent/notify-parent/{admitted.parent_id}/",
                    json={"title": admitted.title, "description": admitted.description},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "User-Agent": "MANA-Parent-Touch/1.0",
                    },
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {401, 403}:
                        async with self._auth_lock:
                            self._auth_retry_at = time.monotonic() + _AUTH_COOLDOWN_SECONDS
                        raise ParentPushRejected(
                            "parent_push_not_authorized",
                            cast(Literal[401, 403], response.status_code),
                        )
                    if response.status_code == 400:
                        raise ParentPushRejected("parent_push_invalid_message", 400)
                    if response.status_code == 404:
                        raise ParentPushRejected("parent_push_parent_not_found", 404)
                    if response.status_code != 201:
                        raise ParentPushUnknown("parent_push_outcome_unknown")
                    payload = await self._read_json(response)
                return self._verify_receipt(payload, admitted)
        except (ParentPushRejected, ParentPushUnknown):
            raise
        except (ValueError, UnicodeError, RecursionError, httpx.HTTPError, TimeoutError):
            if dispatched:
                raise ParentPushUnknown("parent_push_outcome_unknown") from None
            raise ParentPushUnknown("parent_push_auth_unavailable") from None

    @staticmethod
    def _verify_receipt(payload: object, message: ParentPushMessage) -> ParentPushReceipt:
        if not isinstance(payload, dict) or not isinstance(payload.get("message"), str):
            raise ParentPushUnknown("parent_push_outcome_unknown")
        match = _QUEUE_RECEIPT.fullmatch(payload["message"])
        result = payload.get("results")
        if match is None or not isinstance(result, dict):
            raise ParentPushUnknown("parent_push_outcome_unknown")
        identifier = result.get("parent_id")
        if (
            type(identifier) is not int
            or str(identifier) != message.parent_id
            or result.get("title") != message.title
            or result.get("description") != message.description
            or result.get("type") != "ai_agent"
        ):
            raise ParentPushUnknown("parent_push_outcome_unknown")
        return ParentPushReceipt(queued_devices=int(match.group(1)))
