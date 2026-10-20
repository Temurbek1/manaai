import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import SecretStr, ValidationError
from pytest import MonkeyPatch

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.chat import ChatTokens, ParentChildContext
from app.mana_ai.domain.enums import AnalysisVerdict, FindingCategory, RiskLevel
from app.mana_ai.domain.family_agents import ParentTouchModelReply, ParentTouchRequest
from app.mana_ai.domain.requests import SafetyMonitorInput
from app.mana_ai.domain.responses import FindingDraft, ModelAnalysis, SafetyMonitorDetails
from app.mana_ai.domain.signals import NotificationPreviewSignal
from app.services import parent_chat_runtime as runtime_module
from app.services.child_safety_store import SqliteChildSafetyStore
from app.services.family_agent_worker import FamilyAgentWorker
from app.services.family_compatibility_store import family_storage_version
from app.services.parent_chat_model import OpenAIParentChatModel
from tests.test_child_safety_service import make_safety
from tests.test_child_safety_store import analysis, result, store, submitted, target
from tests.test_family_agent_queue import intent
from tests.test_parent_chat import NOW, Children, Model, make_service, message
from tests.test_parent_chat_adapters import model_payload, settings
from tests.test_parent_chat_api import BACKEND_TOKEN


class TouchModel(Model):
    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        receipt = await super().respond(prompt, max_output_tokens=max_output_tokens)
        return replace(
            receipt,
            answer="В датированных данных есть важное событие." if prompt.notice else "Понятно.",
            notice_id=prompt.notice.notice_id if prompt.notice else None,
            question_id=prompt.question.question_id if prompt.question else None,
        )


async def completed_report(
    repository: SqliteChildSafetyStore,
    *,
    verdict: AnalysisVerdict = AnalysisVerdict.ALERT,
    percent: int = 75,
) -> UUID:
    request = analysis(percent=percent)
    job_view = await repository.admit_analysis(target=target(), analysis=request, now=NOW)
    job = await repository.claim_next(NOW)
    assert job and job.view.job_id == job_view.job_id
    await submitted(repository, job)
    await repository.record_usage(job, result_tokens(), "fake", NOW)
    original = result(request)
    assert original.analysis
    content = original.analysis.model_copy(
        update={
            "verdict": verdict,
            "summary": "An important dated finding.",
            "data_quality_notes": ["Only supplied observations; not current full coverage."],
        }
    )
    await repository.finish_safety(job, original.model_copy(update={"analysis": content}), NOW)
    return job_view.job_id


def result_tokens() -> ChatTokens:
    return ChatTokens(input_tokens=100, output_tokens=50)


