"""One-shot local fan-out after a known inventory page, without another acquisition."""

import asyncio
from datetime import datetime
from typing import Any, Protocol

from app.mana_ai.application.dated_collection import DatedCollectionService
from app.mana_ai.application.inventory_tariffs import InventoryTariffStore
from app.mana_ai.application.parent_setup import ParentSetupSink
from app.mana_ai.domain.family_collection import FamilyCollectionWindow
from app.mana_ai.domain.parent_setup import SetupInventoryWork


class SetupInventoryStore(InventoryTariffStore, Protocol):
    async def claim_setup(self, now: datetime) -> SetupInventoryWork | None: ...
    async def finish_setup(
        self, work: SetupInventoryWork, now: datetime, *, accepted: bool | None
    ) -> None: ...


class SetupCollectionService(DatedCollectionService):
    def __init__(
        self,
        *,
        store: SetupInventoryStore,
        setup_receiver: ParentSetupSink | None,
        **collection: Any,
    ) -> None:
        self._setup_store, self._setup_receiver = store, setup_receiver
        super().__init__(store=store, **collection)

    async def process_one(self) -> FamilyCollectionWindow | None:
        if self._setup_receiver is not None:
            if await self._setup_store.inventory_auth_revoked():
                await self._setup_receiver.close_setup_source()
            work = await self._setup_store.claim_setup(self._clock())
            if work is not None:
                try:
                    for parent_id in work.unknown_parent_ids:
                        await self._setup_receiver.invalidate_setup_profile(
                            parent_id, work.collected_at
                        )
                    accepted = await self._setup_receiver.observe_setup_facts(
                        work.facts, self._clock()
                    )
                    await self._setup_store.finish_setup(work, self._clock(), accepted=accepted)
                except asyncio.CancelledError:
                    await asyncio.shield(
                        self._setup_store.finish_setup(work, self._clock(), accepted=None)
                    )
                    raise
                except Exception:
                    await self._setup_store.finish_setup(work, self._clock(), accepted=None)
                return await self._setup_store.manifest(work.window_id)
        result = await super().process_one()
        if self._setup_receiver is not None and await self._setup_store.inventory_auth_revoked():
            await self._setup_receiver.close_setup_source()
        return result
