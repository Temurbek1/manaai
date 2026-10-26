"""GPS uses the existing two collection windows, shared sources and one-chat first contact."""

from dataclasses import replace
from pathlib import Path

from app.mana_ai.domain.child_location import LOCATION_SOURCE
from app.services.location_collection_store import SqliteLocationCollectionStore
from app.services.location_safety_store import SqliteLocationSafetyStore
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from tests.test_dated_collection import options, reviews


async def test_two_windows_collect_gps_without_new_timer_and_coalesce_first_contact(
    tmp_path: Path,
) -> None:
    lab = ChatLab(replace(options(tmp_path / "windows"), manager=True, location=True))
    await lab.start()
    try:
        assert lab.collection and isinstance(lab.collection.store, SqliteLocationCollectionStore)
        first = await lab.collection.collect(9)
        assert first.status == "completed", first
        gps = next(c for c in first.counts if c.source == LOCATION_SOURCE)
        assert gps.target_reads == 1 and gps.available == 1
        assert lab.location.calls == lab.battery.calls == lab.day_provider.calls == 1
        service = reviews(lab)
        prepared = await service.process_one()
        assert prepared and prepared.phase == "prepared" and len(prepared.bundle.snapshots) == 3
        admitted = await service.process_one()
        assert admitted and admitted.phase == "admitted"
        job = await lab.safety.process_one()
        assert job and job.status == "completed", job
        delivery = await lab.store.next_delivery(lab.options.clock.now())
        assert delivery
        answer = await lab.touch.deliver(delivery)
        assert (
            "2026-10-14" in answer.answer and "текущее местоположение неизвестно" in answer.answer
        )
        assert len((await lab.state()).history.messages) == 1
        # Only the existing second occurrence can perform another provider read.
        second = await lab.collection.collect(15)
        assert second.status == "completed", second
        assert lab.location.calls == 2
        with lab.source_store._connection() as db:
            assert db.execute("SELECT COUNT(*) FROM location_snapshots").fetchone()[0] == 1
        again = await lab.collection.collect(15)
        assert again == second and lab.location.calls == 2
    finally:
        await lab.close()


async def test_turning_gps_off_skips_only_its_work_and_never_upgrades_an_old_window(
    tmp_path: Path,
) -> None:
    lab = ChatLab(replace(options(tmp_path / "frozen"), manager=True, location=True))
    await lab.start()
    try:
        assert lab.collection and isinstance(lab.collection.store, SqliteLocationCollectionStore)
        assert isinstance(lab.store, SqliteLocationSafetyStore)
        lab.collection.store._location_enabled = False
        first = await lab.collection.collect(9)
        assert first.status == "completed" and all(
            c.source != LOCATION_SOURCE for c in first.counts
        )
        lab.collection.store._location_enabled = True
        assert await lab.collection.collect(9) == first and lab.location.calls == 0
        # The next captured occurrence may queue GPS; disabled provider wiring
        # refuses it before I/O, without aborting battery/day work.
        lab.sources._location = None
        second = await lab.collection.collect(15)
        assert second.status == "partial", second
        assert lab.location.calls == 0 and lab.battery.calls == 2
        gps = next(c for c in second.counts if c.source == LOCATION_SOURCE)
        assert gps.skipped == 1
    finally:
        await lab.close()


async def test_disabling_gps_after_coalesced_admission_stops_only_new_review(
    tmp_path: Path,
) -> None:
    lab = ChatLab(replace(options(tmp_path / "stopped-review"), manager=True, location=True))
    await lab.start()
    try:
        assert lab.collection and isinstance(lab.store, SqliteLocationSafetyStore)
        await lab.collection.collect(9)
        service = reviews(lab)
        assert await service.process_one()
        admitted = await service.process_one()
        assert admitted and admitted.phase == "admitted" and admitted.job_id is not None
        lab.store._location_enabled = False
        assert await lab.safety.process_one() is None
        result = await lab.store.assessment(LAB_PARENT, admitted.job_id)
        assert result.status == "failed" and result.error_code == "location_source_review_disabled"
        assert (await lab.state()).safety_budget.server_used_tokens == 0
    finally:
        await lab.close()
