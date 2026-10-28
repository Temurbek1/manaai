"""One-chat tariff refinements retain exact previous terms without new authority."""

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.upsell_text import TARIFF_HANDOFF_PLACEHOLDER
from app.mana_ai.domain.chat import ChatTokens
from app.mana_ai.domain.client_upsell import UpsellEnquiry, UpsellIntent
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.parent_touch_manager import ParentTouchManagerHandoff
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.tariff_followup_store import (
    SqliteClosedTariffFollowupStore,
    SqliteTariffFollowupStore,
)
from tests.test_mana_chat_lab import Clock
from tests.test_trial_action_cards import snapshot


async def setup(path: Path, *, enabled: bool = True) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        replace(
            workspace_options(path, clock=clock, worker_enabled=False),
            tariff_handoff=True,
            compact_inputs=True,
            compact_publication=True,
            compact_manager=True,
            tariff_followups=enabled,
        )
    )
    await lab.start()
    return lab, clock


def store(lab: ChatLab) -> SqliteTariffFollowupStore:
    assert isinstance(lab.store, SqliteTariffFollowupStore)
    return lab.store


def request(message: str) -> ParentTouchMessageRequest:
    return ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=message)


async def quote(
    lab: ChatLab, message: str = "Покажи тарифы на 90 дней до 200000 UZS"
) -> ParentTouchMessageRequest:
    original = request(message)
    await lab.touch.admit_message(original)
    assert await lab.touch.process_reviewed_message()
    assert await lab.touch.process_upsell()
    result = await lab.touch.message_state(LAB_PARENT, original.request_id)
    assert result.response and "162 000.00 UZS" in result.response.answer
    return original


