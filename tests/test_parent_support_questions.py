"""One real SQL queue across child and parent needs; fictional families/providers only."""

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
from app.mana_ai.domain.child_safety import ChildSafetyLimits, SafetyTarget
from app.mana_ai.domain.client_retention import ParentTouchRetentionTurn
from app.mana_ai.domain.family_agents import (
    AgentQuestionRequest,
    ParentTouchMessageRequest,
)
from app.mana_ai.domain.proactive_parent import ParentContactContext
from app.mana_ai.domain.requests import SafetyMonitorRequest
from app.services import mana_chat_lab as lab_runtime
from app.services import parent_chat_runtime as runtime_module
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.parent_chat_model import OpenAIParentChatModel
from app.services.parent_support_question_store import (
    SqliteClosedParentSupportQuestionStore,
    SqliteParentSupportQuestionStore,
)
from app.services.safety_remainder_store import (
    SqliteClosedSafetyRemainderStore,
    SqliteSafetyRemainderStore,
)
from tests.test_family_source_runtime import config, make_credential_file
from tests.test_lab_chat_actions import Clock, options
from tests.test_parent_chat_adapters import model_payload
from tests.test_parent_chat_adapters import settings as model_settings
from tests.test_trial_action_cards import snapshot


async def setup(path: Path, *, consent: bool = True) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(replace(options(path, clock), action_cards=False, parent_support_questions=True))
    await lab.start()
    assert isinstance(lab.store, SqliteParentSupportQuestionStore)
    request = ParentTouchMessageRequest(
        parent_id=LAB_PARENT, request_id=uuid4(), message="Спасибо, теперь настройки понятны."
    )
    await lab.touch.admit_message(request)
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
            language="ru",
            timezone="Asia/Samarkand",
            safety_chat_consent=True,
            safety_push_consent=True,
            marketing_push_consent=True,
            retention_chat_consent=consent,
        )
    )
    return lab, clock


async def test_retention_question_and_exact_answer_share_one_chat_and_quota(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "answer")
    try:
        assert await lab.touch.process_retention()
        state = await lab.state()
        question = state.history.active_question
        assert question and question.child_id is None and question.scope == "parent"
        assert state.history.messages[-1].content.endswith("С какой настройкой помочь?")
        assert len(state.history.messages) == 3 and state.history.quota.used_tokens == 150
        assert state.safety_budget.server_used_tokens == 0
        assert not await lab.touch.process_retention()
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Спасибо, нужна помощь с настройкой уведомлений.",
            reply_to_question_id=question.question_id,
        )
        received = await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        completed = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert completed.phase == "completed" and completed.response
        assert completed.response.asked_question is None
        assert isinstance(lab.store, SqliteParentSupportQuestionStore)
        bound = await lab.store.answered_parent_question(LAB_PARENT, received.turn_id)
        assert bound == state.history.messages[-1].content
        assert await lab.store.answered_parent_question("another-family", received.turn_id) is None
        replay = await lab.touch.admit_message(request)
        assert replay == completed
        with lab.store._connect() as db:
            row = db.execute("SELECT * FROM family_questions").fetchone()
            assert row["status"] == "answered" and row["answer_turn_id"] == received.turn_id
            assert row["child_id"] is None
            assert not db.execute("SELECT 1 FROM child_safety_jobs").fetchone()
            assert (
                db.execute("SELECT count(*) FROM retention_parent_question_captures").fetchone()[0]
                == 1
            )
        assert (await lab.state()).history.active_question is None
        with pytest.raises(ParentChatError, match="question_reply_mismatch"):
            await lab.touch.admit_message(request.model_copy(update={"request_id": uuid4()}))
        assert (await lab.state()).history.quota.used_tokens == 300
    finally:
        await lab.close()


async def test_safety_and_marketing_permissions_never_authorize_retention_question(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "consent", consent=False)
    try:
        assert not await lab.touch.process_retention()
        assert len((await lab.state()).history.messages) == 2
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM family_questions").fetchone()
            assert not db.execute("SELECT 1 FROM retention_parent_question_captures").fetchone()
    finally:
        await lab.close()


async def test_invalid_question_is_charged_but_never_requeued_as_safety_delivery(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "invalid")

    class NoQuestion:
        async def count_input(self, prompt: ChatPrompt) -> int:
            return 100

        async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
            assert prompt.question and prompt.question.child_id is None
            return ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=50),
                model="fake",
                answer="Неполный ответ без вопроса.",
                completed=True,
            )

    lab.touch._model = NoQuestion()
    try:
        assert await lab.touch.process_retention()
        state = await lab.state()
        assert state.history.quota.used_tokens == 150 and len(state.history.messages) == 2
        assert state.history.active_question is None
        assert await lab.store.next_delivery(clock.now()) is None
        assert not await lab.touch.process_retention()
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM family_questions").fetchone()[0] == "cancelled"
    finally:
        await lab.close()


