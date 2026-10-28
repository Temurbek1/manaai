"""Run the unchanged mixed-specialist scenarios against new family-v41 captures."""

import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest

from app.services.compact_source_tool_store import SqliteCompactSourceToolStore
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import ChatLab
from tests import test_family_specialist_ordering as scenarios
from tests.test_mana_chat_lab import Clock


def assert_new_captures(directory: Path) -> None:
    with sqlite3.connect(f"file:{directory / 'family.sqlite3'}?mode=ro", uri=True) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 41
        profiles = db.execute("SELECT profile FROM source_tool_turns").fetchall()
        assert profiles and all(json.loads(row[0])["compact_source_tools"] == 1 for row in profiles)
        assert db.execute("SELECT COUNT(*) FROM compact_source_tool_turns").fetchone()[0] == len(
            profiles
        )
        assert db.execute("SELECT 1 FROM tariff_literal_admissions WHERE enabled=1").fetchone()


async def latest_setup(path: Path) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        replace(
            workspace_options(path, clock=clock, worker_enabled=False),
            tariff_handoff=True,
            compact_inputs=True,
            compact_publication=True,
            compact_manager=True,
            tariff_followups=True,
            literal_tariff_followups=True,
            saved_observations=True,
            compact_source_tools=True,
        )
    )
    await lab.start()
    assert isinstance(lab.store, SqliteCompactSourceToolStore)
    return lab, clock


@pytest.mark.parametrize("language", ["ru", "uz-Latn"])
async def test_latest_family_retention_urgent_safety_exact_answers_and_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: Literal["ru", "uz-Latn"]
) -> None:
    monkeypatch.setattr(scenarios, "setup", latest_setup)
    await scenarios.test_urgent_interrupt_retention_exact_answers_controls_replay_and_restart(
        tmp_path, language
    )
    assert_new_captures(tmp_path / language)


async def test_latest_family_urgent_safety_cancels_exact_inflight_tariff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scenarios, "setup", latest_setup)
    await scenarios.test_urgent_safety_cancels_inflight_quote_and_keeps_known_catalog_receipt(
        tmp_path, monkeypatch
    )
    assert_new_captures(tmp_path / "commercial-safety")
