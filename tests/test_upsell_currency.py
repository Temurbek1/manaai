"""A natural tariff request keeps its terms across one bound currency question."""

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.domain.chat import ChatTokens
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.client_upsell import UpsellEnquiry, UpsellScope
from app.mana_ai.domain.family_agents import (
    AgentQuestionRequest,
    ParentTouchMessageRequest,
    ParentTouchMessageState,
)
from app.services import mana_chat_lab as lab_runtime
from app.services import parent_chat_runtime as runtime_module
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.parent_chat_model import OpenAIParentChatModel
from app.services.upsell_currency_store import (
    SqliteClosedUpsellCurrencyStore,
    SqliteUpsellCurrencyStore,
)
from app.services.usage_comparison_safety_store import SqliteUsageComparisonSafetyStore
from tests.test_family_source_runtime import config, make_credential_file
from tests.test_lab_chat_actions import Clock, options
from tests.test_parent_chat_adapters import PROMPT, model_payload
from tests.test_parent_chat_adapters import settings as model_settings
from tests.test_trial_action_cards import snapshot


async def setup(path: Path) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(replace(options(path, clock), action_cards=False, upsell_currency=True))
    await lab.start()
    return lab, clock


async def question(
    lab: ChatLab, text: str = "Покажи тарифы на 90 дней до 200000"
) -> tuple[ParentTouchMessageRequest, ParentTouchMessageState]:
    request = ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=text)
    await lab.touch.admit_message(request)
    assert await lab.touch.process_reviewed_message()
    assert await lab.touch.process_reviewed_message()
    state = await lab.touch.message_state(LAB_PARENT, request.request_id)
    assert state.phase == "completed" and state.response and state.response.asked_question, state
    return request, state


@pytest.mark.parametrize(
    "text,currency",
    [
        ("Покажи тарифы на 90 дней до 200000", "UZS"),
        ("90 kunlik tariflarni ko‘rsating", "USD"),
    ],
)
async def test_currency_answer_preserves_exact_terms_without_another_model_call(
    tmp_path: Path, text: str, currency: str
) -> None:
    lab, _ = await setup(tmp_path / currency)
    try:
        original, state = await question(lab, text)
        assert state.response and state.response.asked_question
        q = state.response.asked_question
        assert q.scope == "parent" and q.child_id is None
        assert "UZS" in state.response.answer and "USD" in state.response.answer
        assert ("valyutada" in state.response.answer) is (currency == "USD")
        before = await lab.state()
        assert lab.catalog.calls == 0
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message=currency.lower(),
            reply_to_question_id=q.question_id,
        )
        result = await lab.touch.admit_message(request)
        assert result.phase == "completed" and result.response
        assert result.response.usage.total == 0
        assert await lab.touch.admit_message(request) == result
        assert not await lab.touch.process_reviewed_message()
        assert (await lab.state()).history.quota == before.history.quota
        with lab.store._connect() as db:
            row = db.execute("SELECT payload FROM upsell_intents").fetchone()
            assert row and '"minimum_days":90' in row[0] and '"maximum_days":90' in row[0]
            assert f'"currency":"{currency}"' in row[0] and text in row[0]
            assert (
                db.execute("SELECT status FROM upsell_currency_questions").fetchone()[0]
                == "resolved"
            )
        assert await lab.touch.process_upsell()
        assert lab.catalog.calls == 1
        history = (await lab.state()).history
        assert len(history.messages) == 5
        if currency == "UZS":
            assert "162 000.00 UZS" in history.messages[-1].content
        assert await lab.touch.admit_message(original) == state
        assert not await lab.touch.process_upsell()
        assert lab.catalog.calls == 1
    finally:
        await lab.close()


