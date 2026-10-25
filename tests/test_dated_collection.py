"""Shared scheduled acquisition -> changed evidence -> specialist -> the parent's one chat."""

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from pytest import MonkeyPatch

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt
from app.mana_ai.application.source_reviews import SourceReviewService
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.family_day_usage import (
    DAY_USAGE_SOURCE,
    DayUsageTarget,
    FamilyDayUsagePage,
    ParentUsageLookup,
)
from app.services.dated_review_safety_store import SqliteDatedReviewSafetyStore
from app.services.day_review_cache import SqliteDayReviewCache
from app.services.lab_collection import LabCollectionClock
from app.services.mana_chat_lab import LAB_CHILD, LAB_PARENT, ChatLab, LabOptions


def options(path: Path) -> LabOptions:
    return LabOptions(
        path,
        clock=LabCollectionClock(),
        worker_enabled=False,
        native_sources=True,
        native_observations=True,
        source_reviews=True,
        reminders=True,
        retention=True,
        upsell=True,
        tariff_context=True,
        expiry=True,
        day_usage=True,
        dated_reviews=True,
        scheduled_collection=True,
        collection_tariffs=True,
        day_collection=True,
    )


def reviews(lab: ChatLab) -> SourceReviewService:
    assert isinstance(lab.source_store, SqliteDayReviewCache)
    assert isinstance(lab.store, SqliteDatedReviewSafetyStore)
    return SourceReviewService(
        lab.source_store,
        lab.store,
        lab._profiles,
        clock=lab.options.clock.now,
        available=lambda: lab.safety.worker_available,
    )


def dump(path: Path) -> list[str]:
    with sqlite3.connect(path) as db:
        return list(db.iterdump())


async def test_two_daily_windows_reuse_one_family_page_and_only_new_context_reaches_chat(
    tmp_path: Path,
) -> None:
    lab = ChatLab(options(tmp_path / "lab"))
    await lab.start()
    try:
        assert lab.collection
        morning = await lab.collection.collect(9)
        assert morning.status == "completed", morning
        assert {c.source for c in morning.counts} == {"firebase.child_battery.v1", DAY_USAGE_SOURCE}
        dated = next(c for c in morning.counts if c.source == DAY_USAGE_SOURCE)
        assert dated.target_reads == 1 and dated.target_scope == "family"
        assert lab.day_provider.calls == lab.battery.calls == 1 and lab.app_usage.calls == 0
        service = reviews(lab)
        prepared = await service.process_one()
        assert prepared and prepared.phase == "prepared"
        assert {s.source for s in prepared.bundle.snapshots} == {
            "firebase.child_battery.v1",
            DAY_USAGE_SOURCE,
        }
        admitted = await service.process_one()
        assert admitted and admitted.phase == "admitted"
        job = await lab.safety.process_one()
        assert job and job.status == "completed", job
        with lab.store._connect() as db:
            context = json.loads(
                db.execute(
                    "SELECT context FROM child_safety_jobs WHERE kind='source_review'"
                ).fetchone()[0]
            )
            assert context["version"] == 4
        delivery = await lab.store.next_delivery(lab.options.clock.now())
        assert delivery
        answer = await lab.touch.deliver(delivery)
        assert "2026-10-24" in answer.answer and "не экранное время" in answer.answer
        first = await lab.state()
        assert len(first.history.messages) == 1
        assert first.history.messages[0].role == "assistant"
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Farzandim 2026-10-24 kuni qaysi ilovalardan foydalangan?",
        )
        await lab.touch.admit_message(request)
        reply_review = await lab.safety.process_one()
        assert reply_review and reply_review.status == "completed"
        assert await lab.touch.process_reviewed_message()
        reply = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert reply.response and "noma’lum" in reply.response.answer
        assert lab.day_provider.calls == 1
        before = await lab.state()
        assert before.safety_budget.server_used_tokens == 450
        afternoon = await lab.collection.collect(15)
        assert afternoon.status == "completed"
        assert lab.day_provider.calls == lab.battery.calls == 2 and lab.app_usage.calls == 0
        assert await service.process_one() is None
        assert await lab.safety.process_one() is None
        assert (await lab.state()).history.messages == before.history.messages
        paths = [
            lab.options.directory / n
            for n in ("family.sqlite3", "sources.sqlite3", "collection.sqlite3")
        ]
        previous = {p.name: dump(p) for p in paths}
        opts = lab.options
        await lab.close()
        lab = ChatLab(opts)
        await lab.start()
        assert lab.collection and await lab.collection.collect(15) == afternoon
        assert lab.day_provider.calls == lab.battery.calls == 0
        assert {p.name: dump(p) for p in paths} == previous
    finally:
        await lab.close()


