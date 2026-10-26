"""Frozen own-child counter comparisons reuse saved source facts, not external reads."""

import asyncio
import json
import sqlite3
from contextlib import suppress
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.day_usage_service import FamilyDayUsageService
from app.mana_ai.application.source_reviews import SourceReviewService
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.family_agents import FamilyNotice
from app.mana_ai.domain.family_day_usage import DayUsageTarget, FamilyDayUsagePage
from app.mana_ai.domain.family_sources import (
    AppUsageCounter,
    ChildAppUsageFacts,
    FamilySourceLimits,
)
from app.mana_ai.domain.source_reviews import (
    SourceReviewBundle,
    SourceReviewPolicy,
    counter_comparison_view,
    reported_counter_changes,
)
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services import parent_chat_runtime as runtime_module
from app.services.day_usage_cache import day_page_fingerprint
from app.services.lab_usage_comparison import LabUsageComparisonClock
from app.services.location_source_cache import SqliteLocationSourceCache
from app.services.mana_chat_lab import LAB_CHILD, LAB_PARENT, ChatLab, LabOptions
from app.services.parent_clarification_store import SqliteClosedParentClarificationStore
from app.services.source_review_prompts import source_review_prompt
from app.services.usage_comparison_cache import SqliteUsageComparisonCache
from app.services.usage_comparison_safety_store import (
    SqliteClosedUsageComparisonSafetyStore,
    SqliteUsageComparisonSafetyStore,
)
from scripts.mana_chat_lab import create_app
from tests.test_family_source_runtime import config, make_credential_file
from tests.test_lab_chat_actions import BASE, session


def snapshot(path: Path) -> dict[str, list[tuple[object, ...]]]:
    with sqlite3.connect(path) as db:
        return {
            name: db.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


def options(directory: Path) -> LabOptions:
    return LabOptions(
        directory,
        clock=LabUsageComparisonClock(),
        worker_enabled=False,
        native_sources=True,
        native_observations=True,
        source_reviews=True,
        reminders=True,
        retention=True,
        upsell=True,
        tariff_context=True,
        expiry=True,
        manager=True,
        day_usage=True,
        dated_reviews=True,
        usage_comparisons=True,
        clarifications=True,
        parent_support_questions=True,
        safety_remainder=True,
        expiry_fixture_days=30,
    )


def reviews(lab: ChatLab) -> SourceReviewService:
    assert isinstance(lab.source_store, SqliteUsageComparisonCache)
    assert isinstance(lab.store, SqliteUsageComparisonSafetyStore)
    return SourceReviewService(
        lab.source_store,
        lab.store,
        lab._profiles,
        clock=lab.options.clock.now,
        available=lambda: lab.safety.worker_available,
    )


async def prepared(path: Path) -> tuple[ChatLab, SourceReviewService, SourceReviewBundle]:
    lab = ChatLab(options(path))
    await lab.start()
    result = await lab.prepare_usage_comparison()
    assert result["status"] == "completed" and lab.day_provider.calls == 2
    service = reviews(lab)
    work = await service.process_one()
    assert work and work.phase == "prepared" and work.bundle.usage_comparison is not None
    return lab, service, work.bundle


async def test_saved_adjacent_days_reach_one_proactive_chat_and_replay_reads_nothing(
    tmp_path: Path,
) -> None:
    lab, service, bundle = await prepared(tmp_path / "chat")
    try:
        view = counter_comparison_view(bundle)
        assert view and view.matched_single_rows[0].change_seconds == 1800
        assert str(view.previous_query_calendar_day) == "2026-10-24"
        assert str(view.current_query_calendar_day) == "2026-10-25"
        assert not view.previous_app_page_complete and not view.current_app_page_complete
        assert not view.verified_behavioral_change
        admitted = await service.process_one()
        assert admitted and admitted.phase == "admitted" and admitted.job_id
        result = await lab.safety.process_one()
        assert result and result.status == "completed"
        delivery = await lab.store.next_delivery(lab.options.clock.now())
        assert delivery
        with lab.store._connect() as db:
            raw = db.execute(
                "SELECT payload FROM family_notices WHERE capability='source-review'"
            ).fetchone()
            assert raw and FamilyNotice.model_validate_json(raw[0]).counter_comparison == view
        answer = await lab.touch.deliver(delivery)
        assert all(
            s in answer.answer for s in ("2026-10-24", "2026-10-25", "1800", "3600", "не экранное")
        )
        state = await lab.state()
        assert len(state.history.messages) == 1 and state.history.messages[0].role == "assistant"
        assert state.safety_budget.server_used_tokens == state.history.quota.used_tokens == 150
        before = snapshot(lab.source_store._path)
        await lab.prepare_usage_comparison()
        assert snapshot(lab.source_store._path) == before and lab.day_provider.calls == 2
        assert await service.process_one() is None
        assert await lab.safety.process_one() is None
        assert len((await lab.state()).history.messages) == 1
        assert await lab.store.next_delivery(lab.options.clock.now()) is None
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM usage_comparison_jobs").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM child_safety_jobs").fetchone()[0] == 1
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
    finally:
        await lab.close()


