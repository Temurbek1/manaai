"""Dispatcher contracts with fake ports, not SQL, device delivery or live acceptance."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.parent_notifications import ParentPushRejected, ParentPushUnknown
from app.mana_ai.application.proactive_parent import ProactiveParentService
from app.mana_ai.domain.parent_notifications import ParentPushMessage, ParentPushReceipt
from app.mana_ai.domain.proactive_parent import (
    ParentContactContext,
    ParentPushClaim,
    ParentPushOutcome,
    ParentPushPage,
    ParentPushState,
)

NOW = datetime(2026, 10, 22, 7, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def contact() -> ParentContactContext:
    return ParentContactContext(
        parent_id="123",
        event_id=uuid4(),
        revision=1,
        observed_at=NOW,
        valid_until=NOW + timedelta(days=1),
        language="uz-Latn",
        timezone="Asia/Samarkand",
        safety_chat_consent=True,
        safety_push_consent=True,
        marketing_push_consent=False,
    )


def pending(*, parent_id: str = "123", turn_id: int = 1) -> ParentPushClaim:
    return ParentPushClaim(
        notification=ParentPushState(
            push_id=uuid4(),
            parent_id=parent_id,
            turn_id=turn_id,
            purpose="safety",
            status="queued",
            created_at=NOW,
            updated_at=NOW,
        ),
        claim_id=uuid4(),
        title="MANA",
        description="Siz uchun yangi xabar bor.",
    )


class Store:
    """Models durable consume-once claims; actual SQLite invariants are tested elsewhere."""

    def __init__(self, *claims: ParentPushClaim) -> None:
        self.pending = list(claims)
        self.states = {claim.notification.push_id: claim.notification for claim in claims}
        self.claim_calls: list[datetime] = []
        self.finish_calls: list[tuple[ParentPushClaim, ParentPushOutcome, datetime]] = []
        self.contexts: dict[str, ParentContactContext] = {}
        self.context_writes: list[tuple[ParentContactContext, datetime]] = []
        self.reads: list[tuple[str, str]] = []

    async def ingest_contact_context(
        self, context: ParentContactContext, now: datetime
    ) -> ParentContactContext:
        self.contexts[context.parent_id] = context
        self.context_writes.append((context, now))
        return context

    async def contact_context(self, parent_id: str, now: datetime) -> ParentContactContext:
        self.reads.append(("context", parent_id))
        return self.contexts[parent_id]

    async def claim_push(self, now: datetime) -> ParentPushClaim | None:
        self.claim_calls.append(now)
        if not self.pending:
            return None
        claim = self.pending.pop(0)
        state = claim.notification.model_copy(update={"status": "submitting", "updated_at": now})
        self.states[state.push_id] = state
        return replace(claim, notification=state)

    async def finish_push(
        self, claim: ParentPushClaim, outcome: ParentPushOutcome, now: datetime
    ) -> ParentPushState:
        self.finish_calls.append((claim, outcome, now))
        assert self.states[claim.notification.push_id].status == "submitting"
        state = claim.notification.model_copy(update=outcome.model_dump() | {"updated_at": now})
        self.states[state.push_id] = state
        return state

    async def pushes(self, parent_id: str, *, after: int, limit: int) -> ParentPushPage:
        self.reads.append(("pushes", parent_id))
        states = [state for state in self.states.values() if state.parent_id == parent_id]
        return ParentPushPage(parent_id=parent_id, pushes=states[after : after + limit])

    async def push(self, parent_id: str, push_id: UUID) -> ParentPushState:
        self.reads.append(("push", parent_id))
        state = self.states[push_id]
        if state.parent_id != parent_id:
            raise ParentChatError("parent_push_not_found", 404)
        return state


class Gateway:
    def __init__(self, *results: ParentPushReceipt | Exception) -> None:
        self.results = list(results)
        self.messages: list[ParentPushMessage] = []

    async def send(self, message: ParentPushMessage) -> ParentPushReceipt:
        self.messages.append(message)
        assert self.results, "Unexpected additional provider dispatch"
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.parametrize("queued_devices", [0, 1, 4])
async def test_verified_queue_receipts_preserve_exact_chat_binding_without_delivery_claims(
    queued_devices: int,
) -> None:
    claim, clock = pending(), Clock()
    store = Store(claim)
    gateway = Gateway(ParentPushReceipt(queued_devices=queued_devices))
    service = ProactiveParentService(store, clock=clock, gateway=gateway)

    state = await service.process_one()

    assert state is not None
    assert state.status == ("queued_by_provider" if queued_devices else "not_queued")
    assert state.queued_devices == queued_devices
    assert state.error_code == (None if queued_devices else "parent_push_no_registered_devices")
    assert state.push_id == claim.notification.push_id
    assert state.parent_id == claim.notification.parent_id
    assert state.turn_id == claim.notification.turn_id
    assert state.purpose == claim.notification.purpose
    assert state.created_at == claim.notification.created_at
    assert gateway.messages == [claim.message]
    assert len(store.finish_calls) == 1
    assert await service.process_one() is None
    restarted = ProactiveParentService(store, clock=clock, gateway=gateway)
    assert await restarted.process_one() is None
    assert gateway.messages == [claim.message]
    assert await restarted.push("123", state.push_id) == state
    assert len(store.finish_calls) == 1


@pytest.mark.parametrize(
    ("failure", "status", "error_code"),
    [
        (
            ParentPushRejected("parent_push_invalid_message", 400),
            "not_queued",
            "parent_push_invalid_message",
        ),
        (
            ParentPushRejected("parent_push_parent_not_found", 404),
            "not_queued",
            "parent_push_parent_not_found",
        ),
        (
            ParentPushUnknown("parent_push_outcome_unknown"),
            "unknown",
            "parent_push_outcome_unknown",
        ),
        (RuntimeError("private upstream response"), "unknown", "parent_push_outcome_unknown"),
    ],
)
async def test_non_auth_failures_close_one_claim_without_replaying_or_pausing_other_work(
    failure: Exception, status: str, error_code: str
) -> None:
    first, second = pending(), pending(parent_id="456", turn_id=2)
    store, clock = Store(first, second), Clock()
    gateway = Gateway(failure, ParentPushReceipt(queued_devices=1))
    service = ProactiveParentService(store, clock=clock, gateway=gateway)

    state = await service.process_one()

    assert state is not None and state.status == status
    assert state.error_code == error_code and state.queued_devices is None
    assert "private upstream" not in state.model_dump_json()
    assert len(store.claim_calls) == len(store.finish_calls) == len(gateway.messages) == 1
    next_state = await service.process_one()
    assert next_state is not None and next_state.push_id == second.notification.push_id
    assert next_state.status == "queued_by_provider"
    assert gateway.messages == [first.message, second.message]
    assert (await service.push("123", first.notification.push_id)) == state
    assert await service.process_one() is None
    assert len(gateway.messages) == len(store.finish_calls) == 2


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        (ParentPushRejected("parent_push_auth_rejected", 401), "not_queued"),
        (ParentPushRejected("parent_push_not_authorized", 403), "not_queued"),
        (ParentPushUnknown("parent_push_auth_unavailable"), "unknown"),
    ],
)
async def test_auth_failure_pauses_before_claiming_next_action_for_exactly_sixty_seconds(
    failure: Exception, expected_status: str
) -> None:
    first, second = pending(), pending(parent_id="456", turn_id=2)
    store, clock = Store(first, second), Clock()
    gateway = Gateway(failure, ParentPushReceipt(queued_devices=2))
    service = ProactiveParentService(store, clock=clock, gateway=gateway)

    failed = await service.process_one()

    assert failed is not None and failed.status == expected_status
    assert await service.process_one() is None
    clock.now = NOW + timedelta(seconds=59, microseconds=999_999)
    assert await service.process_one() is None
    assert store.claim_calls == [NOW]
    assert store.pending == [second]
    assert gateway.messages == [first.message]
    clock.now = NOW + timedelta(seconds=60)
    state = await service.process_one()
    assert state is not None and state.push_id == second.notification.push_id
    assert state.status == "queued_by_provider"
    assert store.claim_calls == [NOW, clock.now]
    assert gateway.messages == [first.message, second.message]
    assert await service.push("123", first.notification.push_id) == failed


async def test_context_registration_and_status_reads_never_claim_or_send() -> None:
    claim, clock = pending(), Clock()
    store, gateway = Store(claim), Gateway(ParentPushReceipt(queued_devices=1))
    service = ProactiveParentService(store, clock=clock, gateway=gateway)
    context = contact()

    assert await service.register(context) == context
    assert await service.register(context) == context
    assert store.context_writes == [(context, NOW), (context, NOW)]
    assert await service.context("123") == context
    assert (await service.pushes("123", after=0, limit=20)).pushes == [claim.notification]
    assert not (await service.pushes("456", after=0, limit=20)).pushes
    assert await service.push("123", claim.notification.push_id) == claim.notification
    with pytest.raises(ParentChatError, match="parent_push_not_found"):
        await service.push("456", claim.notification.push_id)
    assert not store.claim_calls and not store.finish_calls and not gateway.messages
    assert store.pending == [claim]


async def test_disabled_gateway_and_empty_queue_never_dispatch() -> None:
    claim, clock = pending(), Clock()
    store = Store(claim)
    service = ProactiveParentService(store, clock=clock)
    assert await service.process_one() is None
    assert store.claim_calls == store.finish_calls == []
    assert store.pending == [claim]
    empty, gateway = Store(), Gateway()
    assert await ProactiveParentService(empty, clock=clock, gateway=gateway).process_one() is None
    assert empty.claim_calls == [NOW]
    assert not empty.finish_calls and not gateway.messages


class BlockingGateway:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.messages: list[ParentPushMessage] = []

    async def send(self, message: ParentPushMessage) -> ParentPushReceipt:
        self.messages.append(message)
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("The test must cancel the pending provider call")


class BlockingFinishStore(Store):
    def __init__(self, claim: ParentPushClaim) -> None:
        super().__init__(claim)
        self.finish_started = asyncio.Event()
        self.finish_allowed = asyncio.Event()

    async def finish_push(
        self, claim: ParentPushClaim, outcome: ParentPushOutcome, now: datetime
    ) -> ParentPushState:
        self.finish_started.set()
        await self.finish_allowed.wait()
        return await super().finish_push(claim, outcome, now)


async def test_cancelled_provider_call_finishes_unknown_before_propagating_cancellation() -> None:
    claim, clock = pending(), Clock()
    store, gateway = BlockingFinishStore(claim), BlockingGateway()
    service = ProactiveParentService(store, clock=clock, gateway=gateway)
    task = asyncio.create_task(service.process_one())
    try:
        await asyncio.wait_for(gateway.started.wait(), timeout=1)
        task.cancel()
        await asyncio.wait_for(store.finish_started.wait(), timeout=1)
        assert not task.done()
        assert store.states[claim.notification.push_id].status == "submitting"
        assert not store.pending
        store.finish_allowed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        store.finish_allowed.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    state = await service.push("123", claim.notification.push_id)
    assert state.status == "unknown"
    assert state.error_code == "parent_push_outcome_unknown"
    assert state.queued_devices is None
    assert len(store.finish_calls) == 1
    restarted = ProactiveParentService(store, clock=clock, gateway=gateway)
    assert await restarted.process_one() is None
    assert gateway.messages == [claim.message]
    assert (await restarted.push("123", claim.notification.push_id)) == state


@pytest.mark.parametrize("invalid_devices", [-1, True, "1"])
async def test_invalid_unverified_gateway_result_is_unknown_not_provider_queued(
    invalid_devices: object,
) -> None:
    claim, clock = pending(), Clock()
    store = Store(claim)
    # Deliberately bypass construction validation to exercise the service boundary.
    gateway = Gateway(ParentPushReceipt.model_construct(queued_devices=cast(int, invalid_devices)))
    service = ProactiveParentService(store, clock=clock, gateway=gateway)

    state = await service.process_one()

    assert state is not None and state.status == "unknown"
    assert state.queued_devices is None and state.error_code == "parent_push_outcome_unknown"
    assert len(store.finish_calls) == len(gateway.messages) == 1
    assert await service.process_one() is None
    assert len(gateway.messages) == 1
