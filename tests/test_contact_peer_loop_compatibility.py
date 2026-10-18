"""Complete local peer history and unknown costs; no real provider/contact I/O."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.operation_contact_peer_loop_compatibility import (
    check_fingerprint,
    check_peer_loop,
)


async def test_personal_peer_loop_reconstructs_without_dispatch_and_refuses_setup_replay(
    tmp_path: Path,
) -> None:
    path = tmp_path / "peer-history.db"
    await check_peer_loop(path, stage="setup")
    manifest = path.with_suffix(".peer-loop.json")
    receipt = json.loads(manifest.read_text())
    original = manifest.read_bytes()
    assert receipt["owner"] != receipt["reviewer"] and len(receipt["steps"]) == 2
    assert len(receipt["reservation_ids"]) == 4
    assert all(
        word not in manifest.read_text() for word in ("Cookie", "mana_csrf", "encrypted_content")
    )
    for _ in range(2):
        await check_peer_loop(path, stage="verify")
    assert manifest.read_bytes() == original
    with pytest.raises(RuntimeError, match="never resume"):
        await check_peer_loop(path, stage="setup")
    check_fingerprint(path)


@pytest.mark.parametrize(
    "mutation", ["review_event", "unknown_cost", "period_usage", "reviewer_status"]
)
async def test_full_peer_fingerprint_detects_lost_audit_cost_or_identity(
    tmp_path: Path, mutation: str
) -> None:
    path = tmp_path / "peer-history.db"
    await check_peer_loop(path, stage="setup")
    expected = json.loads(path.with_suffix(".peer-loop.json").read_text())
    with sqlite3.connect(path) as connection:
        if mutation == "review_event":
            connection.execute(
                "DELETE FROM operation_contact_review_events WHERE review_id=?",
                (expected["steps"][0]["review_id"],),
            )
        elif mutation == "unknown_cost":
            connection.execute(
                "UPDATE operation_cost_reservations SET actual='{}' WHERE actual='null'"
            )
        elif mutation == "period_usage":
            connection.execute("UPDATE operation_cost_periods SET usage='{}'")
        else:
            connection.execute(
                "UPDATE operation_admin_users SET status='disabled' WHERE user_id=?",
                (expected["reviewer"],),
            )
    with pytest.raises(AssertionError):
        check_fingerprint(path)


async def test_peer_setup_refuses_existing_unmarked_database_without_changes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "existing.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE existing_data (value TEXT)")
        connection.execute("INSERT INTO existing_data VALUES ('preserve this fixture')")
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(RuntimeError, match="new isolated database"):
        await check_peer_loop(path, stage="setup")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original


@pytest.mark.parametrize("hour", [2, 23])
async def test_admission_compatibility_uses_fixture_time_without_relaxing_quiet_hours(
    tmp_path: Path, hour: int
) -> None:
    from app.mana_operation_ai.domain.chat import TopicCreate
    from app.mana_operation_ai.infrastructure.persistence.chat_repository import (
        SqlAlchemyChatRepository,
    )
    from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
    from scripts.operation_contact_admission_compatibility import check_admissions

    path = tmp_path / "admission.db"
    database = OperationDatabase(f"sqlite+aiosqlite:///{path}")
    try:
        await database.create_schema()
        chats = SqlAlchemyChatRepository(database, hourly_limit=20, daily_limit=200)
        await chats.initialize()
        topic = await chats.create(
            "fixture-owner",
            TopicCreate(
                agent_id="retention-agent",
                product="mana",
                title="Quiet-hour audit fixture",
            ),
        )
        with patch("app.mana_operation_ai.application.runtime.SystemClock") as clock:
            clock.return_value.now.return_value = datetime(2026, 10, 18, hour, tzinfo=UTC)
            await check_admissions(
                path, stage="setup", owner="fixture-owner", topic_id=topic.topic_id
            )
            await check_admissions(
                path, stage="verify", owner="fixture-owner", topic_id=topic.topic_id
            )
        expected = json.loads(path.with_suffix(".admissions.json").read_text())
        assert datetime.fromisoformat(expected["fixture_at"]).hour == 12
        assert expected["action"]["status"] == "proposed"
    finally:
        await database.dispose()
