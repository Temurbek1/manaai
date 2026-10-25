"""Reuse settled inventory facts; no second provider read or contact admission."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from app.mana_ai.application.family_collection import (
    CollectionStore,
    FamilyCollectionService,
    FamilyInventorySource,
    SourceObservation,
)
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.domain.family_collection import FamilyCollectionWindow
from app.mana_ai.domain.inventory_tariffs import InventoryTariffWork
from app.mana_ai.domain.retention_expiry import RetentionTariffFact


class InventoryTariffSink(Protocol):
    async def observe_inventory_tariffs(
        self, facts: tuple[RetentionTariffFact, ...], now: datetime
    ) -> bool: ...
    async def close_expiry_source(self) -> None: ...


class InventoryTariffStore(CollectionStore, Protocol):
    async def inventory_auth_revoked(self) -> bool: ...
    async def claim_tariffs(self, now: datetime) -> InventoryTariffWork | None: ...
    async def finish_tariffs(
        self, work: InventoryTariffWork, now: datetime, *, accepted: bool | None
    ) -> None: ...


class TariffCollectionService(FamilyCollectionService):
    def __init__(
        self,
        store: InventoryTariffStore,
        inventory: FamilyInventorySource,
        sources: FamilySourceService,
        observations: SourceObservation,
        *,
        receiver: InventoryTariffSink | None,
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(store, inventory, sources, observations, clock=clock)
        self._tariffs, self._receiver = store, receiver

    async def process_one(self) -> FamilyCollectionWindow | None:
        if self._receiver is None:
            return await super().process_one()
        if await self._tariffs.inventory_auth_revoked():
            await self._receiver.close_expiry_source()
        work = await self._tariffs.claim_tariffs(self._clock())
        if work is not None:
            try:
                accepted = await self._receiver.observe_inventory_tariffs(work.facts, self._clock())
                await self._tariffs.finish_tariffs(work, self._clock(), accepted=accepted)
            except asyncio.CancelledError:
                await asyncio.shield(
                    self._tariffs.finish_tariffs(work, self._clock(), accepted=None)
                )
                raise
            except Exception:
                # A lost completion acknowledgement only observes the same SQL claim.
                await self._tariffs.finish_tariffs(work, self._clock(), accepted=None)
            return await self._tariffs.manifest(work.window_id)
        result = await super().process_one()
        if await self._tariffs.inventory_auth_revoked():
            await self._receiver.close_expiry_source()
        return result
