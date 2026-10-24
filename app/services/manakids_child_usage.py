"""One exact-child first page; no assumed date filter, totals or timezone."""

import asyncio
import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.family_sources import AppUsageCounter, ChildAppUsageFacts


class ManakidsReadToken(Protocol):
    async def access_token(self) -> str: ...


class _DailyCounter(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: str = Field(min_length=19, max_length=19, strict=True)
    total_time: str = Field(min_length=7, max_length=10, strict=True)


class _Application(BaseModel):
    model_config = ConfigDict(extra="ignore")
    app: str = Field(min_length=1, max_length=160, strict=True)
    daily_usage: list[_DailyCounter] = Field(min_length=1, max_length=10)


class _UsagePage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    success: StrictBool
    results: list[_Application] = Field(max_length=10)
    total_count: int = Field(ge=0, le=1000000, strict=True)
    current_page: int = Field(ge=1, le=1, strict=True)
    page_count: int = Field(ge=0, le=100000, strict=True)
    per_page: int = Field(ge=1, le=10, strict=True)


class ManakidsChildUsageSource:
    def __init__(
        self,
        client: httpx.AsyncClient,
        auth: ManakidsReadToken,
        *,
        base_url: str,
        clock: Callable[[], datetime],
        timeout_seconds: float = 30,
    ) -> None:
        if base_url.rstrip("/") != "https://api.manakids.uz" or not 1 <= timeout_seconds <= 60:
            raise ValueError("Explicit MANA provider and bounded timeout are required")
        self._client, self._auth, self._clock = client, auth, clock
        self._base, self._timeout = base_url.rstrip("/"), timeout_seconds

    async def read(self, child_id: int) -> ChildAppUsageFacts:
        if type(child_id) is not int or not 0 < child_id <= 2**63 - 1:
            raise ValueError("A canonical child ID is required")
        async with asyncio.timeout(self._timeout):
            token = await self._auth.access_token()
            if not token or len(token) > 8192 or "\n" in token or "\r" in token:
                raise ParentChatError("family_source_auth_denied", 503)
            async with self._client.stream(
                "GET",
                f"{self._base}/api/v1/admin-panel-child/app-usage-statistics/{child_id}/",
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
                    if len(data) > 65536:
                        raise ValueError("Usage response exceeds its byte ceiling")
                page = _UsagePage.model_validate(json.loads(data))
        if (
            not page.success
            or len(page.results) != min(page.per_page, page.total_count)
            or (page.page_count != (page.total_count + page.per_page - 1) // page.per_page)
        ):
            raise ValueError("Incomplete or inconsistent usage page")
        entries = []
        for row in page.results:
            for counter in row.daily_usage:
                # Preserve a provider calendar label without inventing its timezone
                # or silently converting its timestamp into a measurement period.
                datetime.strptime(counter.date, "%Y-%m-%d %H:%M:%S")
                if not re.fullmatch(r"\d{1,3}:\d{2}:\d{2}", counter.total_time):
                    raise ValueError("Unknown provider duration format")
                hours, minutes, seconds = map(int, counter.total_time.split(":"))
                if minutes > 59 or seconds > 59:
                    raise ValueError("Invalid provider duration")
                entries.append(
                    AppUsageCounter(
                        app_name=row.app,
                        provider_recorded_at=counter.date,
                        reported_seconds=hours * 3600 + minutes * 60 + seconds,
                    )
                )
        return ChildAppUsageFacts(
            child_id=child_id,
            status="available" if page.total_count else "missing",
            entries=tuple(entries),
            returned_apps=len(page.results),
            total_apps=page.total_count,
            complete=len(page.results) == page.total_count,
            collected_at=self._clock(),
        )
