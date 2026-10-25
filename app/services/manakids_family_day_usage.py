"""One scoped first page for a completed query day, without inferred screen time."""

import asyncio
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.family_day_usage import ParentUsageIdentitySource
from app.mana_ai.domain.family_day_usage import FamilyDayUsagePage, ParentUsageLookup
from app.services.manakids_child_usage import ManakidsReadToken, _UsagePage, usage_counter_facts


class _ChildUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    id: int = Field(gt=0, le=2**63 - 1, strict=True)
    app_usage_statistics: _UsagePage


class _FamilyUsagePage(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    success: StrictBool
    results: list[_ChildUsage] = Field(max_length=10)
    total_count: int = Field(ge=0, le=20, strict=True)
    current_page: int = Field(ge=1, le=1, strict=True)
    page_count: int = Field(ge=0, le=20, strict=True)
    per_page: int = Field(ge=1, le=10, strict=True)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Ambiguous family-usage response")
        result[key] = value
    return result


class ManakidsFamilyDayUsageSource:
    """Not runtime-enabled: caller owns durable admission, costs and unknown holds.

    This adapter is an independently qualified source port, not another scheduler
    or authority for old native app-counter tools. It performs one ownership GET
    and one date-filtered usage GET, reusing the server authentication port.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        auth: ManakidsReadToken,
        identities: ParentUsageIdentitySource,
        *,
        base_url: str,
        clock: Callable[[], datetime],
        timeout_seconds: float = 60,
    ) -> None:
        if base_url.rstrip("/") != "https://api.manakids.uz" or not 1 <= timeout_seconds <= 60:
            raise ValueError("Explicit MANA origin and bounded family-read timeout are required")
        self._client, self._auth, self._identities, self._clock = client, auth, identities, clock
        self._base, self._timeout = base_url.rstrip("/"), timeout_seconds

    async def read(self, parent_id: str, requested_day: date) -> FamilyDayUsagePage:
        try:
            async with asyncio.timeout(self._timeout):
                return await self._read(parent_id, requested_day)
        except ParentChatError:
            raise
        except (httpx.HTTPError, TimeoutError):
            raise ParentChatError("family_day_usage_unavailable", 503) from None
        except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
            raise ParentChatError("family_day_usage_invalid", 503) from None

    async def _read(self, parent_id: str, requested_day: date) -> FamilyDayUsagePage:
        self._validate_day(requested_day)
        lookup = await self._identities.read_usage_lookup(parent_id)
        if lookup.parent_id != parent_id:
            raise ParentChatError("family_day_usage_owner_or_date_invalid", 403)
        return await self._read_verified(lookup, requested_day)

    def _validate_day(self, requested_day: date) -> None:
        now = self._clock()
        if now.utcoffset() is None or type(requested_day) is not date:
            raise ValueError("Aware source clock and exact query day are required")
        delta = (now.astimezone(ZoneInfo("Asia/Tashkent")).date() - requested_day).days
        if not 1 <= delta <= 31:
            raise ParentChatError("family_day_usage_day_outside_window", 422)

    async def read_verified(
        self, lookup: ParentUsageLookup, requested_day: date
    ) -> FamilyDayUsagePage:
        try:
            async with asyncio.timeout(self._timeout):
                return await self._read_verified(lookup, requested_day)
        except ParentChatError:
            raise
        except (httpx.HTTPError, TimeoutError):
            raise ParentChatError("family_day_usage_unavailable", 503) from None
        except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError):
            raise ParentChatError("family_day_usage_invalid", 503) from None

    async def _read_verified(
        self, lookup: ParentUsageLookup, requested_day: date
    ) -> FamilyDayUsagePage:
        self._validate_day(requested_day)
        now = self._clock()
        lookup = ParentUsageLookup.model_validate(vars(lookup))
        if not now - timedelta(seconds=180) <= lookup.collected_at <= now:
            raise ParentChatError("family_day_usage_owner_or_date_invalid", 403)
        if not lookup.connected_child_ids:
            raise ParentChatError("family_day_usage_no_connected_children", 409)
        token = await self._auth.access_token()
        if not token or len(token) > 8192 or "\n" in token or "\r" in token:
            raise ParentChatError("family_day_usage_auth_denied", 503)
        async with self._client.stream(
            "GET",
            self._base + "/api/v1/admin-panel-child/app-usage-statistics/",
            params={
                "username": lookup.username.get_secret_value(),
                "start_date": requested_day.isoformat(),
                "end_date": requested_day.isoformat(),
                "page": 1,
            },
            headers={"Authorization": "Bearer " + token, "Accept-Encoding": "identity"},
            follow_redirects=False,
        ) as response:
            if response.status_code in {401, 403}:
                raise ParentChatError("family_day_usage_auth_denied", 503)
            if response.status_code in {400, 404, 422}:
                raise ParentChatError("family_day_usage_query_invalid", 503)
            if response.status_code != 200:
                raise ParentChatError("family_day_usage_unavailable", 503)
            if response.headers.get("content-encoding", "identity") != "identity":
                raise ValueError("Compressed family usage is not admitted")
            data = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=4096):
                data.extend(chunk)
                if len(data) > 262144:
                    raise ValueError("Family usage exceeds its byte ceiling")
            page = _FamilyUsagePage.model_validate(
                json.loads(data, object_pairs_hook=_unique_object)
            )
        expected_pages = (
            {0, 1}
            if page.total_count == 0
            else {(page.total_count + page.per_page - 1) // page.per_page}
        )
        if (
            not page.success
            or len(page.results) != min(page.per_page, page.total_count)
            or page.page_count not in expected_pages
            or len({c.id for c in page.results}) != len(page.results)
        ):
            raise ValueError("Inconsistent family usage pagination")
        owned = set(lookup.connected_child_ids)
        if any(c.id not in owned for c in page.results) or page.total_count > len(owned):
            raise ParentChatError("family_day_usage_child_not_authorized", 403)
        collected = self._clock()
        return FamilyDayUsagePage(
            parent_id=lookup.parent_id,
            requested_day=requested_day,
            ownership_collected_at=lookup.collected_at,
            collected_at=collected,
            owned_children_count=len(owned),
            provider_children_count=page.total_count,
            children=tuple(
                usage_counter_facts(
                    c.id, c.app_usage_statistics, collected, requested_day=requested_day
                )
                for c in page.results
            ),
            complete_family=len(page.results) == page.total_count == len(owned),
        )
