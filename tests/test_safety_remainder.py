"""New captured observations reuse verified remaining tokens, never old/unknown jobs."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt
from app.mana_ai.application.source_reviews import SourceReviewService
from app.mana_ai.domain.chat import ChatTokens
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.requests import SafetyMonitorRequest
from app.services import mana_chat_lab as runtime
from app.services import parent_chat_runtime as runtime_module
from app.services.mana_chat_lab import LAB_CHILD, LAB_PARENT, ChatLab
from app.services.safety_remainder_store import (
    SqliteClosedSafetyRemainderStore,
    SqliteSafetyRemainderStore,
)
from app.services.source_review_cache import SqliteSourceReviewCache
from app.services.trial_end_store import SqliteClosedTrialEndStore, SqliteTrialEndStore
from tests.test_child_safety_store import analysis, result, target
from tests.test_family_source_runtime import config, make_credential_file
from tests.test_lab_chat_actions import Clock, options
from tests.test_source_reviews import read_pair
from tests.test_trial_action_cards import snapshot


def observation(
    now: datetime, *, child: int = LAB_CHILD, percent: int = 12
) -> SafetyMonitorRequest:
    request = analysis(child, percent=percent)
    return request.model_copy(
        update={
            "occurred_at": now,
            "input": request.input.model_copy(
                update={
                    "battery": [request.input.battery[0].model_copy(update={"observed_at": now})]
                }
            ),
        }
    )


async def setup(path: Path) -> tuple[ChatLab, Clock, SqliteSafetyRemainderStore]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(replace(options(path, clock), action_cards=False, safety_remainder=True))
    await lab.start()
    assert isinstance(lab.store, SqliteSafetyRemainderStore)
    return lab, clock, lab.store


async def first(lab: ChatLab, clock: Clock) -> None:
    await lab.safety.admit(target(LAB_PARENT), observation(clock.now()))
    done = await lab.safety.process_one()
    assert done and done.status == "completed" and done.usage and done.usage.total == 150


async def test_second_observation_reuses_1850_without_new_daily_allowance(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "two")
    try:
        await first(lab, clock)
        request, body = target(LAB_PARENT), observation(clock.now(), percent=25)
        admitted = await lab.safety.admit(request, body)
        claim = await store.claim_next(clock.now())
        assert claim and claim.view.job_id == admitted.job_id and claim.reserved_tokens == 1850
        done = await lab.safety._run(claim)
        assert done.status == "completed" and done.usage and done.usage.total == 150
        budget = await lab.safety.budget(LAB_PARENT)
        assert budget.server_daily_limit == budget.parent_daily_limit == 2000
        assert budget.server_used_tokens == 300 and budget.server_reserved_tokens == 0
        assert budget.server_remaining_tokens == 1700
        assert await lab.safety.admit(request, body) == done
        assert await lab.safety.process_one() is None
        with store._connect() as db:
            assert db.execute("SELECT count(*) FROM safety_remainder_admissions").fetchone()[0] == 2
    finally:
        await lab.close()


async def test_coalesced_source_review_can_follow_an_analysis_and_reach_parent_touch(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "source")
    try:
        await first(lab, clock)
        earlier_notice = await store.next_delivery(clock.now())
        assert earlier_notice
        await lab.touch.deliver(earlier_notice)
        await read_pair(lab)
        clock.value += timedelta(seconds=4)
        assert isinstance(lab.source_store, SqliteSourceReviewCache)
        service = SourceReviewService(
            lab.source_store,
            store,
            lab.safety._children,
            clock=clock.now,
            available=lambda: lab.safety.worker_available,
        )
        prepared = await service.process_one()
        assert prepared and prepared.phase == "prepared"
        admitted = await service.process_one()
        assert admitted and admitted.phase == "admitted"
        claim = await store.claim_next(clock.now())
        assert claim and claim.view.kind == "source_review" and claim.reserved_tokens == 1850
        completed = await lab.safety._run(claim)
        assert completed.status == "completed" and completed.result
        assert completed.result.source_review_notify is True
        delivery = await store.next_delivery(clock.now())
        assert delivery
        delivered = await lab.touch.deliver(delivery)
        assert delivered.delivered_notice
        with store._connect() as db:
            proof = db.execute(
                "SELECT source_job_id,capability FROM family_notices WHERE notice_id=?",
                (str(delivered.delivered_notice.notice_id),),
            ).fetchone()
            assert proof["source_job_id"] == str(completed.job_id)
            assert proof["capability"] == "source-review"
        assert len((await lab.state()).history.messages) == 2
        assert (await lab.safety.budget(LAB_PARENT)).server_used_tokens == 300
        assert await service.process_one() is None
        assert lab.battery.calls == lab.app_usage.calls == 1
    finally:
        await lab.close()


async def test_atomic_global_claims_and_cross_day_unknown_reserve_remain_bounded(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "atomic")
    try:
        await first(lab, clock)
        for parent in ("123", "456"):
            await store.admit_analysis(
                target=target(parent),
                analysis=observation(clock.now(), child=int(parent) + 1),
                now=clock.now(),
            )
        claims = await asyncio.gather(*(store.claim_next(clock.now()) for _ in range(4)))
        jobs = [claim for claim in claims if claim]
        assert len(jobs) == 1 and jobs[0].reserved_tokens == 1850
        job = jobs[0]
        await store.authorize_children(job, (int(job.view.parent_id) + 1,), clock.now())
        await store.submit_safety(job, 500, clock.now())
        await store.fail_safety(job, "safety_model_receipt_unknown", clock.now())
        other = await store.claim_next(clock.now())
        assert (
            other and other.view.parent_id != job.view.parent_id and other.reserved_tokens == 1350
        )
        budget = await store.safety_budget(job.view.parent_id, clock.now())
        assert budget.server_used_tokens + budget.server_reserved_tokens == 2000
        await store.fail_safety(other, "synthetic_no_submission", clock.now())
        tomorrow = clock.now() + timedelta(days=1)
        budget = await store.safety_budget(job.view.parent_id, tomorrow)
        assert budget.server_used_tokens == 0 and budget.server_reserved_tokens == 500
        assert budget.parent_blocked_by_unknown
        assert (await store.assessment(job.view.parent_id, job.view.job_id)).status == "unknown"
    finally:
        await lab.close()


async def test_below_64_tokens_does_not_claim_or_consume_another_attempt(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "floor")
    try:
        body = observation(clock.now())
        await store.admit_analysis(target=target(LAB_PARENT), analysis=body, now=clock.now())
        job = await store.claim_next(clock.now())
        assert job
        await store.authorize_children(job, (LAB_CHILD,), clock.now())
        await store.submit_safety(job, 2000, clock.now())
        await store.record_usage(
            job, ChatTokens(input_tokens=1900, output_tokens=37), "fake", clock.now()
        )
        await store.finish_safety(job, result(body), clock.now())
        second = await store.admit_analysis(
            target=target(LAB_PARENT),
            analysis=observation(clock.now(), percent=25),
            now=clock.now(),
        )
        assert (await store.safety_budget(LAB_PARENT, clock.now())).server_remaining_tokens == 63
        assert await store.claim_next(clock.now()) is None
        assert (await store.assessment(LAB_PARENT, second.job_id)).status == "queued"
        with store._connect() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM child_safety_jobs WHERE claim_id IS NOT NULL"
                ).fetchone()[0]
                == 1
            )
    finally:
        await lab.close()


async def test_disabled_new_jobs_and_old_v26_jobs_never_recapture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "legacy"

    def legacy(path: Path, *, remainder_enabled: bool, **family: Any) -> SqliteTrialEndStore:
        return SqliteTrialEndStore(path, **family)

    with monkeypatch.context() as patcher:
        patcher.setattr(runtime, "SqliteSafetyRemainderStore", legacy)
        clock = Clock()
        lab = ChatLab(replace(options(directory, clock), action_cards=False, safety_remainder=True))
        await lab.start()
        await first(lab, clock)
        old = await lab.safety.admit(target(LAB_PARENT), observation(clock.now(), percent=25))
        before = snapshot(lab.store)
        await lab.close()
    lab, clock, store = await setup(directory)
    try:
        after = snapshot(store)
        assert {name: after[name] for name in before} == before
        assert await store.claim_next(clock.now()) is None
        store._remainder_enabled = False
        disabled = await lab.safety.admit(target(LAB_PARENT), observation(clock.now(), percent=35))
        store._remainder_enabled = True
        assert await store.claim_next(clock.now()) is None
        current = await lab.safety.admit(target(LAB_PARENT), observation(clock.now(), percent=45))
        claim = await store.claim_next(clock.now())
        assert claim and claim.view.job_id == current.job_id and claim.reserved_tokens == 1850
        with store._connect() as db:
            assert db.execute("SELECT job_id FROM safety_remainder_admissions").fetchall()[0][
                0
            ] == str(current.job_id)
        assert (await store.assessment(LAB_PARENT, old.job_id)).status == "queued"
        assert (await store.assessment(LAB_PARENT, disabled.job_id)).status == "queued"
    finally:
        await lab.close()


async def test_current_closed_reader_and_old_refusal_preserve_partial_claims(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "closed")
    try:
        await first(lab, clock)
        await lab.safety.admit(target(LAB_PARENT), observation(clock.now(), percent=25))
        claim = await store.claim_next(clock.now())
        assert claim and claim.reserved_tokens == 1850
        await store.authorize_children(claim, (LAB_CHILD,), clock.now())
        await store.submit_safety(claim, 500, clock.now())
        await store.fail_safety(claim, "safety_model_receipt_unknown", clock.now())
        before = snapshot(store)
        closed = SqliteClosedSafetyRemainderStore(
            store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        await closed.touch_history(LAB_PARENT, before=None, limit=30, now=clock.now())
        assert snapshot(store) == before
        with pytest.raises(RuntimeError, match="dedicated database"):
            await SqliteClosedTrialEndStore(
                store._path, daily_limit=2000, timezone="Asia/Samarkand"
            ).initialize()
        assert snapshot(store) == before
    finally:
        await lab.close()


async def test_capture_failure_rolls_back_the_owning_job_and_request_alias(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "rollback")
    try:
        with store._transaction() as db:
            db.execute(
                "CREATE TRIGGER deny_capture BEFORE INSERT ON safety_remainder_admissions "
                "BEGIN SELECT RAISE(ABORT,'synthetic capture failure'); END"
            )
        with pytest.raises(sqlite3.IntegrityError):
            await lab.safety.admit(target(LAB_PARENT), observation(clock.now()))
        with store._connect() as db:
            assert db.execute("SELECT count(*) FROM child_safety_jobs").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM child_safety_requests").fetchone()[0] == 0
    finally:
        await lab.close()


async def test_insufficient_remainder_preserves_exact_context_and_never_infers_or_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock, store = await setup(tmp_path / "preflight")
    calls = 0

    async def count(prompt: ChatPrompt) -> int:
        return 1900

    async def deny(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        nonlocal calls
        calls += 1
        raise AssertionError("Insufficient verified allowance must stop before inference")

    try:
        await first(lab, clock)
        body = observation(clock.now(), percent=25)
        admitted = await lab.safety.admit(target(LAB_PARENT), body)
        claim = await store.claim_next(clock.now())
        assert claim and claim.reserved_tokens == 1850
        original = claim.context.model_dump_json(), claim.data_digest, claim.analysis
        monkeypatch.setattr(lab.safety._model, "count_input", count)
        monkeypatch.setattr(lab.safety._model, "respond", deny)
        failed = await lab.safety._run(claim)
        assert failed.status == "failed" and failed.error_code == "safety_job_token_budget_exceeded"
        assert original == (claim.context.model_dump_json(), claim.data_digest, claim.analysis)
        assert (await lab.safety.budget(LAB_PARENT)).server_used_tokens == 150
        assert (await lab.safety.budget(LAB_PARENT)).server_reserved_tokens == 0
        assert (await lab.safety.admit(target(LAB_PARENT), body)).job_id == admitted.job_id
        assert await lab.safety.process_one() is None and calls == 0
    finally:
        await lab.close()


async def test_runtime_selects_v27_and_feature_off_retains_it_without_idle_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[str] = []

    def deny(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.host or "")
        raise AssertionError("An idle scheduler may not read providers")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(deny))
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
        mana_child_safety_remainder_enabled=True,
        mana_child_safety_limits=ChildSafetyLimits(
            server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=2000, lease_seconds=360
        ),
    )
    for enabled in (True, False):
        current = settings.model_copy(update={"mana_child_safety_remainder_enabled": enabled})
        async with runtime_module.parent_chat_runtime(current):
            with sqlite3.connect(settings.mana_parent_chat_database_path) as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 27
                assert (
                    db.execute("SELECT count(*) FROM safety_remainder_admissions").fetchone()[0]
                    == 0
                )
    assert not requests
    assert not Settings(_env_file=None).mana_child_safety_remainder_enabled
