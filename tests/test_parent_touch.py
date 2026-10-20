import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.family_agents import ParentTouchRequest
from app.services.parent_chat_model import OpenAIParentChatModel
from tests.test_family_agent_queue import intent, store
from tests.test_parent_chat import NOW, Children, Model, message
from tests.test_parent_chat_adapters import model_payload, settings


class TouchModel(Model):
    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        raw = await super().respond(prompt, max_output_tokens=max_output_tokens)
        return replace(
            raw,
            answer="Понятно.\n\nВо сколько ребёнок обычно ложится спать?",
            question_id=prompt.question.question_id if prompt.question else None,
        )


async def test_two_questions_form_a_single_ordered_parent_conversation_and_replay_is_read_only(
    tmp_path: Path,
) -> None:
    repository = await store(tmp_path / "touch.db")
    first = await repository.enqueue(intent(), NOW)
    second = await repository.enqueue(intent("school.schedule"), NOW)
    await repository.enqueue(intent(agent="future-specialist"), NOW)
    model, children = TouchModel(), Children()
    service = ParentTouchService(
        store=repository,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    original = message(text="Что вам нужно уточнить?")
    answer = await service.send(original)
    assert model.prompts[0].structured_reply and model.prompts[
        0
    ].question == first.question.model_copy(update={"status": "offered", "offered_turn_id": 1})
    first_prompt = model.prompts[0].messages[0][1]
    assert '"child_id"' not in first_prompt and '"parent_id"' not in first_prompt
    assert (
        "Synthetic child" in first_prompt and first.question.observed_at.isoformat() in first_prompt
    )
    assert await service.send(original) == answer and model.calls == children.calls == 1
    state = (await repository.questions("123")).questions
    assert [q.status for q in state] == ["awaiting_reply", "queued"]
    reply = ParentTouchRequest(
        parent_id="123",
        request_id=uuid4(),
        message="Обычно в девять вечера.",
        reply_to_question_id=first.question.question_id,
    )
    result = await service.send(reply)
    assert await service.send(reply) == result
    assert model.calls == children.calls == 2
    assert (
        model.prompts[-1].question
        and model.prompts[-1].question.question_id == second.question.question_id
    )
    state = (await repository.questions("123")).questions
    assert [q.status for q in state] == ["answered", "awaiting_reply"]
    history = await service.history("123", before=None, limit=30)
    assert [m.role for m in history.messages] == ["user", "assistant", "user", "assistant"]
    assert history.quota.used_tokens == 300
    assert (await service.history("456", before=None, limit=30)).messages == []


async def test_revoked_child_membership_prevents_question_inference(tmp_path: Path) -> None:
    repository = await store(tmp_path / "revoked.db")
    await repository.enqueue(intent(child=999), NOW)
    model, children = TouchModel(), Children()
    service = ParentTouchService(
        store=repository,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    with pytest.raises(ParentChatError, match="question_child_not_authorized"):
        await service.send(message())
    assert model.calls == model.counts == 0 and children.calls == 1
    assert (await repository.quota("123", NOW)).used_tokens == 0


@pytest.mark.parametrize(
    "change", [None, "foreign", "two_questions", "invalid_json", "body_question"]
)
async def test_strict_touch_schema_and_usage_survive_invalid_decisions(change: str | None) -> None:
    from app.mana_ai.domain.family_agents import FamilyQuestion

    source = intent()
    question = FamilyQuestion(
        question_id=uuid4(),
        parent_id=source.parent_id,
        child_id=source.child_id,
        information_key=source.information_key,
        question=source.question,
        reason=source.reason,
        priority=1,
        status="offered",
        observed_at=NOW,
        expires_at=source.expires_at,
        created_at=NOW,
        offered_turn_id=1,
    )
    reply: dict[str, Any] = {
        "body": "Tushunarli.",
        "question": "Farzandingiz odatda soat nechada uxlaydi?",
        "question_id": str(question.question_id),
    }
    if change == "foreign":
        reply["question_id"] = str(uuid4())
    if change == "two_questions":
        reply["question"] = "Qachon? Nega?"
    if change == "body_question":
        reply["body"] = "Yana savol?"
    payload = model_payload()
    payload["output"][0]["content"][0]["text"] = (
        "not JSON" if change == "invalid_json" else json.dumps(reply)
    )
    requests: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"input_tokens": 100} if request.url.path.endswith("/input_tokens") else payload,
        )

    prompt = ChatPrompt(
        "Synthetic host instructions",
        (("user", "Salom"),),
        structured_reply=True,
        question=question,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        model = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="unit", max_retries=0, http_client=http)
        )
        assert await model.count_input(prompt) == 100
        receipt = await model.respond(prompt, max_output_tokens=512)
    assert receipt.usage.total == 150 and receipt.completed is (change is None)
    assert receipt.question_id == (question.question_id if change is None else None)
    assert receipt.answer == (
        "Tushunarli.\n\nFarzandingiz odatda soat nechada uxlaydi?" if change is None else None
    )
    counted, generated = requests
    assert counted == {key: generated[key] for key in counted}
    assert generated["text"]["format"]["type"] == "json_schema"
    assert generated["text"]["format"]["strict"] is True
    assert "tools" not in generated and generated["store"] is False
