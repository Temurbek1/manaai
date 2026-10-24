"""Server-only Google signing with one bounded OAuth attempt and no SDK refresh."""

import asyncio
import importlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from app.mana_ai.application.chat_ports import ParentChatError

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DATASTORE_SCOPE = "https://www.googleapis.com/auth/datastore"


class FamilyFirestoreToken:
    """The fixed query adapter, not OAuth scope alone, enforces read-only access."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        credential_file: Path,
        *,
        project_id: str,
        clock: Callable[[], datetime],
        timeout_seconds: float = 15,
    ) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{3,62}", project_id):
            raise ValueError("An explicit Firebase project is required")
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("Invalid OAuth timeout")
        try:
            with credential_file.open("rb") as stream:
                data = stream.read(32769)
            info = json.loads(data) if len(data) <= 32768 else None
            if (
                not isinstance(info, dict)
                or info.get("type") != "service_account"
                or info.get("project_id") != project_id
                or not isinstance(info.get("client_email"), str)
                or not re.fullmatch(
                    r"[a-zA-Z0-9._-]{1,128}@"
                    + re.escape(project_id)
                    + r"\.iam\.gserviceaccount\.com",
                    info["client_email"],
                )
                or info.get("universe_domain", "googleapis.com") != "googleapis.com"
            ):
                raise ValueError("Invalid binding")
            # Use only the supported signer API. No refresh()/authorized transport,
            # delegated subject, quota project or credential-controlled token URL.
            info["token_uri"] = _TOKEN_URL
            credentials = importlib.import_module("google.oauth2.service_account")
            self._credentials = credentials.Credentials.from_service_account_info(info)
            self._jwt = importlib.import_module("google.auth.jwt")
        except (OSError, ValueError, TypeError, KeyError, ImportError):
            raise ValueError("Firebase service credentials are invalid or unavailable") from None
        self._client, self._clock, self._timeout = client, clock, timeout_seconds
        self._lock = asyncio.Lock()
        self._access_token: str | None = None
        self._refresh_at: datetime | None = None
        self._next_attempt_at: datetime | None = None
        self._blocked = False

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise ValueError("An aware OAuth clock is required")
        return now.astimezone(UTC)

    async def token(self) -> str:
        async with self._lock:
            now = self._now()
            if self._blocked:
                raise ParentChatError("family_source_auth_denied", 503)
            if self._access_token and self._refresh_at and now < self._refresh_at:
                return self._access_token
            if self._next_attempt_at and now < self._next_attempt_at:
                raise ParentChatError("family_source_unavailable", 503)
            issued = int(now.timestamp())
            assertion = self._jwt.encode(
                self._credentials.signer,
                {
                    "iss": self._credentials.service_account_email,
                    "scope": _DATASTORE_SCOPE,
                    "aud": _TOKEN_URL,
                    "iat": issued,
                    "exp": issued + 3600,
                },
            )
            if not isinstance(assertion, bytes):
                raise ValueError("Invalid signed assertion")
            self._next_attempt_at = now + timedelta(seconds=60)
            async with asyncio.timeout(self._timeout):
                async with self._client.stream(
                    "POST",
                    _TOKEN_URL,
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": assertion.decode("ascii"),
                    },
                    headers={"Accept-Encoding": "identity"},
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {408, 429} or response.status_code >= 500:
                        raise ParentChatError("family_source_unavailable", 503)
                    if response.status_code != 200:
                        self._blocked = True
                        raise ParentChatError("family_source_auth_denied", 503)
                    try:
                        if response.headers.get("content-encoding", "identity") != "identity":
                            raise ValueError("Compressed OAuth response")
                        data = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=4096):
                            data.extend(chunk)
                            if len(data) > 16384:
                                raise ValueError("Oversized OAuth response")
                        payload = json.loads(data)
                        if not isinstance(payload, dict):
                            raise ValueError("Invalid OAuth payload")
                        token, expires = payload.get("access_token"), payload.get("expires_in")
                        if (
                            not isinstance(token, str)
                            or not 1 <= len(token) <= 8192
                            or not token.isascii()
                            or any(char.isspace() for char in token)
                            or type(expires) is not int
                            or not 1 <= expires <= 3600
                            or payload.get("token_type") != "Bearer"
                        ):
                            raise ValueError("Invalid OAuth receipt")
                    except (ValueError, TypeError):
                        self._blocked = True
                        raise ParentChatError("family_source_invalid", 503) from None
            refresh_at = now + timedelta(seconds=expires - min(60, expires / 2))
            if self._now() >= refresh_at:
                raise ParentChatError("family_source_unavailable", 503)
            self._access_token, self._refresh_at = token, refresh_at
            return token
