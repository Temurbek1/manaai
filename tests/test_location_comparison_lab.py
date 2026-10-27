"""The isolated two-point lab exercises the actual shared same-chat workflow."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.source_reviews import SourceReviewService
from app.mana_ai.domain.source_reviews import location_comparison_view
from app.services.lab_location_comparison import (
    LabLocationComparisonClock,
    prepare_location_comparison,
)
from app.services.lab_workspace import workspace_options
from app.services.location_comparison_cache import SqliteLocationComparisonCache
from app.services.location_comparison_safety_store import SqliteLocationComparisonSafetyStore
from app.services.mana_chat_lab import ChatLab


def rows(path: Path) -> dict[str, list[tuple[object, ...]]]:
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        return {
            name: db.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


async def test_fixture_first_contact_replay_and_restart_preserve_all_saved_state(
    tmp_path: Path,
) -> None:
    selected = replace(
        workspace_options(tmp_path, clock=LabLocationComparisonClock(), worker_enabled=False),
        tariff_handoff=True,
        compact_inputs=True,
        compact_publication=True,
        compact_manager=True,
        location_comparisons=True,
        usage_comparisons=False,
    )
    lab = ChatLab(selected)
    await lab.start()
    try:
        assert any(s.key == "location-comparison" for s in lab.bootstrap().scenarios)
        assert not any(s.key == "usage-comparison" for s in lab.bootstrap().scenarios)
        with pytest.raises(ParentChatError, match="lab_usage_comparison_disabled"):
            await lab.prepare_usage_comparison()
        assert (await prepare_location_comparison(lab))["external_requests"] == 0
        assert lab.location.calls == 2
        assert isinstance(lab.source_store, SqliteLocationComparisonCache)
        assert isinstance(lab.store, SqliteLocationComparisonSafetyStore)
        reviews = SourceReviewService(
            lab.source_store,
            lab.store,
            lab._profiles,
            clock=lab.options.clock.now,
            available=lambda: lab.safety.worker_available,
        )
        prepared = await reviews.process_one()
        assert prepared and prepared.phase == "prepared"
        view = location_comparison_view(prepared.bundle)
        assert view and view.stored_point_relation == "different"
        admitted = await reviews.process_one()
        assert admitted and admitted.phase == "admitted"
        result = await lab.safety.process_one()
        assert result and result.status == "completed"
        delivery = await lab.store.next_delivery(lab.options.clock.now())
        assert delivery
        response = await lab.touch.deliver(delivery)
        assert "2026-10-25" in response.answer and "2026-10-26" in response.answer
        assert "нельзя восстановить маршрут" in response.answer
        state = await lab.state()
        assert len(state.history.messages) == 1
        assert state.history.messages[0].role == "assistant"
        assert state.history.quota.used_tokens == state.safety_budget.server_used_tokens == 150
        family_before, source_before = rows(lab.store._path), rows(lab.source_store._path)
        assert (await prepare_location_comparison(lab))["status"] == "completed"
        assert rows(lab.store._path) == family_before
        assert rows(lab.source_store._path) == source_before
        assert lab.location.calls == 2
        await lab.close()
        lab = ChatLab(replace(selected, clock=LabLocationComparisonClock()))
        await lab.start()
        assert rows(lab.store._path) == family_before
        assert rows(lab.source_store._path) == source_before
        assert (await lab.state()).history.messages == state.history.messages
        assert lab.location.calls == 0
        assert (await prepare_location_comparison(lab))["status"] == "completed"
        assert rows(lab.store._path) == family_before
        assert rows(lab.source_store._path) == source_before
        assert lab.location.calls == 0
    finally:
        await lab.close()