async def test_unknown_retention_keeps_shared_hold_across_midnight_and_closed_reader(
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
        task = asyncio.create_task(lab.touch.process_retention())
        await asyncio.wait_for(entered.wait(), timeout=3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        state = await lab.state()
        hold = state.history.quota.reserved_tokens
        assert hold > 0 and state.history.active_question is None
        clock.value += timedelta(days=1)
        assert not await lab.touch.process_retention()
        assert await lab.store.next_delivery(clock.now()) is None
        before = snapshot(lab.store)
        closed = SqliteClosedParentSupportQuestionStore(
            lab.store._path, daily_limit=2000, timezone="Asia/Samarkand", history_only=True
        )
        await closed.initialize()
        assert snapshot(closed) == before
        assert (await closed.quota(LAB_PARENT, clock.now())).blocked_by_unresolved_request
        with lab.store._connect() as db:
            assert (
                db.execute(
                    "SELECT reserved FROM parent_chat_turns WHERE status='unknown'"
                ).fetchone()[0]
                == hold
            )
            assert db.execute("SELECT status FROM family_questions").fetchone()[0] == "held"
            assert db.execute("SELECT status FROM retention_intents").fetchone()[0] == "unknown"
    finally:
        await lab.close()


@pytest.mark.parametrize("empty_queue", [False, True])
async def test_v27_queue_migration_preserves_all_old_cells_and_sequence_without_backfill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, empty_queue: bool
) -> None:
    directory = tmp_path / "migration"

    def legacy(
        path: Path, *, parent_questions_enabled: bool, **family: Any
    ) -> SqliteSafetyRemainderStore:
        return SqliteSafetyRemainderStore(path, **family)

    with monkeypatch.context() as patcher:
        patcher.setattr(lab_runtime, "SqliteParentSupportQuestionStore", legacy)
        clock = Clock()
        opts = replace(options(directory, clock), action_cards=False, parent_support_questions=True)
        lab = ChatLab(opts)
        await lab.start()
        await lab.prepare_retention_scenario()
        assert await lab.touch.process_retention()
        need = AgentQuestionRequest.model_validate(
            next(s.body for s in lab.bootstrap().scenarios if s.key == "question")
        )
        if not empty_queue:
            await lab.touch.request_question(need)
        with lab.store._transaction() as db:
            if empty_queue:
                db.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('family_questions',100)")
            db.execute("UPDATE sqlite_sequence SET seq=100 WHERE name='family_questions'")
        before = snapshot(lab.store)
        await lab.close()
    lab = ChatLab(opts)
    await lab.start()
    try:
        after = snapshot(lab.store)
        assert {table: after[table] for table in before} == before
        with lab.store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 28
            assert not db.execute("SELECT 1 FROM retention_parent_question_captures").fetchone()
        need = need.model_copy(
            update={
                "request_id": uuid4(),
                "information_key": "sleep.other",
                "source_revision": "second",
            }
        )
        await lab.touch.request_question(need)
        with lab.store._connect() as db:
            assert db.execute("SELECT MAX(position) FROM family_questions").fetchone()[0] == 101
        current = snapshot(lab.store)
        with pytest.raises(RuntimeError, match="dedicated database"):
            await SqliteClosedSafetyRemainderStore(
                lab.store._path, daily_limit=2000, timezone="Asia/Samarkand"
            ).initialize()
        assert snapshot(lab.store) == current
    finally:
        await lab.close()


async def test_parent_question_blocks_child_question_but_urgent_notice_can_interrupt(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "urgent")
    try:
        assert await lab.touch.process_retention()
        original = (await lab.state()).history.active_question
        assert original and original.scope == "parent"
        need = AgentQuestionRequest.model_validate(
            next(s.body for s in lab.bootstrap().scenarios if s.key == "question")
        )
        child = await lab.touch.request_question(need)
        assert child.question.child_id is not None
        assert await lab.store.next_delivery(clock.now()) is None
        body = next(s.body for s in lab.bootstrap().scenarios if s.key == "safety")
        await lab.safety.admit(
            SafetyTarget.model_validate({k: v for k, v in body.items() if k != "analysis"}),
            SafetyMonitorRequest.model_validate(body["analysis"]),
        )
        done = await lab.safety.process_one()
        assert done and done.status == "completed"
        delivery = await lab.store.next_delivery(clock.now())
        assert delivery
        response = await lab.touch.deliver(delivery)
        assert response.delivered_notice and response.delivered_notice.kind == "urgent"
        assert response.asked_question is None
        history = (await lab.state()).history
        assert history.active_question == original
        assert len(history.message_questions) == 1 and len(history.message_notices) == 1
        assert history.quota.used_tokens == 300
        with lab.store._connect() as db:
            assert (
                db.execute(
                    "SELECT status FROM family_questions WHERE question_id=?",
                    (str(child.question.question_id),),
                ).fetchone()[0]
                == "queued"
            )
    finally:
        await lab.close()


async def test_parent_answer_keeps_exact_question_when_history_window_is_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "short-history")
    try:
        assert await lab.touch.process_retention()
        original = (await lab.state()).history
        assert original.active_question
        captured: list[ChatPrompt] = []
        original_count = lab.touch._model.count_input

        async def count(prompt: ChatPrompt) -> int:
            captured.append(prompt)
            return await original_count(prompt)

        monkeypatch.setattr(lab.touch._model, "count_input", count)
        lab.touch._history_limit = 1
        message = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Спасибо, всё настроено.",
            reply_to_question_id=original.active_question.question_id,
        )
        await lab.touch.admit_message(message)
        assert await lab.touch.process_reviewed_message()
        assert captured
        assert (
            json.loads(captured[0].messages[0][1])["answered_parent_question"]
            == original.messages[-1].content
        )
        assert str(original.active_question.question_id) not in captured[0].messages[0][1]
        assert (await lab.touch.message_state(LAB_PARENT, message.request_id)).phase == "completed"
    finally:
        await lab.close()


