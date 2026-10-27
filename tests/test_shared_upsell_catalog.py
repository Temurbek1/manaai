"""Concurrent families observe one public-price receipt without repeating its read."""

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ChatChild, ParentChildContext
from app.mana_ai.domain.client_upsell import CatalogReadClaim, CatalogReadObservation
from app.mana_ai.domain.conversion_catalog import ConversionCatalogObservation
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.services.client_upsell_store import SqliteClientUpsellStore
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from tests.test_compact_parent_manager import setup
from tests.test_trial_action_cards import snapshot

OTHER_PARENT = "900002"


def upsell_store(lab: ChatLab) -> SqliteClientUpsellStore:
    assert isinstance(lab.store, SqliteClientUpsellStore)
    return lab.store


async def admit_pair(
    lab: ChatLab, monkeypatch: pytest.MonkeyPatch
) -> tuple[ParentTouchMessageRequest, ParentTouchMessageRequest, dict[str, int]]:
    profile = lab._profiles.read
    reads = {LAB_PARENT: 0, OTHER_PARENT: 0}

    async def own_profile(parent_id: str) -> ParentChildContext:
        reads[parent_id] += 1
        if parent_id == LAB_PARENT:
            return await profile(parent_id)
        assert parent_id == OTHER_PARENT
        return ParentChildContext(
            parent_id=parent_id,
            children=[ChatChild(child_id=900102, name="Other fictional child", connected=True)],
            collected_at=lab.options.clock.now(),
            limitations=["Second isolated fictional family; no external data."],
        )

    monkeypatch.setattr(lab._profiles, "read", own_profile)
    requests = (
        ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Покажи тарифы на 90 дней UZS",
        ),
        ParentTouchMessageRequest(
            parent_id=OTHER_PARENT,
            request_id=uuid4(),
            message="Покажи тарифы на 90 дней USD",
        ),
    )
    for request in requests:
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(request.parent_id, request.request_id)
        assert state.phase == "responding" and state.response is None
    return *requests, reads


async def blocked_pair(
    lab: ChatLab, monkeypatch: pytest.MonkeyPatch, *, lost: bool = False
) -> tuple[asyncio.Task[bool], asyncio.Task[bool], asyncio.Event]:
    owner_entered, waiter_entered, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    source = lab.catalog.read
    observation = upsell_store(lab).catalog_observation

    async def blocked_source() -> ConversionCatalogObservation:
        owner_entered.set()
        await release.wait()
        if lost:
            raise TimeoutError("Fictional lost shared catalog receipt")
        return await source()

    async def observe(claim: CatalogReadClaim, now: datetime) -> CatalogReadObservation:
        result = await observation(claim, now)
        if result.status == "reading":
            waiter_entered.set()
        return result

    monkeypatch.setattr(lab.catalog, "read", blocked_source)
    monkeypatch.setattr(lab.store, "catalog_observation", observe)
    owner = asyncio.create_task(lab.touch.process_upsell())
    await asyncio.wait_for(owner_entered.wait(), 3)
    waiter = asyncio.create_task(lab.touch.process_upsell())
    await asyncio.wait_for(waiter_entered.wait(), 3)
    return owner, waiter, release


async def test_two_original_turns_share_one_inflight_read_and_keep_family_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "two-families")
    release = asyncio.Event()
    try:
        first, second, reads = await admit_pair(lab, monkeypatch)
        owner, waiter, release = await blocked_pair(lab, monkeypatch)
        assert (await lab.touch.message_state(second.parent_id, second.request_id)).response is None
        release.set()
        assert all(await asyncio.wait_for(asyncio.gather(owner, waiter), 3))
        first_done = await lab.touch.message_state(first.parent_id, first.request_id)
        second_done = await lab.touch.message_state(second.parent_id, second.request_id)
        assert first_done.response and "162 000.00 UZS" in first_done.response.answer
        assert second_done.response and "нет варианта" in second_done.response.answer
        assert "162 000" not in second_done.response.answer
        assert first_done.turn_id != second_done.turn_id
        assert reads == {LAB_PARENT: 2, OTHER_PARENT: 2}
        assert lab.catalog.calls == 1
        with lab.store._connect() as db:
            assert tuple(
                db.execute(
                    "SELECT COUNT(*),SUM(reserved_http_attempts) FROM upsell_catalog_reads"
                ).fetchone()
            ) == (1, 2)
            assert db.execute("SELECT COUNT(*) FROM parent_chat_turns").fetchone()[0] == 2
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
        before = snapshot(lab.store)
        assert await lab.touch.admit_message(first) == first_done
        assert await lab.touch.admit_message(second) == second_done
        assert snapshot(lab.store) == before
        assert not await lab.touch.process_upsell() and lab.catalog.calls == 1
    finally:
        release.set()
        await lab.close()