@pytest.mark.parametrize("budget", [False, True])
async def test_followup_preserves_budget_currency_and_original_objective_without_extra_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, budget: bool
) -> None:
    lab, _ = await setup(tmp_path / "refine")
    prompts: list[ChatPrompt] = []
    respond = lab.touch._model.respond

    async def observe(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        prompts.append(prompt)
        return await respond(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(lab.touch._model, "respond", observe)
    try:
        original = await quote(
            lab,
            "Покажи тарифы на 90 дней до 200000 UZS" if budget else "Покажи тарифы на 90 дней UZS",
        )
        refinement = request("а на 180 дней?")
        await lab.touch.admit_message(refinement)
        current = await lab.touch.message_state(LAB_PARENT, refinement.request_id)
        context = await store(lab).tariff_followup_context(LAB_PARENT, current.turn_id)
        assert context and context.origin_messages[0].message == original.message
        assert context.origin_intent.choice.maximum_price_minor == (20000000 if budget else None)
        assert context.quote.options[0].price_minor == 16200000
        assert await store(lab).parent_publication_version(LAB_PARENT, current.turn_id) == 6
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_upsell()
        completed = await lab.touch.message_state(LAB_PARENT, refinement.request_id)
        assert (
            completed.response
            and ("нет варианта" if budget else "299 000.00 UZS") in completed.response.answer
        )
        data = json.loads(prompts[-1].messages[0][1])["tariff_followup"]
        assert data["original_requests"] == [original.message]
        assert data["previous_terms"]["maximum_price_minor"] == (20000000 if budget else None)
        assert data["previous_quote"]["recipient_eligibility"] == "not_verified"
        assert "Do not reset their budget/duration/currency" in prompts[-1].instructions
        with lab.store._connect() as db:
            last = UpsellIntent.model_validate_json(
                db.execute("SELECT payload FROM upsell_intents ORDER BY position DESC").fetchone()[
                    0
                ]
            )
            assert last.choice.minimum_days == last.choice.maximum_days == 180
            assert last.choice.currency == "UZS"
            assert last.choice.maximum_price_minor == (20000000 if budget else None)
            assert not db.execute("SELECT 1 FROM conversion_trial_grants").fetchone()
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
        assert lab.catalog.calls == 1
        state = await lab.state()
        assert state.history.quota.used_tokens == 300
        assert state.safety_budget.server_used_tokens == 0
        before = snapshot(lab.store)
        assert await lab.touch.admit_message(refinement) == completed
        assert snapshot(lab.store) == before and lab.catalog.calls == 1
        assert await lab.touch.admit_message(original)
    finally:
        await lab.close()


async def test_explicit_original_currency_answer_is_preserved_as_a_bound_request(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "currency-origin")
    try:
        original = request("Покажи тарифы на 90 дней до 200000")
        await lab.touch.admit_message(original)
        assert await lab.touch.process_reviewed_message()
        first = await lab.touch.message_state(LAB_PARENT, original.request_id)
        assert first.response and first.response.asked_question
        answer = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="UZS",
            reply_to_question_id=first.response.asked_question.question_id,
        )
        await lab.touch.admit_message(answer)
        assert await lab.touch.process_upsell()
        refinement = request("а на 180 дней?")
        state = await lab.touch.admit_message(refinement)
        context = await store(lab).tariff_followup_context(LAB_PARENT, state.turn_id)
        assert context and tuple(m.message for m in context.origin_messages) == (
            original.message,
            "UZS",
        )
        assert context.origin_intent.choice.currency == "UZS"
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_upsell()
        completed = await lab.touch.message_state(LAB_PARENT, refinement.request_id)
        assert completed.response and completed.response.asked_question is None
        assert "нет варианта" in completed.response.answer and lab.catalog.calls == 1
    finally:
        await lab.close()


@pytest.mark.parametrize("fence", ["before", "late", "tamper"])
async def test_disabled_or_changed_followup_never_redispatches_owning_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fence: str
) -> None:
    lab, _ = await setup(tmp_path / fence)
    calls = 0
    respond = lab.touch._model.respond

    async def stop_late(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        nonlocal calls
        calls += 1
        receipt = await respond(prompt, max_output_tokens=max_output_tokens)
        store(lab)._tariff_followups_enabled = False
        return receipt

    try:
        await quote(lab)
        refinement = request("а на 180 дней?")
        state = await lab.touch.admit_message(refinement)
        if fence == "before":
            store(lab)._tariff_followups_enabled = False
        elif fence == "tamper":
            with lab.store._transaction() as db:
                db.execute(
                    "UPDATE tariff_followup_captures SET payload=payload||' ' WHERE turn_id=?",
                    (state.turn_id,),
                )
        else:
            monkeypatch.setattr(lab.touch._model, "respond", stop_late)
        assert await lab.touch.process_reviewed_message()
        closed = await lab.touch.message_state(LAB_PARENT, refinement.request_id)
        assert closed.phase == "failed" and closed.response is None
        assert calls == (1 if fence == "late" else 0)
        assert lab.catalog.calls == 1 and not await lab.touch.process_upsell()
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM upsell_intents").fetchone()[0] == 1
            charge = db.execute(
                "SELECT input_tokens,output_tokens,reserved FROM parent_chat_turns WHERE id=?",
                (state.turn_id,),
            ).fetchone()
            assert tuple(charge) == ((100, 50, 0) if fence == "late" else (None, None, 0))
        assert await lab.touch.admit_message(refinement) == closed
    finally:
        await lab.close()


@pytest.mark.parametrize("intervening", ["greeting", "stale", "foreign"])
async def test_context_never_falls_back_to_an_unrelated_or_stale_quote(
    tmp_path: Path, intervening: str
) -> None:
    lab, clock = await setup(tmp_path / intervening)
    try:
        await quote(lab)
        if intervening == "greeting":
            hello = request("Привет")
            await lab.touch.admit_message(hello)
            assert await lab.touch.process_reviewed_message()
        elif intervening == "stale":
            clock.value += timedelta(hours=6, seconds=1)
        refinement = request("а на 180 дней?")
        if intervening == "foreign":
            refinement = refinement.model_copy(update={"parent_id": "900002"})
        state = await lab.touch.admit_message(refinement)
        assert await store(lab).tariff_followup_context(refinement.parent_id, state.turn_id) is None
        assert await store(lab).parent_publication_version(refinement.parent_id, state.turn_id) == 5
        assert lab.catalog.calls == 1
    finally:
        await lab.close()


async def test_bound_clarification_keeps_the_original_complete_tariff_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "clarification")
    respond = lab.touch._model.respond

    async def clarify(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        text = prompt.messages[-1][1]
        data = json.loads(prompt.messages[0][1])
        if text == "Покажи другой вариант":
            assert "tariff_followup" in data
            return ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=50),
                model="lab-simulated-not-billed",
                completed=True,
                answer="На какой срок подобрать тариф?",
                clarification_question="На какой срок подобрать тариф?",
            )
        if text == "180 дней":
            prior = data["tariff_followup"]
            assert prior["earlier_refinement_requests"] == ["Покажи другой вариант"]
            enquiry = UpsellEnquiry.model_validate(
                {
                    **prior["previous_terms"],
                    "parent_quote": text,
                    "minimum_days": 180,
                    "maximum_days": 180,
                }
            )
            return ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=50),
                model="lab-simulated-not-billed",
                completed=True,
                answer=TARIFF_HANDOFF_PLACEHOLDER,
                manager_handoff=ParentTouchManagerHandoff(
                    target="upsell", call_id="fictional-refinement", tariff_enquiry=enquiry
                ),
            )
        return await respond(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(lab.touch._model, "respond", clarify)
    try:
        original = await quote(lab)
        refinement = request("Покажи другой вариант")
        await lab.touch.admit_message(refinement)
        assert await lab.touch.process_reviewed_message()
        question = await lab.touch.message_state(LAB_PARENT, refinement.request_id)
        assert question.response and question.response.asked_question
        answer = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="180 дней",
            reply_to_question_id=question.response.asked_question.question_id,
        )
        state = await lab.touch.admit_message(answer)
        context = await store(lab).tariff_followup_context(LAB_PARENT, state.turn_id)
        assert context and context.origin_messages[0].message == original.message
        assert context.refinement_requests[0].message == refinement.message
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_upsell()
        result = await lab.touch.message_state(LAB_PARENT, answer.request_id)
        assert result.response and "нет варианта" in result.response.answer
        assert lab.catalog.calls == 1 and (await lab.state()).safety_budget.server_used_tokens == 0
    finally:
        await lab.close()


