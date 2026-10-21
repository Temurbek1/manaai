"""One bounded account-only Parent List read, with no scan, retry or fallback."""

import asyncio
import json
import math
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ParentChatId
from app.mana_ai.domain.conversion_accounts import ConversionAccountFacts

_PARENT_ID = TypeAdapter(ParentChatId)
_ACCESS_TOKEN = re.compile(r"[A-Za-z0-9._~-]{1,8192}", flags=re.ASCII)
_AUTH_COOLDOWN_SECONDS = 60


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Ambiguous account response")
        result[key] = value
    return result


class _Account(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    id: int = Field(gt=0, le=2**63 - 1, strict=True)
    # All three newly announced keys must exist, even when the backend explicitly
    # knows no value. Missing is not false, and numeric/string booleans are invalid.
    is_paid: StrictBool | None
    created_at: AwareDatetime | None
    agent_trial_used: StrictBool | None
    payment_date: AwareDatetime | None
    valid_until: AwareDatetime | None

    @field_validator("created_at", "payment_date", "valid_until", mode="before")
    @classmethod
    def explicit_dates(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Account dates must be ISO strings or explicit null")
        return datetime.fromisoformat(value)


class _Page(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    count: int = Field(ge=0, le=1, strict=True)
    results: list[_Account] = Field(max_length=1)
    next: None = None


class ManakidsConversionAccountSource:
    """Not runtime-enabled: durable event admission must precede source dispatch.

    This adapter returns evidence only. It never infers consent, activity, a free
    start, paid conversion or lifetime trial history from a display tariff name.
    An old response missing the new keys fails closed, not into a legacy parser.
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
            parsed = httpx.URL(base_url)
        except (ValueError, httpx.InvalidURL):
            raise ValueError("A valid HTTPS account API origin is required") from None
        if (
            parsed.scheme != "https"
            or not parsed.host
            or parsed.userinfo
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("A valid HTTPS account API origin is required")
        if not username or not password:
            raise ValueError("Account API credentials are required")
        if not math.isfinite(wall_timeout_seconds) or not 0 < wall_timeout_seconds <= 120:
            raise ValueError("Account API wall timeout must be between 0 and 120 seconds")
        self._client = client
        self._base = str(parsed).rstrip("/")
        self._username, self._password = username, password
        self._wall_timeout = wall_timeout_seconds
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._auth_lock = asyncio.Lock()
        self._auth_retry_at = 0.0

    @staticmethod
    async def _json(response: httpx.Response, maximum: int) -> object:
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=4096):
            data.extend(chunk)
            if len(data) > maximum:
                raise ValueError("Bounded account response exceeded")
        payload: object = json.loads(data, object_pairs_hook=_unique_object)
        return payload

    async def _access(self) -> str:
        async with self._auth_lock:
            if time.monotonic() < self._auth_retry_at:
                raise ParentChatError("conversion_account_auth_cooling_down", 503)
            self._auth_retry_at = time.monotonic() + _AUTH_COOLDOWN_SECONDS
            async with self._client.stream(
                "POST",
                self._base + "/api/v1/admin-panel-auth/login/",
                json={"username": self._username, "password": self._password},
                headers={"User-Agent": "MANA-Conversion/1.0"},
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise ParentChatError("conversion_account_auth_unavailable", 503)
                payload = await self._json(response, 16_384)
            token = payload.get("access") if isinstance(payload, dict) else None
            if not isinstance(token, str) or not _ACCESS_TOKEN.fullmatch(token):
                raise ParentChatError("conversion_account_auth_unavailable", 503)
            self._auth_retry_at = 0.0
            return token

    async def read(self, parent_id: str) -> ConversionAccountFacts:
        try:
            parent_id = _PARENT_ID.validate_python(parent_id)
            if int(parent_id) > 2**63 - 1:
                raise ValueError("Out of range parent")
        except (ValidationError, ValueError):
            raise ParentChatError("parent_profile_id_required", 422) from None
        try:
            async with asyncio.timeout(self._wall_timeout):
                token = await self._access()
                async with self._client.stream(
                    "GET",
                    self._base + "/api/v1/admin-panel-parent/parent-list/",
                    params={"parent_id": parent_id, "limit": 1, "offset": 0},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "User-Agent": "MANA-Conversion/1.0",
                    },
                    follow_redirects=False,
                ) as response:
                    if response.status_code in {401, 403}:
                        async with self._auth_lock:
                            self._auth_retry_at = time.monotonic() + _AUTH_COOLDOWN_SECONDS
                    if response.status_code != 200:
                        raise ParentChatError("conversion_account_unavailable", 503)
                    payload = await self._json(response, 65_536)
                page = _Page.model_validate(payload)
                if page.count == 0 and not page.results:
                    raise ParentChatError("parent_not_found", 404)
                if page.count != 1 or len(page.results) != 1:
                    raise ParentChatError("conversion_account_invalid", 503)
                account = page.results[0]
                if str(account.id) != parent_id:
                    raise ParentChatError("conversion_account_owner_mismatch", 503)
                return ConversionAccountFacts(
                    parent_id=parent_id,
                    collected_at=self._clock(),
                    is_paid=account.is_paid,
                    agent_trial_used=account.agent_trial_used,
                    created_at=account.created_at,
                    payment_date=account.payment_date,
                    valid_until=account.valid_until,
                )
        except ParentChatError:
            raise
        except ValidationError:
            raise ParentChatError("conversion_account_invalid", 503) from None
        except (ValueError, UnicodeError, RecursionError):
            raise ParentChatError("conversion_account_invalid", 503) from None
        except (httpx.HTTPError, TimeoutError):
            raise ParentChatError("conversion_account_unavailable", 503) from None
