"""A tariff tool finishes its original parent turn; no acknowledgement message leaks."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.conversion_catalog import ConversionCatalogObservation
from app.mana_ai.domain.family_agents import AgentQuestionRequest, ParentTouchMessageRequest
from app.services import mana_chat_lab as lab_runtime
from app.services import parent_chat_runtime as runtime_module
from app.services.inline_upsell_store import SqliteClosedInlineUpsellStore, SqliteInlineUpsellStore
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.upsell_currency_store import SqliteUpsellCurrencyStore
from tests.test_family_source_runtime import config, make_credential_file
from tests.test_lab_chat_actions import Clock, options
from tests.test_trial_action_cards import snapshot


async def setup(path: Path) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        replace(options(path, clock), action_cards=False, upsell_currency=True, inline_upsell=True)
    )
    await lab.start()
    return lab, clock


async def ask(
    lab: ChatLab, message: str = "Покажи тарифы на 90 дней UZS"
) -> ParentTouchMessageRequest:
    request = ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=message)
    await lab.touch.admit_message(request)
    assert await lab.touch.process_reviewed_message()
    assert await lab.touch.process_reviewed_message()
    return request


async def test_one_original_answer_and_status_replay_without_another_generation(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "one-answer")
    try:
        request = await ask(lab)
        waiting = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert waiting.phase == "responding" and waiting.response is None, waiting
        state = await lab.state()
        assert len(state.history.messages) == 1 and state.history.quota.used_tokens == 300
        assert state.history.quota.reserved_tokens == 0
        assert await lab.touch.admit_message(request) == waiting
        assert lab.catalog.calls == 0 and not await lab.touch.process_reviewed_message()
        assert await lab.touch.process_upsell()
        done = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert done.phase == "completed" and done.response
        assert done.turn_id == waiting.turn_id and "162 000.00 UZS" in done.response.answer
        assert done.response.usage.total == 300
        assert await lab.touch.admit_message(request) == done
        assert len((await lab.state()).history.messages) == 2
        assert lab.catalog.calls == 1 and not await lab.touch.process_upsell()
        with lab.store._connect() as db:
            assert (
                db.execute("SELECT status FROM upsell_inline_replies").fetchone()[0] == "completed"
            )
            assert (
                db.execute("SELECT delivered_turn_id FROM upsell_intents").fetchone()[0]
                == done.turn_id
            )
    finally:
        await lab.close()


async def test_currency_answer_waits_for_its_quote_without_a_second_ack(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "currency")
    try:
        request = await ask(lab, "90 kunlik tariflarni ko‘rsating")
        question = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert question.response and question.response.asked_question
        answer = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="UZS",
            reply_to_question_id=question.response.asked_question.question_id,
        )
        waiting = await lab.touch.admit_message(answer)
        assert waiting.phase == "responding" and waiting.response is None
        assert await lab.touch.admit_message(answer) == waiting
        assert len((await lab.state()).history.messages) == 3
        assert await lab.touch.process_upsell()
        done = await lab.touch.message_state(LAB_PARENT, answer.request_id)
        assert done.response and done.response.usage.total == 0
        assert "162 000.00 UZS" in done.response.answer and "kun" in done.response.answer
        state = await lab.state()
        assert len(state.history.messages) == 4 and state.history.quota.used_tokens == 300
        assert await lab.touch.admit_message(answer) == done
        assert await lab.touch.admit_message(request) == question
        assert not await lab.touch.process_reviewed_message() and lab.catalog.calls == 1
    finally:
        await lab.close()


@pytest.mark.parametrize("lost", [False, True])
async def test_cancel_during_catalog_preserves_receipt_without_late_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lost: bool
) -> None:
    lab, _ = await setup(tmp_path / ("lost" if lost else "cancel"))
    entered, release = asyncio.Event(), asyncio.Event()
    original = lab.catalog.read

    async def blocked() -> ConversionCatalogObservation:
        entered.set()
        await release.wait()
        if lost:
            raise TimeoutError("Fictional lost receipt")
        return await original()

    monkeypatch.setattr(lab.catalog, "read", blocked)
    try:
        request = await ask(lab)
        task = asyncio.create_task(lab.touch.process_upsell())
        await asyncio.wait_for(entered.wait(), 3)
        cancel = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Отмена"
        )
        result = await lab.touch.admit_message(cancel)
        assert result.response and result.response.usage.total == 0
        assert "отменён" in result.response.answer
        release.set()
        assert await task
        assert (await lab.touch.message_state(LAB_PARENT, request.request_id)).phase == "failed"
        assert await lab.touch.admit_message(cancel) == result
        assert len((await lab.state()).history.messages) == 3
        assert not await lab.touch.process_upsell()
        with lab.store._connect() as db:
            row = db.execute(
                "SELECT status,reserved_http_attempts FROM upsell_catalog_reads"
            ).fetchone()
            assert row[0] == ("unknown" if lost else "recorded") and row[1] == 2
            assert (
                db.execute("SELECT status FROM upsell_inline_replies").fetchone()[0] == "cancelled"
            )
    finally:
        release.set()
        await lab.close()


@pytest.mark.parametrize("fence", ["disabled", "expired", "safety"])
async def test_pending_source_is_fenced_before_any_read(tmp_path: Path, fence: str) -> None:
    lab, clock = await setup(tmp_path / fence)
    try:
        request = await ask(lab)
        assert isinstance(lab.store, SqliteInlineUpsellStore)
        if fence == "disabled":
            lab.store._inline_enabled = False
        elif fence == "expired":
            clock.value += timedelta(seconds=181)
        else:
            need = AgentQuestionRequest.model_validate(
                next(s.body for s in lab.bootstrap().scenarios if s.key == "question")
            )
            await lab.touch.request_question(need)
        assert not await lab.touch.process_upsell()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed" and state.response is None
        assert lab.catalog.calls == 0
        assert (await lab.state()).history.quota.used_tokens == 300
        if fence == "safety":
            assert await lab.store.next_delivery(clock.now())
    finally:
        await lab.close()


async def test_waiting_restart_and_closed_reader_preserve_exact_cells(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "restart")
    try:
        request = await ask(lab)
        before = snapshot(lab.store)
        await SqliteClosedInlineUpsellStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
        assert snapshot(lab.store) == before
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        assert snapshot(lab.store) == before
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "responding" and state.response is None
        assert not await lab.touch.process_reviewed_message()
        assert await lab.touch.process_upsell()
        assert (await lab.touch.message_state(LAB_PARENT, request.request_id)).phase == "completed"
        assert lab.catalog.calls == 1
    finally:
        await lab.close()


async def test_prior_v31_pending_turn_does_not_gain_inline_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def legacy(path: Path, *, inline_enabled: bool, **family: Any) -> SqliteUpsellCurrencyStore:
        return SqliteUpsellCurrencyStore(path, **family)

    clock = Clock()
    clock.value = Clock.value
    opts = replace(
        options(tmp_path / "upgrade", clock),
        action_cards=False,
        upsell_currency=True,
        inline_upsell=True,
    )
    with monkeypatch.context() as patcher:
        patcher.setattr(lab_runtime, "SqliteInlineUpsellStore", legacy)
        old = ChatLab(opts)
        await old.start()
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Покажи тарифы на 90 дней UZS"
        )
        original = await old.touch.admit_message(request)
        before = snapshot(old.store)
        await old.close()
    lab = ChatLab(opts)
    await lab.start()
    try:
        after = snapshot(lab.store)
        assert {name: after[name] for name in before} == before
        assert await lab.touch.admit_message(request) == original
        assert (
            await lab.touch.process_reviewed_message()
            and await lab.touch.process_reviewed_message()
        )
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "completed" and state.response
        assert "Проверю" in state.response.answer
        assert await lab.touch.process_upsell()
        assert len((await lab.state()).history.messages) == 3
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM upsell_inline_admissions").fetchone()
            assert not db.execute("SELECT 1 FROM upsell_inline_replies").fetchone()
    finally:
        await lab.close()


@pytest.mark.parametrize("stage", ["queued", "handoff"])
async def test_disable_before_model_admission_makes_no_additional_paid_call(
    tmp_path: Path, stage: str
) -> None:
    lab, _ = await setup(tmp_path / stage)
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Покажи тарифы UZS"
        )
        await lab.touch.admit_message(request)
        if stage == "handoff":
            assert await lab.touch.process_reviewed_message()
        before = (await lab.state()).history.quota.used_tokens
        assert isinstance(lab.store, SqliteInlineUpsellStore)
        lab.store._inline_enabled = False
        assert not await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed" and state.error_code == "upsell_inline_disabled"
        assert (await lab.state()).history.quota.used_tokens == before
        assert lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_atomic_staging_failure_retains_unknown_model_hold(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "atomic")
    try:
        with lab.store._transaction() as db:
            db.execute(
                "CREATE TRIGGER deny_inline BEFORE INSERT ON upsell_inline_replies "
                "BEGIN SELECT RAISE(ABORT,'fictional failure'); END"
            )
        request = await ask(lab)
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "unknown"
        quota = (await lab.state()).history.quota
        assert quota.used_tokens == 150 and quota.reserved_tokens > 0
        before = snapshot(lab.store)
        await SqliteClosedInlineUpsellStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
        assert snapshot(lab.store) == before
        clock.value += timedelta(days=1)
        assert (await lab.store.quota(LAB_PARENT, clock.now())).blocked_by_unresolved_request
        assert (
            not await lab.touch.process_reviewed_message() and not await lab.touch.process_upsell()
        )
        assert snapshot(lab.store) == before
        assert lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_corrupted_intent_is_refused_before_source_access(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "proof")
    try:
        request = await ask(lab)
        with lab.store._transaction() as db:
            db.execute("UPDATE upsell_intents SET payload=replace(payload,'UZS','USD')")
        assert not await lab.touch.process_upsell()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed" and state.error_code == "upsell_reply_checkpoint_invalid"
        assert lab.catalog.calls == 0
        assert (await lab.state()).history.quota.used_tokens == 300
    finally:
        await lab.close()


async def test_two_workers_publish_only_one_original_answer(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "workers")
    try:
        request = await ask(lab)
        results = await asyncio.gather(lab.touch.process_upsell(), lab.touch.process_upsell())
        assert sorted(results) == [False, True]
        assert lab.catalog.calls == 1
        assert (await lab.touch.message_state(LAB_PARENT, request.request_id)).phase == "completed"
        assert len((await lab.state()).history.messages) == 2
    finally:
        await lab.close()


async def test_late_explicit_cancel_is_a_controlled_noop_without_model_fallback(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "late-cancel")
    try:
        request = await ask(lab)
        assert await lab.touch.process_upsell()
        before = (await lab.state()).history
        cancel = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="cancel tariff request"
        )
        for command in (cancel, cancel.model_copy(update={"request_id": uuid4()})):
            with pytest.raises(ParentChatError, match="upsell_reply_not_waiting"):
                await lab.touch.admit_message(command)
        assert (await lab.state()).history == before
        assert not await lab.touch.process_reviewed_message()
        assert (await lab.touch.message_state(LAB_PARENT, request.request_id)).phase == "completed"
        assert lab.catalog.calls == 1
    finally:
        await lab.close()


async def test_unknown_catalog_completes_once_and_remains_blocked_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "unknown-source")
    calls = 0

    async def lost() -> ConversionCatalogObservation:
        nonlocal calls
        calls += 1
        raise TimeoutError("Fictional lost catalogue response")

    monkeypatch.setattr(lab.catalog, "read", lost)
    try:
        request = await ask(lab)
        assert await lab.touch.process_upsell()
        done = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert done.phase == "completed" and done.response and "не удалось" in done.response.answer
        assert len((await lab.state()).history.messages) == 2 and calls == 1
        before = snapshot(lab.store)
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        assert snapshot(lab.store) == before
        assert await lab.touch.admit_message(request) == done
        clock.value += timedelta(days=1)
        assert isinstance(lab.store, SqliteInlineUpsellStore)
        assert (await lab.store.catalog_admission(clock.now())).refusal == "blocked"
        assert lab.catalog.calls == 0 and calls == 1
        assert not await lab.touch.process_upsell()
    finally:
        await lab.close()


async def test_expired_ownership_context_cannot_publish_after_slow_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "stale-context")
    try:
        request = await ask(lab)
        profiles = lab._profiles.read
        catalogue = lab.catalog.read

        async def older(parent_id: str) -> ParentChildContext:
            context = await profiles(parent_id)
            return context.model_copy(update={"collected_at": clock.now() - timedelta(seconds=170)})

        async def slow() -> ConversionCatalogObservation:
            clock.value += timedelta(seconds=20)
            return await catalogue()

        monkeypatch.setattr(lab._profiles, "read", older)
        monkeypatch.setattr(lab.catalog, "read", slow)
        assert await lab.touch.process_upsell()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed" and state.error_code == "upsell_reply_source_unavailable"
        assert len((await lab.state()).history.messages) == 1 and lab.catalog.calls == 1
        assert (await lab.state()).history.quota.used_tokens == 300
    finally:
        await lab.close()


async def test_actual_runtime_and_validated_closed_configuration_are_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[str] = []

    def denied(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.host)
        raise AssertionError("Unexpected idle provider access")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_: httpx.MockTransport(denied))
    active = config(
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
        mana_client_upsell_currency_enabled=True,
        mana_upsell_inline_results_enabled=True,
        mana_child_safety_limits=ChildSafetyLimits(
            job_tokens=2000, server_daily_tokens=2000, parent_daily_tokens=2000, lease_seconds=360
        ),
    )
    closed_values = active.model_dump()
    for key, value in tuple(closed_values.items()):
        if key.startswith("mana_") and type(value) is bool:
            closed_values[key] = False
    closed_values.update(mana_parent_chat_enabled=True, mana_parent_touch_enabled=True)
    closed = Settings(_env_file=None, **closed_values)
    for current in (
        active,
        active.model_copy(update={"mana_upsell_inline_results_enabled": False}),
        closed,
    ):
        async with runtime_module.parent_chat_runtime(current):
            with sqlite3.connect(active.mana_parent_chat_database_path) as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 32
                assert not db.execute("SELECT 1 FROM upsell_inline_admissions").fetchone()
    assert not requests
