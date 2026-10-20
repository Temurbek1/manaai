import asyncio
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.child_safety import SafetyInformationNeed, SafetyModelDecision
from app.mana_ai.domain.enums import AnalysisVerdict, FindingCategory, RiskLevel
from app.mana_ai.domain.family_agents import ParentTouchRequest
from app.mana_ai.domain.responses import FindingDraft, ModelAnalysis, SafetyMonitorDetails
from app.services.child_safety_model import OpenAIChildSafetyModel
from app.services.child_safety_prompts import ChildSafetyPromptBuilder
from app.services.child_safety_store import SqliteChildSafetyStore
from tests.test_child_safety_store import analysis, limits, store, target
from tests.test_parent_chat import NOW, Children, Model, message
from tests.test_parent_chat_adapters import model_payload, settings
from tests.test_parent_touch_api import TouchModel


class Clock:
    def now(self) -> datetime:
        return NOW


class SafetyModel(Model):
    change: str | None = None
    ask = True

    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        receipt = await super().respond(prompt, max_output_tokens=max_output_tokens)
        data = json.loads(prompt.messages[0][1])
        child = data["kind"] == "child_data"
        semantic = (
            ModelAnalysis(
                verdict=AnalysisVerdict.INSUFFICIENT_DATA,
                summary="Only dated, supplied observations were reviewed.",
                details=SafetyMonitorDetails(parent_context="Synthetic", significant_event_count=0),
            )
            if child
            else None
        )
        question = (
            SafetyInformationNeed(
                child_alias="child-99" if self.change == "foreign_child" else "child-1",
                information_key="battery.charging",
                question="Is the child charging the device?",
                reason="Charging state is missing from the dated battery report.",
                priority=1,
            )
            if child and self.ask
            else None
        )
        if semantic and self.change == "invented_evidence":
            semantic = semantic.model_copy(
                update={
                    "findings": [
                        FindingDraft(
                            category=FindingCategory.BATTERY_ANOMALY,
                            risk_level=RiskLevel.HIGH,
                            confidence=99,
                            title="Unsupported",
                            summary="Unsupported",
                            recommendation="Unsupported",
                            evidence_ids=["NOT-SUPPLIED"],
                        )
                    ]
                }
            )
        decision = SafetyModelDecision(
            analysis=semantic,
            followup_summary=None
            if child
            else "Parent answer reviewed against historical findings.",
            question=question,
        )
        return replace(
            receipt,
            answer="not JSON" if self.change == "invalid_json" else decision.model_dump_json(),
        )


async def make_safety(
    tmp_path: Path,
) -> tuple[ChildSafetyService, SqliteChildSafetyStore, Children, SafetyModel]:
    repository, children, model = await store(tmp_path / "safety.db"), Children(), SafetyModel()
    service = ChildSafetyService(
        store=repository,
        children=children,
        model=model,
        prompts=ChildSafetyPromptBuilder(),
        clock=Clock(),
        limits=limits(),
        max_output_tokens=256,
    )
    return service, repository, children, model


async def test_actual_service_analysis_question_parent_answer_and_historical_followup(
    tmp_path: Path,
) -> None:
    safety, repository, children, model = await make_safety(tmp_path)
    source, request = target(), analysis()
    admitted = await safety.admit(source, request)
    assert model.calls == children.calls == 0
    completed = await safety.process_one()
    assert completed and completed.job_id == admitted.job_id and completed.status == "completed"
    assert completed.result and completed.result.analysis and completed.result.question_id
    assert completed.result.analysis.proposed_actions == []
    assert model.calls == model.counts == children.calls == 1
    private_input = model.prompts[0].messages[0][1]
    assert '"parent_id"' not in private_input and '"child_id"' not in private_input
    assert '"subject_id"' not in private_input and "child-1" in private_input
    assert await safety.admit(source, request) == completed
    assert (
        await safety.admit(source.model_copy(update={"request_id": uuid4()}), request)
    ).job_id == completed.job_id
    touch = ParentTouchService(
        store=repository,
        children=children,
        model=TouchModel(),
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
        safety=safety,
    )
    delivered = await touch.send_touch(
        ParentTouchRequest.model_validate(message(text="Salom").model_dump())
    )
    assert (
        delivered.asked_question
        and delivered.asked_question.question_id == completed.result.question_id
    )
    first_review = await safety.process_one()
    assert (
        first_review
        and first_review.kind == "parent_message"
        and first_review.status == "completed"
    )
    reply = ParentTouchRequest(
        parent_id="123",
        request_id=uuid4(),
        message="Ha, zaryad olayapti.",
        reply_to_question_id=delivered.asked_question.question_id,
    )
    await touch.send_touch(reply)
    followup = await safety.process_one()
    assert followup and followup.result and followup.result.followup_summary
    text = model.prompts[-1].messages[0][1]
    assert "Ha, zaryad olayapti." in text
    assert '"signal_first_observed_at"' in text and NOW.isoformat() in text
    assert '"processed_at"' in text and '"profile_collected_at"' in text
    assert "fresh measurement" in model.prompts[-1].instructions
    assert (await repository.questions("123")).questions[0].status == "answered"
    calls = model.calls, children.calls
    assert await safety.process_one() is None and (model.calls, children.calls) == calls
    assert (await safety.budget("123")).parent_used_tokens == 450
    assert (await touch.history("123", before=None, limit=30)).quota.used_tokens == 300


