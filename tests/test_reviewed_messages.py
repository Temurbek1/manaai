import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from pytest import MonkeyPatch

from app import product_ai_main
from app.core.config import Settings, get_settings
from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.child_safety import SafetyInformationNeed, SafetyModelDecision
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.services.child_safety_prompts import ChildSafetyPromptBuilder
from app.services.child_safety_store import SqliteChildSafetyStore
from app.services.family_agent_worker import FamilyAgentWorker
from app.services.family_compatibility_store import SqliteFamilyCompatibilityStore
from app.services.reviewed_message_store import (
    SqliteClosedReviewedBrokerStore,
    SqliteReviewedMessageStore,
)
from tests.test_child_safety_store import limits
from tests.test_parent_chat import NOW, Children, Model, message
from tests.test_parent_chat_api import BACKEND_TOKEN, HEADERS
from tests.test_parent_touch_api import PREFIX, TouchModel


class Clock:
    value = NOW

    def now(self) -> datetime:
        return self.value


class ReviewModel(Model):
    ask = True

    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        receipt = await super().respond(prompt, max_output_tokens=max_output_tokens)
        payload = json.loads(prompt.messages[0][1])
        assert payload["kind"] == "parent_message"
        assert "before Parent-Touch responds" in prompt.instructions
        decision = SafetyModelDecision(
            analysis=None,
            followup_summary="Based on the parent's report, bedtime is unknown. No diagnosis.",
            question=SafetyInformationNeed(
                child_alias="child-1",
                information_key="sleep.bedtime",
                question="Farzandingiz qachon uxlaydi?",
                reason="The parent's request needs the missing bedtime.",
                priority=1,
            )
            if self.ask and not payload["conversation_needs"]
            else None,
        )
        return replace(receipt, answer=decision.model_dump_json())

    async def close(self) -> None:
        pass


async def environment(
    path: Path,
) -> tuple[
    ParentTouchService,
    SqliteReviewedMessageStore,
    ChildSafetyService,
    ReviewModel,
    TouchModel,
    Children,
    Clock,
]:
    budget = limits(server_daily_tokens=10_000, parent_daily_tokens=5000, job_tokens=1000)
    store = SqliteReviewedMessageStore(
        path, limits=budget, daily_limit=2000, timezone="Asia/Samarkand"
    )
    await store.initialize()
    children, review_model, touch_model, clock = Children(), ReviewModel(), TouchModel(), Clock()
    safety = ChildSafetyService(
        store=store,
        children=children,
        model=review_model,
        prompts=ChildSafetyPromptBuilder(),
        clock=clock,
        limits=budget,
        max_output_tokens=256,
    )
    touch = ParentTouchService(
        store=store,
        children=children,
        model=touch_model,
        clock=clock.now,
        max_output_tokens=512,
        history_turn_limit=2,
        safety=safety,
        reviewed=store,
    )
    return touch, store, safety, review_model, touch_model, children, clock


def request(text: str = "Farzandim uyqusi haqida yordam bering.") -> ParentTouchMessageRequest:
    return ParentTouchMessageRequest(parent_id="123", request_id=uuid4(), message=text)


