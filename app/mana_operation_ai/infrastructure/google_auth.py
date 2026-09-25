import asyncio
import importlib
from typing import Any, Protocol

from app.mana_operation_ai.application.ports import (
    ProviderPermanentError,
    ProviderTransientError,
)


class GoogleAccessTokenProvider(Protocol):
    async def access_token(self) -> str: ...


class GoogleServiceAccountTokenProvider:
    """Refresh a scoped Google OAuth token without exposing credential material."""

    def __init__(self, service_account_file: str, *, scopes: list[str]) -> None:
        if not scopes:
            raise ValueError("At least one Google OAuth scope is required")
        service_account = importlib.import_module("google.oauth2.service_account")
        transport_requests = importlib.import_module("google.auth.transport.requests")
        self._credentials: Any = service_account.Credentials.from_service_account_file(
            service_account_file,
            scopes=scopes,
        )
        self._request: Any = transport_requests.Request()
        self._lock = asyncio.Lock()

    async def access_token(self) -> str:
        async with self._lock:
            if not self._credentials.valid or not self._credentials.token:
                try:
                    await asyncio.to_thread(self._credentials.refresh, self._request)
                except Exception as exc:
                    raise ProviderTransientError("Google access token refresh failed") from exc
            token = self._credentials.token
            if not isinstance(token, str) or not token:
                raise ProviderPermanentError("Google credentials did not produce an access token")
            return token
