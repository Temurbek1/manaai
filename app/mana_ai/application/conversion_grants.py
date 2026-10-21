"""A bounded, non-retrying write after an explicit account-bound parent acceptance."""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from app.mana_ai.domain.conversion_grants import TrialAcceptance, TrialGrantResult, TrialGrantState


class TrialGrantRejected(Exception):
    """A definitive refusal; no purchase/transaction was created by this request."""

    def __init__(self, code: str) -> None:
        self.code = code


class TrialGrantGateway(Protocol):
    async def grant(self, parent_id: str, days: int) -> TrialGrantResult: ...


class TrialGrantStore(Protocol):
    async def trial_grant(self, parent_id: str) -> TrialGrantState: ...
    async def claim_trial_grant(
        self, acceptance: TrialAcceptance, now: datetime
    ) -> tuple[TrialGrantState, bool]: ...

    async def finish_trial_grant(
        self, state: TrialGrantState, now: datetime
    ) -> TrialGrantState: ...


class TrialGrantService:
    def __init__(
        self, store: TrialGrantStore, gateway: TrialGrantGateway, *, clock: Callable[[], datetime]
    ) -> None:
        self._store, self._gateway, self._clock = store, gateway, clock

    async def state(self, parent_id: str) -> TrialGrantState:
        return await self._store.trial_grant(parent_id)

    async def accept(self, acceptance: TrialAcceptance) -> TrialGrantState:
        state, dispatch = await self._store.claim_trial_grant(acceptance, self._clock())
        if not dispatch:
            return state
        try:
            async with asyncio.timeout(45):
                result = await self._gateway.grant(state.parent_id, state.days)
            expected_end = self._clock() + timedelta(days=state.days)
            if (
                result.parent_id != state.parent_id
                or abs((result.valid_until - expected_end).total_seconds()) > 300
            ):
                raise ValueError("Provider receipt does not verify this grant")
            updated = state.model_copy(update={"status": "granted", "result": result})
        except TrialGrantRejected as exc:
            updated = state.model_copy(update={"status": "rejected", "error_code": exc.code})
        except (Exception, asyncio.CancelledError) as exc:
            updated = state.model_copy(
                update={"status": "unknown", "error_code": "trial_grant_outcome_unknown"}
            )
            await asyncio.shield(self._store.finish_trial_grant(updated, self._clock()))
            if isinstance(exc, asyncio.CancelledError):
                raise
            return updated
        return await self._store.finish_trial_grant(updated, self._clock())
