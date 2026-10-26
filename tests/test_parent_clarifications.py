"""A single reactive manager question shares SQL history/priority with the specialists."""

import asyncio
import json
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
from app.mana_ai.domain.family_agents import AgentQuestionRequest, ParentTouchMessageRequest
from app.services import mana_chat_lab as runtime
from app.services import parent_chat_runtime as runtime_module
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.parent_chat_model import OpenAIParentChatModel
from app.services.parent_clarification_store import (
    SqliteClosedParentClarificationStore,
    SqliteParentClarificationStore,
)
from app.services.parent_support_question_store import (
    SqliteClosedParentSupportQuestionStore,
    SqliteParentSupportQuestionStore,
)
from tests.test_family_source_runtime import config, make_credential_file
from tests.test_lab_chat_actions import Clock, options
from tests.test_parent_chat_adapters import model_payload
from tests.test_parent_chat_adapters import settings as model_settings
from tests.test_parent_touch_manager_model import manager_prompt as sdk_prompt
from tests.test_parent_touch_manager_model import native_payload
from tests.test_trial_action_cards import snapshot


async def setup(path: Path) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(replace(options(path, clock), action_cards=False, clarifications=True))
    await lab.start()
    assert isinstance(lab.store, SqliteParentClarificationStore)
    return lab, clock


@pytest.mark.parametrize(
    "language,message",
    [("ru", "Как настроить MANA?"), ("uz-Latn", "MANA qanday sozlanadi?")],
)
async def test_one_question_then_exact_neutral_answer_without_safety_budget(
    tmp_path: Path, language: str, message: str
) -> None:
    lab, clock = await setup(tmp_path / language)
    try:
        # Reactive communication needs no Retention/marketing permission.
        assert lab.touch.proactive
        context = await lab.store.contact_context(LAB_PARENT, clock.now())
        assert context
        await lab.touch.proactive.register(
            context.model_copy(
                update={
                    "event_id": uuid4(),
                    "revision": context.revision + 1,
                    "retention_chat_consent": False,
                    "marketing_push_consent": False,
                }
            )
        )
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message=message
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        first = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert first.phase == "completed" and first.response and first.response.asked_question
        question = first.response.asked_question
        assert question.child_id is None and question.scope == "parent"
        assert len((await lab.state()).history.messages) == 2
        assert await lab.touch.admit_message(request) == first
        response = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Android",
            reply_to_question_id=question.question_id,
        )
        admitted = await lab.touch.admit_message(response)
        assert await lab.touch.process_reviewed_message()
        completed = await lab.touch.message_state(LAB_PARENT, response.request_id)
        assert completed.phase == "completed" and completed.response
        assert completed.response.asked_question is None
        assert (
            ("ruxsat" in completed.response.answer)
            if language == "uz-Latn"
            else ("разрешение" in completed.response.answer)
        )
        assert await lab.touch.admit_message(response) == completed
        history = (await lab.state()).history
        assert history.active_question is None and len(history.messages) == 4
        assert history.quota.used_tokens == 300 and history.quota.reserved_tokens == 0
        assert (await lab.state()).safety_budget.server_used_tokens == 0
        assert isinstance(lab.store, SqliteParentClarificationStore)
        assert (
            await lab.store.answered_parent_question(LAB_PARENT, admitted.turn_id)
            == first.response.answer
        )
        assert await lab.store.answered_parent_question("900003", admitted.turn_id) is None
        with lab.store._connect() as db:
            assert (
                db.execute("SELECT count(*) FROM parent_clarification_questions").fetchone()[0] == 1
            )
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
            assert not db.execute("SELECT 1 FROM child_safety_jobs").fetchone()
        with pytest.raises(ParentChatError, match="question_reply_mismatch"):
            await lab.touch.admit_message(response.model_copy(update={"request_id": uuid4()}))
    finally:
        await lab.close()


async def test_old_capture_cannot_gain_question_after_flag_is_enabled(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "old-turn")
    assert isinstance(lab.store, SqliteParentClarificationStore)
    lab.store._clarifications_enabled = False
    request = ParentTouchMessageRequest(
        parent_id=LAB_PARENT, request_id=uuid4(), message="Спасибо."
    )
    await lab.touch.admit_message(request)
    lab.store._clarifications_enabled = True

    class Unadmitted:
        async def count_input(self, prompt: ChatPrompt) -> int:
            assert prompt.manager_scope and not prompt.manager_scope.clarifications_enabled
            return 100

        async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
            return ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=50),
                model="lab-simulated-not-billed",
                completed=True,
                answer="Какая настройка?",
                clarification_question="Какая настройка?",
            )

    lab.touch._model = Unadmitted()
    try:
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed"
        assert (await lab.state()).history.quota.used_tokens == 150
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM parent_clarification_admissions").fetchone()
            assert not db.execute("SELECT 1 FROM family_questions").fetchone()
    finally:
        await lab.close()


