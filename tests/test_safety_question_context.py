import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ChatPrompt
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.child_safety import SafetyContextSnapshot
from app.mana_ai.domain.family_agents import ParentTouchRequest
from app.services.child_safety_model import OpenAIChildSafetyModel
from app.services.child_safety_prompts import ChildSafetyPromptBuilder
from app.services.parent_chat_model import OpenAIParentChatModel
from tests.test_child_safety_store import store
from tests.test_family_agent_queue import intent
from tests.test_parent_chat import NOW, Children, message
from tests.test_parent_chat_adapters import settings
from tests.test_parent_touch_evidence import TouchModel


async def test_new_snapshot_freezes_pending_needs_and_exact_explicit_parent_answers(
    tmp_path: Path,
) -> None:
    repository, children = await store(tmp_path / "questions.db"), Children()
    first = await repository.enqueue(intent("sleep.bedtime"), NOW)
    await repository.enqueue(intent("sleep.wake_time"), NOW)
    await repository.enqueue(intent(parent="456", child=457), NOW)
    touch = ParentTouchService(
        store=repository,
        children=children,
        model=TouchModel(),
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    await touch.send(message())
    assert await repository.materialize_parent_event(NOW)
    job = await repository.claim_next(NOW)
    assert job and job.context.version == 2
    assert [(need.information_key, need.status) for need in job.context.conversation_needs] == [
        ("sleep.bedtime", "offered"),
        ("sleep.wake_time", "queued"),
    ]
    assert all(need.child_id == 124 for need in job.context.conversation_needs)
    await repository.fail_safety(job, "synthetic_context_fixture", NOW)
    reply = ParentTouchRequest(
        parent_id="123",
        request_id=uuid4(),
        message="Обычно в 22:00.",
        reply_to_question_id=first.question.question_id,
    )
    await touch.send_touch(reply)
    assert await repository.materialize_parent_event(NOW)
    next_job = await repository.claim_next(NOW)
    assert next_job
    needs = next_job.context.conversation_needs
    assert needs[0].status == "answered" and needs[0].answer
    assert needs[0].answer.content == reply.message
    assert needs[1].status == "offered" and needs[1].answer is None
    prompt = ChildSafetyPromptBuilder().build(next_job, await children.read("123"), [])
    payload = json.loads(prompt.input.messages[0][1])
    assert payload["conversation_needs_scope"] == "authorized_children_pending_and_recent_answers"
    assert payload["conversation_needs"][0]["answer"]["content"] == reply.message
    assert "child_id" not in payload["conversation_needs"][0]
    assert "question_id" not in payload["conversation_needs"][0]
    assert payload["conversation_needs"][0]["child_alias"] == "child-1"
    assert job.context.conversation_needs[0].status == "offered"  # No old snapshot upgrade.
    assert prompt.input.safety_parent_review
    historical = replace(job, context=job.context.model_copy(update={"typed_parent_review": False}))
    assert (
        not ChildSafetyPromptBuilder()
        .build(historical, await children.read("123"), [])
        .input.safety_parent_review
    )


async def test_v1_snapshot_remains_v1_and_revoked_needs_do_not_reach_the_model(
    tmp_path: Path,
) -> None:
    repository, children = await store(tmp_path / "legacy.db"), Children()
    await repository.enqueue(intent(), NOW)
    await repository.admit(message(), NOW)
    assert await repository.materialize_parent_event(NOW)
    job = await repository.claim_next(NOW)
    assert job
    old = job.context.model_copy(
        update={"version": 1, "conversation_needs": [], "typed_parent_review": False}
    )
    assert SafetyContextSnapshot.model_validate_json(old.model_dump_json()).version == 1
    with pytest.raises(ValidationError, match="Historical v1"):
        SafetyContextSnapshot.model_validate(job.context.model_dump() | {"version": 1})
    context = (await children.read("123")).model_copy(update={"children": []})
    payload = json.loads(ChildSafetyPromptBuilder().build(job, context, []).input.messages[0][1])
    assert payload["conversation_needs"] == []


async def test_review_schema_has_no_sensor_analysis_and_cannot_be_used_by_the_speaker() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ) as http:
        client = AsyncOpenAI(api_key="unit", max_retries=0, http_client=http)
        model = OpenAIChildSafetyModel(settings(), client=client)
        prompt = ChatPrompt("Synthetic", (), safety_parent_review=True)
        format_spec = model._text(prompt)["format"]
        assert format_spec["type"] == "json_schema"
        schema = cast(dict[str, Any], format_spec["schema"])
        assert schema["properties"]["analysis"]["type"] == "null"
        assert schema["properties"]["followup_summary"]["type"] == "string"
        assert "ModelAnalysis" not in schema.get("$defs", {})
        assert set(schema["required"]) == {"analysis", "followup_summary", "question"}
        speaker = OpenAIParentChatModel(settings(), client=client)
        with pytest.raises(ValueError, match="specialist review protocol"):
            speaker._text(prompt)