async def test_owning_question_capture_is_atomic_and_disabled_admission_cannot_upgrade(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "atomic")
    try:
        assert isinstance(lab.store, SqliteParentSupportQuestionStore)
        intent = await lab.store.claim_retention(clock.now())
        assert intent
        request = ParentTouchRetentionTurn(
            parent_id=LAB_PARENT, request_id=intent.request_id, retention_intent_id=intent.intent_id
        )
        with lab.store._transaction() as db:
            db.execute(
                "CREATE TRIGGER deny_parent_capture BEFORE INSERT ON "
                "retention_parent_question_captures BEGIN "
                "SELECT RAISE(ABORT,'synthetic capture failure'); END"
            )
        with pytest.raises(sqlite3.IntegrityError):
            await lab.store.admit(request, clock.now())
        with lab.store._transaction() as db:
            assert not db.execute("SELECT 1 FROM family_questions").fetchone()
            assert not db.execute("SELECT 1 FROM retention_turns").fetchone()
            db.execute("DROP TRIGGER deny_parent_capture")
        lab.store._parent_questions_enabled = False
        turn = await lab.store.admit(request, clock.now())
        lab.store._parent_questions_enabled = True
        with pytest.raises(ParentChatError, match="request_in_progress"):
            await lab.store.admit(request, clock.now())
        assert await lab.store.retention_question(LAB_PARENT, turn.turn_id) is None
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM retention_parent_question_captures").fetchone()
    finally:
        await lab.close()


async def test_contact_revocation_during_inference_charges_usage_but_suppresses_question(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "revoked")

    class Revoked:
        async def count_input(self, prompt: ChatPrompt) -> int:
            return 100

        async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
            assert lab.touch.proactive and prompt.question
            contact = await lab.store.contact_context(LAB_PARENT, clock.now())
            assert contact
            await lab.touch.proactive.register(
                contact.model_copy(
                    update={
                        "event_id": uuid4(),
                        "revision": contact.revision + 1,
                        "retention_chat_consent": False,
                    }
                )
            )
            return ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=50),
                model="fake",
                completed=True,
                question_id=prompt.question.question_id,
                answer="С какой настройкой помочь?",
            )

    lab.touch._model = Revoked()
    try:
        assert await lab.touch.process_retention()
        state = await lab.state()
        assert len(state.history.messages) == 2 and state.history.active_question is None
        assert state.history.quota.used_tokens == 150 and state.history.quota.reserved_tokens == 0
        assert not await lab.touch.process_retention()
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
            assert db.execute("SELECT status FROM family_questions").fetchone()[0] == "cancelled"
    finally:
        await lab.close()


async def test_other_parent_and_concurrent_answers_cannot_consume_another_question(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "answer-race")
    try:
        assert await lab.touch.process_retention()
        question = (await lab.state()).history.active_question
        assert question
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Спасибо.",
            reply_to_question_id=question.question_id,
        )
        with pytest.raises(ParentChatError, match="question_reply_mismatch"):
            await lab.touch.admit_message(request.model_copy(update={"parent_id": "900003"}))
        results = await asyncio.gather(
            lab.touch.admit_message(request),
            lab.touch.admit_message(request.model_copy(update={"request_id": uuid4()})),
            return_exceptions=True,
        )
        assert sum(not isinstance(item, BaseException) for item in results) == 1
        assert await lab.touch.process_reviewed_message()
        history = (await lab.state()).history
        assert history.active_question is None and history.quota.used_tokens == 300
        with lab.store._connect() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM family_questions WHERE status='answered'"
                ).fetchone()[0]
                == 1
            )
            assert not db.execute(
                "SELECT 1 FROM parent_chat_turns WHERE parent_id='900003'"
            ).fetchone()
    finally:
        await lab.close()