async def test_disabling_new_protocol_before_generation_does_not_fallback(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "disabled")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Как настроить MANA?"
        )
        await lab.touch.admit_message(request)
        assert isinstance(lab.store, SqliteParentClarificationStore)
        lab.store._clarifications_enabled = False
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "failed" and state.error_code == "parent_clarifications_disabled"
        assert (await lab.state()).history.quota.used_tokens == 0
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM family_questions").fetchone()
            assert not db.execute("SELECT 1 FROM child_safety_jobs").fetchone()
    finally:
        await lab.close()


async def test_child_question_answer_keeps_original_specialist_review(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "child")
    try:
        need = AgentQuestionRequest.model_validate(
            next(s.body for s in lab.bootstrap().scenarios if s.key == "question")
        )
        await lab.touch.request_question(need)
        delivery = await lab.store.next_delivery(clock.now())
        assert delivery
        spoken = await lab.touch.deliver(delivery)
        assert spoken.asked_question
        response = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="В девять вечера.",
            reply_to_question_id=spoken.asked_question.question_id,
        )
        admitted = await lab.touch.admit_message(response)
        assert admitted.phase == "awaiting_review"
        with lab.store._connect() as db:
            assert db.execute("SELECT count(*) FROM child_safety_parent_events").fetchone()[0] == 1
            assert not db.execute("SELECT 1 FROM parent_clarification_admissions").fetchone()
    finally:
        await lab.close()


async def test_current_closed_reader_and_restart_keep_unknown_hold_without_question(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "unknown")
    entered = asyncio.Event()

    class Lost:
        async def count_input(self, prompt: ChatPrompt) -> int:
            return 100

        async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
            entered.set()
            await asyncio.Future()
            raise AssertionError("unreachable")

    lab.touch._model = Lost()
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Как настроить MANA?"
        )
        await lab.touch.admit_message(request)
        task = asyncio.create_task(lab.touch.process_reviewed_message())
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "unknown"
        with lab.store._connect() as db:
            hold = db.execute(
                "SELECT reserved FROM parent_chat_turns WHERE status='unknown'"
            ).fetchone()[0]
            assert hold > 0 and not db.execute("SELECT 1 FROM family_questions").fetchone()
        before = snapshot(lab.store)
        closed = SqliteClosedParentClarificationStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        assert snapshot(closed) == before
        clock.value += timedelta(days=1)
        assert (await closed.quota(LAB_PARENT, clock.now())).blocked_by_unresolved_request
        assert not await lab.touch.process_reviewed_message()
        assert snapshot(lab.store) == before
        with pytest.raises(RuntimeError, match="dedicated database"):
            await SqliteClosedParentSupportQuestionStore(
                lab.store._path, daily_limit=2000, timezone="Asia/Samarkand"
            ).initialize()
        assert snapshot(lab.store) == before
    finally:
        await lab.close()


async def test_v28_pending_manager_turn_never_recaptures_new_question_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "v28"

    def legacy(
        path: Path, *, clarifications_enabled: bool, **family: Any
    ) -> SqliteParentSupportQuestionStore:
        return SqliteParentSupportQuestionStore(path, **family)

    with monkeypatch.context() as patcher:
        patcher.setattr(runtime, "SqliteParentClarificationStore", legacy)
        clock = Clock()
        clock.value = Clock.value
        opts = replace(options(directory, clock), action_cards=False, clarifications=True)
        lab = ChatLab(opts)
        await lab.start()
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Спасибо."
        )
        admitted = await lab.touch.admit_message(request)
        before = snapshot(lab.store)
        await lab.close()
    lab = ChatLab(opts)
    await lab.start()
    try:
        after = snapshot(lab.store)
        assert {t: after[t] for t in before} == before
        assert isinstance(lab.store, SqliteParentClarificationStore)
        with lab.store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 29
            assert not db.execute("SELECT 1 FROM parent_clarification_admissions").fetchone()
        # The queued protocol is still the old body-only reply, despite the current flag.
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert (
            state.phase == "completed" and state.response and state.response.asked_question is None
        )
        assert state.turn_id == admitted.turn_id
    finally:
        await lab.close()


