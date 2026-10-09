import asyncio
import importlib
from datetime import datetime, timedelta
from typing import Any, Protocol

import httpx

from app.mana_operation_ai.application.cost_control import CostBudgetExceeded
from app.mana_operation_ai.application.ports import (
    Clock,
    ProviderPermanentError,
    ProviderTransientError,
)
from app.mana_operation_ai.infrastructure.metered_http import MeteredReadHttp

_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleAccessTokenProvider(Protocol):
    async def access_token(self) -> str: ...


class GoogleServiceAccountTokenProvider:
    """Use Google's signer, but admit every OAuth attempt through the shared ledger.

    The credential SDK's refresh transport is deliberately never invoked: it can
    retry internally outside the adapter's admission policy. Tokens stay in memory.
    """

    def __init__(
        self,
        service_account_file: str,
        *,
        scopes: list[str],
        client: httpx.AsyncClient,
        metered_http: MeteredReadHttp,
        clock: Clock,
    ) -> None:
        if not scopes or any(
            not scope or any(char.isspace() for char in scope) for scope in scopes
        ):
            raise ValueError("At least one Google OAuth scope is required")
        service_account = importlib.import_module("google.oauth2.service_account")
        self._credentials: Any = service_account.Credentials.from_service_account_file(
            service_account_file,
            scopes=scopes,
        )
        self._jwt: Any = importlib.import_module("google.auth.jwt")
        self._scopes = tuple(dict.fromkeys(scopes))
        self._client = client
        self._http = metered_http
        self._clock = clock
        self._token: str | None = None
        self._refresh_at: datetime | None = None
        self._blocked = False
        self._next_attempt_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def access_token(self) -> str:
        async with self._lock:
            now = self._clock.now()
            if now.utcoffset() is None:
                raise ValueError("Google OAuth requires a timezone-aware clock")
            if self._blocked:
                raise ProviderPermanentError("Google OAuth authorization is blocked")
            if self._token is not None and self._refresh_at is not None and now < self._refresh_at:
                return self._token
            if self._next_attempt_at is not None and now < self._next_attempt_at:
                raise ProviderTransientError("Google OAuth refresh is cooling down")
            try:
                assertion = self._jwt.encode(
                    self._credentials.signer,
                    {
                        "iss": self._credentials.service_account_email,
                        "scope": " ".join(self._scopes),
                        "aud": _TOKEN_URL,
                        "iat": int(now.timestamp()),
                        "exp": int(now.timestamp()) + 3600,
                    },
                ).decode("ascii")
            except Exception as exc:
                self._blocked = True
                raise ProviderPermanentError("Google OAuth assertion could not be signed") from exc
            # Fence concurrent callers after a failed or cancelled attempt. The
            # durable source gate separately survives worker restart/process loss.
            self._next_attempt_at = now + timedelta(seconds=60)
            try:
                response = await self._http.request(
                    self._client,
                    "POST",
                    _TOKEN_URL,
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": assertion,
                    },
                )
            except httpx.TransportError as exc:
                raise ProviderTransientError("Google OAuth request failed") from exc
            except CostBudgetExceeded:
                # Exhaustion is not invalid credentials. A later admitted source
                # cycle may resume after period rollover without replacing keys.
                raise
            except ProviderPermanentError:
                self._blocked = True
                raise
            if response.status_code in {408, 429} or response.status_code >= 500:
                raise ProviderTransientError("Google OAuth request temporarily failed")
            if response.status_code != 200:
                self._blocked = True
                raise ProviderPermanentError("Google OAuth authorization was rejected")
            try:
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Invalid token response")
                token, expires, kind = (
                    payload.get("access_token"),
                    payload.get("expires_in"),
                    payload.get("token_type"),
                )
                if (
                    not isinstance(token, str)
                    or not token
                    or not token.isascii()
                    or any(char.isspace() for char in token)
                    or type(expires) is not int
                    or not 1 <= expires <= 3600
                    or kind != "Bearer"
                ):
                    raise ValueError("Invalid token response")
            except (ValueError, TypeError) as exc:
                self._blocked = True
                raise ProviderPermanentError("Google OAuth token response is invalid") from exc
            # Count from dispatch, not receipt; never extend life by request latency.
            refresh_at = now + timedelta(seconds=expires - min(60, expires / 2))
            if self._clock.now() >= refresh_at:
                raise ProviderTransientError("Google OAuth response arrived too late")
            self._token = token
            self._refresh_at = refresh_at
            self._next_attempt_at = None
            return token