async def test_review_precedes_the_only_speaker_and_binds_answer_once(tmp_path: Path) -> None:
    touch, store, safety, review, speaker, children, _ = await environment(tmp_path / "family.db")
    original = request()
    first, concurrent = await asyncio.gather(
        touch.admit_message(original), touch.admit_message(original)
    )
    assert first == concurrent and first.phase == "awaiting_review"
    assert children.calls == review.calls == speaker.calls == 0
    assert not await touch.process_reviewed_message()
    assert (await touch.message_state("123", original.request_id)) == first
    assert len((await touch.read_touch_history("123", before=None, limit=30)).messages) == 1
    with pytest.raises(ParentChatError, match="previous_request_unresolved"):
        await touch.send(message(text="A competing legacy message"))
    assert children.calls == 0
    completed_review = await safety.process_one()
    assert completed_review and completed_review.status == "completed" and completed_review.result
    assert speaker.calls == 0
    assert await touch.process_reviewed_message()
    completed = await touch.message_state("123", original.request_id)
    assert completed.phase == "completed" and completed.response
    assert completed.response.asked_question
    context = json.loads(speaker.prompts[-1].messages[0][1])
    assert context["specialist_guidance"]["summary"] == completed_review.result.followup_summary
    assert datetime.fromisoformat(context["specialist_guidance"]["parent_message_at"]) == NOW
    assert "authorized_child_ids" not in context["specialist_guidance"]
    assert speaker.prompts[-1].response_language == "uz-Latn"
    assert "independent condition/normality/risk" in speaker.prompts[-1].instructions
    assert (await store.quota("123", NOW)).used_tokens == 150
    assert (await store.safety_budget("123", NOW)).parent_used_tokens == 150
    assert children.calls == 2 and speaker.calls == review.calls == 1
    assert await touch.admit_message(original) == completed
    assert not await touch.process_reviewed_message() and await safety.process_one() is None
    answer = request("Soat 21 da.").model_copy(
        update={"reply_to_question_id": completed.response.asked_question.question_id}
    )
    await touch.admit_message(answer)
    assert (await store.questions("123")).questions[0].status == "answered"
    await safety.process_one()
    assert "Soat 21 da." in review.prompts[-1].messages[0][1]
    assert '"status": "answered"' in review.prompts[-1].messages[0][1]
    await touch.process_reviewed_message()
    replied = await touch.message_state("123", answer.request_id)
    assert replied.response and replied.response.asked_question is None
    assert review.calls == speaker.calls == 2


@pytest.mark.parametrize("stage", ["review", "speaker"])
async def test_unknown_never_reinfers_after_restart_or_midnight(tmp_path: Path, stage: str) -> None:
    path = tmp_path / "unknown.db"
    touch, store, safety, review, speaker, _, clock = await environment(path)
    original = request()
    await touch.admit_message(original)
    (review if stage == "review" else speaker).error = TimeoutError("synthetic lost receipt")
    await safety.process_one()
    await touch.process_reviewed_message()
    state = await touch.message_state("123", original.request_id)
    assert state.phase == ("failed" if stage == "review" else "unknown")
    if stage == "review":
        assert (await store.safety_budget("123", NOW)).parent_blocked_by_unknown
        assert speaker.calls == 0 and (await store.quota("123", NOW)).reserved_tokens == 0
    else:
        assert (await store.quota("123", NOW)).blocked_by_unresolved_request
    resumed, new_store, new_safety, new_review, new_speaker, children, clock = await environment(
        path
    )
    clock.value = NOW + timedelta(days=1)
    assert (await resumed.admit_message(original)).phase == state.phase
    assert not await resumed.process_reviewed_message() and await new_safety.process_one() is None
    assert children.calls == new_review.calls == new_speaker.calls == 0
    assert (await new_store.safety_budget("123", clock.value)).parent_blocked_by_unknown == (
        stage == "review"
    )


async def test_waiting_deadline_expires_without_starting_an_old_review(tmp_path: Path) -> None:
    touch, _, safety, review, speaker, children, clock = await environment(tmp_path / "expiry.db")
    original = request()
    await touch.admit_message(original)
    clock.value += timedelta(minutes=6)
    state = await touch.message_state("123", original.request_id)
    assert state.phase == "failed" and state.error_code == "preparation_abandoned"
    assert await safety.process_one() is None
    assert not await touch.process_reviewed_message()
    assert children.calls == review.calls == speaker.calls == 0
    assert (await touch.admit_message(original)).phase == "failed"


async def test_claim_survives_restart_without_reclaiming_generation(tmp_path: Path) -> None:
    path = tmp_path / "claim.db"
    touch, store, safety, _, speaker, _, _ = await environment(path)
    original = request()
    await touch.admit_message(original)
    await safety.process_one()
    claims = await asyncio.gather(
        store.claim_reviewed_response(NOW), store.claim_reviewed_response(NOW)
    )
    assert sum(c is not None for c in claims) == 1
    restarted, _, _, _, _, children, clock = await environment(path)
    assert not await restarted.process_reviewed_message()
    clock.value += timedelta(minutes=6)
    assert (await restarted.message_state("123", original.request_id)).phase == "failed"
    assert children.calls == speaker.calls == 0


