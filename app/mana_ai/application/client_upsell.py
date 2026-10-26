"""Model-selected needs, bounded shared catalogue and exact host-owned price quotes."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Protocol

from app.mana_ai.application.chat_ports import ParentChatError, ParentChildrenSource
from app.mana_ai.application.conversion_catalog import ConversionCatalogSource
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.client_upsell import (
    CatalogAdmission,
    CatalogReadClaim,
    UpsellChoice,
    UpsellQuote,
    UpsellScope,
    UpsellWork,
)
from app.mana_ai.domain.conversion_catalog import ConversionCatalogObservation
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest, ParentTouchMessageState


def select_tariffs(
    choice: UpsellChoice, catalog: ConversionCatalogObservation, *, now: datetime
) -> UpsellQuote:
    choice = UpsellChoice.model_validate(choice.model_dump())
    catalog = ConversionCatalogObservation.model_validate(catalog.model_dump())
    if not now - timedelta(hours=6) <= catalog.collected_at <= now:
        raise ParentChatError("upsell_catalog_not_current", 409)
    options = [
        t
        for t in catalog.tariffs
        if t.currency == choice.currency
        and choice.minimum_days <= t.duration_days <= choice.maximum_days
        and (choice.maximum_price_minor is None or t.price_minor <= choice.maximum_price_minor)
    ]
    options.sort(
        key=lambda t: (
            Fraction(t.price_minor, t.duration_days)
            if choice.objective == "lowest_daily"
            else t.price_minor,
            t.duration_days,
            t.tariff_id,
        )
    )
    return UpsellQuote(
        catalog_collected_at=catalog.collected_at,
        options=tuple(options[: 3 if choice.objective == "list" else 1]),
        objective=choice.objective,
    )


class ClientUpsellStore(Protocol):
    async def upsell_currency_control(
        self, request: ParentTouchMessageRequest, now: datetime
    ) -> ParentTouchMessageState | None: ...
    async def upsell_scope(self, parent_id: str, turn_id: int) -> UpsellScope | None: ...
    async def claim_upsell(self, now: datetime) -> UpsellWork | None: ...
    async def upsell_active(self, work: UpsellWork, now: datetime) -> bool: ...
    async def catalog_admission(self, now: datetime) -> CatalogAdmission: ...
    async def catalog_result(
        self, claim: CatalogReadClaim
    ) -> ConversionCatalogObservation | None: ...
    async def finish_catalog(
        self,
        claim: CatalogReadClaim,
        now: datetime,
        *,
        snapshot: ConversionCatalogObservation | None,
    ) -> None: ...
    async def finish_upsell(
        self,
        work: UpsellWork,
        now: datetime,
        *,
        quote: UpsellQuote | None,
        context_at: datetime | None,
        error: str | None = None,
    ) -> None: ...
    async def publish_ready_upsell(self, now: datetime) -> bool: ...


class ClientUpsellService:
    def __init__(
        self,
        store: ClientUpsellStore,
        source: ConversionCatalogSource,
        children: ParentChildrenSource,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._store, self._source, self._children, self._clock = store, source, children, clock

    async def scope(self, parent_id: str, turn_id: int) -> UpsellScope | None:
        return await self._store.upsell_scope(parent_id, turn_id)

    async def control(self, request: ParentTouchMessageRequest) -> ParentTouchMessageState | None:
        return await self._store.upsell_currency_control(request, self._clock())

    async def process_one(self) -> bool:
        if await self._store.publish_ready_upsell(self._clock()):
            return True
        work = await self._store.claim_upsell(self._clock())
        if work is None:
            return False
        context_at = None
        try:
            raw = await self._children.read(work.intent.parent_id)
            context = ParentChildContext.model_validate(raw.model_dump())
            now = self._clock()
            if (
                context.parent_id != work.intent.parent_id
                or not now - timedelta(seconds=180) <= context.collected_at <= now
            ):
                raise ParentChatError("upsell_ownership_denied", 403)
            context_at = context.collected_at
            if not await self._store.upsell_active(work, self._clock()):
                return True
            admitted = await self._store.catalog_admission(self._clock())
            snapshot = admitted.snapshot
            if admitted.claim:
                try:
                    snapshot = await self._source.read()
                    await self._store.finish_catalog(
                        admitted.claim, self._clock(), snapshot=snapshot
                    )
                except BaseException as exc:
                    await asyncio.shield(
                        self._store.finish_catalog(admitted.claim, self._clock(), snapshot=None)
                    )
                    if isinstance(exc, asyncio.CancelledError):
                        raise
                    snapshot = await self._store.catalog_result(admitted.claim)
                    if snapshot is None:
                        raise
            if snapshot is None:
                raise ParentChatError("upsell_catalog_unavailable", 503)
            quote = select_tariffs(work.intent.choice, snapshot, now=self._clock())
            await self._store.finish_upsell(
                work, self._clock(), quote=quote, context_at=context.collected_at
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self._store.finish_upsell(
                    work, self._clock(), quote=None, context_at=None, error="upsell_outcome_unknown"
                )
            )
            raise
        except Exception:
            await self._store.finish_upsell(
                work,
                self._clock(),
                quote=None,
                context_at=context_at,
                error="upsell_catalog_unavailable",
            )
        return True
