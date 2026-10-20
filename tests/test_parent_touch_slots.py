import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI

from app.mana_ai.application.chat_ports import ChatPrompt, ParentChatError
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.family_agents import ParentTouchRequest
from app.services.parent_chat_model import OpenAIParentChatModel
from tests.test_child_safety_store import store
from tests.test_family_agent_queue import intent
from tests.test_parent_chat import NOW, Children, message
from tests.test_parent_chat_adapters import model_payload, settings
from tests.test_parent_touch_evidence import TouchModel, completed_report


@pytest.mark.parametrize("selection", ["none", "question", "notice", "both"])
async def test_slot_sdk_binds_only_runtime_selected_ids_and_counts_the_same_schema(
    tmp_path: Path, selection: str
) -> None:
    repository = await store(tmp_path / "slots.db")
    if selection in {"question", "both"}:
        await repository.enqueue(intent(), NOW)
    if selection in {"notice", "both"}:
        await completed_report(repository)
    turn = await repository.admit(message(), NOW)
    context = await repository.evidence_for_turn("123", turn.turn_id, (124,))
    assert context
    question = await repository.question_for_turn("123", turn.turn_id)
    prompt = ChatPrompt(
        "Synthetic",
        (("user", "Salom"),),
        structured_reply=True,
        slot_reply=True,
        question=question,
        notice=context.notice,
    )
    answer = {
        "body": f"{NOW.date().isoformat()}: Tushunarli." if context.notice else "Tushunarli.",
        "question": "Farzandingiz soat nechada uxlaydi?" if question else None,
        "notice_communicated": context.notice is not None,
    }
    sent: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        sent.append(payload)
        response = model_payload()
        response["output"][0]["content"][0]["text"] = json.dumps(answer)
        return httpx.Response(
            200,
            json={"input_tokens": 100} if request.url.path.endswith("/input_tokens") else response,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        adapter = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="unit", max_retries=0, http_client=http)
        )
        assert await adapter.count_input(prompt) == 100
        receipt = await adapter.respond(prompt, max_output_tokens=512)
    assert receipt.completed and receipt.usage.total == 150
    assert receipt.question_id == (question.question_id if question else None)
    assert receipt.notice_id == (context.notice.notice_id if context.notice else None)
    count, generation = sent
    assert count == {key: generation[key] for key in count}
    assert "question_id" not in generation["text"]["format"]["schema"]["properties"]
    if question:
        assert str(question.question_id) not in json.dumps(generation)
    if context.notice:
        assert str(context.notice.notice_id) not in json.dumps(generation)


@pytest.mark.parametrize(
    "change",
    [
        {"notice_communicated": True},
        {"notice_communicated": "false"},
        {"question": "An unadmitted question?"},
        {"question_id": str(uuid4())},
        {"notice_id": str(uuid4())},
        {"body": "What was the question_id"},
        {"body": "notice_communicated=true"},
        {"body": "Use reply_to_question_id"},
        {"body": "Two? Questions?"},
    ],
)
async def test_unadmitted_or_invalid_slot_outputs_keep_raw_usage(change: dict[str, object]) -> None:
    payload = model_payload()
    answer = {"body": "Понятно.", "question": None, "notice_communicated": False} | change
    payload["output"][0]["content"][0]["text"] = json.dumps(answer)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        adapter = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="unit", max_retries=0, http_client=http)
        )
        receipt = await adapter.respond(
            ChatPrompt("Synthetic", (), structured_reply=True, slot_reply=True),
            max_output_tokens=512,
        )
    assert receipt.usage.total == 150 and not receipt.completed
    assert receipt.failure_code == "reply_schema_invalid"
    assert receipt.notice_id is None
    assert receipt.question_id is None


