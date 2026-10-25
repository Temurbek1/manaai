"""One filtered ownership read; never enumerate families or follow pagination."""

import asyncio
import base64
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, ValidationError

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ChatChild, ParentChildContext, ParentTariffContext
from app.mana_ai.domain.family_day_usage import ParentUsageLookup


def _tariff_context(row: object, collected_at: datetime) -> ParentTariffContext | None:
    """Optional billing failures must not discard valid child ownership evidence."""
    if not isinstance(row, dict):
        return None
    try:
        values = {
            name: row[name]
            for name in (
                "tariff_name",
                "is_paid",
                "valid_until",
                "payment_date",
                "agent_trial_used",
            )
        }
        for name in ("valid_until", "payment_date"):
            raw = values[name]
            if raw is not None:
                if not isinstance(raw, str) or len(raw) > 80:
                    return None
                values[name] = datetime.fromisoformat(raw)
        return ParentTariffContext.model_validate(values | {"collected_at": collected_at})
    except (KeyError, ValueError, ValidationError):
        return None


class _Child(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int = Field(gt=0, strict=True)
    fullname: str | None = Field(default=None, max_length=100)
    age: int | None = Field(default=None, ge=0, le=150, strict=True)
    is_connected: StrictBool


class ManakidsParentProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int = Field(gt=0, strict=True)
    children: list[_Child] = Field(max_length=20)
    children_count: int | None = Field(default=None, ge=0, strict=True)


class _Page(BaseModel):
    model_config = ConfigDict(extra="ignore")
    count: int = Field(ge=0, le=1, strict=True)
    results: list[ManakidsParentProfile] = Field(max_length=1)
    next: str | None = None


class ManakidsChatChildrenSource:
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
        self._client = client
        self._base = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._auth_lock = asyncio.Lock()
        self._auth_retry_at = 0.0
        self._wall_timeout = wall_timeout_seconds
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)

    async def _read_json(self, response: httpx.Response) -> object:
        if response.status_code in {401, 403}:
            raise ParentChatError("child_source_auth_denied", 503)
        if response.status_code != 200:
            raise ParentChatError("child_context_unavailable", 503)
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=4096):
            data.extend(chunk)
            if len(data) > 65_536:
                raise ParentChatError("child_context_too_large", 503)
        try:
            return json.loads(data)
        except (ValueError, UnicodeError):
            raise ParentChatError("child_context_invalid", 503) from None

    async def _access_token(self) -> str:
        async with self._auth_lock:
            if self._token is not None and time.monotonic() < self._token_expires_at:
                return self._token
            self._token = None
            if time.monotonic() < self._auth_retry_at:
                raise ParentChatError("child_source_auth_cooling_down", 503)
            self._auth_retry_at = time.monotonic() + 60
            try:
                async with self._client.stream(
                    "POST",
                    self._base + "/api/v1/admin-panel-auth/login/",
                    json={"username": self._username, "password": self._password},
                    follow_redirects=False,
                ) as response:
                    payload = await self._read_json(response)
            except httpx.HTTPError:
                raise ParentChatError("child_context_unavailable", 503) from None
            if not isinstance(payload, dict):
                raise ParentChatError("child_context_invalid", 503)
            token = payload.get("access") or payload.get("access_token") or payload.get("token")
            if not isinstance(token, str) or not token or len(token) > 8192:
                raise ParentChatError("child_context_invalid", 503)
            # Unverified exp is only a bounded cache hint, never authorization.
            # The backend still verifies the bearer; no failed GET is retried.
            lifetime = 300.0
            if token.count(".") == 2:
                try:
                    part = token.split(".")[1]
                    claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
                    expiry = claims.get("exp") if isinstance(claims, dict) else None
                    if type(expiry) is int:
                        lifetime = min(3600.0, float(expiry) - time.time() - 30)
                except (ValueError, UnicodeError, OverflowError):
                    pass  # An opaque token still has the short server cache bound.
            if lifetime <= 0:
                raise ParentChatError("child_context_invalid", 503)
            self._token = token
            self._token_expires_at = time.monotonic() + lifetime
            return token

    async def access_token(self) -> str:
        """Server adapter port; no credential/token is exposed to a model or client."""
        return await self._access_token()

    async def read(self, parent_id: str) -> ParentChildContext:
        try:
            async with asyncio.timeout(self._wall_timeout):
                return await self._read(parent_id)
        except TimeoutError:
            raise ParentChatError("child_context_unavailable", 503) from None

    async def _read(self, parent_id: str) -> ParentChildContext:
        context, _ = await self._read_profile(parent_id)
        return context

    async def read_usage_lookup(self, parent_id: str) -> ParentUsageLookup:
        try:
            async with asyncio.timeout(self._wall_timeout):
                context, username = await self._read_profile(parent_id)
            return ParentUsageLookup(
                parent_id=context.parent_id,
                username=SecretStr(username),
                connected_child_ids=tuple(c.child_id for c in context.children if c.connected),
                collected_at=context.collected_at,
            )
        except TimeoutError:
            raise ParentChatError("child_context_unavailable", 503) from None
        except (ValidationError, TypeError, ValueError):
            raise ParentChatError("family_usage_lookup_invalid", 503) from None

    async def _read_profile(self, parent_id: str) -> tuple[ParentChildContext, str]:
        # The documented Parent API is keyed by Parent.pk, not Firebase Auth UID.
        if not parent_id.isascii() or not parent_id.isdecimal() or str(int(parent_id)) != parent_id:
            raise ParentChatError("parent_profile_id_required", 422)
        if not 0 < int(parent_id) <= 2**63 - 1:
            raise ParentChatError("parent_profile_id_required", 422)
        token = await self._access_token()
        try:
            async with self._client.stream(
                "GET",
                self._base + "/api/v1/admin-panel-parent/parent-list/",
                params={"parent_id": parent_id, "limit": 1, "offset": 0},
                headers={"Authorization": f"Bearer {token}"},
                follow_redirects=False,
            ) as response:
                if response.status_code == 401:
                    # The next distinct human request may log in; never replay this read.
                    if self._token == token:
                        self._token = None
                    self._auth_retry_at = time.monotonic() + 60
                payload = await self._read_json(response)
        except httpx.HTTPError:
            raise ParentChatError("child_context_unavailable", 503) from None
        try:
            page = _Page.model_validate(payload)
        except ValidationError:
            raise ParentChatError("child_context_invalid", 503) from None
        if page.count == 0 and not page.results:
            raise ParentChatError("parent_not_found", 404)
        if page.count != 1 or len(page.results) != 1 or page.next:
            raise ParentChatError("child_context_invalid", 503)
        parent = page.results[0]
        if str(parent.id) != parent_id:
            raise ParentChatError("child_context_owner_mismatch", 503)
        if len({child.id for child in parent.children}) != len(parent.children):
            raise ParentChatError("child_context_invalid", 503)
        if parent.children_count is not None and parent.children_count != len(parent.children):
            raise ParentChatError("child_context_incomplete", 503)
        collected_at = self._clock()
        # The raw row is considered only after exact parent and child coverage checks.
        assert isinstance(payload, dict) and isinstance(payload["results"], list)
        tariff = _tariff_context(payload["results"][0], collected_at)
        context = ParentChildContext(
            parent_id=parent_id,
            children=[
                ChatChild(
                    child_id=child.id,
                    name=child.fullname,
                    age=child.age if child.age and child.age < 18 else None,
                    connected=child.is_connected,
                )
                for child in parent.children
            ],
            collected_at=collected_at,
            tariff=tariff,
            limitations=[
                "Verified MANA parent-child profiles only, not behavioral or medical evidence.",
                "Connection is not online status. This profile read contains no location, calls "
                "or app usage; separately supplied backend observations are dated evidence only.",
            ],
        )
        username = payload["results"][0].get("phone")
        return context, username if isinstance(username, str) else ""