@pytest.mark.parametrize(
    "protocol,currency,valid",
    [
        ("catalog-enquiry-v1", None, False),
        ("catalog-currency-v2", None, True),
        ("catalog-currency-v2", "UZS", True),
    ],
)
async def test_actual_sdk_keeps_old_schema_and_accounts_priced_new_decisions(
    protocol: str, currency: str | None, valid: bool
) -> None:
    requests: list[dict[str, Any]] = []
    payload = model_payload()
    payload["output"][0]["content"][0]["text"] = json.dumps(
        {
            "body": "",
            "question": None,
            "notice_communicated": False,
            "reminder": None,
            "upsell": {
                "parent_quote": "Покажи тарифы",
                "objective": "list",
                "currency": currency,
                "minimum_days": 1,
                "maximum_days": 366,
                "maximum_price_minor": None,
            },
        }
    )

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=payload)

    prompt = replace(
        PROMPT,
        structured_reply=True,
        slot_reply=True,
        upsell_scope=UpsellScope.model_validate({"protocol": protocol}),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        adapter = OpenAIParentChatModel(
            model_settings(), client=AsyncOpenAI(api_key="fake", max_retries=0, http_client=http)
        )
        receipt = await adapter.respond(prompt, max_output_tokens=512)
    assert receipt.completed is valid and receipt.usage.total == 150
    assert (receipt.upsell_enquiry is not None) is (valid and currency is None)
    assert (receipt.upsell_choice is not None) is (valid and currency is not None)
    schema = requests[0]["text"]["format"]["schema"]
    assert schema["properties"]["question"] == {"type": "null"}
    definition = schema["$defs"]["UpsellEnquiry" if protocol.endswith("v2") else "UpsellChoice"]
    assert ("anyOf" in definition["properties"]["currency"]) is protocol.endswith("v2")
    assert len(requests) == 1


async def test_disabled_after_answer_cancels_only_unsubmitted_enquiry(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "stop")
    try:
        _, state = await question(lab)
        assert state.response and state.response.asked_question
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="UZS",
            reply_to_question_id=state.response.asked_question.question_id,
        )
        await lab.touch.admit_message(request)
        assert isinstance(lab.store, SqliteUpsellCurrencyStore)
        lab.store._currency_enabled = False
        assert not await lab.touch.process_upsell()
        assert lab.catalog.calls == 0
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM upsell_intents").fetchone()[0] == "cancelled"
        assert (await lab.touch.admit_message(request)).phase == "completed"
    finally:
        await lab.close()


async def test_different_nonce_and_foreign_parent_cannot_reanswer(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "races")
    try:
        _, state = await question(lab)
        assert state.response and state.response.asked_question
        q = state.response.asked_question
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="UZS",
            reply_to_question_id=q.question_id,
        )
        results = await asyncio.gather(*(lab.touch.admit_message(request) for _ in range(2)))
        assert results[0] == results[1]
        with pytest.raises(ParentChatError, match="upsell_currency_question_not_active"):
            await lab.touch.admit_message(request.model_copy(update={"request_id": uuid4()}))
        with pytest.raises(ParentChatError, match="question_reply_mismatch"):
            await lab.touch.admit_message(
                request.model_copy(update={"request_id": uuid4(), "parent_id": "888888"})
            )
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM upsell_intents").fetchone()[0] == 1
        assert lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_expiry_and_disabled_profile_do_not_read_or_answer(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "expired")
    try:
        _, state = await question(lab)
        assert state.response and state.response.asked_question
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="USD",
            reply_to_question_id=state.response.asked_question.question_id,
        )
        assert isinstance(lab.store, SqliteUpsellCurrencyStore)
        lab.store._currency_enabled = False
        with pytest.raises(ParentChatError, match="upsell_currency_disabled"):
            await lab.touch.admit_message(request)
        lab.store._currency_enabled = True
        clock.value += timedelta(days=1)
        with pytest.raises(ParentChatError, match="upsell_currency_question_not_active"):
            await lab.touch.admit_message(request)
        assert lab.catalog.calls == 0
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM upsell_intents").fetchone()[0] == 0
    finally:
        await lab.close()


async def test_old_pending_turn_migrates_without_currency_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def legacy(
        path: Path, *, currency_enabled: bool, **family: Any
    ) -> SqliteUsageComparisonSafetyStore:
        return SqliteUsageComparisonSafetyStore(path, **family)

    clock = Clock()
    clock.value = Clock.value
    opts = replace(options(tmp_path / "upgrade", clock), action_cards=False, upsell_currency=True)
    with monkeypatch.context() as patcher:
        patcher.setattr(lab_runtime, "SqliteUpsellCurrencyStore", legacy)
        old = ChatLab(opts)
        await old.start()
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Подбери тариф на 90 дней"
        )
        state = await old.touch.admit_message(request)
        before = snapshot(old.store)
        await old.close()
    lab = ChatLab(opts)
    await lab.start()
    try:
        after = snapshot(lab.store)
        assert {name: after[name] for name in before} == before
        assert await lab.touch.admit_message(request) == state
        with lab.store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 31
            assert not db.execute("SELECT 1 FROM upsell_currency_admissions").fetchone()
        assert lab.touch.upsell
        scope = await lab.touch.upsell.scope(LAB_PARENT, state.turn_id)
        assert scope and scope.protocol == "catalog-enquiry-v1"
    finally:
        await lab.close()