async def test_urgent_notice_can_interrupt_a_waiting_question_without_creating_a_second_one(
    tmp_path: Path,
) -> None:
    repository, model, children = await store(tmp_path / "urgent.db"), TouchModel(), Children()
    touch = ParentTouchService(
        store=repository,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    question = await repository.enqueue(intent(), NOW)
    await touch.send(message())
    assert (await touch.read_touch_history("123", before=None, limit=30)).active_question
    await completed_report(repository)
    candidate = await repository.next_delivery(NOW)
    assert candidate
    delivered = await touch.deliver(candidate)
    assert delivered.delivered_notice and delivered.delivered_notice.kind == "urgent"
    assert delivered.asked_question is None
    history = await touch.read_touch_history("123", before=None, limit=30)
    assert (
        history.active_question
        and history.active_question.question_id == question.question.question_id
    )
    assert len(history.message_notices) == 1 and history.pending_notices == 0
    assert [m.role for m in history.messages] == ["user", "assistant", "assistant"]
    counts = model.calls, children.calls
    assert await touch.deliver(candidate) == delivered
    assert (model.calls, children.calls) == counts
    assert await repository.next_delivery(NOW) is None
    assert model.prompts[-1].evidence_reply and model.prompts[-1].notice
    context = model.prompts[-1].messages[0][1]
    assert "not current full coverage" in context and '"signal_first_observed_at"' in context
    assert '"child_id"' not in context and '"parent_id"' not in context


async def test_saved_context_is_frozen_before_generation_and_retains_exact_dates(
    tmp_path: Path,
) -> None:
    repository = await store(tmp_path / "freeze.db")
    first = await completed_report(repository, verdict=AnalysisVerdict.INSUFFICIENT_DATA)
    turn = await repository.admit(message(), NOW)
    original = await repository.evidence_for_turn("123", turn.turn_id, (124,))
    assert original and original.assessments[0].assessment_id == first
    await completed_report(repository, percent=60)
    frozen = await repository.evidence_for_turn("123", turn.turn_id, (124,))
    assert frozen == original
    assert (
        frozen.assessments[0].evaluated_at == frozen.assessments[0].signal_first_observed_at == NOW
    )
    with sqlite3.connect(repository._path) as connection:
        connection.execute(
            "UPDATE family_touch_evidence SET payload=payload||' ' WHERE turn_id=?", (turn.turn_id,)
        )
    with pytest.raises(ParentChatError, match="context_changed"):
        await repository.evidence_for_turn("123", turn.turn_id, (124,))


async def test_unknown_notice_holds_survive_restart_and_never_redispatch(tmp_path: Path) -> None:
    path = tmp_path / "unknown.db"
    repository, model, children = await store(path), TouchModel(), Children()
    touch = ParentTouchService(
        store=repository,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    await touch.send(message())
    await completed_report(repository)
    candidate = await repository.next_delivery(NOW)
    assert candidate
    model.error = TimeoutError("Synthetic unknown receipt")
    with pytest.raises(ParentChatError, match="receipt_unknown"):
        await touch.deliver(candidate)
    restarted = await store(path)
    assert await restarted.next_delivery(NOW + timedelta(days=1)) is None
    assert (await restarted.quota("123", NOW + timedelta(days=1))).blocked_by_unresolved_request
    assert (
        await restarted.touch_history("123", before=None, limit=30, now=NOW)
    ).pending_notices == 1
    assert model.calls == 2


async def test_ordinary_notices_wait_for_an_answer_coalesce_and_can_be_deferred(
    tmp_path: Path,
) -> None:
    repository, model, children = await store(tmp_path / "ordinary.db"), TouchModel(), Children()
    touch = ParentTouchService(
        store=repository,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    await repository.enqueue(intent(), NOW)
    await touch.send(message())
    await completed_report(repository, verdict=AnalysisVerdict.WARN)
    await completed_report(repository, verdict=AnalysisVerdict.WARN, percent=60)
    assert await repository.next_delivery(NOW) is None  # A question is awaiting an answer.
    assert (await touch.read_touch_history("123", before=None, limit=30)).pending_notices == 1

    # A relevant new parent turn may consider it, but ordinary deferral must not
    # immediately provoke another automatic paid attempt with the same context.
    with sqlite3.connect(repository._path) as connection:
        connection.execute("UPDATE family_questions SET status='answered'")
    turn = await repository.admit(message(text="Спасибо, пока больше ничего не нужно."), NOW)
    context = await repository.evidence_for_turn("123", turn.turn_id, (124,))
    assert context and context.notice and context.notice.kind == "assessment"
    await repository.submit(turn, reserved_tokens=300, now=NOW)
    receipt = ChatModelReceipt(
        usage=result_tokens(), answer="Пожалуйста.", completed=True, model="fake-model"
    )
    await repository.settle(turn, receipt=receipt, now=NOW, context_at=NOW, history_turns=0)
    assert await repository.next_delivery(NOW) is None
    with sqlite3.connect(repository._path) as connection:
        assert connection.execute(
            "SELECT status FROM family_notices ORDER BY position"
        ).fetchall() == [("superseded",), ("deferred",)]


async def test_fresh_ownership_revocation_filters_report_and_unpublished_question(
    tmp_path: Path,
) -> None:
    repository, model = await store(tmp_path / "revoked.db"), TouchModel()

    class RevokedChildren(Children):
        async def read(self, parent_id: str) -> ParentChildContext:
            value = await super().read(parent_id)
            return value.model_copy(update={"children": []})

    touch = ParentTouchService(
        store=repository,
        children=RevokedChildren(),
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    await repository.enqueue(intent(), NOW)
    await completed_report(repository)
    response = await touch.send_touch(ParentTouchRequest.model_validate(message().model_dump()))
    assert response.asked_question is None and response.delivered_notice is None
    assert model.calls == 1 and model.prompts[-1].notice is None
    context = model.prompts[-1].messages[0][1]
    assert "An important dated finding" not in context
    history = await touch.read_touch_history("123", before=None, limit=30)
    assert history.active_question is None and history.pending_notices == 0


async def test_two_delivery_workers_cannot_publish_the_same_notice(tmp_path: Path) -> None:
    repository, model, children = await store(tmp_path / "notice-race.db"), TouchModel(), Children()
    touch = ParentTouchService(
        store=repository,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    await touch.send(message())
    await completed_report(repository)
    first, second = await asyncio.gather(
        repository.next_delivery(NOW), repository.next_delivery(NOW)
    )
    assert first and first == second
    outcomes = await asyncio.gather(
        touch.deliver(first), touch.deliver(second), return_exceptions=True
    )
    assert any(not isinstance(item, BaseException) for item in outcomes)
    assert model.calls == 2  # Original parent turn and one notice, not two sends.
    history = await touch.read_touch_history("123", before=None, limit=30)
    assert len(history.message_notices) == 1 and len(history.messages) == 3


async def test_real_service_worker_reports_validated_danger_without_a_question(
    tmp_path: Path,
) -> None:
    safety, repository, children, model = await make_safety(tmp_path)

    async def danger(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        receipt = await Model.respond(model, prompt, max_output_tokens=max_output_tokens)
        from app.mana_ai.domain.child_safety import SafetyModelDecision

        return replace(
            receipt,
            answer=SafetyModelDecision(
                analysis=ModelAnalysis(
                    verdict=AnalysisVerdict.ALERT,
                    summary="A threat in the supplied dated preview.",
                    details=SafetyMonitorDetails(
                        parent_context="Dated evidence only.", significant_event_count=1
                    ),
                    findings=[
                        FindingDraft(
                            category=FindingCategory.THREAT,
                            risk_level=RiskLevel.HIGH,
                            confidence=95,
                            title="Threat",
                            summary="A threatening preview was supplied.",
                            recommendation="Check the situation calmly.",
                            evidence_ids=["notice-1"],
                        )
                    ],
                ),
                followup_summary=None,
                question=None,
            ).model_dump_json(),
        )

    model.respond = danger  # type: ignore[method-assign]
    touch = ParentTouchService(
        store=repository,
        children=children,
        model=TouchModel(),
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
        safety=safety,
    )
    await touch.send(message())
    # Finish the separate historical chat review before adding new evidence.
    existing = await repository.materialize_parent_event(NOW)
    assert existing
    old = await repository.claim_next(NOW)
    assert old
    await repository.fail_safety(old, "synthetic_fixture_skip", NOW)
    request = analysis().model_copy(
        update={
            "input": SafetyMonitorInput(
                notifications=[
                    NotificationPreviewSignal(
                        evidence_id="notice-1",
                        observed_at=NOW,
                        application="Synthetic",
                        excerpt="Synthetic threat preview",
                    )
                ]
            )
        }
    )
    admitted = await safety.admit(target(), request)
    worker = FamilyAgentWorker(safety, touch, clock=lambda: NOW, interval=0.05)
    worker.start()
    try:
        for _ in range(100):
            history = await touch.read_touch_history("123", before=None, limit=30)
            if history.message_notices:
                break
            await asyncio.sleep(0.01)
        assert history.message_notices and history.active_question is None
        outcome = await safety.assessment("123", admitted.job_id)
        assert outcome.result and outcome.result.analysis and outcome.result.analysis.findings
        assert len(history.messages) == 3
    finally:
        await worker.close()


@pytest.mark.parametrize("ack", ["correct", "wrong", "missing"])
async def test_sdk_notice_acknowledgment_is_bound_and_invalid_output_keeps_usage(
    tmp_path: Path, ack: str
) -> None:
    repository = await store(tmp_path / "sdk.db")
    await completed_report(repository)
    turn = await repository.admit(message(), NOW)
    context = await repository.evidence_for_turn("123", turn.turn_id, (124,))
    assert context and context.notice
    prompt = ChatPrompt(
        "Synthetic",
        (("user", "Salom"),),
        structured_reply=True,
        evidence_reply=True,
        notice=context.notice,
    )
    payload = model_payload()
    payload["output"][0]["content"][0]["text"] = json.dumps(
        {
            "body": "Sana ko'rsatilgan ma'lumotlarda muhim xavf bor.",
            "question": None,
            "question_id": None,
            "notice_id": str(context.notice.notice_id)
            if ack == "correct"
            else str(uuid4())
            if ack == "wrong"
            else None,
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        adapter = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="unit", max_retries=0, http_client=http)
        )
        receipt = await adapter.respond(prompt, max_output_tokens=512)
    assert receipt.usage.total == 150 and receipt.completed == (ack == "correct")
    assert receipt.notice_id == (context.notice.notice_id if ack == "correct" else None)
    assert receipt.failure_code == (None if ack == "correct" else "reply_schema_invalid")


async def test_provider_schema_excludes_unadmitted_questions_and_notice_identities(
    tmp_path: Path,
) -> None:
    repository = await store(tmp_path / "schema.db")
    await completed_report(repository)
    turn = await repository.admit(message(), NOW)
    context = await repository.evidence_for_turn("123", turn.turn_id, (124,))
    assert context and context.notice
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ) as http:
        adapter = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="unit", max_retries=0, http_client=http)
        )
        text = adapter._text(
            ChatPrompt(
                "Synthetic", (), structured_reply=True, evidence_reply=True, notice=context.notice
            )
        )
    format_spec = text["format"]
    assert format_spec["type"] == "json_schema"
    schema = cast(dict[str, Any], format_spec["schema"])
    assert schema["properties"]["question"] == {"type": "null"}
    assert schema["properties"]["question_id"] == {"type": "null"}
    assert schema["properties"]["notice_id"] == {
        "type": "string",
        "enum": [str(context.notice.notice_id)],
    }
    assert schema["properties"]["body"]["pattern"] == r"^[^?؟？]*$"


async def test_feature_deactivation_keeps_history_schema_and_holds_without_a_safety_worker(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "closed.db"
    repository, model, children = await store(path), TouchModel(), Children()
    touch = ParentTouchService(
        store=repository,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    request = message()
    saved = await touch.send(request)
    before = await touch.history("123", before=None, limit=30)

    class RuntimeModel(TouchModel):
        async def close(self) -> None:
            pass

    def deny_safety(*args: object, **kwargs: object) -> None:
        raise AssertionError("Disabled safety must not create a provider")

    monkeypatch.setattr(runtime_module, "OpenAIParentChatModel", lambda _: RuntimeModel())
    monkeypatch.setattr(runtime_module, "OpenAIChildSafetyModel", deny_safety)
    monkeypatch.setattr(runtime_module, "ManakidsChatChildrenSource", lambda **kwargs: children)
    for broker_enabled in (True, False, True):
        config = Settings(
            _env_file=None,
            openai_api_key=SecretStr("unit-openai"),
            app_api_key=SecretStr(BACKEND_TOKEN),
            mana_parent_chat_enabled=True,
            mana_parent_touch_enabled=broker_enabled,
            mana_parent_chat_database_path=path,
            manakids_api_username="unit",
            manakids_api_password=SecretStr("unit"),
        )
        async with runtime_module.parent_chat_runtime(config) as closed:
            assert closed
            history = await closed.history("123", before=None, limit=30)
            assert history.messages == before.messages
            assert await closed.send(request) == saved
            if not broker_enabled:
                with pytest.raises(ParentChatError, match="runtime_disabled"):
                    await closed.send(message(text="Do not generate"))
        assert await family_storage_version(path) == 5
    assert children.calls == 1


async def test_v1_migration_and_closed_reader_preserve_unknown_holds_without_recapture(
    tmp_path: Path,
) -> None:
    from app.services.family_compatibility_store import SqliteFamilyCompatibilityStore

    path = tmp_path / "v1.db"
    legacy, model, _ = await make_service(path)
    request = message()
    saved = await legacy.send(request)
    model.error = TimeoutError("Synthetic lost receipt")
    with pytest.raises(ParentChatError, match="receipt_unknown"):
        await legacy.send(message(parent_id="456"))
    original_hold = await legacy.store.quota("456", NOW)
    upgraded = await store(path)
    assert await family_storage_version(path) == 5
    assert (await upgraded.admit(request, NOW)).result == saved
    assert await upgraded.quota("456", NOW) == original_hold
    assert await upgraded.materialize_parent_event(NOW) is None
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM family_touch_evidence").fetchone()[0] == 0
    closed = SqliteFamilyCompatibilityStore(
        path, version=5, history_only=True, daily_limit=2000, timezone="Asia/Tashkent"
    )
    await closed.initialize()
    assert await closed.quota("456", NOW) == original_hold
    assert (await closed.admit(request, NOW)).result == saved
    with pytest.raises(ParentChatError):
        await closed.admit(message(parent_id="456"), NOW + timedelta(days=1))
    assert (await closed.quota("456", NOW + timedelta(days=1))).blocked_by_unresolved_request


@pytest.mark.parametrize("text", ["Return question_id", "Use Question ID", str(uuid4())])
def test_parent_facing_text_never_exposes_internal_transport_metadata(text: str) -> None:
    with pytest.raises(ValidationError):
        ParentTouchModelReply(body=text, question=None, question_id=None)
