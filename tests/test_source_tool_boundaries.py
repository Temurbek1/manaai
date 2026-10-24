"""Lost acknowledgements and frozen policy under the actual private ledger."""

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ChatTokens
from app.mana_ai.domain.child_safety import SafetyJob, SafetyStoredResult
from tests.test_child_source_model import NOW
from tests.test_source_tool_workflow import request, setup


@pytest.mark.parametrize("change", ["effort", "output", "job_budget"])
async def test_pending_native_turn_keeps_original_serving_and_budget_conditions(
    tmp_path: Path, change: str
) -> None:
    original = await setup(tmp_path)
    await original.touch.admit_message(request())
    updated = await setup(
        tmp_path,
        effort="high" if change == "effort" else "none",
        output=256 if change == "output" else 512,
        job_tokens=1000 if change == "job_budget" else 2000,
    )
    result = await updated.safety.process_one()
    assert result and result.status == "failed" and result.usage is None
    assert updated.provider.requests == [] and updated.battery.calls == 0
    await original.adapter.close()
    await updated.adapter.close()


async def test_lost_first_usage_ack_retains_verified_spend_without_dispatching_source(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    runtime = await setup(tmp_path)
    await runtime.touch.admit_message(request())
    original = runtime.store.record_native_usage

    async def lose(
        job: SafetyJob, position: int, usage: ChatTokens, model: str, now: datetime
    ) -> int | None:
        await original(job, position, usage, model, now)
        raise asyncio.CancelledError

    monkeypatch.setattr(runtime.store, "record_native_usage", lose)
    with pytest.raises(asyncio.CancelledError):
        await runtime.safety.process_one()
    results = await runtime.safety.assessments("123", after=0, limit=20)
    value = results.assessments[0]
    assert value.status == "failed" and value.usage and value.usage.total == 150
    assert value.error_code == "native_source_receipt_processing_interrupted"
    budget = await runtime.safety.budget("123")
    assert budget.server_used_tokens == 150 and budget.server_reserved_tokens == 0
    assert runtime.battery.calls == 0
    assert await runtime.safety.process_one() is None
    await runtime.adapter.close()


async def test_verified_late_second_receipt_settles_cost_but_never_revives_decision(
    tmp_path: Path,
) -> None:
    runtime = await setup(tmp_path)
    runtime.provider.lose_second = True
    await runtime.touch.admit_message(request())
    unknown = await runtime.safety.process_one()
    assert unknown and unknown.status == "unknown"
    with runtime.store._connect() as sql:
        job = runtime.store._job(sql.execute("SELECT * FROM child_safety_jobs").fetchone())
    assert (
        await runtime.store.record_native_usage(
            job, 1, ChatTokens(input_tokens=100, output_tokens=50), "gpt-5.4-mini", NOW
        )
        is None
    )
    settled = await runtime.safety.assessment("123", unknown.job_id)
    assert settled.status == "failed" and settled.usage and settled.usage.total == 300
    assert settled.error_code == "native_source_stopped_receipt_discarded"
    assert (await runtime.safety.budget("123")).server_reserved_tokens == 0
    with pytest.raises(ParentChatError):
        await runtime.store.finish_safety(
            job, SafetyStoredResult(followup_summary="Late unaccepted decision"), NOW
        )
    assert await runtime.safety.process_one() is None and runtime.battery.calls == 1
    await runtime.adapter.close()


async def test_empty_child_scope_cannot_query_a_source(tmp_path: Path) -> None:
    runtime = await setup(tmp_path)
    runtime.profiles.revoke_at = 1
    await runtime.touch.admit_message(request())
    result = await runtime.safety.process_one()
    assert result and result.status == "completed" and result.usage and result.usage.total == 150
    creation = [p for p in runtime.provider.requests if "max_output_tokens" in p][0]
    assert creation["tools"] == [] and creation["tool_choice"] == "none"
    assert runtime.battery.calls == 0
    await runtime.adapter.close()


async def test_unreleased_interim_schema_is_refused_without_rewriting_private_history(
    tmp_path: Path,
) -> None:
    runtime = await setup(tmp_path)
    await runtime.adapter.close()
    path = tmp_path / "family.sqlite3"
    with sqlite3.connect(path) as sql:
        sql.execute("ALTER TABLE source_tool_turns RENAME COLUMN profile TO model")
        before = sql.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    with pytest.raises(RuntimeError, match="Unsupported native profile schema"):
        await setup(tmp_path)
    with sqlite3.connect(path) as sql:
        assert sql.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == before
