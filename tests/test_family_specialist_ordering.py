"""Mixed specialists traverse the actual single-chat broker with fictional providers."""

import asyncio
from contextlib import suppress
from datetime import timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest

from app.mana_ai.domain.child_safety import SafetyTarget
from app.mana_ai.domain.conversion_catalog import ConversionCatalogObservation
from app.mana_ai.domain.family_agents import AgentQuestionRequest, ParentTouchMessageRequest
from app.mana_ai.domain.proactive_parent import ParentContactContext
from app.mana_ai.domain.requests import SafetyMonitorRequest
from app.services.mana_chat_lab import LAB_CHILD, LAB_PARENT, ChatLab
from app.services.parent_support_question_store import SqliteParentSupportQuestionStore
from tests.test_compact_parent_manager import setup
from tests.test_trial_action_cards import snapshot


async def urgent_observation(lab: ChatLab) -> None:
    body = next(s.body for s in lab.bootstrap().scenarios if s.key == "safety")
    await lab.safety.admit(
        SafetyTarget.model_validate({k: v for k, v in body.items() if k != "analysis"}),
        SafetyMonitorRequest.model_validate(body["analysis"]),
    )
    completed = await lab.safety.process_one()
    assert completed and completed.status == "completed"


async def child_question(lab: ChatLab) -> AgentQuestionRequest:
    now = lab.options.clock.now()
    return AgentQuestionRequest(
        parent_id=LAB_PARENT,
        child_id=LAB_CHILD,
        agent_id="child-safety",
        request_id=uuid4(),
        information_key="school.current_routine",
        question="Как сейчас проходит учёба ребёнка?",
        reason="Fictional dated child-support clarification, no current risk assertion.",
        source_revision="fictional-ordering-v1",
        observed_at=now,
        expires_at=now + timedelta(hours=1),
    )


@pytest.mark.parametrize("language", ["ru", "uz-Latn"])
async def test_urgent_interrupt_retention_exact_answers_controls_replay_and_restart(
    tmp_path: Path, language: Literal["ru", "uz-Latn"]
) -> None:
    lab, clock = await setup(tmp_path / language)
    try:
        initial = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Спасибо за помощь с настройками."
        )
        await lab.touch.admit_message(initial)
        assert await lab.touch.process_reviewed_message()
        clock.value += timedelta(days=15)
        assert lab.touch.proactive
        await lab.touch.proactive.register(
            ParentContactContext(
                parent_id=LAB_PARENT,
                event_id=uuid4(),
                revision=int(clock.now().timestamp() * 1000000),
                observed_at=clock.now(),
                valid_until=clock.now() + timedelta(days=1),
                language=language,
                timezone="Asia/Samarkand",
                safety_chat_consent=True,
                safety_push_consent=False,
                marketing_push_consent=False,
                retention_chat_consent=True,
            )
        )
        assert await lab.touch.process_retention()
        original = (await lab.state()).history.active_question
        assert original and original.scope == "parent" and original.child_id is None
        need = await child_question(lab)
        queued = await lab.touch.request_question(need)
        assert await lab.store.next_delivery(clock.now()) is None
        await urgent_observation(lab)
        interruption = await lab.store.next_delivery(clock.now())
        assert interruption
        notice = await lab.touch.deliver(interruption)
        assert notice.speaker == "parent-touch" and notice.delivered_notice
        assert notice.delivered_notice.kind == "urgent" and notice.asked_question is None
        assert (await lab.state()).history.active_question == original
        answer = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message=(
                "Спасибо, с настройками разобрался."
                if language == "ru"
                else "Rahmat, sozlamalarni tushundim."
            ),
            reply_to_question_id=original.question_id,
        )
        admitted = await lab.touch.admit_message(answer)
        if not await lab.touch.process_reviewed_message():
            # A queued child need keeps its existing review-first owning path.
            reviewed = await lab.safety.process_one()
            assert reviewed and reviewed.status == "completed"
            assert await lab.touch.process_reviewed_message()
        parent_answer = await lab.touch.message_state(LAB_PARENT, answer.request_id)
        assert parent_answer.phase == "completed"
        assert isinstance(lab.store, SqliteParentSupportQuestionStore)
        assert await lab.store.answered_parent_question(LAB_PARENT, admitted.turn_id)
        child_offer = parent_answer.response
        if child_offer is None or child_offer.asked_question is None:
            offered = await lab.store.next_delivery(clock.now())
            assert offered
            child_offer = await lab.touch.deliver(offered)
        assert child_offer.speaker == "parent-touch" and child_offer.asked_question
        assert child_offer.asked_question.question_id == queued.question.question_id
        active = (await lab.state()).history.active_question
        assert active and active.child_id == LAB_CHILD
        controls = (
            ("не пиши первым", "возобнови напоминания об этом чате")
            if language == "ru"
            else ("birinchi bo‘lib yozmang", "bu chat haqida yana eslatib turing")
        )
        control_requests = []
        for text in controls:
            control = ParentTouchMessageRequest(
                parent_id=LAB_PARENT,
                request_id=uuid4(),
                message=text,
                reply_to_question_id=active.question_id,
            )
            control_requests.append(control)
            completed = await lab.touch.admit_message(control)
            assert completed.phase == "completed" and completed.response
            assert completed.response.usage.total == 0
            assert (await lab.state()).history.active_question == active
        exact_child_answer = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message=(
                "На этой неделе с учёбой всё спокойно."
                if language == "ru"
                else "Bu hafta o‘qishi yaxshi ketmoqda."
            ),
            reply_to_question_id=active.question_id,
        )
        child_admitted = await lab.touch.admit_message(exact_child_answer)
        safety = await lab.safety.process_one()
        assert safety and safety.status == "completed"
        assert await lab.touch.process_reviewed_message()
        child_answer = await lab.touch.message_state(LAB_PARENT, exact_child_answer.request_id)
        assert child_answer.phase == "completed" and child_answer.response
        assert child_answer.response.speaker == "parent-touch"
        final = await lab.state()
        assert final.history.active_question is None
        assert len(final.history.message_questions) == 2
        assert len(final.history.message_notices) == 1
        assert {m.role for m in final.history.messages} == {"user", "assistant"}
        assert final.history.quota.used_tokens <= 2000
        assert final.safety_budget.server_used_tokens <= 2000
        assert lab.battery.calls == lab.catalog.calls == lab.app_usage.calls == 0
        with lab.store._connect() as db:
            rows = db.execute(
                "SELECT question_id,child_id,status,answer_turn_id FROM family_questions "
                "ORDER BY position"
            ).fetchall()
            assert [tuple(r) for r in rows] == [
                (str(original.question_id), None, "answered", admitted.turn_id),
                (str(active.question_id), LAB_CHILD, "answered", child_admitted.turn_id),
            ]
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
        saved = snapshot(lab.store)
        requests = [initial, answer, *control_requests, exact_child_answer]
        for request in requests:
            assert (await lab.touch.admit_message(request)).phase == "completed"
        repeated_need = await lab.touch.request_question(need)
        assert repeated_need.request_id == queued.request_id
        assert repeated_need.coalesced is queued.coalesced
        assert repeated_need.question.question_id == queued.question.question_id
        assert repeated_need.question.status == "answered"
        assert repeated_need.question.answer_turn_id == child_admitted.turn_id
        assert snapshot(lab.store) == saved
        options = lab.options
        await lab.close()
        lab = ChatLab(options)
        await lab.start()
        assert snapshot(lab.store) == saved
        assert (await lab.state()).history == final.history
        for request in requests:
            assert (await lab.touch.admit_message(request)).phase == "completed"
        assert not await lab.touch.process_reviewed_message()
        assert not await lab.touch.process_upsell()
        assert not await lab.touch.process_retention()
        assert await lab.store.next_delivery(clock.now()) is None
        assert snapshot(lab.store) == saved
    finally:
        await lab.close()


