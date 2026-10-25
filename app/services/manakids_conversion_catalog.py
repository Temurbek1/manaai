"""Manual catalog evidence: one login and one bounded GET, never a payment call."""

import asyncio
import json
import math
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.conversion_catalog import (
    ConversionCatalogObservation,
    ConversionTariffPrice,
)

_TOKEN = re.compile(r"[A-Za-z0-9._~-]{1,8192}", flags=re.ASCII)
_PRICE = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,2})?", flags=re.ASCII)
_DURATION = re.compile(r"([1-9][0-9]{0,2}) 00:00:00", flags=re.ASCII)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Ambiguous catalog response")
        result[key] = value
    return result


class _Tariff(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    id: int = Field(gt=0, le=2**63 - 1, strict=True)
    price: str = Field(strict=True, max_length=15)
    price_currency: str = Field(strict=True, max_length=3)
    duration: str = Field(strict=True, max_length=12)

    def price_fact(self) -> ConversionTariffPrice:
        if not _PRICE.fullmatch(self.price):
            raise ValueError("An exact decimal catalog price is required")
        duration = _DURATION.fullmatch(self.duration)
        if duration is None:
            raise ValueError("A whole-day catalog duration is required")
        return ConversionTariffPrice.model_validate(
            {
                "tariff_id": str(self.id),
                "currency": self.price_currency.upper(),
                "price_minor": int(Decimal(self.price) * 100),
                "duration_days": int(duration.group(1)),
            }
        )


class ManakidsConversionCatalogSource:
    """Bounded evidence adapter; the caller owns cache and durable read admission.

    The caller must durably admit an authorized read before invoking this adapter.
    Replay/restart must observe that receipt rather than call read again. No
    catalogue read is added to account events, publication or application start.
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        base_url: str,
        username: str,
        password: str,
        wall_timeout_seconds: float = 30,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        try:
            origin = httpx.URL(base_url)
        except (ValueError, httpx.InvalidURL):
            raise ValueError("A valid HTTPS catalog API origin is required") from None
        if (
            origin.scheme != "https"
            or not origin.host
            or origin.userinfo
            or origin.query
            or origin.fragment
            or origin.path not in {"", "/"}
        ):
            raise ValueError("A valid HTTPS catalog API origin is required")
        if not username or not password:
            raise ValueError("Catalog API credentials are required")
        if not math.isfinite(wall_timeout_seconds) or not 0 < wall_timeout_seconds <= 120:
            raise ValueError("Catalog API wall timeout must be between 0 and 120 seconds")
        self._client, self._base = client, str(origin).rstrip("/")
        self._username, self._password = username, password
        self._wall_timeout = wall_timeout_seconds
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._lock = asyncio.Lock()
        self._auth_retry_at = 0.0

    @staticmethod
    async def _json(response: httpx.Response, maximum: int) -> object:
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=4096):
            data.extend(chunk)
            if len(data) > maximum:
                raise ValueError("Bounded catalog response exceeded")
        payload: object = json.loads(data, object_pairs_hook=_unique_object)
        return payload

    async def read(self) -> ConversionCatalogObservation:
        try:
            async with asyncio.timeout(self._wall_timeout), self._lock:
                if time.monotonic() < self._auth_retry_at:
                    raise ParentChatError("conversion_catalog_auth_cooling_down", 503)
                self._auth_retry_at = time.monotonic() + 60
                async with self._client.stream(
                    "POST",
                    self._base + "/api/v1/admin-panel-auth/login/",
                    json={"username": self._username, "password": self._password},
                    headers={"User-Agent": "MANA-Conversion/1.0"},
                    follow_redirects=False,
                ) as response:
                    if response.status_code != 200:
                        raise ParentChatError("conversion_catalog_auth_unavailable", 503)
                    auth = await self._json(response, 16384)
                token = auth.get("access") if isinstance(auth, dict) else None
                if not isinstance(token, str) or not _TOKEN.fullmatch(token):
                    raise ParentChatError("conversion_catalog_auth_unavailable", 503)
                self._auth_retry_at = 0.0
                async with self._client.stream(
                    "GET",
                    self._base + "/api/v1/tariffs/",
                    params={"limit": 25, "offset": 0},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "User-Agent": "MANA-Conversion/1.0",
                    },
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {401, 403}:
                        self._auth_retry_at = time.monotonic() + 60
                    if response.status_code != 200:
                        raise ParentChatError("conversion_catalog_unavailable", 503)
                    payload = await self._json(response, 65536)
                if not isinstance(payload, list) or len(payload) > 25:
                    raise ValueError("A bounded catalog array is required")
                return ConversionCatalogObservation(
                    collected_at=self._clock(),
                    tariffs=tuple(_Tariff.model_validate(row).price_fact() for row in payload),
                )
        except ParentChatError:
            raise
        except (ValidationError, ValueError, UnicodeError, RecursionError):
            raise ParentChatError("conversion_catalog_invalid", 503) from None
        except (httpx.HTTPError, TimeoutError):
            raise ParentChatError("conversion_catalog_unavailable", 503) from None
