"""Exact parent tariff commands reuse existing catalog work without model charges."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.literal_tariff_followups import (
    apply_literal_tariff_change,
    literal_tariff_change,
)
from app.mana_ai.domain.client_upsell import UpsellChoice
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.services.lab_workspace import workspace_options
from app.services.literal_tariff_followup_store import (
    SqliteClosedLiteralTariffFollowupStore,
    SqliteLiteralTariffFollowupStore,
)
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from tests.test_mana_chat_lab import Clock
from tests.test_tariff_followups import quote, request
from tests.test_trial_action_cards import snapshot


@pytest.mark.parametrize(
    ("text", "kind", "value", "language"),
    [
        ("А на180 дней?", "duration_days", 180, "ru"),
        ("yana 180 kun", "duration_days", 180, "uz-Latn"),
        ("яна 90 кун", "duration_days", 90, "uz-Cyrl"),
        ("What about 365 days?", "duration_days", 365, "en"),
        ("До 350000 UZS", "maximum_total", 35000000, "ru"),
        ("Byudjet 350000 UZS gacha", "maximum_total", 35000000, "uz-Latn"),
        ("Budget up to 12.34 USD", "maximum_total", 1234, "en"),
        ("А в USD?", "currency", "USD", "ru"),
        ("UZSda", "currency", "UZS", "uz-Latn"),
        ("in USD", "currency", "USD", "en"),
    ],
)
def test_literal_parser_is_exact_and_keeps_the_complete_message(
    text: str, kind: str, value: int | str, language: str
) -> None:
    change = literal_tariff_change(text)
    assert change and change.kind == kind and change.exact_message == text
    assert change.language == language
    assert (change.duration_days or change.maximum_price_minor or change.currency) == value


@pytest.mark.parametrize(
    "text",
    [
        "А на 180 дней или 365?",
        "А на 180 дней, но не увеличивай бюджет",
        "А на 0 дней?",
        "А на 367 дней?",
        "А на -180 дней?",
        "А на 1.5 дней?",
        "до 1e6 UZS",
        "до 0 UZS",
        "до 200 000 UZS",
        "до 200000 UZS и покажи ребёнка",
        "А дешевле?",
        "Translate 'in USD'",
    ],
)
def test_other_intent_or_ambiguous_numeric_text_stays_model_directed(text: str) -> None:
    assert literal_tariff_change(text) is None


def test_literal_update_keeps_all_other_terms_and_never_converts_a_budget() -> None:
    prior = UpsellChoice(
        parent_quote="Покажи тарифы на 90 дней до 200000 UZS",
        objective="list",
        currency="UZS",
        minimum_days=90,
        maximum_days=90,
        maximum_price_minor=20000000,
    )
    duration = literal_tariff_change("А на 180 дней?")
    assert duration
    changed = apply_literal_tariff_change(prior, duration)
    assert changed.minimum_days == changed.maximum_days == 180
    assert changed.currency == "UZS" and changed.maximum_price_minor == 20000000
    currency = literal_tariff_change("in USD")
    assert currency
    with pytest.raises(ValueError, match="explicit replacement"):
        apply_literal_tariff_change(prior, currency)
    explicit = literal_tariff_change("up to 100 USD")
    assert explicit
    updated = apply_literal_tariff_change(prior, explicit)
    assert updated.currency == "USD" and updated.maximum_price_minor == 10000
    assert updated.minimum_days == updated.maximum_days == 90


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
            tariff_followups=True,
            literal_tariff_followups=enabled,
        )
    )
    await lab.start()
    return lab, clock


def store(lab: ChatLab) -> SqliteLiteralTariffFollowupStore:
    assert isinstance(lab.store, SqliteLiteralTariffFollowupStore)
    return lab.store


def forbid_model(lab: ChatLab, monkeypatch: pytest.MonkeyPatch) -> None:
    async def count(prompt: ChatPrompt) -> int:
        raise AssertionError("A literal refinement cannot count a new model input")

    async def respond(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        raise AssertionError("A literal refinement cannot submit another generation")

    monkeypatch.setattr(lab.touch._model, "count_input", count)
    monkeypatch.setattr(lab.touch._model, "respond", respond)


@pytest.mark.parametrize("exhausted", [False, True])
async def test_literal_duration_finishes_its_original_turn_even_with_zero_model_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exhausted: bool
) -> None:
    lab, _ = await setup(tmp_path / "duration")
    try:
        original = await quote(lab, "Покажи тарифы на 90 дней UZS")
        if exhausted:
            with lab.store._transaction() as db:
                db.execute(
                    "UPDATE parent_chat_quota SET used=2000 WHERE parent_id=?", (LAB_PARENT,)
                )
        forbid_model(lab, monkeypatch)
        refinement = request("А на180 дней?")
        admitted = await lab.touch.admit_message(refinement)
        assert admitted.phase == "responding" and admitted.response is None
        assert not await lab.touch.process_reviewed_message()
        assert await lab.touch.admit_message(refinement) == await lab.touch.message_state(
            LAB_PARENT, refinement.request_id
        )
        assert await lab.touch.process_upsell()
        result = await lab.touch.message_state(LAB_PARENT, refinement.request_id)
        assert result.turn_id == admitted.turn_id and result.response
        assert result.response.usage.total == 0 and "299 000.00 UZS" in result.response.answer
        state = await lab.state()
        assert state.history.quota.used_tokens == (2000 if exhausted else 150)
        assert state.safety_budget.server_used_tokens == 0
        assert lab.catalog.calls == 1 and not await lab.touch.process_upsell()
        assert len(state.history.messages) == 4
        before = snapshot(lab.store)
        assert await lab.touch.admit_message(refinement) == result
        assert snapshot(lab.store) == before
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM parent_chat_turns").fetchone()[0] == 2
            assert db.execute("SELECT COUNT(*) FROM tariff_literal_derivations").fetchone()[0] == 1
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
            assert not db.execute("SELECT 1 FROM conversion_trial_grants").fetchone()
        assert await lab.touch.admit_message(original)
    finally:
        await lab.close()


async def test_literal_chain_keeps_budget_then_explicitly_changes_it_and_retains_all_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "chain")
    try:
        original = await quote(lab)
        forbid_model(lab, monkeypatch)
        duration = request("А на180 дней?")
        await lab.touch.admit_message(duration)
        assert await lab.touch.process_upsell()
        no_match = await lab.touch.message_state(LAB_PARENT, duration.request_id)
        assert no_match.response and "нет варианта" in no_match.response.answer
        budget = request("До350000 UZS")
        await lab.touch.admit_message(budget)
        assert await lab.touch.process_upsell()
        result = await lab.touch.message_state(LAB_PARENT, budget.request_id)
        assert result.response and "299 000.00 UZS" in result.response.answer
        assert lab.catalog.calls == 1
        # A later free-form request can still see every original word and explicit change.
        freeform = request("Какой вариант лучше для нас?")
        current = await lab.touch.admit_message(freeform)
        context = await store(lab).tariff_followup_context(LAB_PARENT, current.turn_id)
        assert context and tuple(m.message for m in context.literal_predecessors) == (
            original.message,
            duration.message,
        )
        assert context.origin_messages[0].message == budget.message
        assert context.presentation()["earlier_literal_requests"] == [
            original.message,
            duration.message,
        ]
        assert context.origin_intent.choice.maximum_price_minor == 35000000
        assert context.origin_intent.choice.minimum_days == 180
        assert (await lab.state()).history.quota.used_tokens == 150
        assert clock.now() == Clock.value
    finally:
        await lab.close()


@pytest.mark.parametrize("fence", ["disabled", "tamper", "unknown_source"])
async def test_literal_fences_never_fall_back_to_model_or_repeat_a_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fence: str
) -> None:
    lab, _ = await setup(tmp_path / fence)
    try:
        await quote(lab, "Покажи тарифы на 90 дней UZS")
        forbid_model(lab, monkeypatch)
        refinement = request("А на180 дней?")
        state = await lab.touch.admit_message(refinement)
        if fence == "disabled":
            store(lab)._literal_tariff_followups_enabled = False
        else:
            with lab.store._transaction() as db:
                if fence == "tamper":
                    db.execute(
                        "UPDATE tariff_literal_derivations SET fingerprint='changed' "
                        "WHERE turn_id=?",
                        (state.turn_id,),
                    )
                else:
                    db.execute("UPDATE upsell_catalog_reads SET status='unknown'")
        performed = await lab.touch.process_upsell()
        result = await lab.touch.message_state(LAB_PARENT, refinement.request_id)
        if fence == "unknown_source":
            assert (
                performed and result.response and "не удалось подтвердить" in result.response.answer
            )
        else:
            assert not performed and result.phase == "failed" and result.response is None
        assert (await lab.state()).history.quota.used_tokens == 150
        assert lab.catalog.calls == 1 and not await lab.touch.process_reviewed_message()
        assert await lab.touch.admit_message(refinement) == result
    finally:
        await lab.close()


async def test_exact_cancellation_uses_existing_tariff_status_and_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "cancel")
    try:
        await quote(lab, "Покажи тарифы на 90 дней UZS")
        forbid_model(lab, monkeypatch)
        refinement = request("А на180 дней?")
        await lab.touch.admit_message(refinement)
        status = await lab.touch.message_state(LAB_PARENT, refinement.request_id)
        assert status.can_cancel_tariff
        cancel = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Отмени подбор",
            cancel_tariff_request_id=refinement.request_id,
        )
        cancelled = await lab.touch.admit_message(cancel)
        assert cancelled.response and cancelled.response.usage.total == 0
        assert (await lab.touch.message_state(LAB_PARENT, refinement.request_id)).phase == "failed"
        assert not await lab.touch.process_upsell() and lab.catalog.calls == 1
        assert await lab.touch.admit_message(cancel) == cancelled
    finally:
        await lab.close()


async def test_pending_literal_and_all_prior_cells_survive_closed_reader_and_reconstruction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "restart"
    lab, _ = await setup(directory)
    try:
        await quote(lab, "Покажи тарифы на 90 дней UZS")
        refinement = request("А на180 дней?")
        waiting = await lab.touch.admit_message(refinement)
        before = snapshot(lab.store)
        closed = SqliteClosedLiteralTariffFollowupStore(
            directory / "family.sqlite3", daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        assert snapshot(closed) == before
    finally:
        await lab.close()
    restored, _ = await setup(directory)
    try:
        forbid_model(restored, monkeypatch)
        assert await restored.touch.admit_message(refinement) == await restored.touch.message_state(
            LAB_PARENT, refinement.request_id
        )
        assert await restored.touch.process_upsell()
        completed = await restored.touch.message_state(LAB_PARENT, refinement.request_id)
        assert completed.turn_id == waiting.turn_id and completed.response
        assert completed.response.usage.total == 0 and "299 000.00 UZS" in completed.response.answer
        assert restored.catalog.calls == 0 and not await restored.touch.process_upsell()
    finally:
        await restored.close()


async def test_disabled_origin_never_acquires_literal_eligibility_after_rearming(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "old-origin")
    try:
        store(lab)._literal_tariff_followups_enabled = False
        await quote(lab, "Покажи тарифы на 90 дней UZS")
        store(lab)._literal_tariff_followups_enabled = True
        # Use the declared fake model's free-form phrase; the no-space variant is
        # separately exercised above through the exact host parser.
        refinement = request("А на 180 дней?")
        current = await lab.touch.admit_message(refinement)
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM tariff_literal_derivations").fetchone()
            assert db.execute(
                "SELECT 1 FROM parent_touch_manager_turns WHERE turn_id=?", (current.turn_id,)
            ).fetchone()
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_upsell()
        result = await lab.touch.message_state(LAB_PARENT, refinement.request_id)
        assert result.response and result.response.usage.total == 150
        assert (await lab.state()).history.quota.used_tokens == 300
    finally:
        await lab.close()


async def test_bound_currency_origin_retains_every_request_across_literal_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "currency-origin")
    try:
        original = request("Покажи тарифы на 90 дней до 200000")
        await lab.touch.admit_message(original)
        assert await lab.touch.process_reviewed_message()
        offered = await lab.touch.message_state(LAB_PARENT, original.request_id)
        assert offered.response and offered.response.asked_question
        currency = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="UZS",
            reply_to_question_id=offered.response.asked_question.question_id,
        )
        await lab.touch.admit_message(currency)
        assert await lab.touch.process_upsell()
        forbid_model(lab, monkeypatch)
        duration = request("А на 180 дней?")
        await lab.touch.admit_message(duration)
        assert await lab.touch.process_upsell()
        final = await lab.touch.message_state(LAB_PARENT, duration.request_id)
        assert final.response and final.response.usage.total == 0
        assert "нет варианта" in final.response.answer
        freeform = await lab.touch.admit_message(request("Какой вариант лучше?"))
        context = await store(lab).tariff_followup_context(LAB_PARENT, freeform.turn_id)
        assert context and tuple(m.message for m in context.literal_predecessors) == (
            original.message,
            currency.message,
        )
        assert context.origin_messages[0].message == duration.message
        assert context.origin_intent.choice.currency == "UZS"
        assert context.origin_intent.choice.maximum_price_minor == 20000000
        assert lab.catalog.calls == 1
    finally:
        await lab.close()


async def test_malformed_quote_origin_refuses_before_any_model_or_host_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "invalid-origin")
    try:
        await quote(lab)
        forbid_model(lab, monkeypatch)
        with lab.store._transaction() as db:
            db.execute("UPDATE upsell_intents SET payload='{}'")
        before = snapshot(lab.store)
        with pytest.raises(ParentChatError, match="tariff_followup_origin_invalid"):
            await lab.touch.admit_message(request("А на 180 дней?"))
        assert snapshot(lab.store) == before
        assert lab.catalog.calls == 1
    finally:
        await lab.close()


async def test_literal_command_limit_refuses_without_using_model_quota_or_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "command-ceiling")
    try:
        await quote(lab, "Покажи тарифы на 90 дней UZS")
        store(lab)._reminder_policy = store(lab)._reminder_policy.model_copy(
            update={"parent_commands_per_24h": 1}
        )
        forbid_model(lab, monkeypatch)
        first = request("А на 180 дней?")
        await lab.touch.admit_message(first)
        assert await lab.touch.process_upsell()
        before = snapshot(lab.store)
        with pytest.raises(ParentChatError, match="assistant_command_limit_exceeded"):
            await lab.touch.admit_message(request("А на 90 дней?"))
        assert snapshot(lab.store) == before
        assert lab.catalog.calls == 1
        assert await lab.touch.admit_message(first)
    finally:
        await lab.close()
