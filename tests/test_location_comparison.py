"""Two saved GPS samples join one metered same-chat flow without another source read."""

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt
from app.mana_ai.application.source_reviews import SourceReviewService
from app.mana_ai.domain.child_location import LOCATION_SOURCE, ChildLocationFacts
from app.mana_ai.domain.family_agents import FamilyNotice
from app.mana_ai.domain.family_sources import FamilySourceTarget
from app.mana_ai.domain.source_reviews import SourceReviewBundle, location_comparison_view
from app.services.lab_workspace import workspace_options
from app.services.location_comparison_cache import SqliteLocationComparisonCache
from app.services.location_comparison_safety_store import (
    SqliteClosedLocationComparisonSafetyStore,
    SqliteLocationComparisonSafetyStore,
)
from app.services.mana_chat_lab import LAB_CHILD, LAB_PARENT, ChatLab
from app.services.source_review_cache import SqliteSourceReviewCache
from app.services.source_review_prompts import source_review_prompt
from app.services.source_review_safety_store import SqliteSourceReviewSafetyStore
from app.services.usage_comparison_cache import SqliteUsageComparisonCache
from tests.test_mana_chat_lab import Clock


def snapshots(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    with sqlite3.connect(path) as db:
        return {
            name: db.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


async def setup(path: Path, *, enabled: bool = True) -> tuple[ChatLab, Clock, SourceReviewService]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        replace(
            workspace_options(path, clock=clock, worker_enabled=False),
            tariff_handoff=True,
            compact_inputs=True,
            compact_publication=True,
            compact_manager=True,
            location_comparisons=enabled,
        )
    )
    await lab.start()
    assert isinstance(lab.source_store, SqliteSourceReviewCache)
    assert isinstance(lab.store, SqliteSourceReviewSafetyStore)
    service = SourceReviewService(
        lab.source_store,
        lab.store,
        lab._profiles,
        clock=clock.now,
        available=lambda: lab.safety.worker_available,
    )
    return lab, clock, service


def target() -> FamilySourceTarget:
    return FamilySourceTarget(
        parent_id=LAB_PARENT, child_id=LAB_CHILD, source=LOCATION_SOURCE, request_id=uuid4()
    )


def facts(clock: Clock, *, point: str = "a", observed: Any = "now") -> ChildLocationFacts:
    stamp = clock.now() - timedelta(minutes=1) if observed == "now" else observed
    return ChildLocationFacts(
        child_id=LAB_CHILD,
        status="available",
        position_fingerprint=point * 64,
        observed_at=stamp,
        source_updated_at=clock.now() - timedelta(seconds=1),
        collected_at=clock.now(),
        quality="dated" if stamp is not None else "unknown_measurement_time",
        mock=False,
        sample=False,
        is_moving=False,
        accuracy_reported=True,
    )


async def pair(lab: ChatLab, clock: Clock, *, same_point: bool = False) -> FamilySourceTarget:
    assert isinstance(lab.source_store, SqliteLocationComparisonCache)
    # The first saved observation predates the newly eligible consumer; no first-contact
    # assertion is manufactured from it. The next already permitted read is the trigger.
    lab.source_store._dispatch_enabled = False
    first = target()
    assert (await lab.source_store.claim(first, clock.now())).read_provider
    await lab.source_store.complete(first, facts(clock), clock.now())
    clock.value += timedelta(hours=6)
    lab.source_store._dispatch_enabled = True
    second = target()
    assert (await lab.source_store.claim(second, clock.now())).read_provider
    await lab.source_store.complete(
        second, facts(clock, point="a" if same_point else "b"), clock.now()
    )
    return second


async def prepared(lab: ChatLab, clock: Clock, service: SourceReviewService) -> SourceReviewBundle:
    clock.value += timedelta(seconds=4)
    work = await service.process_one()
    assert work and work.phase == "prepared" and work.bundle.location_comparison
    return work.bundle


async def test_two_points_publish_once_keep_dates_and_survive_restart_and_closed_reader(
    tmp_path: Path,
) -> None:
    path = tmp_path / "same-chat"
    lab, clock, service = await setup(path)
    try:
        request = await pair(lab, clock)
        bundle = await prepared(lab, clock, service)
        view = location_comparison_view(bundle)
        assert view and view.chronology == "ordered_measurements"
        assert view.stored_point_relation == "different"
        assert not view.verified_movement and not view.route_reconstructed
        assert view.previous.observed_at and view.current.observed_at
        assert view.previous.observed_at < view.current.observed_at
        work = await service.process_one()
        assert work and work.phase == "admitted"
        result = await lab.safety.process_one()
        assert result and result.status == "completed", result
        with lab.store._connect() as db:
            notice = FamilyNotice.model_validate_json(
                db.execute("SELECT payload FROM family_notices").fetchone()[0]
            )
            assert notice.location_comparison == view
            assert db.execute("SELECT COUNT(*) FROM location_comparison_jobs").fetchone()[0] == 1
        delivery = await lab.store.next_delivery(clock.now())
        assert delivery
        answer = await lab.touch.deliver(delivery)
        assert "2026-10-24" in answer.answer
        assert (await lab.state()).history.quota.used_tokens == 150
        assert (await lab.state()).safety_budget.server_used_tokens == 150
        assert lab.location.calls == lab.battery.calls == lab.app_usage.calls == 0
        with lab.source_store._connection() as db:
            assert db.execute("SELECT COUNT(*),SUM(units) FROM source_reads").fetchone()[:] == (
                2,
                4,
            )
        family_before = snapshots(path / "family.sqlite3")
        source_before = snapshots(lab.source_store._path)
        assert (await lab.source_store.claim(request, clock.now())).admitted is False
        assert await service.process_one() is None
        assert await lab.safety.process_one() is None
        assert await lab.store.next_delivery(clock.now()) is None
        assert snapshots(lab.source_store._path) == source_before
        saved = await lab.state()
        await lab.close()
        lab, _, service = await setup(path)
        assert snapshots(path / "family.sqlite3") == family_before
        assert snapshots(lab.source_store._path) == source_before
        closed = SqliteClosedLocationComparisonSafetyStore(
            path / "family.sqlite3", history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        history = await closed.touch_history(LAB_PARENT, before=None, limit=20, now=clock.now())
        assert history.messages == saved.history.messages
        assert snapshots(path / "family.sqlite3") == family_before
    finally:
        await lab.close()


@pytest.mark.parametrize("case", ["same", "unknown", "equal", "regressed", "missing", "mock"])
async def test_comparison_keeps_temporal_and_quality_uncertainty(tmp_path: Path, case: str) -> None:
    lab, clock, service = await setup(tmp_path / case)
    try:
        await pair(lab, clock, same_point=case == "same")
        bundle = await prepared(lab, clock, service)
        data = bundle.model_dump(mode="json")
        current = data["snapshots"][0]
        previous = data["location_comparison"]["previous"]["facts"]
        if case == "unknown":
            current["facts"]["observed_at"] = None
            current["facts"]["quality"] = "unknown_measurement_time"
        elif case == "equal":
            current["facts"]["observed_at"] = previous["observed_at"]
        elif case == "regressed":
            assert bundle.location_comparison
            stamp = bundle.location_comparison.previous.facts.observed_at
            assert stamp is not None
            current["facts"]["observed_at"] = (stamp - timedelta(seconds=1)).isoformat()
        elif case == "missing":
            current["facts"] = ChildLocationFacts(
                child_id=LAB_CHILD,
                status="missing",
                collected_at=clock.now(),
                quality="no_observation",
            ).model_dump(mode="json")
        elif case == "mock":
            current["facts"]["mock"] = True
        replacement = ChildLocationFacts.model_validate(current["facts"])
        current["fingerprint"] = replacement.fingerprint()
        data["location_comparison"]["current_fingerprint"] = replacement.fingerprint()
        view = location_comparison_view(SourceReviewBundle.model_validate(data))
        assert view
        assert view.stored_point_relation == (
            "same" if case == "same" else "different" if case == "mock" else "not_comparable"
        )
        assert (
            view.chronology
            == {
                "same": "ordered_measurements",
                "mock": "ordered_measurements",
                "unknown": "unknown_measurement_time",
                "equal": "same_measurement_time",
                "regressed": "regressed_measurement_time",
                "missing": "missing_observation",
            }[case]
        )
        assert not view.verified_movement and not view.route_reconstructed
        if case == "mock":
            assert view.current.mock is True
    finally:
        await lab.close()


async def test_admission_freezes_prior_atomically_and_replay_never_recaptures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock, _ = await setup(tmp_path / "atomic")
    assert isinstance(lab.source_store, SqliteLocationComparisonCache)
    source = lab.source_store
    try:
        first = target()
        await source.claim(first, clock.now())
        await source.complete(first, facts(clock), clock.now())
        clock.value += timedelta(hours=6)
        original = source._source_admitted

        def fail(*args: Any) -> None:
            original(*args)
            raise RuntimeError("Local admission transaction aborted")

        monkeypatch.setattr(source, "_source_admitted", fail)
        before = snapshots(source._path)
        second = target()
        with pytest.raises(RuntimeError):
            await source.claim(second, clock.now())
        assert snapshots(source._path) == before
        monkeypatch.setattr(source, "_source_admitted", original)
        await source.claim(second, clock.now())
        with source._connection() as db:
            frozen = db.execute(
                "SELECT previous_payload FROM location_comparison_admissions WHERE request_id=?",
                (str(second.request_id),),
            ).fetchone()[0]
        source._location_comparisons_enabled = False
        assert not (await source.claim(second, clock.now())).admitted
        with source._connection() as db:
            assert (
                db.execute(
                    "SELECT previous_payload FROM location_comparison_admissions "
                    "WHERE request_id=?",
                    (str(second.request_id),),
                ).fetchone()[0]
                == frozen
            )
    finally:
        await lab.close()


async def test_disabled_admission_never_gains_a_previous_point_after_rearming(
    tmp_path: Path,
) -> None:
    lab, clock, service = await setup(tmp_path / "old-capture")
    assert isinstance(lab.source_store, SqliteLocationComparisonCache)
    try:
        await pair(lab, clock)
        clock.value += timedelta(hours=6)
        lab.source_store._location_comparisons_enabled = False
        request = target()
        await lab.source_store.claim(request, clock.now())
        lab.source_store._location_comparisons_enabled = True
        await lab.source_store.complete(request, facts(clock, point="c"), clock.now())
        clock.value += timedelta(seconds=4)
        work = await service.process_one()
        assert work and work.bundle.location_comparison is None
        with lab.source_store._connection() as db:
            capture = db.execute(
                "SELECT enabled,previous_payload FROM location_comparison_admissions "
                "WHERE request_id=?",
                (str(request.request_id),),
            ).fetchone()
            assert tuple(capture) == (0, None)
    finally:
        await lab.close()


@pytest.mark.parametrize("change", ["child", "parent", "snapshot", "fingerprint", "same", "future"])
async def test_comparison_rejects_foreign_or_changed_provenance(
    tmp_path: Path, change: str
) -> None:
    lab, clock, service = await setup(tmp_path / change)
    try:
        await pair(lab, clock)
        bundle = await prepared(lab, clock, service)
        data = bundle.model_dump(mode="json")
        comparison = data["location_comparison"]
        if change == "child":
            comparison["previous"]["facts"]["child_id"] += 1
        elif change == "parent":
            # Parent IDs are bound on the enclosing bundle and admission; a view
            # cannot introduce its own second family identifier.
            comparison["parent_id"] = "123"
        elif change == "snapshot":
            comparison["current_snapshot_id"] = str(uuid4())
        elif change == "fingerprint":
            comparison["current_fingerprint"] = "f" * 64
        elif change == "same":
            comparison["previous"] = data["snapshots"][0]
        else:
            comparison["previous"]["facts"]["collected_at"] = (
                clock.now() + timedelta(days=1)
            ).isoformat()
        with pytest.raises(ValidationError):
            SourceReviewBundle.model_validate(data)
    finally:
        await lab.close()


async def test_safety_prompt_omits_identifiers_coordinates_and_preserves_both_dates(
    tmp_path: Path,
) -> None:
    lab, clock, service = await setup(tmp_path / "prompt")
    try:
        await pair(lab, clock)
        bundle = await prepared(lab, clock, service)
        await service.process_one()
        job = await lab.store.claim_next(clock.now())
        assert job
        prompt = source_review_prompt(job, await lab._profiles.read(LAB_PARENT))
        data = json.loads(prompt.input.messages[0][1])
        view = location_comparison_view(bundle)
        assert view and data["saved_location_comparison"] == view.model_dump(mode="json")
        serialized = json.dumps(data)
        assert all(
            name not in serialized
            for name in ("position_fingerprint", "latitude", "longitude", "child_id", "parent_id")
        )
        assert (
            "not a route" in prompt.input.instructions
            and "not verified movement" in prompt.input.instructions
        )
    finally:
        await lab.close()


@pytest.mark.parametrize("when", ["queued", "before_submission", "after_submission"])
async def test_stop_fences_safety_while_retaining_verified_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    lab, clock, service = await setup(tmp_path / when)
    assert isinstance(lab.store, SqliteLocationComparisonSafetyStore)
    store = lab.store
    try:
        await pair(lab, clock)
        await prepared(lab, clock, service)
        admitted = await service.process_one()
        assert admitted and admitted.job_id
        model = lab.safety._model
        if when == "queued":
            store._location_comparisons_enabled = False
        elif when == "before_submission":
            original_count = model.count_input

            async def count(prompt: ChatPrompt) -> int:
                result = await original_count(prompt)
                store._location_comparisons_enabled = False
                return result

            monkeypatch.setattr(model, "count_input", count)
        else:
            original_respond = model.respond

            async def respond(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
                result = await original_respond(prompt, max_output_tokens=max_output_tokens)
                store._location_comparisons_enabled = False
                return result

            monkeypatch.setattr(model, "respond", respond)
        await lab.safety.process_one()
        view = await lab.store.assessment(LAB_PARENT, admitted.job_id)
        assert view.status == "failed" and not view.result
        assert (await lab.state()).safety_budget.server_used_tokens == (
            150 if when == "after_submission" else 0
        )
        assert not (await lab.state()).history.messages
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM family_notices").fetchone()[0] == 0
    finally:
        await lab.close()


async def test_late_source_completion_retains_capture_and_stops_only_comparison(
    tmp_path: Path,
) -> None:
    lab, clock, service = await setup(tmp_path / "source-stop")
    assert isinstance(lab.source_store, SqliteLocationComparisonCache)
    try:
        first = target()
        await lab.source_store.claim(first, clock.now())
        await lab.source_store.complete(first, facts(clock), clock.now())
        clock.value += timedelta(hours=6)
        second = target()
        await lab.source_store.claim(second, clock.now())
        lab.source_store._location_comparisons_enabled = False
        completed = await lab.source_store.complete(second, facts(clock, point="b"), clock.now())
        assert completed.status == "completed"
        with lab.source_store._connection() as db:
            assert db.execute("SELECT previous_payload FROM location_comparison_heads").fetchone()[
                0
            ]
        clock.value += timedelta(seconds=4)
        assert await service.process_one() is None
        assert (await lab.state()).safety_budget.server_used_tokens == 0
        assert not (await lab.state()).history.messages
    finally:
        await lab.close()


async def test_concurrent_exact_admissions_capture_the_same_prior_once(tmp_path: Path) -> None:
    lab, clock, _ = await setup(tmp_path / "concurrent")
    assert isinstance(lab.source_store, SqliteLocationComparisonCache)
    try:
        first = target()
        await lab.source_store.claim(first, clock.now())
        await lab.source_store.complete(first, facts(clock), clock.now())
        clock.value += timedelta(hours=6)
        second = target()
        left, right = await asyncio.gather(
            lab.source_store.claim(second, clock.now()), lab.source_store.claim(second, clock.now())
        )
        assert sorted((left.admitted, right.admitted)) == [False, True]
        assert left.receipt == right.receipt
        with lab.source_store._connection() as db:
            assert (
                db.execute("SELECT COUNT(*) FROM location_comparison_admissions").fetchone()[0] == 2
            )
            frozen = db.execute(
                "SELECT previous_payload FROM location_comparison_admissions WHERE request_id=?",
                (str(second.request_id),),
            ).fetchone()[0]
            assert frozen
    finally:
        await lab.close()


async def test_actual_old_source8_inflight_completion_never_gains_comparison(
    tmp_path: Path,
) -> None:
    lab, clock, _ = await setup(tmp_path / "old-source8", enabled=False)
    source = lab.source_store
    assert isinstance(source, SqliteUsageComparisonCache)
    try:
        with source._connection() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 8
        first = target()
        await source.claim(first, clock.now())
        await source.complete(first, facts(clock), clock.now())
        clock.value += timedelta(hours=6)
        inflight = target()
        await source.claim(inflight, clock.now())
        upgraded = SqliteLocationComparisonCache(
            source._path,
            binding=source._binding,
            limits=source._limits,
            policy=source._policy,
            review_policy=source._review_policy,
            enabled=True,
            location_enabled=True,
            dated_reviews_enabled=True,
            comparisons_enabled=True,
            location_comparisons_enabled=True,
        )
        await upgraded.initialize()
        await upgraded.complete(inflight, facts(clock, point="b"), clock.now())
        clock.value += timedelta(seconds=4)
        work = await upgraded.claim_next_review(clock.now())
        assert work and work.bundle.location_comparison is None
        with upgraded._connection() as db:
            assert (
                db.execute("SELECT COUNT(*) FROM location_comparison_admissions").fetchone()[0] == 0
            )
            assert (
                db.execute("SELECT previous_payload FROM location_comparison_heads").fetchone()[0]
                is None
            )
    finally:
        await lab.close()


@pytest.mark.parametrize("when", ["queued", "before_submission", "after_submission", "unknown"])
async def test_parent_touch_stop_or_lost_receipt_preserves_one_chat_and_costs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    lab, clock, service = await setup(tmp_path / ("parent-" + when))
    assert isinstance(lab.store, SqliteLocationComparisonSafetyStore)
    store = lab.store
    try:
        await pair(lab, clock)
        await prepared(lab, clock, service)
        await service.process_one()
        safety = await lab.safety.process_one()
        assert safety and safety.status == "completed"
        model = lab.touch._model
        if when == "queued":
            store._location_comparisons_enabled = False
            assert await lab.store.next_delivery(clock.now()) is None
            assert not (await lab.state()).history.messages
            return
        delivery = await lab.store.next_delivery(clock.now())
        assert delivery
        if when == "before_submission":
            original_count = model.count_input

            async def count(prompt: ChatPrompt) -> int:
                size = await original_count(prompt)
                store._location_comparisons_enabled = False
                return size

            monkeypatch.setattr(model, "count_input", count)
        else:
            original_respond = model.respond

            async def respond(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
                if when == "unknown":
                    raise asyncio.CancelledError()
                receipt = await original_respond(prompt, max_output_tokens=max_output_tokens)
                store._location_comparisons_enabled = False
                return receipt

            monkeypatch.setattr(model, "respond", respond)
        with pytest.raises((Exception, asyncio.CancelledError)):
            await lab.touch.deliver(delivery)
        state = await lab.state()
        assert not state.history.messages
        assert state.history.quota.used_tokens == (150 if when == "after_submission" else 0)
        assert state.safety_budget.server_used_tokens == 150
        if when == "unknown":
            assert state.history.quota.reserved_tokens > 0
            before = snapshots(lab.store._path)
            closed = SqliteClosedLocationComparisonSafetyStore(
                lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
            )
            await closed.initialize()
            history = await closed.touch_history(
                LAB_PARENT, before=None, limit=20, now=clock.now() + timedelta(days=1)
            )
            assert history.quota.blocked_by_unresolved_request
            assert snapshots(lab.store._path) == before
    finally:
        await lab.close()
