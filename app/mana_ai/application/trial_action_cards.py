"""Reuse the owning one-time grant executor after a durable button confirmation."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from app.mana_ai.application.conversion_grants import (
    TrialGrantGateway,
    TrialGrantService,
    TrialGrantStore,
)
from app.mana_ai.domain.conversion_grants import TrialButtonAcceptance, TrialGrantState


class TrialButtonGrantStore(TrialGrantStore, Protocol):
    async def claim_button_trial(
        self, acceptance: TrialButtonAcceptance, now: datetime
    ) -> tuple[TrialGrantState, bool]: ...


class TrialButtonGrantService(TrialGrantService):
    def __init__(
        self,
        store: TrialButtonGrantStore,
        gateway: TrialGrantGateway,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        super().__init__(store, gateway, clock=clock)
        self._button_store = store

    async def accept_button(self, acceptance: TrialButtonAcceptance) -> TrialGrantState:
        state, dispatch = await self._button_store.claim_button_trial(acceptance, self._clock())
        return await self._dispatch(state, dispatch)