async def test_exact_arithmetic_omits_unmatched_and_ambiguous_apps(tmp_path: Path) -> None:
    lab, _, bundle = await prepared(tmp_path / "math")
    try:
        assert bundle.usage_comparison
        previous = bundle.usage_comparison.previous.facts
        current = next(s.facts for s in bundle.snapshots if isinstance(s.facts, ChildAppUsageFacts))
        assert isinstance(previous, ChildAppUsageFacts)
        current = current.model_copy(
            update={
                "entries": current.entries
                + (
                    AppUsageCounter(
                        app_name="Only current",
                        provider_recorded_at="2026-10-25 15:00:00",
                        reported_seconds=500,
                    ),
                ),
                "returned_apps": 2,
            }
        )
        rows = reported_counter_changes(current, previous)
        assert len(rows) == 1 and rows[0].change_seconds == 1800
        ambiguous = previous.model_copy(
            update={
                "entries": previous.entries
                + (
                    previous.entries[0].model_copy(
                        update={"provider_recorded_at": "2026-10-24 13:00:00"}
                    ),
                )
            }
        )
        assert reported_counter_changes(current, ambiguous) == ()
        with pytest.raises(ValueError):
            reported_counter_changes(
                current, previous.model_copy(update={"child_id": LAB_CHILD + 1})
            )
    finally:
        await lab.close()


@pytest.mark.parametrize(
    "change", ["foreign_child", "nonadjacent_day", "fingerprint", "snapshot", "future_collection"]
)
async def test_comparison_requires_exact_frozen_provenance(tmp_path: Path, change: str) -> None:
    lab, _, bundle = await prepared(tmp_path / change)
    try:
        data = bundle.model_dump(mode="json")
        comparison = data["usage_comparison"]
        if change == "foreign_child":
            comparison["previous"]["facts"]["child_id"] = LAB_CHILD + 1
        elif change == "nonadjacent_day":
            comparison["previous"]["requested_day"] = "2026-10-22"
        elif change == "fingerprint":
            comparison["current_fingerprint"] = "0" * 64
        elif change == "snapshot":
            comparison["current_snapshot_id"] = str(uuid4())
        else:
            comparison["previous"]["facts"]["collected_at"] = (
                bundle.frozen_at + timedelta(days=1)
            ).isoformat()
        with pytest.raises(ValidationError):
            SourceReviewBundle.model_validate(data)
    finally:
        await lab.close()


async def test_disabled_capture_cannot_gain_history_on_replay_or_reenable(tmp_path: Path) -> None:
    lab = ChatLab(options(tmp_path / "disabled"))
    await lab.start()
    assert isinstance(lab.source_store, SqliteUsageComparisonCache)
    lab.source_store._comparisons_enabled = False
    try:
        await lab.prepare_usage_comparison()
        lab.source_store._comparisons_enabled = True
        await lab.prepare_usage_comparison()
        work = await reviews(lab).process_one()
        assert work and work.bundle.usage_comparison is None and lab.day_provider.calls == 2
        assert "usage_comparison" not in work.bundle.model_dump(mode="json")
        legacy = work.bundle.model_dump(mode="json")
        assert SourceReviewBundle.model_validate(legacy).model_dump(mode="json") == legacy
    finally:
        await lab.close()