@pytest.mark.parametrize("change", ["foreign_child", "invalid_json"])
async def test_bad_decisions_retain_cost_but_publish_no_question(
    tmp_path: Path, change: str
) -> None:
    service, repository, children, model = await make_safety(tmp_path)
    model.change = change
    await service.admit(target(), analysis())
    failed = await service.process_one()
    assert failed and failed.status == "failed" and failed.error_code == "safety_invalid_decision"
    assert failed.usage and failed.usage.total == 150
    assert not (await repository.questions("123")).questions
    assert (await service.budget("123")).server_used_tokens == 150
    assert model.calls == children.calls == 1
    assert await service.process_one() is None


async def test_missing_receipt_retains_its_reservation_and_does_not_retry(tmp_path: Path) -> None:
    service, repository, children, model = await make_safety(tmp_path)
    model.error = TimeoutError("Synthetic unknown receipt")
    original = target()
    await service.admit(original, analysis())
    unknown = await service.process_one()
    assert unknown and unknown.status == "unknown"
    assert (await service.budget("123")).server_reserved_tokens == 356
    await service.admit(target(), analysis(percent=60))
    assert await service.process_one() is None
    await service.admit(original.model_copy(update={"request_id": uuid4()}), analysis())
    assert model.calls == children.calls == 1
    assert not (await repository.questions("123")).questions


async def test_revoked_or_foreign_child_denies_generation_after_fresh_source(
    tmp_path: Path,
) -> None:
    service, _, children, model = await make_safety(tmp_path)
    await service.admit(target().model_copy(update={"child_id": 999}), analysis(999))
    denied = await service.process_one()
    assert denied and denied.error_code == "safety_child_not_authorized"
    assert model.calls == model.counts == 0 and children.calls == 1
    assert (await service.budget("123")).server_reserved_tokens == 0


async def test_single_model_decision_uses_existing_evidence_validation(tmp_path: Path) -> None:
    service, _, _, model = await make_safety(tmp_path)
    model.change = "invented_evidence"
    await service.admit(target(), analysis())
    done = await service.process_one()
    assert done and done.result and done.result.analysis
    assert done.result.analysis.status.value == "degraded"
    assert not done.result.analysis.findings
    assert model.calls == 1


@pytest.mark.parametrize("state", ["completed", "queued", "invalid_usage"])
async def test_real_sdk_child_transport_strict_schema_receipt_and_zero_retry(state: str) -> None:
    payload = model_payload()
    payload["output"][0]["content"][0]["text"] = "invalid JSON: metering must precede parsing"
    if state == "queued":
        payload["status"] = "queued"
        payload["usage"] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if state == "invalid_usage":
        payload["usage"]["input_tokens"] = "100"
    seen = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"input_tokens": 100} if request.url.path.endswith("/input_tokens") else payload,
        )

    prompt = ChatPrompt("Synthetic", (("user", "Synthetic facts"),))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        model = OpenAIChildSafetyModel(
            settings(), client=AsyncOpenAI(api_key="unit", max_retries=0, http_client=http)
        )
        assert await model.count_input(prompt) == 100
        if state == "completed":
            receipt = await model.respond(prompt, max_output_tokens=256)
            assert receipt.usage.total == 150 and receipt.answer and receipt.completed
        else:
            with pytest.raises(ValueError):
                await model.respond(prompt, max_output_tokens=256)
    counted, generated = seen
    assert counted == {key: generated[key] for key in counted}
    schema = generated["text"]["format"]["schema"]
    assert schema["required"] == list(schema["properties"])
    for definition in schema["$defs"].values():
        if "properties" in definition:
            assert set(definition["required"]) == set(definition["properties"])
            assert definition["additionalProperties"] is False
    assert generated["store"] is False and "tools" not in generated


async def test_cancelled_submitted_inference_keeps_its_hold(tmp_path: Path) -> None:
    safety, _, _, model = await make_safety(tmp_path)
    model.release = asyncio.Event()
    await safety.admit(target(), analysis())
    task = asyncio.create_task(safety.process_one())
    await model.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    budget = await safety.budget("123")
    assert budget.parent_blocked_by_unknown and budget.parent_reserved_tokens == 356
    assert await safety.process_one() is None
    assert model.calls == 1


async def test_unavailable_worker_preserves_exact_and_content_replay(tmp_path: Path) -> None:
    safety, _, children, model = await make_safety(tmp_path)
    original = target()
    await safety.admit(original, analysis())
    completed = await safety.process_one()
    safety.worker_available = False
    assert await safety.admit(original, analysis()) == completed
    assert (await safety.admit(target(), analysis())).job_id == completed.job_id
    with pytest.raises(ParentChatError, match="worker_unavailable"):
        await safety.admit(target(), analysis(percent=60))
    assert children.calls == model.calls == 1


async def test_server_attempt_ceiling_applies_to_zero_token_source_failures(tmp_path: Path) -> None:
    from app.services.child_safety_store import SqliteChildSafetyStore

    repository = SqliteChildSafetyStore(
        tmp_path / "global-attempts.db",
        daily_limit=2000,
        timezone="Asia/Tashkent",
        limits=limits(server_daily_attempts=1),
    )
    await repository.initialize()
    await repository.admit_analysis(target=target(), analysis=analysis(), now=NOW)
    await repository.admit_analysis(target=target("456"), analysis=analysis(457), now=NOW)
    job = await repository.claim_next(NOW)
    assert job
    await repository.fail_safety(job, "safety_source_or_context_unavailable", NOW)
    assert await repository.claim_next(NOW) is None
    assert (await repository.safety_budget("456", NOW)).server_used_tokens == 0