async def test_late_review_keeps_cost_but_cannot_publish_after_parent_expiry(
    tmp_path: Path,
) -> None:
    touch, store, safety, review, speaker, _, clock = await environment(tmp_path / "late.db")
    original = request()
    await touch.admit_message(original)
    clock.value = NOW + timedelta(seconds=120)
    review.release = asyncio.Event()
    running = asyncio.create_task(safety.process_one())
    await review.started.wait()
    clock.value = NOW + timedelta(seconds=301)
    assert (await touch.message_state("123", original.request_id)).phase == "failed"
    review.release.set()
    late = await running
    assert late and late.status == "failed" and late.usage and late.usage.total == 150
    assert not (await store.questions("123")).questions
    assert (
        not await touch.process_reviewed_message()
        and await store.next_delivery(clock.value) is None
    )
    assert (
        speaker.calls == 0
        and (await store.safety_budget("123", clock.value)).parent_used_tokens == 150
    )


async def test_failed_speaker_choice_is_not_automatically_retried_next_day(tmp_path: Path) -> None:
    touch, store, safety, _, speaker, _, clock = await environment(tmp_path / "quota.db")
    with store._transaction() as connection:
        day, _ = store._period(NOW)
        connection.execute(
            "INSERT INTO parent_chat_quota(parent_id,day,used) VALUES('123',?,1750)", (day,)
        )
    original = request()
    await touch.admit_message(original)
    await safety.process_one()
    assert await touch.process_reviewed_message()
    state = await touch.message_state("123", original.request_id)
    assert state.phase == "failed" and state.error_code == "daily_token_budget_exceeded"
    assert speaker.calls == 0
    assert await store.next_delivery(NOW) is None
    clock.value += timedelta(days=1)
    assert await store.next_delivery(clock.value) is None
    assert (await touch.admit_message(original)).phase == "failed"


async def test_revoked_child_and_known_invalid_review_never_reach_speaker(tmp_path: Path) -> None:
    touch, store, safety, review, speaker, _, _ = await environment(tmp_path / "revoked.db")
    original = request()
    await touch.admit_message(original)
    await safety.process_one()
    claim = await store.claim_reviewed_response(NOW)
    assert claim
    with pytest.raises(ParentChatError, match="reviewed_message_child_not_authorized"):
        await store.review_guidance("123", claim[0].turn.turn_id, ())
    assert speaker.calls == 0
    # A separate new family workflow with a known invalid specialist decision.
    other = request().model_copy(update={"parent_id": "223"})
    review.complete = False
    await touch.admit_message(other)
    await safety.process_one()
    await touch.process_reviewed_message()
    invalid = await touch.message_state("223", other.request_id)
    assert invalid.phase == "failed" and invalid.error_code == "child_safety_review_unavailable"
    assert speaker.calls == 0 and (await store.safety_budget("223", NOW)).parent_used_tokens == 150


