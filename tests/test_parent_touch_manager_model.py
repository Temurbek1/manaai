"""Actual pinned SDK transport with fictional HTTP responses, never live inference."""

import json
from dataclasses import replace
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from app.mana_ai.domain.parent_touch_manager import CHILD_REVIEW_TOOL, ParentTouchManagerScope
from app.services.parent_chat_model import OpenAIParentChatModel
from tests.test_parent_chat_adapters import PROMPT, model_payload, settings


def manager_prompt() -> Any:
    return replace(
        PROMPT,
        structured_reply=True,
        response_language="ru",
        manager_scope=ParentTouchManagerScope(
            language="ru", upsell_enabled=True, reminders_enabled=True
        ),
    )


def native_payload() -> dict[str, Any]:
    payload = model_payload()
    payload["output"] = [
        {"type": "reasoning", "summary": []},
        {
            "type": "function_call",
            "name": CHILD_REVIEW_TOOL,
            "arguments": "{}",
            "call_id": "call_original",
            "status": "completed",
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "output_text", "text": "Not JSON; must not be parsed or published."}
            ],
        },
    ]
    return payload


async def test_native_handoff_precedes_text_with_the_same_count_contract() -> None:
    requests: list[dict[str, Any]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={"input_tokens": 100}
            if request.url.path.endswith("/input_tokens")
            else native_payload(),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        adapter = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="fake-key", max_retries=0, http_client=http)
        )
        prompt = manager_prompt()
        assert await adapter.count_input(prompt) == 100
        result = await adapter.respond(prompt, max_output_tokens=512)
    assert result.completed and result.manager_handoff
    assert result.manager_handoff.target == "child_safety" and result.answer is None
    assert result.usage.total == 150
    assert requests[0]["tools"] == requests[1]["tools"]
    assert requests[0]["text"] == requests[1]["text"]
    assert requests[1]["store"] is False
    assert requests[0]["parallel_tool_calls"] is requests[1]["parallel_tool_calls"] is False
    assert len(requests[0]["tools"]) == 3
    for tool in requests[0]["tools"]:
        assert tool["strict"] and tool["parameters"] == {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        }


@pytest.mark.parametrize(
    "change",
    [
        "name",
        "arguments",
        "nonobject",
        "call_id",
        "two_calls",
        "unfinished",
        "extra_output",
        "disabled",
        "stage",
    ],
)
async def test_unadmitted_native_decision_retains_usage_without_a_handoff(change: str) -> None:
    payload = native_payload()
    prompt = manager_prompt()
    call = payload["output"][1]
    if change == "name":
        call["name"] = "arbitrary_sql"
    if change == "arguments":
        call["arguments"] = '{"parent_id":"another-family"}'
    if change == "nonobject":
        call["arguments"] = "[]"
    if change == "call_id":
        call["call_id"] = "bad\ncall"
    if change == "two_calls":
        payload["output"].append(dict(call))
    if change == "unfinished":
        call["status"] = "in_progress"
    if change == "extra_output":
        payload["output"].append({"type": "computer_call", "id": "bad"})
    if change == "disabled":
        prompt = replace(prompt, manager_scope=ParentTouchManagerScope(language="ru"))
        call["name"] = "request_tariff_help"
    if change == "stage":
        prompt = replace(
            prompt, manager_scope=ParentTouchManagerScope(language="ru", stage="upsell")
        )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        adapter = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="fake-key", max_retries=0, http_client=http)
        )
        result = await adapter.respond(prompt, max_output_tokens=512)
    assert not result.completed and result.manager_handoff is None
    assert result.usage.total == 150 and result.answer is None


@pytest.mark.parametrize("status", ["queued", "in_progress"])
async def test_pending_zero_usage_never_dispatches_or_releases_a_router_hold(status: str) -> None:
    payload = native_payload()
    payload["status"] = status
    payload["usage"] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        adapter = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="fake-key", max_retries=0, http_client=http)
        )
        with pytest.raises(ValueError):
            await adapter.respond(manager_prompt(), max_output_tokens=512)


async def test_ordinary_manager_json_has_no_specialist_or_action_fields() -> None:
    payload = model_payload()
    payload["output"][0]["content"][0]["text"] = json.dumps(
        {"body": "Здравствуйте. Помогу с MANA."}
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        adapter = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="fake-key", max_retries=0, http_client=http)
        )
        prompt = manager_prompt()
        schema: Any = adapter._text(prompt)["format"]
        assert schema["schema"]["required"] == ["body"]
        result = await adapter.respond(prompt, max_output_tokens=512)
    assert result.completed and result.answer == "Здравствуйте. Помогу с MANA."
    assert result.manager_handoff is None and result.usage.total == 150