async def test_disabling_captured_preparation_skips_it_without_ownership_or_model_retry(
    tmp_path: Path,
) -> None:
    lab, service, _ = await prepared(tmp_path / "stop-cache")
    assert isinstance(lab.source_store, SqliteUsageComparisonCache)
    lab.source_store._comparisons_enabled = False
    try:
        assert await service.process_one() is None
        state = await lab.state()
        assert state.source_reviews[0].phase == "skipped"
        assert state.safety_budget.server_used_tokens == 0 and lab.day_provider.calls == 2
        lab.source_store._comparisons_enabled = True
        assert await service.process_one() is None
    finally:
        await lab.close()


async def test_unknown_model_hold_survives_current_closed_restart_and_midnight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = options(tmp_path / "unknown")
    lab = ChatLab(selected)
    await lab.start()
    await lab.prepare_usage_comparison()
    service = reviews(lab)
    await service.process_one()
    admitted = await service.process_one()
    assert admitted and admitted.job_id
    entered = asyncio.Event()

    async def blocked(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("Cancelled inference cannot return a verified receipt")

    monkeypatch.setattr(lab.safety._model, "respond", blocked)
    task = asyncio.create_task(lab.safety.process_one())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    state = await lab.state()
    assert state.safety_budget.server_reserved_tokens == 612
    before = snapshot(lab.store._path)
    closed = SqliteClosedUsageComparisonSafetyStore(
        lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
    )
    await closed.initialize()
    assert snapshot(lab.store._path) == before
    with pytest.raises(RuntimeError):
        await SqliteClosedParentClarificationStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
    assert snapshot(lab.store._path) == before
    tomorrow = lab.options.clock.now() + timedelta(days=1)
    assert (await lab.store.safety_budget(LAB_PARENT, tomorrow)).server_reserved_tokens == 612
    await lab.close()
    restart = ChatLab(replace(selected, clock=LabUsageComparisonClock()))
    await restart.start()
    try:
        assert snapshot(restart.store._path) == before
        assert await restart.safety.process_one() is None
        assert restart.day_provider.calls == 0
    finally:
        await restart.close()


async def test_model_prompt_contains_minimized_math_and_old_protocol_is_unchanged(
    tmp_path: Path,
) -> None:
    lab, service, bundle = await prepared(tmp_path / "prompt")
    try:
        await service.process_one()
        job = await lab.store.claim_next(lab.options.clock.now())
        assert job
        prompt = source_review_prompt(job, await lab._profiles.read(LAB_PARENT)).input
        data = json.loads(prompt.messages[0][1])
        projection = data["saved_counter_comparison"]
        assert projection["matched_single_rows"][0]["change_seconds"] == 1800
        assert "child_id" not in json.dumps(projection) and "snapshot_id" not in json.dumps(
            projection
        )
        assert "never actual" in prompt.instructions or "not actual" in prompt.instructions
        legacy = bundle.model_dump()
        legacy.pop("usage_comparison")
        old_bundle = SourceReviewBundle.model_validate(legacy)
        old_job = replace(job, context=job.context.model_copy(update={"source_review": old_bundle}))
        old_prompt = source_review_prompt(old_job, await lab._profiles.read(LAB_PARENT)).input
        assert "saved_counter_comparison" not in old_prompt.instructions
        assert "saved_counter_comparison" not in old_prompt.messages[0][1]
    finally:
        await lab.close()


async def test_old_inflight_source_upgrade_preserves_cells_without_comparison_capture(
    tmp_path: Path,
) -> None:
    lab = ChatLab(options(tmp_path / "old-source"))
    await lab.start()
    common: dict[str, Any] = dict(
        binding="fake-lab-mana-battery-v1",
        limits=FamilySourceLimits(),
        policy=SourceSafetyPolicy(timezone="Asia/Samarkand"),
        enabled=True,
        review_policy=SourceReviewPolicy(),
        dated_reviews_enabled=True,
    )
    path = tmp_path / "legacy-v7.sqlite3"
    old = SqliteLocationSourceCache(path, **common)
    await old.initialize()
    service = FamilyDayUsageService(
        old, lab.day_provider, lab.day_provider, clock=lab.options.clock.now
    )
    baseline = DayUsageTarget(
        parent_id=LAB_PARENT,
        child_id=LAB_CHILD,
        request_id=uuid4(),
        requested_day=lab.options.clock.now().date() - timedelta(days=1),
    )
    assert (await service.read_for_analysis(baseline)).status == "completed"
    assert isinstance(lab.options.clock, LabUsageComparisonClock)
    lab.options.clock.next_day()
    target = baseline.model_copy(
        update={"request_id": uuid4(), "requested_day": baseline.requested_day + timedelta(days=1)}
    )
    assert (await old.claim_day(target, lab.options.clock.now())).admitted
    before = snapshot(path)
    upgraded = SqliteUsageComparisonCache(path, comparisons_enabled=True, **common)
    await upgraded.initialize()
    after = snapshot(path)
    assert {name: after[name] for name in before} == before
    try:
        lookup = await lab.day_provider.read_usage_lookup(LAB_PARENT)
        page = await lab.day_provider.read_verified(lookup, target.requested_day)
        receipt = await upgraded.complete_day(target, page, lab.options.clock.now())
        assert receipt.status == "completed"
        work = await upgraded.claim_next_review(lab.options.clock.now() + timedelta(seconds=3))
        assert work and work.bundle.usage_comparison is None
        with upgraded._connection() as db:
            assert not db.execute("SELECT 1 FROM usage_comparison_admissions").fetchone()
            assert not db.execute("SELECT 1 FROM usage_comparison_heads").fetchone()
        current = snapshot(path)
        with pytest.raises(ValueError):
            await old.initialize()
        assert snapshot(path) == current
    finally:
        await lab.close()


async def test_late_disabled_model_result_keeps_verified_cost_without_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, service, _ = await prepared(tmp_path / "late")
    assert isinstance(lab.store, SqliteUsageComparisonSafetyStore)
    await service.process_one()
    original = lab.safety._model.respond

    async def late(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        result = await original(prompt, max_output_tokens=max_output_tokens)
        assert isinstance(lab.store, SqliteUsageComparisonSafetyStore)
        lab.store._comparisons_enabled = False
        return result

    monkeypatch.setattr(lab.safety._model, "respond", late)
    try:
        result = await lab.safety.process_one()
        assert result and result.status == "failed"
        state = await lab.state()
        assert (
            state.safety_budget.server_used_tokens == 150
            and state.safety_budget.server_reserved_tokens == 0
        )
        assert not state.history.messages
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM family_notices").fetchone()
    finally:
        await lab.close()


async def test_unknown_source_is_never_redispatched_by_scenario_replay_or_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = options(tmp_path / "source-unknown")
    lab = ChatLab(selected)
    await lab.start()
    original = lab.day_provider.read_verified
    entered = asyncio.Event()

    async def interrupted(lookup: Any, requested_day: Any) -> Any:
        if str(requested_day) == "2026-10-25":
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("Cancelled source must not produce data")
        return await original(lookup, requested_day)

    monkeypatch.setattr(lab.day_provider, "read_verified", interrupted)
    pending = asyncio.create_task(lab.prepare_usage_comparison())
    await asyncio.wait_for(entered.wait(), 5)
    pending.cancel()
    with suppress(asyncio.CancelledError):
        await pending
    assert lab.day_provider.calls == 1
    before = snapshot(lab.source_store._path)
    with pytest.raises(ParentChatError, match="lab_usage_comparison_unresolved"):
        await lab.prepare_usage_comparison()
    assert snapshot(lab.source_store._path) == before
    await lab.close()
    restored = ChatLab(replace(selected, clock=LabUsageComparisonClock()))
    await restored.start()
    try:
        with pytest.raises(ParentChatError, match="lab_usage_comparison_unresolved"):
            await restored.prepare_usage_comparison()
        assert restored.day_provider.calls == 0 and snapshot(restored.source_store._path) == before
    finally:
        await restored.close()


async def test_local_scenario_api_requires_session_csrf_and_replay_only_observes(
    tmp_path: Path,
) -> None:
    app = create_app(options=options(tmp_path / "api"))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        body = {"parent_id": LAB_PARENT}
        denied = await client.post("/lab/usage-comparison", json=body)
        assert denied.status_code == 401
        headers = await session(client)
        denied = await client.post("/lab/usage-comparison", json=body)
        assert denied.status_code == 403
        result = await client.post("/lab/usage-comparison", json=body, headers=headers)
        assert result.status_code == 200 and result.json()["status"] == "completed"
        lab = app.state.chat_lab
        before = snapshot(lab.source_store._path)
        repeated = await client.post("/lab/usage-comparison", json=body, headers=headers)
        assert repeated.json() == result.json()
        assert lab.day_provider.calls == 2 and snapshot(lab.source_store._path) == before


async def test_actual_runtime_selects_v30_v8_without_idle_io_and_retains_disabled_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[str] = []

    def denied(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.host)
        raise AssertionError("Idle provider request")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_: httpx.MockTransport(denied))
    settings = config(
        tmp_path,
        make_credential_file(tmp_path),
        mana_parent_touch_review_first_enabled=True,
        mana_child_safety_enabled=True,
        mana_child_safety_source_tools_enabled=True,
        mana_family_source_safety_enabled=True,
        mana_family_app_usage_enabled=True,
        mana_family_source_reviews_enabled=True,
        mana_parent_reminders_enabled=True,
        mana_client_retention_enabled=True,
        mana_client_upsell_enabled=True,
        mana_retention_expiry_enabled=True,
        mana_parent_touch_manager_enabled=True,
        mana_family_day_usage_enabled=True,
        mana_family_day_reviews_enabled=True,
        mana_family_usage_comparisons_enabled=True,
        mana_child_safety_limits=ChildSafetyLimits(
            job_tokens=2000, server_daily_tokens=2000, parent_daily_tokens=2000, lease_seconds=360
        ),
    )
    for enabled in (True, False):
        current = settings.model_copy(update={"mana_family_usage_comparisons_enabled": enabled})
        async with runtime_module.parent_chat_runtime(current):
            with sqlite3.connect(settings.mana_parent_chat_database_path) as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 30
                assert not db.execute("SELECT 1 FROM usage_comparison_jobs").fetchone()
            with sqlite3.connect(settings.mana_family_source_database_path) as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 8
                assert not db.execute("SELECT 1 FROM usage_comparison_admissions").fetchone()
    assert not requests


async def test_bounded_full_family_cache_is_minimized_before_own_child_context(
    tmp_path: Path,
) -> None:
    lab = ChatLab(options(tmp_path / "large-family"))
    await lab.start()
    assert isinstance(lab.source_store, SqliteUsageComparisonCache)
    now = lab.options.clock.now()
    day = now.date() - timedelta(days=1)
    children = tuple(
        ChildAppUsageFacts(
            child_id=LAB_CHILD + child,
            status="available",
            returned_apps=10,
            total_apps=10,
            complete=True,
            collected_at=now,
            entries=tuple(
                AppUsageCounter(
                    app_name="🎵" * 156 + str(app),
                    provider_recorded_at=f"{day} 12:{counter:02}:00",
                    reported_seconds=3600,
                )
                for app in range(10)
                for counter in range(10)
            ),
        )
        for child in range(10)
    )
    page = FamilyDayUsagePage(
        parent_id=LAB_PARENT,
        requested_day=day,
        ownership_collected_at=now,
        collected_at=now,
        owned_children_count=10,
        provider_children_count=10,
        children=children,
        complete_family=True,
    )
    payload = page.model_dump_json()
    assert 262144 < len(payload.encode()) < 1048576
    identity = str(uuid4())
    try:
        with lab.source_store._connection() as db:
            db.execute(
                "INSERT INTO day_usage_snapshots VALUES(?,?,?,?,?)",
                (identity, LAB_PARENT, str(day), day_page_fingerprint(page), payload),
            )
            db.execute(
                "INSERT INTO day_usage_heads VALUES(?,?,?,?)",
                (LAB_PARENT, str(day), identity, now.isoformat()),
            )
            previous = lab.source_store._previous(
                db,
                DayUsageTarget(
                    parent_id=LAB_PARENT,
                    child_id=LAB_CHILD,
                    request_id=uuid4(),
                    requested_day=day + timedelta(days=1),
                ),
                LAB_CHILD,
                now + timedelta(days=1),
            )
        assert previous and previous.facts.child_id == LAB_CHILD
        assert isinstance(previous.facts, ChildAppUsageFacts) and len(previous.facts.entries) == 100
    finally:
        await lab.close()