async def test_v5_upgrade_and_current_closed_broker_preserve_exact_replay(tmp_path: Path) -> None:
    path = tmp_path / "upgrade.db"
    old = SqliteChildSafetyStore(path, limits=limits(), daily_limit=2000, timezone="Asia/Samarkand")
    await old.initialize()
    legacy = ParentTouchService(
        store=old,
        children=Children(),
        model=TouchModel(),
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    legacy_request = message(text="Salom")
    legacy_result = await legacy.send(legacy_request)
    with old._connect() as connection:
        old_snapshot = connection.execute(
            "SELECT context FROM child_safety_parent_events WHERE turn_id=1"
        ).fetchone()[0]
        assert "review_first" not in old_snapshot
    touch, store, safety, _, _, _, _ = await environment(path)
    assert await touch.send(legacy_request) == legacy_result
    with store._connect() as connection:
        assert (
            connection.execute(
                "SELECT context FROM child_safety_parent_events WHERE turn_id=1"
            ).fetchone()[0]
            == old_snapshot
        )
    original = request()
    await touch.admit_message(original)
    # A prior ordinary event is reviewed first using its historical protocol.
    await store.materialize_parent_event(NOW)
    with store._transaction() as connection:
        connection.execute(
            "UPDATE child_safety_jobs SET status='failed' WHERE parent_turn_cutoff=1"
        )
    await safety.process_one()
    await touch.process_reviewed_message()
    expected = await touch.message_state("123", original.request_id)
    assert expected.phase == "completed"
    closed = SqliteClosedReviewedBrokerStore(path, daily_limit=2000, timezone="Asia/Samarkand")
    await closed.initialize()
    closed_touch = ParentTouchService(
        store=closed,
        children=Children(),
        model=TouchModel(),
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
        reviewed=closed,
    )
    assert await closed_touch.admit_message(original) == expected
    assert not await closed_touch.process_reviewed_message()
    with pytest.raises(ParentChatError, match="review_first_disabled"):
        await closed_touch.admit_message(request())
    reader = SqliteFamilyCompatibilityStore(
        path, version=6, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
    )
    await reader.initialize()
    assert (await reader.history("123", before=None, limit=30, now=NOW)).messages[
        -1
    ].role == "assistant"
    with pytest.raises(RuntimeError):
        await old.initialize()


async def test_http_status_is_sql_only_private_and_does_not_redispatch(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    touch, _, safety, review, speaker, children, _ = await environment(tmp_path / "api.db")
    config = Settings(
        _env_file=None, openai_api_key=SecretStr("fake-key"), app_api_key=SecretStr(BACKEND_TOKEN)
    )
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: config)
    app = product_ai_main.create_app()
    app.dependency_overrides[get_settings] = lambda: config
    app.state.parent_chat_service = touch
    original = request()
    body = original.model_dump(mode="json")
    route = PREFIX + f"/parent-touch/messages/{original.request_id}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://unit") as client:
        assert (await client.post(PREFIX + "/parent-touch/messages", json=body)).status_code == 401
        admitted = await client.post(PREFIX + "/parent-touch/messages", json=body, headers=HEADERS)
        assert admitted.status_code == 202 and admitted.json()["phase"] == "awaiting_review"
        for _ in range(2):
            observed = await client.get(route + "?parent_id=123", headers=HEADERS)
            assert (
                observed.json() == admitted.json()
                and observed.headers["cache-control"] == "no-store"
            )
        assert (await client.get(route + "?parent_id=456", headers=HEADERS)).status_code == 404
        assert children.calls == review.calls == speaker.calls == 0
        conflict = await client.post(
            PREFIX + "/parent-touch/messages", json=body | {"message": "changed"}, headers=HEADERS
        )
        assert conflict.status_code == 409
        invalid = await client.post(
            PREFIX + "/parent-touch/messages",
            json=body | {"child_observations": []},
            headers=HEADERS,
        )
        assert invalid.status_code == 422
        await safety.process_one()
        await touch.process_reviewed_message()
        result = await client.get(route + "?parent_id=123", headers=HEADERS)
        assert result.json()["phase"] == "completed"
        assert "summary" not in result.text and "authorized_child_ids" not in result.text
        calls = children.calls, review.calls, speaker.calls
        replay = await client.post(PREFIX + "/parent-touch/messages", json=body, headers=HEADERS)
        assert (
            replay.json() == result.json()
            and (children.calls, review.calls, speaker.calls) == calls
        )


async def test_actual_worker_orders_review_then_speaker(tmp_path: Path) -> None:
    touch, _, safety, review, speaker, _, _ = await environment(tmp_path / "worker.db")
    original = request()
    await touch.admit_message(original)
    worker = FamilyAgentWorker(safety, touch, clock=lambda: NOW, interval=0.01)
    worker.start()
    try:
        for _ in range(150):
            state = await touch.message_state("123", original.request_id)
            if state.phase == "completed":
                break
            await asyncio.sleep(0.01)
        assert state.phase == "completed" and review.calls == speaker.calls == 1
    finally:
        await worker.close()


def test_review_first_is_opt_in_and_requires_explicit_safety_budget() -> None:
    assert not Settings(_env_file=None).mana_parent_touch_review_first_enabled
    with pytest.raises(ValidationError, match="require the Child-Safety worker"):
        Settings(_env_file=None, mana_parent_touch_review_first_enabled=True)