async def test_unknown_refinement_keeps_its_hold_over_closed_reader_restart_and_midnight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "unknown"
    lab, clock = await setup(directory)

    async def lost(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        raise TimeoutError("Fictional lost submitted refinement response")

    try:
        await quote(lab)
        refinement = request("а на 180 дней?")
        await lab.touch.admit_message(refinement)
        monkeypatch.setattr(lab.touch._model, "respond", lost)
        assert await lab.touch.process_reviewed_message()
        unknown = await lab.touch.message_state(LAB_PARENT, refinement.request_id)
        assert unknown.phase == "unknown" and unknown.response is None
        quota = (await lab.state()).history.quota
        assert quota.used_tokens == 150 and quota.reserved_tokens == 612
        before = snapshot(lab.store)
        closed = SqliteClosedTariffFollowupStore(
            directory / "family.sqlite3", daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        assert snapshot(closed) == before
    finally:
        await lab.close()
    restored, next_clock = await setup(directory)
    try:
        next_clock.value = clock.now() + timedelta(days=1)
        assert await restored.touch.admit_message(refinement) == unknown
        quota = (await restored.state()).history.quota
        assert quota.blocked_by_unresolved_request and quota.reserved_tokens == 0
        with restored.store._connect() as db:
            assert (
                db.execute(
                    "SELECT reserved FROM parent_chat_turns WHERE id=?", (unknown.turn_id,)
                ).fetchone()[0]
                == 612
            )
        assert snapshot(restored.store) == before
        assert restored.catalog.calls == 0 and not await restored.touch.process_upsell()
        with pytest.raises(ParentChatError, match="previous_request_unresolved"):
            await restored.touch.admit_message(request("Покажи другой тариф"))
    finally:
        await restored.close()


async def test_previously_admitted_protocol_five_never_acquires_followup_context(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "no-upgrade")
    try:
        await quote(lab)
        store(lab)._tariff_followups_enabled = False
        refinement = request("а на 180 дней?")
        state = await lab.touch.admit_message(refinement)
        store(lab)._tariff_followups_enabled = True
        assert await store(lab).tariff_followup_context(LAB_PARENT, state.turn_id) is None
        assert await store(lab).parent_publication_version(LAB_PARENT, state.turn_id) == 5
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM tariff_followup_captures").fetchone()
        assert lab.catalog.calls == 1
    finally:
        await lab.close()


async def test_historical_quote_never_bypasses_unknown_catalog_receipt(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "unknown-catalog")
    try:
        await quote(lab)
        with lab.store._transaction() as db:
            db.execute("UPDATE upsell_catalog_reads SET status='unknown'")
        refinement = request("а на 180 дней?")
        state = await lab.touch.admit_message(refinement)
        assert await store(lab).tariff_followup_context(LAB_PARENT, state.turn_id)
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_upsell()
        completed = await lab.touch.message_state(LAB_PARENT, refinement.request_id)
        assert completed.response and "не удалось подтвердить" in completed.response.answer
        assert "162 000" not in completed.response.answer
        assert lab.catalog.calls == 1
        with lab.store._connect() as db:
            row = db.execute(
                "SELECT COUNT(*),SUM(reserved_http_attempts),MAX(status) FROM upsell_catalog_reads"
            ).fetchone()
            assert tuple(row) == (1, 2, "unknown")
    finally:
        await lab.close()


async def test_strictly_cheaper_bound_is_calculated_by_host_and_never_raises_zero(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "cheaper-bound")
    try:
        await quote(lab)
        refinement = request("а дешевле?")
        state = await lab.touch.admit_message(refinement)
        context = await store(lab).tariff_followup_context(LAB_PARENT, state.turn_id)
        assert context
        assert context.presentation()["strictly_cheaper_reference"] == {
            "currency": "UZS",
            "maximum_price_minor": 16199999,
            "positive_price_can_match": True,
            "historical_reference_not_commercial_authority": True,
        }
        minimum_quote = context.quote.model_copy(
            update={"options": (context.quote.options[0].model_copy(update={"price_minor": 1}),)}
        )
        minimum = context.model_copy(update={"quote": minimum_quote})
        assert minimum.presentation()["strictly_cheaper_reference"] == {
            "currency": "UZS",
            "maximum_price_minor": 0,
            "positive_price_can_match": False,
            "historical_reference_not_commercial_authority": True,
        }
    finally:
        await lab.close()
