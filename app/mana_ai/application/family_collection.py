"""One common acquisition loop; model analysis/contact policies stay independent."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.domain.family_collection import (
    FamilyCollectionWindow,
    FamilyCollectionWork,
    FamilyInventoryPage,
)
from app.mana_ai.domain.family_day_usage import DayUsageReceipt, DayUsageTarget
from app.mana_ai.domain.family_sources import FamilySourceReceipt, FamilySourceTarget


class FamilyInventorySource(Protocol):
    async def read(self, offset: int, limit: int) -> FamilyInventoryPage: ...


class CollectionStore(Protocol):
    @property
    def page_size(self) -> int: ...
    async def claim_next(
        self, now: datetime
    ) -> FamilyCollectionWork | FamilyCollectionWindow | None: ...
    async def finish_page(
        self, work: FamilyCollectionWork, page: FamilyInventoryPage, now: datetime
    ) -> None: ...
    async def fail_page(
        self, work: FamilyCollectionWork, code: str, now: datetime, *, unknown: bool
    ) -> None: ...
    async def finish_source(
        self,
        work: FamilyCollectionWork,
        receipt: FamilySourceReceipt | DayUsageReceipt | None,
        now: datetime,
        *,
        refusal: str | None = None,
        stop_window: bool = False,
    ) -> None: ...
    async def manifest(self, identity: UUID) -> FamilyCollectionWindow: ...
    async def latest(self, limit: int = 10) -> tuple[FamilyCollectionWindow, ...]: ...


class SourceObservation(Protocol):
    async def observation(self, target: FamilySourceTarget) -> FamilySourceReceipt: ...


class FamilyCollectionService:
    def __init__(
        self,
        store: CollectionStore,
        inventory: FamilyInventorySource,
        sources: FamilySourceService,
        observations: SourceObservation,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._store, self._inventory, self._sources, self._observations, self._clock = (
            store,
            inventory,
            sources,
            observations,
            clock,
        )

    async def windows(self, limit: int = 10) -> tuple[FamilyCollectionWindow, ...]:
        return await self._store.latest(limit)

    async def _read_source(
        self, target: FamilySourceTarget | DayUsageTarget
    ) -> FamilySourceReceipt | DayUsageReceipt:
        if isinstance(target, DayUsageTarget):
            raise ParentChatError("family_source_not_enabled", 503)
        return await self._sources.read(target)

    async def _observe_source(
        self, target: FamilySourceTarget | DayUsageTarget
    ) -> FamilySourceReceipt | DayUsageReceipt:
        if isinstance(target, DayUsageTarget):
            raise ParentChatError("family_source_not_enabled", 503)
        return await self._observations.observation(target)

    async def process_one(self) -> FamilyCollectionWindow | None:
        work = await self._store.claim_next(self._clock())
        if work is None or isinstance(work, FamilyCollectionWindow):
            return work
        if work.kind == "inventory":
            try:
                page = await self._inventory.read(work.offset, self._store.page_size)
                await self._store.finish_page(work, page, self._clock())
            except asyncio.CancelledError:
                await asyncio.shield(
                    self._store.fail_page(work, "inventory_unknown", self._clock(), unknown=True)
                )
                raise
            except ParentChatError as error:
                permanent = error.code in {
                    "family_inventory_auth_denied",
                    "family_inventory_query_invalid",
                    "child_source_auth_denied",
                }
                await self._store.fail_page(
                    work,
                    error.code if permanent else "inventory_unknown",
                    self._clock(),
                    unknown=not permanent,
                )
            except (ValueError, TypeError):
                await self._store.fail_page(work, "inventory_invalid", self._clock(), unknown=False)
            except Exception:
                # A lost local completion acknowledgement is observed in SQL by fail_page.
                await self._store.fail_page(work, "inventory_unknown", self._clock(), unknown=True)
        else:
            assert work.target is not None
            if work.kind == "observe_source":
                await self._observe(work)
            else:
                try:
                    receipt = await self._read_source(work.target)
                    await self._store.finish_source(work, receipt, self._clock())
                except asyncio.CancelledError:
                    await asyncio.shield(self._observe(work))
                    raise
                except ParentChatError as error:
                    known = error.code in {
                        "family_source_circuit_open",
                        "family_source_read_unresolved",
                        "family_source_read_cooldown",
                        "family_source_request_limit",
                        "family_source_document_limit",
                        "family_source_not_enabled",
                    }
                    if known:
                        await self._store.finish_source(
                            work,
                            None,
                            self._clock(),
                            refusal=error.code,
                            stop_window=error.code
                            in {"family_source_request_limit", "family_source_document_limit"},
                        )
                    else:
                        await self._observe(work)
                except Exception:
                    await self._observe(work)
        return await self._store.manifest(work.window_id)

    async def _observe(self, work: FamilyCollectionWork) -> None:
        assert work.target is not None
        try:
            receipt = await self._observe_source(work.target)
        except ParentChatError as error:
            if error.code != "family_source_request_not_found":
                raise
            receipt = None  # Absence is not permission to dispatch the unknown claim again.
        await self._store.finish_source(work, receipt, self._clock())
