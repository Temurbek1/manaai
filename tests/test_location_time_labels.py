"""New captured UTC labels survive the entire same-chat path without relabeling old work."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.source_reviews import SourceReviewService
from app.mana_ai.domain.child_location import LocationComparisonView
from app.mana_ai.domain.family_sources import FamilySourceLimits
from app.mana_ai.domain.source_reviews import SourceReviewPolicy, location_comparison_view
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services.lab_workspace import workspace_options
from app.services.location_comparison_safety_store import SqliteLocationComparisonSafetyStore
from app.services.location_time_cache import SqliteLocationTimeCache
from app.services.mana_chat_lab import ChatLab
from tests.test_location_comparison import facts, pair, prepared, target
from tests.test_location_comparison import setup as prior_setup
from tests.test_mana_chat_lab import Clock


async def setup(path: Path) -> tuple[ChatLab, Clock, SourceReviewService]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        replace(
            workspace_options(path, clock=clock, worker_enabled=False),
            tariff_handoff=True,
            compact_inputs=True,
            compact_publication=True,
            compact_manager=True,
            location_comparisons=True,
            location_time_labels=True,
        )
    )
    await lab.start()
    assert isinstance(lab.store, SqliteLocationComparisonSafetyStore)
    assert isinstance(lab.source_store, SqliteLocationTimeCache)
    service = SourceReviewService(
        lab.source_store,
        lab.store,
        lab._profiles,
        clock=clock.now,
        available=lambda: lab.safety.worker_available,
    )
    return lab, clock, service


async def test_exact_two_utc_labels_reach_one_assistant_message_and_replay_is_free(
    tmp_path: Path,
) -> None:
    lab, clock, service = await setup(tmp_path)
    try:
        await pair(lab, clock)
        bundle = await prepared(lab, clock, service)
        view = location_comparison_view(bundle)
        assert view and view.presentation_version == 2
        assert view.previous_measurement_label == "2026-10-24 08:59:00 UTC"
        assert view.current_measurement_label == "2026-10-24 14:59:00 UTC"
        with pytest.raises(ValidationError, match="exactly preserve"):
            LocationComparisonView.model_validate(
                view.model_dump() | {"current_measurement_label": "2026-10-23 22:59:00 UTC"}
            )
        admitted = await service.process_one()
        assert admitted and admitted.phase == "admitted"
        result = await lab.safety.process_one()
        assert result and result.status == "completed"
        delivery = await lab.store.next_delivery(clock.now())
        assert delivery
        answer = await lab.touch.deliver(delivery)
        assert view.previous_measurement_label in answer.answer
        assert view.current_measurement_label in answer.answer
        state = await lab.state()
        assert len(state.history.messages) == 1
        assert state.history.quota.used_tokens == state.safety_budget.server_used_tokens == 150
        assert await lab.touch.deliver(delivery) == answer
        assert len((await lab.state()).history.messages) == 1
        with lab.source_store._connection() as db:
            assert db.execute("SELECT COUNT(*),SUM(units) FROM source_reads").fetchone()[:] == (
                2,
                4,
            )
    finally:
        await lab.close()


@pytest.mark.parametrize("stop", ["before_model", "late_model", "wrong_labels"])
async def test_time_stop_and_invalid_display_keep_verified_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop: str
) -> None:
    lab, clock, service = await setup(tmp_path)
    assert isinstance(lab.store, SqliteLocationComparisonSafetyStore)
    store = lab.store
    try:
        await pair(lab, clock)
        await prepared(lab, clock, service)
        admitted = await service.process_one()
        assert admitted and admitted.phase == "admitted"
        completed = await lab.safety.process_one()
        assert completed and completed.status == "completed"
        delivery = await lab.store.next_delivery(clock.now())
        assert delivery
        original = lab.touch._model.respond
        if stop == "before_model":
            store._location_time_labels_enabled = False
        else:

            async def changed(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
                receipt = await original(prompt, max_output_tokens=max_output_tokens)
                if stop == "late_model":
                    store._location_time_labels_enabled = False
                    return receipt
                return replace(receipt, answer="Две записи от 2026-10-23; проверьте карту.")

            monkeypatch.setattr(lab.touch._model, "respond", changed)
        with pytest.raises(ParentChatError):
            await lab.touch.deliver(delivery)
        state = await lab.state()
        assert state.history.messages == []
        assert state.history.quota.used_tokens == (0 if stop == "before_model" else 150)
        assert not state.history.quota.blocked_by_unresolved_request
        assert state.safety_budget.server_used_tokens == 150
    finally:
        await lab.close()


async def test_original_source9_inflight_read_never_gains_time_marker(tmp_path: Path) -> None:
    lab, clock, _ = await prior_setup(tmp_path)
    try:
        lab.source_store._dispatch_enabled = False
        first = target()
        await lab.source_store.claim(first, clock.now())
        await lab.source_store.complete(first, facts(clock), clock.now())
        clock.value += timedelta(hours=6)
        lab.source_store._dispatch_enabled = True
        current = target()
        await lab.source_store.claim(current, clock.now())
        cache = SqliteLocationTimeCache(
            lab.source_store._path,
            binding="fake-lab-mana-battery-v1",
            limits=FamilySourceLimits(),
            policy=SourceSafetyPolicy(timezone="Asia/Samarkand"),
            enabled=True,
            review_policy=SourceReviewPolicy(),
            dated_reviews_enabled=True,
            location_enabled=True,
            comparisons_enabled=True,
            location_comparisons_enabled=True,
            location_time_labels_enabled=True,
        )
        await cache.initialize()
        await cache.complete(current, facts(clock, point="b"), clock.now())
        clock.value += timedelta(seconds=3)
        work = await cache.claim_next_review(clock.now())
        assert work and work.bundle.location_comparison
        assert work.bundle.location_comparison.presentation_version is None
        assert "presentation_version" not in work.bundle.location_comparison.model_dump()
        with cache._connection() as db:
            assert not db.execute("SELECT 1 FROM location_time_admissions").fetchone()
    finally:
        await lab.close()


async def test_source_stop_after_admission_retains_marker_without_single_point_fallback(
    tmp_path: Path,
) -> None:
    lab, clock, _ = await setup(tmp_path)
    assert isinstance(lab.source_store, SqliteLocationTimeCache)
    try:
        lab.source_store._dispatch_enabled = False
        first = target()
        await lab.source_store.claim(first, clock.now())
        await lab.source_store.complete(first, facts(clock), clock.now())
        clock.value += timedelta(hours=6)
        lab.source_store._dispatch_enabled = True
        current = target()
        await lab.source_store.claim(current, clock.now())
        lab.source_store._location_time_labels_enabled = False
        await lab.source_store.complete(current, facts(clock, point="b"), clock.now())
        clock.value += timedelta(seconds=3)
        assert await lab.source_store.claim_next_review(clock.now()) is None
        with lab.source_store._connection() as db:
            assert db.execute("SELECT version FROM location_time_heads").fetchone()[0] == 2
        assert (await lab.state()).history.quota.used_tokens == 0
    finally:
        await lab.close()