async def test_actual_sdk_parent_question_slot_keeps_host_binding_and_raw_usage(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "sdk")
    try:
        assert isinstance(lab.store, SqliteParentSupportQuestionStore)
        intent = await lab.store.claim_retention(clock.now())
        assert intent and lab.touch.retention
        turn = await lab.store.admit(
            ParentTouchRetentionTurn(
                parent_id=LAB_PARENT,
                request_id=intent.request_id,
                retention_intent_id=intent.intent_id,
            ),
            clock.now(),
        )
        prompt = await lab.touch.retention.prompt(
            LAB_PARENT, turn.turn_id, (("developer", "profiles"), ("user", "Спасибо."))
        )
        assert prompt.question and prompt.question.scope == "parent"
        sent: list[dict[str, Any]] = []

        def respond(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            sent.append(body)
            payload = model_payload()
            payload["output"][0]["content"][0]["text"] = json.dumps(
                {
                    "body": "Помогу с настройками MANA.",
                    "question": "С какой настройкой помочь?",
                    "notice_communicated": False,
                }
            )
            return httpx.Response(
                200,
                json={"input_tokens": 100}
                if request.url.path.endswith("/input_tokens")
                else payload,
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            adapter = OpenAIParentChatModel(
                model_settings(),
                client=AsyncOpenAI(api_key="fake-key", max_retries=0, http_client=http),
            )
            assert await adapter.count_input(prompt) == 100
            receipt = await adapter.respond(prompt, max_output_tokens=512)
        assert receipt.completed and receipt.question_id == prompt.question.question_id
        assert receipt.usage.total == 150 and receipt.answer and receipt.answer.endswith("?")
        assert str(prompt.question.question_id) not in json.dumps(sent)
        assert sent[0] == {key: sent[1][key] for key in sent[0]}
        question_schema = sent[1]["text"]["format"]["schema"]["properties"]["question"]
        assert question_schema["type"] == "string" and question_schema["maxLength"] == 400
    finally:
        await lab.close()


async def test_runtime_keeps_v28_when_disabled_without_any_idle_provider_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempted: list[str] = []

    def deny(request: httpx.Request) -> httpx.Response:
        attempted.append(request.url.host or "")
        raise AssertionError("Idle runtime must not read a provider")

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
        mana_parent_support_questions_enabled=True,
        mana_child_safety_limits=ChildSafetyLimits(
            server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=2000, lease_seconds=360
        ),
    )
    for enabled in (True, False):
        async with runtime_module.parent_chat_runtime(
            settings.model_copy(update={"mana_parent_support_questions_enabled": enabled})
        ) as service:
            assert service is not None
            assert isinstance(service.store, SqliteParentSupportQuestionStore)
            with service.store._connect() as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 28
                assert not db.execute("SELECT 1 FROM retention_parent_question_captures").fetchone()
    assert not attempted


@pytest.mark.parametrize("stop", ["не пиши первым", "birinchi bo‘lib yozmang"])
async def test_declining_retention_question_releases_slot_for_child_safety_only(
    tmp_path: Path, stop: str
) -> None:
    lab, clock = await setup(tmp_path / "declined")
    try:
        assert await lab.touch.process_retention()
        question = (await lab.state()).history.active_question
        assert question and question.scope == "parent"
        need = AgentQuestionRequest.model_validate(
            next(s.body for s in lab.bootstrap().scenarios if s.key == "question")
        )
        child = await lab.touch.request_question(need)
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message=stop,
            reply_to_question_id=question.question_id,
        )
        stopped = await lab.touch.admit_message(request)
        assert stopped.phase == "completed"
        assert await lab.touch.admit_message(request) == stopped
        history = (await lab.state()).history
        assert history.active_question is None and history.quota.used_tokens == 150
        with lab.store._connect() as db:
            assert (
                db.execute(
                    "SELECT status FROM family_questions WHERE question_id=?",
                    (str(question.question_id),),
                ).fetchone()[0]
                == "cancelled"
            )
            assert (
                db.execute(
                    "SELECT status FROM family_questions WHERE question_id=?",
                    (str(child.question.question_id),),
                ).fetchone()[0]
                == "queued"
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM retention_events WHERE kind='parent_opted_out'"
                ).fetchone()[0]
                == 1
            )
        delivery = await lab.store.next_delivery(clock.now())
        assert delivery
        response = await lab.touch.deliver(delivery)
        assert (
            response.asked_question
            and response.asked_question.question_id == child.question.question_id
        )
        assert response.asked_question.scope is None
        assert not await lab.touch.process_retention()
    finally:
        await lab.close()