async def test_empty_dated_page_is_not_a_daily_screen_time_or_background_model_trigger(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    lab = ChatLab(options(tmp_path / "empty"))
    await lab.start()
    original = lab.day_provider.read_verified

    async def empty(lookup: ParentUsageLookup, day: date) -> FamilyDayUsagePage:
        page = await original(lookup, day)
        return FamilyDayUsagePage.model_validate(
            page.model_dump()
            | {"children": (), "provider_children_count": 0, "complete_family": False}
        )

    monkeypatch.setattr(lab.day_provider, "read_verified", empty)
    try:
        assert lab.collection
        result = await lab.collection.collect(9)
        dated = next(c for c in result.counts if c.source == DAY_USAGE_SOURCE)
        assert dated.unavailable == 1 and dated.available == 0
        work = await reviews(lab).process_one()
        assert work and all(s.source != DAY_USAGE_SOURCE for s in work.bundle.snapshots)
        assert (await lab.state()).safety_budget.server_used_tokens == 0
    finally:
        await lab.close()


async def test_unknown_family_read_does_not_repeat_at_afternoon_or_restart(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    lab = ChatLab(options(tmp_path / "unknown"))
    await lab.start()
    calls = 0

    async def lost(lookup: ParentUsageLookup, day: date) -> FamilyDayUsagePage:
        nonlocal calls
        calls += 1
        raise TimeoutError("fictional lost family page")

    monkeypatch.setattr(lab.day_provider, "read_verified", lost)
    try:
        assert lab.collection
        first = await lab.collection.collect(9)
        assert first.status == "unknown", first
        assert calls == 1
        later = await lab.collection.collect(15)
        assert later.status in {"partial", "unknown"}
        assert calls == 1
        with lab.source_store._connection() as db:
            assert db.execute("SELECT status FROM day_usage_ownership").fetchone()[0] == "unknown"
        opts = lab.options
        await lab.close()
        lab = ChatLab(opts)
        await lab.start()
        assert lab.collection
        assert await lab.collection.collect(15) == later
        assert lab.day_provider.calls == 0
    finally:
        await lab.close()


async def test_consumer_capture_stays_disabled_after_toggle_mid_read(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    lab = ChatLab(options(tmp_path / "capture"))
    await lab.start()
    assert isinstance(lab.source_store, SqliteDayReviewCache)
    try:
        assert lab.collection
        lab.collection.clock.advance(9)
        store = lab.source_store
        monkeypatch.setattr(store, "_dated_reviews_enabled", False)
        target = DayUsageTarget(
            parent_id=LAB_PARENT,
            child_id=LAB_CHILD,
            request_id=uuid4(),
            requested_day=lab.options.clock.now().date() - timedelta(days=1),
        )
        claim = await store.claim_day(target, lab.options.clock.now())
        assert claim.admitted
        monkeypatch.setattr(store, "_dated_reviews_enabled", True)
        lookup = await lab.day_provider.read_usage_lookup(LAB_PARENT)
        page = await lab.day_provider.read_verified(lookup, target.requested_day)
        await store.complete_day(target, page, lab.options.clock.now())
        assert await reviews(lab).process_one() is None
        with store._connection() as db:
            assert db.execute("SELECT phase FROM review_events").fetchone()[0] == "disabled"
    finally:
        await lab.close()


async def test_stopped_dated_consumer_does_not_dispatch_queued_model_job(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    lab = ChatLab(options(tmp_path / "stopped"))
    await lab.start()
    try:
        assert lab.collection
        await lab.collection.collect(9)
        service = reviews(lab)
        await service.process_one()
        await service.process_one()
        monkeypatch.setattr(lab.store, "_dated_reviews_enabled", False)
        assert await lab.safety.process_one() is None
        budget = (await lab.state()).safety_budget
        assert budget.server_used_tokens == budget.server_reserved_tokens == 0
        with lab.store._connect() as db:
            assert (
                db.execute("SELECT error_code FROM child_safety_jobs").fetchone()[0]
                == "dated_source_review_disabled"
            )
    finally:
        await lab.close()


async def test_stopping_after_verified_generation_keeps_cost_but_publishes_no_notice(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    lab = ChatLab(options(tmp_path / "late-stop"))
    await lab.start()
    store = lab.store
    assert isinstance(store, SqliteDatedReviewSafetyStore)
    original = lab.safety._model.respond

    async def stop_after_receipt(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        receipt = await original(prompt, max_output_tokens=max_output_tokens)
        store._dated_reviews_enabled = False
        return receipt

    monkeypatch.setattr(lab.safety._model, "respond", stop_after_receipt)
    try:
        assert lab.collection
        await lab.collection.collect(9)
        service = reviews(lab)
        await service.process_one()
        await service.process_one()
        result = await lab.safety.process_one()
        assert result and result.status == "failed"
        state = await lab.state()
        assert state.safety_budget.server_used_tokens == 150
        assert state.safety_budget.server_reserved_tokens == 0
        assert not state.history.messages
        assert await lab.store.next_delivery(lab.options.clock.now()) is None
    finally:
        await lab.close()
