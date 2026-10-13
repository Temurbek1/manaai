"""Single-attempt read-only transport for manual MANA source capabilities."""

from typing import Any

import httpx

from app.mana_operation_ai.application.ports import ProviderPermanentError, ProviderTransientError
from app.mana_operation_ai.infrastructure.google_auth import GoogleAccessTokenProvider
from app.mana_operation_ai.infrastructure.metered_http import MeteredReadHttp


class AnalyticsReadHttp:
    def __init__(
        self, client: httpx.AsyncClient, token: GoogleAccessTokenProvider, meter: MeteredReadHttp
    ) -> None:
        self._client, self._token, self._meter = client, token, meter

    async def request(
        self, method: str, url: str, *, document_limit: int = 0, **kwargs: Any
    ) -> object:
        token = await self._token.access_token()
        try:
            response = await self._meter.request(
                self._client,
                method,
                url,
                headers={"Authorization": "Bearer " + token},
                document_limit=document_limit,
                **kwargs,
            )
        except httpx.TransportError as exc:
            raise ProviderTransientError("MANA analytics read failed; no automatic retry") from exc
        if response.status_code != 200:
            error = (
                ProviderTransientError
                if response.status_code in {408, 429} or response.status_code >= 500
                else ProviderPermanentError
            )
            raise error("MANA analytics source rejected the bounded read")
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderPermanentError("MANA analytics source returned invalid JSON") from exc