async def test_compact_prompt_preserves_facts_dates_qualifications_and_hidden_bindings(
    tmp_path: Path,
) -> None:
    repository, model, children = await store(tmp_path / "context.db"), TouchModel(), Children()
    requested = await repository.enqueue(intent(), NOW)
    await completed_report(repository)
    touch = ParentTouchService(
        store=repository,
        model=model,
        children=children,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    response = await touch.send_touch(ParentTouchRequest.model_validate(message().model_dump()))
    assert response.asked_question and response.delivered_notice
    prompt = model.prompts[-1]
    assert prompt.slot_reply and prompt.minimum_output_tokens == 256
    assert "Address the adult parent, never the child" in prompt.instructions
    data = json.loads(prompt.messages[0][1])
    report = data["assessments"]["saved_assessments"][0]
    assert report["data_quality_notes"] == [
        "Only supplied observations; not current full coverage."
    ]
    assert report["signal_first_observed_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert data["admitted_question"]["question"] == requested.question.question
    assert data["admitted_question"]["reason"] == requested.question.reason
    assert data["admitted_question"]["observed_at"] == NOW.isoformat()
    assert str(requested.question.question_id) not in prompt.messages[0][1]
    assert str(response.delivered_notice.notice_id) not in prompt.messages[0][1]


async def test_notice_output_floor_refuses_before_generation_without_releasing_other_holds(
    tmp_path: Path,
) -> None:
    repository, model, children = await store(tmp_path / "floor.db"), TouchModel(), Children()
    touch = ParentTouchService(
        store=repository,
        model=model,
        children=children,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    await touch.send(message())
    await completed_report(repository)
    # Exactly 250 tokens remain, below the selected notice's minimum output
    # even with zero input. Known pre-dispatch refusal must spend no model tokens.
    with repository._transaction() as connection:
        connection.execute("UPDATE parent_chat_quota SET used=1750 WHERE parent_id='123'")
    request = await repository.next_delivery(NOW)
    assert request
    counts = model.calls, model.counts
    with pytest.raises(ParentChatError, match="daily_token_budget_exceeded"):
        await touch.deliver(request)
    assert model.calls == counts[0] and model.counts > counts[1]
    assert (await repository.quota("123", NOW)).used_tokens == 1750
    assert (await repository.quota("123", NOW)).reserved_tokens == 0
    assert (await repository.safety_budget("123", NOW)).parent_used_tokens == 150
    assert await repository.next_delivery(NOW) is None
    with pytest.raises(ParentChatError, match="daily_token_budget_exceeded"):
        await touch.deliver(request)
    assert model.calls == counts[0]


async def test_revoked_assistant_only_delivery_never_generates_an_empty_message(
    tmp_path: Path,
) -> None:
    repository, model = await store(tmp_path / "revoked.db"), TouchModel()

    class Revocable(Children):
        revoked = False

        async def read(self, parent_id: str) -> ParentChildContext:
            context = await super().read(parent_id)
            return context.model_copy(update={"children": []}) if self.revoked else context

    children = Revocable()
    touch = ParentTouchService(
        store=repository,
        model=model,
        children=children,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    await touch.send(message())
    await completed_report(repository)
    request = await repository.next_delivery(NOW)
    assert request
    children.revoked = True
    with pytest.raises(ParentChatError, match="no_authorized_communication"):
        await touch.deliver(request)
    assert model.calls == 1
    assert len((await touch.history("123", before=None, limit=30)).messages) == 2


@pytest.mark.parametrize("dates_present", [False, True])
async def test_notice_preserves_actual_observation_dates_not_processing_time(
    tmp_path: Path,
    dates_present: bool,
) -> None:
    repository = await store(tmp_path / "dated-notice.db")
    await completed_report(repository)
    turn = await repository.admit(message(), NOW)
    context = await repository.evidence_for_turn("123", turn.turn_id, (124,))
    assert context and context.notice
    start, end = NOW - timedelta(days=3), NOW - timedelta(days=2)
    notice = context.notice.model_copy(
        update={
            "assessment": context.notice.assessment.model_copy(
                update={
                    "signal_first_observed_at": start,
                    "signal_last_observed_at": end,
                }
            )
        }
    )
    payload = model_payload()
    payload["output"][0]["content"][0]["text"] = json.dumps(
        {
            "body": f"Запись за {start.date()}–{end.date()}: ограниченные данные."
            if dates_present
            else f"Данные собраны {NOW.date()}.",
            "question": None,
            "notice_communicated": True,
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        model = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="unit", max_retries=0, http_client=http)
        )
        receipt = await model.respond(
            ChatPrompt(
                "Synthetic",
                (),
                structured_reply=True,
                slot_reply=True,
                notice=notice,
            ),
            max_output_tokens=512,
        )
    assert receipt.usage.total == 150 and receipt.completed == dates_present
    assert receipt.notice_id == (notice.notice_id if dates_present else None)