@pytest.mark.parametrize("enabled", [False, True])
async def test_actual_sdk_new_question_contract_is_private_and_raw_usage_survives_rejection(
    enabled: bool,
) -> None:
    prompt = sdk_prompt()
    prompt = replace(
        prompt,
        manager_scope=prompt.manager_scope.model_copy(update={"clarifications_enabled": enabled}),
    )
    sent: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        body = model_payload()
        body["output"][0]["content"][0]["text"] = json.dumps(
            {"body": "Помогу с настройкой.", "question": "У вас Android или iPhone?"}
        )
        return httpx.Response(
            200, json={"input_tokens": 100} if request.url.path.endswith("/input_tokens") else body
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        adapter = OpenAIParentChatModel(
            model_settings(),
            client=AsyncOpenAI(api_key="fake-key", max_retries=0, http_client=http),
        )
        assert await adapter.count_input(prompt) == 100
        receipt = await adapter.respond(prompt, max_output_tokens=512)
    assert receipt.usage.total == 150 and receipt.completed == enabled
    assert receipt.clarification_question == ("У вас Android или iPhone?" if enabled else None)
    assert receipt.question_id is None
    assert sent[0] == {k: sent[1][k] for k in sent[0]}
    schema = sent[1]["text"]["format"]["schema"]
    assert ("question" in schema["properties"]) == enabled
    assert schema["additionalProperties"] is False


async def test_native_owner_handoff_precedes_accompanying_question_prose() -> None:
    prompt = sdk_prompt()
    prompt = replace(
        prompt,
        manager_scope=prompt.manager_scope.model_copy(update={"clarifications_enabled": True}),
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=native_payload()))
    ) as http:
        adapter = OpenAIParentChatModel(
            model_settings(),
            client=AsyncOpenAI(api_key="fake-key", max_retries=0, http_client=http),
        )
        receipt = await adapter.respond(prompt, max_output_tokens=512)
    assert (
        receipt.completed
        and receipt.manager_handoff
        and receipt.manager_handoff.target == "child_safety"
    )
    assert receipt.answer is None and receipt.clarification_question is None
    assert receipt.usage.total == 150


async def test_late_child_priority_suppresses_question_after_charging_usage(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "priority")

    class HigherPriority:
        async def count_input(self, prompt: ChatPrompt) -> int:
            return 100

        async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
            need = AgentQuestionRequest.model_validate(
                next(s.body for s in lab.bootstrap().scenarios if s.key == "question")
            )
            await lab.touch.request_question(need)
            return ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=50),
                model="lab-simulated-not-billed",
                completed=True,
                answer="Какой телефон?",
                clarification_question="Какой телефон?",
            )

    lab.touch._model = HigherPriority()
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Как настроить MANA?"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        assert (await lab.touch.message_state(LAB_PARENT, request.request_id)).phase == "failed"
        state = await lab.state()
        assert state.history.quota.used_tokens == 150
        assert len(state.history.messages) == 1 and state.history.messages[0].role == "user"
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM parent_clarification_questions").fetchone()
            assert db.execute("SELECT status FROM family_questions").fetchone()[0] == "queued"
        assert await lab.store.next_delivery(clock.now())
    finally:
        await lab.close()


async def test_question_publication_failure_retains_hold_and_does_not_duplicate(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "atomic")
    try:
        with lab.store._transaction() as db:
            db.execute(
                "CREATE TRIGGER deny_clarification BEFORE INSERT ON "
                "parent_clarification_questions BEGIN "
                "SELECT RAISE(ABORT,'synthetic failure'); END"
            )
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Как настроить MANA?"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "unknown"
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM family_questions").fetchone()
            assert not db.execute("SELECT 1 FROM parent_clarification_questions").fetchone()
            assert (
                db.execute(
                    "SELECT reserved FROM parent_chat_turns WHERE status='unknown'"
                ).fetchone()[0]
                > 0
            )
        assert not await lab.touch.process_reviewed_message()
        assert (await lab.touch.admit_message(request)).phase == "unknown"
    finally:
        await lab.close()


async def test_concurrent_answers_are_one_reply_to_one_parent_question(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "race")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Как настроить MANA?"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        state = (await lab.state()).history
        assert state.active_question
        answer = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Android",
            reply_to_question_id=state.active_question.question_id,
        )
        with pytest.raises(ParentChatError, match="question_reply_mismatch"):
            await lab.touch.admit_message(answer.model_copy(update={"parent_id": "900003"}))
        outcomes = await asyncio.gather(
            lab.touch.admit_message(answer),
            lab.touch.admit_message(answer.model_copy(update={"request_id": uuid4()})),
            return_exceptions=True,
        )
        assert sum(not isinstance(o, BaseException) for o in outcomes) == 1
        assert await lab.touch.process_reviewed_message()
        assert (await lab.state()).history.quota.used_tokens == 300
        with lab.store._connect() as db:
            assert (
                db.execute("SELECT count(*) FROM parent_clarification_questions").fetchone()[0] == 1
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM family_questions WHERE status='answered'"
                ).fetchone()[0]
                == 1
            )
    finally:
        await lab.close()


async def test_runtime_admits_v29_and_disabling_retains_private_state_without_idle_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = []

    def deny(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.host)
        raise AssertionError("Idle source call")

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
        mana_parent_touch_clarifications_enabled=True,
        mana_child_safety_limits=ChildSafetyLimits(
            server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=2000, lease_seconds=360
        ),
    )
    for enabled in (True, False):
        async with runtime_module.parent_chat_runtime(
            settings.model_copy(update={"mana_parent_touch_clarifications_enabled": enabled})
        ) as service:
            assert service and isinstance(service.store, SqliteParentClarificationStore)
            with service.store._connect() as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 29
                assert not db.execute("SELECT 1 FROM parent_clarification_admissions").fetchone()
    assert not requests
