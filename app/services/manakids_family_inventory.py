"""Finite read-only parent pagination; provider links are never followed."""

import asyncio
import json
from collections.abc import Callable
from datetime import datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.family_collection import FamilyInventoryPage, InventoryFamily
from app.services.manakids_child_usage import ManakidsReadToken
from app.services.parent_chat_children import ManakidsParentProfile


class _InventoryPage(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    count: int = Field(ge=0, le=100000000, strict=True)
    results: list[ManakidsParentProfile] = Field(max_length=100)
    next: str | None = None


class ManakidsFamilyInventory:
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
            raise ValueError("Explicit MANA inventory provider and timeout are required")
        self._client, self._auth, self._clock = client, auth, clock
        self._base, self._timeout = base_url.rstrip("/"), timeout_seconds

    async def read(self, offset: int, limit: int) -> FamilyInventoryPage:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid inventory page")
        async with asyncio.timeout(self._timeout):
            token = await self._auth.access_token()
            if not token or len(token) > 8192 or "\n" in token or "\r" in token:
                raise ParentChatError("family_inventory_auth_denied", 503)
            async with self._client.stream(
                "GET",
                self._base + "/api/v1/admin-panel-parent/parent-list/",
                params={"limit": limit, "offset": offset},
                headers={"Authorization": "Bearer " + token, "Accept-Encoding": "identity"},
                follow_redirects=False,
            ) as response:
                if response.status_code in {401, 403}:
                    raise ParentChatError("family_inventory_auth_denied", 503)
                if response.status_code in {400, 404, 422}:
                    raise ParentChatError("family_inventory_query_invalid", 503)
                if response.status_code != 200:
                    raise ParentChatError("family_inventory_unavailable", 503)
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ValueError("Compressed inventory responses are not admitted")
                raw = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    raw.extend(chunk)
                    if len(raw) > 262144:
                        raise ValueError("Inventory response exceeds its byte ceiling")
                page = _InventoryPage.model_validate(json.loads(raw))
        result = FamilyInventoryPage(
            offset=offset,
            limit=limit,
            total_parents=page.count,
            collected_at=self._clock(),
            families=tuple(
                InventoryFamily(
                    parent_id=str(p.id),
                    connected_child_ids=tuple(c.id for c in p.children if c.is_connected),
                )
                for p in page.results
            ),
        )
        if (page.next is None) != result.exhausted or any(
            len({c.id for c in p.children}) != len(p.children)
            or p.children_count is not None
            and p.children_count != len(p.children)
            for p in page.results
        ):
            raise ValueError("Incomplete inventory coverage")
        return result
