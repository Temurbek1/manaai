"""Conversion proposes; Parent-Touch alone owns publication in the parent's chat."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.mana_ai.application.conversion_grants import TrialGrantService
from app.mana_ai.domain.chat import ParentChatRequest, ResponseLanguage
from app.mana_ai.domain.conversion import (
    ConversionAdmission,
    ConversionOffer,
    ConversionOutcome,
    ConversionProposal,
    ConversionProposalPage,
    ConversionSnapshot,
)

OfferRenderer = Callable[[ConversionOffer, int, ResponseLanguage], str]


class ConversionStore(Protocol):
    async def suppress_from_message(self, request: ParentChatRequest, now: datetime) -> None: ...
    async def suppress_conversion(self, parent_id: str, now: datetime) -> None: ...
    async def ingest_conversion(
        self, snapshot: ConversionSnapshot, now: datetime
    ) -> ConversionAdmission: ...

    async def conversion_outcome(
        self, outcome: ConversionOutcome, now: datetime
    ) -> ConversionProposal: ...

    async def conversion_proposals(
        self, parent_id: str, after: int, limit: int
    ) -> ConversionProposalPage: ...

    async def conversion_proposal(
        self, parent_id: str, proposal_id: UUID
    ) -> ConversionProposal: ...

    async def publish_conversion(self, now: datetime, renderer: OfferRenderer) -> bool: ...
    async def publish_trial_result(self, now: datetime) -> bool: ...


class ConversionService:
    def __init__(
        self,
        store: ConversionStore,
        *,
        clock: Callable[[], datetime],
        grants: TrialGrantService | None = None,
    ) -> None:
        self._store, self._clock = store, clock
        self.grants = grants

    async def observe(self, snapshot: ConversionSnapshot) -> ConversionAdmission:
        return await self._store.ingest_conversion(snapshot, self._clock())

    async def opt_out(self, parent_id: str) -> None:
        await self._store.suppress_conversion(parent_id, self._clock())

    async def observe_parent_message(self, request: ParentChatRequest) -> None:
        # A conservative exact negative preference, never a purchase/positive
        # consent inferred by a model. Works even when the paid chat quota is full.
        normalized = request.message.strip().strip(".!? ").casefold().replace("’", "'")
        if normalized in {
            "не присылай предложения",
            "не присылайте предложения",
            "не хочу рекламу",
            "не присылай рекламу",
            "отпиши от предложений",
            "отписаться от предложений",
            "stop offers",
            "no more offers",
            "unsubscribe",
            "stop promotions",
            "taklif yubormang",
            "takliflarni yubormang",
            "reklama yubormang",
            "таклиф юборманг",
            "реклама юборманг",
        }:
            await self._store.suppress_from_message(request, self._clock())

    async def outcome(self, outcome: ConversionOutcome) -> ConversionProposal:
        return await self._store.conversion_outcome(outcome, self._clock())

    async def proposals(self, parent_id: str, *, after: int, limit: int) -> ConversionProposalPage:
        return await self._store.conversion_proposals(parent_id, after, limit)

    async def proposal(self, parent_id: str, proposal_id: UUID) -> ConversionProposal:
        return await self._store.conversion_proposal(parent_id, proposal_id)

    async def communicate(self, renderer: OfferRenderer) -> bool:
        # Called only by the host's Parent-Touch communication loop, never GET.
        if await self._store.publish_trial_result(self._clock()):
            return True
        return await self._store.publish_conversion(self._clock(), renderer)
