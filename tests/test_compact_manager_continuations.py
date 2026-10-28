"""Captured44 stops fence owning work while known and unknown receipts survive."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.source_tool_workflow import SourceToolWorkflow
from app.mana_ai.domain.conversion_catalog import ConversionCatalogObservation
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.services.compact_manager_decision_store import (
    SqliteClosedCompactManagerDecisionStore,
    SqliteCompactManagerDecisionStore,
)
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from tests.test_compact_manager_native import setup
from tests.test_mana_chat_lab import Clock
from tests.test_saved_observations import snapshot


async def ask(lab: ChatLab, message: str) -> ParentTouchMessageRequest:
    request = ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=message)
    await lab.touch.admit_message(request)
    assert await lab.touch.process_reviewed_message()
    return request


def native_store(lab: ChatLab) -> SqliteCompactManagerDecisionStore:
    assert isinstance(lab.store, SqliteCompactManagerDecisionStore)
    return lab.store


def native_workflow(lab: ChatLab) -> SourceToolWorkflow:
    assert isinstance(lab.safety._native_sources, SourceToolWorkflow)
    return lab.safety._native_sources


def fence(lab: ChatLab, change: str) -> None:
    if change == "disabled":
        native_store(lab)._compact_decisions_enabled = False
    else:
        with lab.store._transaction() as db:
            if change == "audit_lost":
                db.execute("DELETE FROM compact_manager_decisions")
            elif change == "capture_lost":
                db.execute("DELETE FROM compact_manager_admissions")
            elif change == "audit_changed":
                db.execute("UPDATE compact_manager_decisions SET fingerprint='changed'")
            elif change == "admission_and_marker_lost":
                db.execute("DELETE FROM compact_manager_admissions")
                db.execute(
                    "UPDATE parent_publication_captures SET manager_binding=(SELECT binding "
                    "FROM parent_touch_manager_turns m WHERE "
                    "m.turn_id=parent_publication_captures.turn_id)"
                )
            else:
                raise AssertionError("Unknown fictional stop")


@pytest.mark.parametrize(
    "change",
    ["disabled", "audit_lost", "capture_lost", "audit_changed", "admission_and_marker_lost"],
)
@pytest.mark.parametrize("owner", ["child_safety", "battery", "tariff"])
async def test_queued_owning_work_stops_before_model_or_source(
    tmp_path: Path, change: str, owner: str
) -> None:
    lab = await setup(tmp_path / (owner + change))
    try:
        request = await ask(
            lab,
            {
                "child_safety": "Как помочь ребёнку учиться?",
                "battery": "Какой заряд у ребёнка?",
                "tariff": "Тариф на 90 дней до 200000 UZS",
            }[owner],
        )
        fence(lab, change)
        if owner == "tariff":
            assert not await lab.touch.process_upsell()
        else:
            job = await lab.safety.process_one()
            assert job is not None and job.status == "failed"
            assert (await lab.safety.budget(LAB_PARENT)).server_used_tokens == 0
            await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed" and state.response is None
        assert lab.catalog.calls == lab.battery.calls == 0
        assert (await lab.state()).history.quota.used_tokens == 150
    finally:
        await lab.close()


@pytest.mark.parametrize("change", ["disabled", "audit_lost"])
async def test_stop_after_priced_native_safety_receipt_prevents_source_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    lab = await setup(tmp_path / change)
    original = native_workflow(lab)._model.respond_source

    async def priced_then_stopped(*args: Any, **kwargs: Any) -> Any:
        result = await original(*args, **kwargs)
        fence(lab, change)
        return result

    monkeypatch.setattr(native_workflow(lab)._model, "respond_source", priced_then_stopped)
    try:
        request = await ask(lab, "Какой заряд у ребёнка?")
        job = await lab.safety.process_one()
        assert job is not None and job.status == "failed"
        budget = await lab.safety.budget(LAB_PARENT)
        assert budget.server_used_tokens == 150 and budget.server_reserved_tokens == 0
        assert lab.battery.calls == 0
        await lab.touch.process_reviewed_message()
        assert (await lab.touch.message_state(LAB_PARENT, request.request_id)).phase == "failed"
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM source_tool_receipts").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM compact_manager_rejections").fetchone()[0] == 0
    finally:
        await lab.close()


@pytest.mark.parametrize("change", ["disabled", "audit_lost"])
@pytest.mark.parametrize("lost", [False, True])
async def test_late_catalogue_outcome_retains_read_meter_without_publishing_or_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str, lost: bool
) -> None:
    lab = await setup(tmp_path / (change + str(lost)))
    entered, release = asyncio.Event(), asyncio.Event()
    original = lab.catalog.read

    async def blocked() -> ConversionCatalogObservation:
        entered.set()
        await release.wait()
        if lost:
            raise TimeoutError("Fictional submitted catalogue outcome is unknown")
        return await original()

    monkeypatch.setattr(lab.catalog, "read", blocked)
    try:
        request = await ask(lab, "Тариф на 90 дней до 200000 UZS")
        task = asyncio.create_task(lab.touch.process_upsell())
        await asyncio.wait_for(entered.wait(), 3)
        fence(lab, change)
        release.set()
        assert await task
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed" and state.response is None
        assert (await lab.state()).history.quota.used_tokens == 150
        with lab.store._connect() as db:
            row = db.execute(
                "SELECT status,reserved_http_attempts FROM upsell_catalog_reads"
            ).fetchone()
            assert tuple(row) == ("unknown" if lost else "recorded", 2)
            assert (
                db.execute("SELECT status FROM upsell_inline_replies").fetchone()[0] == "cancelled"
            )
        calls = lab.catalog.calls
        assert not await lab.touch.process_upsell() and lab.catalog.calls == calls
        assert await lab.touch.admit_message(request) == state
        before = snapshot(lab.store._path)
        await SqliteClosedCompactManagerDecisionStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
        assert snapshot(lab.store._path) == before
    finally:
        release.set()
        await lab.close()


@pytest.mark.parametrize("change", ["disabled", "audit_lost", "capture_lost"])
async def test_currency_answer_cannot_resume_a_stopped_native_enquiry(
    tmp_path: Path, change: str
) -> None:
    lab = await setup(tmp_path / change)
    try:
        request = await ask(lab, "Тариф на 90 дней до 200000")
        question = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert question.response and question.response.asked_question
        fence(lab, change)
        before = snapshot(lab.store._path)
        with pytest.raises(ParentChatError):
            await lab.touch.admit_message(
                ParentTouchMessageRequest(
                    parent_id=LAB_PARENT,
                    request_id=uuid4(),
                    message="UZS",
                    reply_to_question_id=question.response.asked_question.question_id,
                )
            )
        assert snapshot(lab.store._path) == before
        assert lab.catalog.calls == 0
        assert await lab.touch.admit_message(request) == question
    finally:
        await lab.close()


@pytest.mark.parametrize("change", ["disabled", "capture_lost"])
@pytest.mark.parametrize("owner", ["child_safety", "tariff"])
async def test_late_known_initial_native_decision_is_metered_and_minimally_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str, owner: str
) -> None:
    lab = await setup(tmp_path / (owner + change))
    original = lab.touch._model.respond

    async def late(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        receipt = await original(prompt, max_output_tokens=max_output_tokens)
        fence(lab, change)
        return receipt

    monkeypatch.setattr(lab.touch._model, "respond", late)
    try:
        request = await ask(
            lab,
            "Как помочь ребёнку учиться?"
            if owner == "child_safety"
            else "Тариф на 90 дней до 200000 UZS",
        )
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed" and state.response is None
        quota = (await lab.state()).history.quota
        assert quota.used_tokens == 150 and quota.reserved_tokens == 0
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM compact_manager_decisions").fetchone()[0] == 0
            row = db.execute("SELECT * FROM compact_manager_rejections").fetchone()
            assert row["reason"] == ("disabled" if change == "disabled" else "capture_invalid")
            assert row["failure_code"] is None
            assert (
                row["kind"] == ("child_safety" if owner == "child_safety" else "upsell")
                if change == "disabled"
                else row["kind"] is None
            )
            assert row["call_id"] is not None if change == "disabled" else row["call_id"] is None
            assert set(row.keys()) == {
                "turn_id",
                "parent_id",
                "reason",
                "failure_code",
                "call_id",
                "kind",
                "recorded_at",
            }
            assert db.execute("SELECT COUNT(*) FROM child_safety_parent_events").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM upsell_intents").fetchone()[0] == 0
        assert lab.catalog.calls == lab.battery.calls == 0
    finally:
        await lab.close()


async def test_known_invalid_output_has_only_allowlisted_rejection_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = await setup(tmp_path / "invalid")
    original = lab.touch._model.respond

    async def invalid(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        receipt = await original(prompt, max_output_tokens=max_output_tokens)
        return replace(
            receipt,
            completed=False,
            answer=None,
            native_manager_invocation=None,
            failure_code="reply_schema_invalid",
        )

    monkeypatch.setattr(lab.touch._model, "respond", invalid)
    try:
        await ask(lab, "Привет")
        assert (await lab.state()).history.quota.used_tokens == 150
        with lab.store._connect() as db:
            row = db.execute("SELECT * FROM compact_manager_rejections").fetchone()
            assert row["reason"] == "output_invalid"
            assert row["failure_code"] == "reply_schema_invalid"
            assert row["call_id"] is None and row["kind"] is None
            assert "Здравствуйте" not in str(tuple(row))
        fence(lab, "admission_and_marker_lost")
        with lab.store._connect() as db, pytest.raises(ParentChatError):
            native_store(lab)._native_capture(db, LAB_PARENT, row["turn_id"])
    finally:
        await lab.close()


@pytest.mark.parametrize("owner", ["reply", "child_safety", "tariff"])
async def test_completed_history_and_closed_reader_remain_exact_after_disable(
    tmp_path: Path, owner: str
) -> None:
    lab = await setup(tmp_path / owner)
    try:
        request = await ask(
            lab,
            {
                "reply": "Привет",
                "child_safety": "Как помочь ребёнку учиться?",
                "tariff": "Тариф на 90 дней до 200000 UZS",
            }[owner],
        )
        if owner == "child_safety":
            job = await lab.safety.process_one()
            assert job and job.status == "completed"
            assert await lab.touch.process_reviewed_message()
        elif owner == "tariff":
            assert await lab.touch.process_upsell()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "completed" and state.response
        history = await lab.touch.read_touch_history(LAB_PARENT, before=None, limit=100)
        before = snapshot(lab.store._path)
        fence(lab, "disabled")
        assert await lab.touch.admit_message(request) == state
        assert await lab.touch.read_touch_history(LAB_PARENT, before=None, limit=100) == history
        assert await native_store(lab).input_presentation(LAB_PARENT, state.turn_id) == 1
        await SqliteClosedCompactManagerDecisionStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
        assert snapshot(lab.store._path) == before
    finally:
        await lab.close()


async def test_uncaptured_legacy_owner_continues_without_native_metadata(tmp_path: Path) -> None:
    lab = await setup(tmp_path / "legacy")
    try:
        native_store(lab)._compact_decisions_enabled = False
        request = await ask(lab, "Как помочь ребёнку учиться?")
        native_store(lab)._compact_decisions_enabled = True
        job = await lab.safety.process_one()
        assert job and job.status == "completed"
        assert await lab.touch.process_reviewed_message()
        assert (await lab.touch.message_state(LAB_PARENT, request.request_id)).phase == "completed"
        with lab.store._connect() as db:
            for table in (
                "compact_manager_admissions",
                "compact_manager_decisions",
                "compact_manager_rejections",
            ):
                assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    finally:
        await lab.close()


async def test_unknown_safety_hold_survives_disable_and_midnight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = await setup(tmp_path / "unknown")

    async def lost(*args: Any, **kwargs: Any) -> Any:
        fence(lab, "disabled")
        raise TimeoutError("Fictional submitted native receipt is unknown")

    monkeypatch.setattr(native_workflow(lab)._model, "respond_source", lost)
    try:
        await ask(lab, "Как помочь ребёнку учиться?")
        job = await lab.safety.process_one()
        assert job and job.status == "unknown"
        budget = await lab.safety.budget(LAB_PARENT)
        assert budget.server_used_tokens == 0 and budget.server_reserved_tokens > 0
        with lab.store._connect() as db:
            original = tuple(
                db.execute(
                    "SELECT status,reserved,input_tokens,output_tokens FROM child_safety_jobs"
                ).fetchone()
            )
        assert isinstance(lab.options.clock, Clock)
        lab.options.clock.value += timedelta(days=1)
        await lab.touch.process_reviewed_message()
        assert await lab.safety.process_one() is None
        with lab.store._connect() as db:
            assert (
                tuple(
                    db.execute(
                        "SELECT status,reserved,input_tokens,output_tokens FROM child_safety_jobs"
                    ).fetchone()
                )
                == original
            )
        before = snapshot(lab.store._path)
        await SqliteClosedCompactManagerDecisionStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
        assert snapshot(lab.store._path) == before
    finally:
        await lab.close()
