"""One native tariff decision under the original shared policy, quotas and chat."""

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
from openai import AsyncOpenAI

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.upsell_text import TARIFF_HANDOFF_PLACEHOLDER
from app.mana_ai.domain.client_upsell import UpsellEnquiry
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.parent_touch_manager import UPSELL_TOOL, ParentTouchManagerScope
from app.services import mana_chat_lab as lab_runtime
from app.services.inline_upsell_store import SqliteInlineUpsellStore
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.parent_chat_model import OpenAIParentChatModel
from app.services.tariff_handoff_store import (
    SqliteClosedTariffHandoffStore,
    SqliteTariffHandoffStore,
)
from tests.test_mana_chat_lab import Clock
from tests.test_parent_chat_adapters import settings as model_settings
from tests.test_trial_action_cards import snapshot


async def setup(path: Path) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        replace(workspace_options(path, clock=clock, worker_enabled=False), tariff_handoff=True)
    )
    await lab.start()
    assert isinstance(lab.store, SqliteTariffHandoffStore)
    return lab, clock


@pytest.mark.parametrize("missing", [False, True])
async def test_one_call_preserves_terms_currency_binding_quote_and_exact_replay(
    tmp_path: Path, missing: bool
) -> None:
    lab, _ = await setup(tmp_path / str(missing))
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Покажи тарифы на 90 дней до 200000" + ("" if missing else " UZS"),
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        assert not await lab.touch.process_reviewed_message()
        first = await lab.touch.message_state(LAB_PARENT, request.request_id)
        if missing:
            assert first.response and first.response.asked_question
            answer = ParentTouchMessageRequest(
                parent_id=LAB_PARENT,
                request_id=uuid4(),
                message="UZS",
                reply_to_question_id=first.response.asked_question.question_id,
            )
            waiting = await lab.touch.admit_message(answer)
            assert waiting.phase == "responding" and waiting.response is None
            final_request = answer
        else:
            assert first.phase == "responding" and first.response is None
            final_request = request
        assert (await lab.state()).history.quota.used_tokens == 150
        assert lab.catalog.calls == 0
        assert await lab.touch.process_upsell()
        done = await lab.touch.message_state(LAB_PARENT, final_request.request_id)
        assert done.response and "162 000.00 UZS" in done.response.answer
        assert done.response.usage.total == (0 if missing else 150)
        state = await lab.state()
        assert len(state.history.messages) == (4 if missing else 2)
        assert state.history.quota.used_tokens == 150
        assert state.safety_budget.server_used_tokens == 0
        assert lab.catalog.calls == 1
        expected_first = first if missing else done
        assert await lab.touch.admit_message(request) == expected_first
        assert await lab.touch.admit_message(final_request) == done
        assert not await lab.touch.process_reviewed_message()
        assert not await lab.touch.process_upsell() and lab.catalog.calls == 1
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM manager_tariff_decisions").fetchone()[0] == 1
            assert db.execute("SELECT SUM(used) FROM parent_chat_quota").fetchone()[0] == 150
            assert not db.execute("SELECT 1 FROM conversion_trial_grants").fetchone()
    finally:
        await lab.close()


@pytest.mark.parametrize(
    "arguments,valid",
    [
        ({"enquiry": None}, True),
        ({}, False),
        ({"enquiry": None, "parent_id": "another-family"}, False),
        ({"enquiry": {"parent_quote": "tariffs"}}, False),
    ],
)
async def test_native_account_fallback_and_invalid_arguments_keep_verified_usage(
    arguments: dict[str, Any],
    valid: bool,
) -> None:
    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "gpt-test",
                "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                "output": [
                    {
                        "type": "function_call",
                        "name": UPSELL_TOOL,
                        "call_id": "call-account",
                        "status": "completed",
                        "arguments": json.dumps(arguments),
                    }
                ],
            },
        )

    client = AsyncOpenAI(
        api_key="fake-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(reply)),
    )
    model = OpenAIParentChatModel(model_settings(), client=client)
    try:
        receipt = await model.respond(
            ChatPrompt(
                "Synthetic account help",
                (("user", "Which tariff do I have?"),),
                structured_reply=True,
                manager_scope=ParentTouchManagerScope(
                    language="en", upsell_enabled=True, tariff_handoff_enabled=True
                ),
            ),
            max_output_tokens=256,
        )
        assert receipt.usage.total == 150 and receipt.completed is valid
        assert receipt.answer is None
        if valid:
            assert receipt.manager_handoff and receipt.manager_handoff.tariff_enquiry is None
        else:
            assert (
                receipt.manager_handoff is None and receipt.failure_code == "reply_schema_invalid"
            )
    finally:
        await client.close()