async def test_failed_question_publication_retains_unknown_hold_across_closed_restart(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "atomic")
    try:
        with lab.store._transaction() as db:
            db.execute(
                "CREATE TRIGGER deny_currency BEFORE INSERT ON upsell_currency_questions "
                "BEGIN SELECT RAISE(ABORT,'fictional failure'); END"
            )
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Покажи тарифы"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "unknown"
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM family_questions").fetchone()
            assert not db.execute("SELECT 1 FROM upsell_currency_questions").fetchone()
            hold = db.execute(
                "SELECT reserved FROM parent_chat_turns WHERE status='unknown'"
            ).fetchone()[0]
            assert hold > 0
        assert (await lab.touch.admit_message(request)).phase == "unknown"
        assert not await lab.touch.process_reviewed_message()
        before = snapshot(lab.store)
        closed = SqliteClosedUpsellCurrencyStore(
            lab.store._path, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        clock.value += timedelta(days=1)
        assert (await closed.quota(LAB_PARENT, clock.now())).blocked_by_unresolved_request
        assert snapshot(lab.store) == before
    finally:
        await lab.close()


@pytest.mark.parametrize("fence", ["priority", "disabled"])
async def test_late_decision_keeps_cost_but_creates_no_currency_question(
    tmp_path: Path, fence: str
) -> None:
    lab, _ = await setup(tmp_path / fence)
    request = ParentTouchMessageRequest(
        parent_id=LAB_PARENT, request_id=uuid4(), message="Покажи тарифы"
    )

    class Late:
        async def count_input(self, prompt: ChatPrompt) -> int:
            return 100

        async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
            if fence == "priority":
                need = AgentQuestionRequest.model_validate(
                    next(s.body for s in lab.bootstrap().scenarios if s.key == "question")
                )
                await lab.touch.request_question(need)
            else:
                assert isinstance(lab.store, SqliteUpsellCurrencyStore)
                lab.store._currency_enabled = False
            return ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=50),
                model="lab-simulated-not-billed",
                completed=True,
                answer="Awaiting host validation.",
                upsell_enquiry=UpsellEnquiry(
                    parent_quote=request.message,
                    objective="list",
                    currency=None,
                    minimum_days=1,
                    maximum_days=366,
                    maximum_price_minor=None,
                ),
            )

    try:
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        lab.touch._model = Late()
        assert await lab.touch.process_reviewed_message()
        assert (await lab.touch.message_state(LAB_PARENT, request.request_id)).phase == "failed"
        assert (await lab.state()).history.quota.used_tokens == 300
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM upsell_currency_questions").fetchone()
        assert lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_unknown_catalog_after_currency_binding_is_not_redispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "unknown-catalog")
    calls = 0

    async def lost() -> object:
        nonlocal calls
        calls += 1
        raise TimeoutError("Fictional lost catalogue receipt")

    monkeypatch.setattr(lab.catalog, "read", lost)
    try:
        original, state = await question(lab)
        assert state.response and state.response.asked_question
        answer = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="UZS",
            reply_to_question_id=state.response.asked_question.question_id,
        )
        await lab.touch.admit_message(answer)
        assert await lab.touch.process_upsell()
        assert calls == 1
        await lab.touch.admit_message(original)
        await lab.touch.admit_message(answer)
        assert not await lab.touch.process_upsell()
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        clock.value += timedelta(days=1)
        assert lab.touch.upsell
        admission = await lab.touch.upsell._store.catalog_admission(clock.now())
        assert admission.refusal == "blocked" and admission.claim is None
        assert calls == 1 and lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_actual_runtime_wires_v31_and_closed_reader_without_idle_sources(
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
        mana_client_upsell_currency_enabled=True,
        mana_child_safety_limits=ChildSafetyLimits(
            job_tokens=2000, server_daily_tokens=2000, parent_daily_tokens=2000, lease_seconds=360
        ),
    )
    for changed in (
        {},
        {"mana_client_upsell_currency_enabled": False},
        {"mana_child_safety_enabled": False, "mana_client_upsell_currency_enabled": False},
    ):
        async with runtime_module.parent_chat_runtime(settings.model_copy(update=changed)):
            with sqlite3.connect(settings.mana_parent_chat_database_path) as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 31
                assert not db.execute("SELECT 1 FROM upsell_currency_admissions").fetchone()
    assert not requests