async def test_urgent_safety_cancels_inflight_quote_and_keeps_known_catalog_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "commercial-safety")
    entered, release = asyncio.Event(), asyncio.Event()
    task: asyncio.Task[bool] | None = None
    original = lab.catalog.read

    async def waiting_catalog() -> ConversionCatalogObservation:
        entered.set()
        await release.wait()
        return await original()

    monkeypatch.setattr(lab.catalog, "read", waiting_catalog)
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Покажи тарифы на 90 дней UZS",
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        waiting = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert waiting.phase == "responding" and waiting.response is None
        charged = (await lab.state()).history.quota.used_tokens
        task = asyncio.create_task(lab.touch.process_upsell())
        await asyncio.wait_for(entered.wait(), 3)
        await urgent_observation(lab)
        # The SQL-only priority observer closes the settled tariff wait before
        # admitting the urgent message; the independent source claim remains.
        delivery = await lab.store.next_delivery(clock.now())
        assert delivery
        release.set()
        assert await asyncio.wait_for(task, 3)
        refused = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert refused.phase == "failed" and refused.response is None
        assert refused.error_code == "upsell_reply_interrupted"
        assert (await lab.state()).history.quota.used_tokens == charged
        response = await lab.touch.deliver(delivery)
        assert response.speaker == "parent-touch"
        assert response.delivered_notice and response.delivered_notice.kind == "urgent"
        assert response.asked_question is None
        history = (await lab.state()).history
        assert len(history.messages) == 2  # Parent's enquiry then the urgent assistant notice.
        assert all("162 000" not in message.content for message in history.messages)
        assert lab.catalog.calls == 1
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM upsell_catalog_reads").fetchone()[0] == "recorded"
            assert (
                db.execute("SELECT status FROM upsell_inline_replies").fetchone()[0] == "cancelled"
            )
        saved = snapshot(lab.store)
        assert await lab.touch.admit_message(request) == refused
        assert not await lab.touch.process_upsell()
        assert await lab.store.next_delivery(clock.now()) is None
        assert snapshot(lab.store) == saved
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await lab.close()