async def test_changed_original_call_cannot_price_a_later_currency_answer(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "answer-pair")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Тариф на 90 дней"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        first = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert first.response and first.response.asked_question
        answer = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="UZS",
            reply_to_question_id=first.response.asked_question.question_id,
        )
        await lab.touch.admit_message(answer)
        with lab.store._transaction() as db:
            db.execute("UPDATE manager_tariff_decisions SET call_id='changed-call'")
        assert not await lab.touch.process_upsell()
        result = await lab.touch.message_state(LAB_PARENT, answer.request_id)
        assert result.phase == "failed" and result.error_code == "tariff_handoff_pairing_changed"
        assert lab.catalog.calls == 0 and (await lab.state()).history.quota.used_tokens == 150
    finally:
        await lab.close()


@pytest.mark.parametrize("enabled", [False, True])
async def test_actual_sdk_keeps_old_empty_call_schema_and_new_nullable_typed_arguments(
    enabled: bool,
) -> None:
    seen: list[dict[str, Any]] = []
    enquiry = UpsellEnquiry(
        parent_quote="90 days in UZS",
        objective="list",
        currency="UZS",
        minimum_days=90,
        maximum_days=90,
        maximum_price_minor=None,
    )

    def reply(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if request.url.path.endswith("input_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "gpt-test",
                "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                "output": [
                    {
                        "type": "function_call",
                        "name": UPSELL_TOOL,
                        "call_id": "call-price",
                        "status": "completed",
                        "arguments": json.dumps({"enquiry": enquiry.model_dump()}),
                    },
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "Untrusted accompanying price prose"}
                        ],
                    },
                ],
            },
        )

    client = AsyncOpenAI(
        api_key="fake-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(reply)),
    )
    model = OpenAIParentChatModel(model_settings(), client=client)
    prompt = ChatPrompt(
        "Synthetic manager",
        (("user", "90 days in UZS"),),
        structured_reply=True,
        manager_scope=ParentTouchManagerScope(
            language="en", upsell_enabled=True, tariff_handoff_enabled=enabled
        ),
    )
    try:
        assert await model.count_input(prompt) == 100
        receipt = await model.respond(prompt, max_output_tokens=256)
        assert receipt.usage.total == 150
        assert receipt.completed is enabled
        if enabled:
            assert receipt.manager_handoff and receipt.manager_handoff.tariff_enquiry == enquiry
            assert receipt.answer == TARIFF_HANDOFF_PLACEHOLDER
        else:
            assert receipt.manager_handoff is None and receipt.answer is None
        tool = next(t for t in seen[0]["tools"] if t["name"] == UPSELL_TOOL)
        assert tool["strict"] is True
        assert tool["parameters"]["additionalProperties"] is False
        assert tool["parameters"]["required"] == (["enquiry"] if enabled else [])
        assert seen[0]["tools"] == seen[1]["tools"]
        assert seen[0]["parallel_tool_calls"] is False
    finally:
        await client.close()