async def test_parent_cancellation_fences_only_waiter_not_catalog_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "cancel-waiter")
    release = asyncio.Event()
    try:
        first, second, reads = await admit_pair(lab, monkeypatch)
        owner, waiter, release = await blocked_pair(lab, monkeypatch)
        cancellation = ParentTouchMessageRequest(
            parent_id=second.parent_id,
            request_id=uuid4(),
            message="Отмени подбор",
            cancel_tariff_request_id=second.request_id,
        )
        cancelled = await lab.touch.admit_message(cancellation)
        assert cancelled.response and cancelled.response.usage.total == 0
        assert await asyncio.wait_for(waiter, 3)
        assert (
            await lab.touch.message_state(second.parent_id, second.request_id)
        ).phase == "failed"
        assert not owner.done()
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM upsell_catalog_reads").fetchone()[0] == "reading"
        release.set()
        assert await asyncio.wait_for(owner, 3)
        completed = await lab.touch.message_state(first.parent_id, first.request_id)
        assert completed.response and "162 000.00 UZS" in completed.response.answer
        assert lab.catalog.calls == 1 and reads == {LAB_PARENT: 2, OTHER_PARENT: 2}
        assert await lab.touch.admit_message(cancellation) == cancelled
    finally:
        release.set()
        await lab.close()


async def test_lost_owner_receipt_stops_waiter_without_retry_and_survives_reconstruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "lost-shared"
    lab, clock = await setup(directory)
    release = asyncio.Event()
    try:
        first, second, _ = await admit_pair(lab, monkeypatch)
        owner, waiter, release = await blocked_pair(lab, monkeypatch, lost=True)
        release.set()
        assert all(await asyncio.wait_for(asyncio.gather(owner, waiter), 3))
        for request in (first, second):
            state = await lab.touch.message_state(request.parent_id, request.request_id)
            assert state.response and "не удалось подтвердить" in state.response.answer
        with lab.store._connect() as db:
            claim = db.execute(
                "SELECT claim_id,expires_at,status FROM upsell_catalog_reads"
            ).fetchone()
            assert claim[2] == "unknown"
        retained = snapshot(lab.store)
        assert (await upsell_store(lab).catalog_admission(clock.now())).refusal == "blocked"
        assert snapshot(lab.store) == retained
    finally:
        release.set()
        await lab.close()
    restored, later = await setup(directory)
    try:
        later.value = clock.now() + timedelta(days=1)
        assert (await upsell_store(restored).catalog_admission(later.now())).refusal == "blocked"
        assert snapshot(restored.store) == retained
        assert restored.catalog.calls == 0 and not await restored.touch.process_upsell()
    finally:
        await restored.close()


async def test_worker_cancellation_leaves_shared_owner_and_stopped_waiter_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "worker-cancel")
    release = asyncio.Event()
    try:
        first, second, _ = await admit_pair(lab, monkeypatch)
        owner, waiter, release = await blocked_pair(lab, monkeypatch)
        waiter.cancel()
        with suppress(asyncio.CancelledError):
            await waiter
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM upsell_catalog_reads").fetchone()[0] == "reading"
        release.set()
        assert await asyncio.wait_for(owner, 3)
        assert (await lab.touch.message_state(first.parent_id, first.request_id)).response
        assert lab.catalog.calls == 1
        # The cancelled worker has no source authority and cannot regenerate its original turn.
        assert not await lab.touch.process_upsell()
        second_state = await lab.touch.message_state(second.parent_id, second.request_id)
        assert second_state.phase == "failed" and second_state.response is None
        assert second_state.error_code == "upsell_reply_source_unavailable"
        with lab.store._connect() as db:
            charged = db.execute(
                "SELECT input_tokens,output_tokens,reserved FROM parent_chat_turns "
                "WHERE id=? AND parent_id=?",
                (second_state.turn_id, second.parent_id),
            ).fetchone()
            assert tuple(charged) == (100, 50, 0)
        assert (await upsell_store(lab).catalog_admission(clock.now())).snapshot is not None
    finally:
        release.set()
        await lab.close()