async def test_one_call_can_finish_with_less_than_a_second_generation_remaining(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "remainder")
    try:
        with lab.store._transaction() as db:
            day, _ = lab.store._period(lab.options.clock.now())
            db.execute(
                "INSERT INTO parent_chat_quota(parent_id,day,used,attempts) VALUES(?,?,1770,0)",
                (LAB_PARENT, day),
            )
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Тариф на 90 дней UZS"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_upsell()
        result = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert result.response and "162 000.00 UZS" in result.response.answer
        assert (await lab.state()).history.quota.used_tokens == 1920
        assert not await lab.touch.process_reviewed_message()
    finally:
        await lab.close()


@pytest.mark.parametrize("fence", ["before_model", "late_model", "before_source", "changed_pair"])
async def test_disabled_or_changed_handoff_cannot_read_sources_and_keeps_known_costs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fence: str,
) -> None:
    lab, _ = await setup(tmp_path / fence)
    store = lab.store
    assert isinstance(store, SqliteTariffHandoffStore)
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Тариф на 90 дней UZS"
        )
        await lab.touch.admit_message(request)
        if fence == "before_model":
            store._tariff_handoff_enabled = False
        elif fence == "late_model":
            original = lab.touch._model.respond

            async def late(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
                result = await original(prompt, max_output_tokens=max_output_tokens)
                store._tariff_handoff_enabled = False
                return result

            monkeypatch.setattr(lab.touch._model, "respond", late)
        assert await lab.touch.process_reviewed_message()
        if fence == "before_source":
            store._tariff_handoff_enabled = False
        elif fence == "changed_pair":
            with lab.store._transaction() as db:
                db.execute("DELETE FROM manager_tariff_decisions")
        assert not await lab.touch.process_upsell()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed" and state.response is None, state
        assert lab.catalog.calls == 0
        assert (await lab.state()).history.quota.used_tokens == (
            0 if fence == "before_model" else 150
        )
    finally:
        await lab.close()


async def test_disabled_currency_answer_rolls_back_without_binding_or_read(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "currency-disable")
    assert isinstance(lab.store, SqliteTariffHandoffStore)
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Тариф на 90 дней"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        first = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert first.response and first.response.asked_question
        before = snapshot(lab.store)
        lab.store._tariff_handoff_enabled = False
        with pytest.raises(ParentChatError, match="tariff_handoff_disabled"):
            await lab.touch.admit_message(
                ParentTouchMessageRequest(
                    parent_id=LAB_PARENT,
                    request_id=uuid4(),
                    message="UZS",
                    reply_to_question_id=first.response.asked_question.question_id,
                )
            )
        assert snapshot(lab.store) == before
        assert lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_actual_v32_pending_message_retains_two_call_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = SqliteTariffHandoffStore

    def prior(
        path: Path, *, tariff_handoff_enabled: bool, **family: Any
    ) -> SqliteInlineUpsellStore:
        return SqliteInlineUpsellStore(path, **family)

    monkeypatch.setattr(lab_runtime, "SqliteTariffHandoffStore", prior)
    lab, clock = None, Clock()
    clock.value = Clock.value
    options = replace(
        workspace_options(tmp_path / "prior", clock=clock, worker_enabled=False),
        tariff_handoff=True,
    )
    old = ChatLab(options)
    await old.start()
    request = ParentTouchMessageRequest(
        parent_id=LAB_PARENT, request_id=uuid4(), message="Тариф на 90 дней UZS"
    )
    await old.touch.admit_message(request)
    await old.close()
    monkeypatch.setattr(lab_runtime, "SqliteTariffHandoffStore", original)
    lab = ChatLab(options)
    await lab.start()
    try:
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM manager_tariff_admissions").fetchone()
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_upsell()
        assert (await lab.state()).history.quota.used_tokens == 300
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM manager_tariff_decisions").fetchone()
    finally:
        await lab.close()


@pytest.mark.parametrize("failure", ["lost_model", "staging_sql"])
async def test_unknown_receipt_or_failed_atomic_publication_stays_held_across_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    lab, clock = await setup(tmp_path / failure)
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Тариф на 90 дней UZS"
        )
        await lab.touch.admit_message(request)
        if failure == "staging_sql":
            with lab.store._transaction() as db:
                db.execute(
                    "CREATE TRIGGER refuse_decision BEFORE INSERT ON manager_tariff_decisions "
                    "BEGIN SELECT RAISE(FAIL,'fictional lost settlement'); END"
                )
            assert await lab.touch.process_reviewed_message()
        else:
            entered = asyncio.Event()

            async def lost(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
                entered.set()
                await asyncio.Event().wait()
                raise AssertionError("Unreachable")

            monkeypatch.setattr(lab.touch._model, "respond", lost)
            work = asyncio.create_task(lab.touch.process_reviewed_message())
            await asyncio.wait_for(entered.wait(), 3)
            work.cancel()
            with suppress(asyncio.CancelledError):
                await work
        state = await lab.state()
        assert state.history.quota.blocked_by_unresolved_request
        hold = state.history.quota.reserved_tokens
        assert hold > 0 and lab.catalog.calls == 0
        before = snapshot(lab.store)
        await SqliteClosedTariffHandoffStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
        assert snapshot(lab.store) == before
        await lab.close()
        resumed = ChatLab(lab.options)
        await resumed.start()
        lab = resumed
        assert snapshot(lab.store) == before
        assert not await lab.touch.process_reviewed_message()
        assert not await lab.touch.process_upsell()
        quota = await lab.store.quota(LAB_PARENT, clock.now() + timedelta(days=1))
        assert quota.blocked_by_unresolved_request
        assert snapshot(lab.store) == before
    finally:
        await lab.close()


async def test_two_workers_claim_one_native_tariff_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab, _ = await setup(tmp_path / "two-workers")
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    original = lab.touch._model.respond

    async def blocked(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return await original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(lab.touch._model, "respond", blocked)
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Тариф на 90 дней UZS"
        )
        await lab.touch.admit_message(request)
        first = asyncio.create_task(lab.touch.process_reviewed_message())
        await asyncio.wait_for(entered.wait(), 3)
        assert not await lab.touch.process_reviewed_message()
        release.set()
        assert await first
        assert await lab.touch.process_upsell()
        assert calls == 1 and lab.catalog.calls == 1
        assert (await lab.state()).history.quota.used_tokens == 150
    finally:
        release.set()
        await lab.close()


async def test_current_account_question_keeps_its_original_owning_workflow(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "account")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Какой у меня тариф?"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.response and "Fictional 1-Month" in state.response.answer
        assert state.response.usage.total == 300 and lab.catalog.calls == 0
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM manager_tariff_decisions").fetchone()
    finally:
        await lab.close()


async def test_actual_runtime_and_validated_closed_profile_retain_current_schema_without_idle_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings
    from app.mana_ai.domain.child_safety import ChildSafetyLimits
    from app.services import parent_chat_runtime as runtime
    from tests.test_family_source_runtime import config, make_credential_file

    requests: list[str] = []

    def denied(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.host)
        raise AssertionError("No idle provider request belongs to configuration acceptance")

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
        mana_parent_touch_tariff_handoff_enabled=True,
        mana_child_safety_limits=ChildSafetyLimits(
            job_tokens=2000, server_daily_tokens=2000, parent_daily_tokens=2000, lease_seconds=360
        ),
    )
    values = active.model_dump()
    for key, value in tuple(values.items()):
        if key.startswith("mana_") and type(value) is bool:
            values[key] = False
    values.update(mana_parent_chat_enabled=True, mana_parent_touch_enabled=True)
    closed = Settings(_env_file=None, **values)
    for settings in (
        active,
        active.model_copy(update={"mana_parent_touch_tariff_handoff_enabled": False}),
        closed,
    ):
        async with runtime.parent_chat_runtime(settings):
            with sqlite3.connect(active.mana_parent_chat_database_path) as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 34
                assert not db.execute("SELECT 1 FROM manager_tariff_admissions").fetchone()
    assert requests == []