async def test_catalog_observation_is_readonly_and_bound_to_original_receipt(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "bound-observation")
    try:
        store = upsell_store(lab)
        admission = await store.catalog_admission(clock.now())
        assert admission.claim
        busy = await store.catalog_admission(clock.now())
        assert busy.refusal == "busy" and busy.waiting_for == admission.claim
        before = snapshot(lab.store)
        assert (await store.catalog_observation(admission.claim, clock.now())).status == "reading"
        expired = clock.now() + timedelta(seconds=181)
        assert (await store.catalog_observation(admission.claim, expired)).status == "unknown"
        assert snapshot(lab.store) == before
        changed = admission.claim.model_copy(update={"expires_at": expired})
        with pytest.raises(ParentChatError, match="upsell_catalog_claim_invalid"):
            await store.catalog_observation(changed, clock.now())
        assert snapshot(lab.store) == before
        catalog = await lab.catalog.read()
        await store.finish_catalog(admission.claim, clock.now(), snapshot=catalog)
        saved = snapshot(lab.store)
        observed = await store.catalog_observation(admission.claim, clock.now())
        assert observed.status == "recorded" and observed.snapshot == catalog
        assert snapshot(lab.store) == saved
    finally:
        await lab.close()


async def test_stalled_wall_clock_cannot_extend_original_wait_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "wall-clock")
    try:
        await admit_pair(lab, monkeypatch)
        assert lab.touch.upsell
        store = upsell_store(lab)
        work = await store.claim_upsell(clock.now())
        admission = await store.catalog_admission(clock.now())
        assert work and admission.claim
        bounded = work.model_copy(update={"expires_at": clock.now() + timedelta(milliseconds=20)})
        before = snapshot(lab.store)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(
                lab.touch.upsell._observe_catalog(bounded, admission.claim, context_at=clock.now()),
                1,
            )
        assert snapshot(lab.store) == before and lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_shared_waiter_expiry_never_publishes_a_late_price_or_reissues_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "expired-waiter")
    release = asyncio.Event()
    try:
        first, second, reads = await admit_pair(lab, monkeypatch)
        owner, waiter, release = await blocked_pair(lab, monkeypatch)
        clock.value += timedelta(seconds=181)
        assert await asyncio.wait_for(waiter, 3)
        with lab.store._connect() as db:
            # Observation and the waiter's own expiry cannot settle another worker's read.
            assert db.execute("SELECT status FROM upsell_catalog_reads").fetchone()[0] == "reading"
        assert not owner.done()
        release.set()
        assert await asyncio.wait_for(owner, 3)
        for request in (first, second):
            result = await lab.touch.message_state(request.parent_id, request.request_id)
            assert result.phase == "failed" and result.response is None
            history = await lab.touch.read_touch_history(request.parent_id, before=None, limit=100)
            assert len(history.messages) == 1 and history.messages[0].role == "user"
        assert lab.catalog.calls == 1 and reads == {LAB_PARENT: 2, OTHER_PARENT: 2}
        with lab.store._connect() as db:
            retained = db.execute(
                "SELECT COUNT(*),SUM(reserved_http_attempts),MAX(status) FROM upsell_catalog_reads"
            ).fetchone()
            assert tuple(retained) == (1, 2, "unknown")
            assert not db.execute("SELECT 1 FROM upsell_catalog").fetchone()
        assert (await upsell_store(lab).catalog_admission(clock.now())).refusal == "blocked"
        assert not await lab.touch.process_upsell() and lab.catalog.calls == 1
    finally:
        release.set()
        await lab.close()
