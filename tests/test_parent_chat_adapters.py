import json
from copy import deepcopy
from dataclasses import replace
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI, InternalServerError
from pydantic import SecretStr

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ChatModelRejected, ChatPrompt, ParentChatError
from app.services.parent_chat_children import ManakidsChatChildrenSource
from app.services.parent_chat_model import OpenAIParentChatModel

PROMPT = ChatPrompt("Synthetic instructions", (("user", "Farzandimga qanday yordam beraman?"),))


@pytest.mark.parametrize("zone,valid", [("Asia/Tashkent", True), ("No/SuchZone", False)])
async def test_reminder_arguments_preserve_verified_usage_without_model_self_approval(
    zone: str, valid: bool
) -> None:
    from datetime import UTC, datetime

    from app.mana_ai.domain.parent_reminders import ReminderScope

    payload = model_payload()
    payload["output"][0]["content"][0]["text"] = json.dumps(
        {
            "body": "",
            "question": None,
            "notice_communicated": False,
            "reminder": {
                "content": "buy notebooks",
                "due_at": "2026-10-26T09:00:00+05:00",
                "timezone": zone,
            },
        }
    )
    prompt = replace(
        PROMPT,
        structured_reply=True,
        slot_reply=True,
        reminder_scope=ReminderScope(
            now=datetime(2026, 10, 25, tzinfo=UTC),
            default_timezone="Asia/Tashkent",
            timezone_basis="application_default_requires_confirmation",
            active=(),
            pending=None,
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        adapter = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="fake-key", max_retries=0, http_client=http)
        )
        receipt = await adapter.respond(prompt, max_output_tokens=512)
    assert receipt.usage.total == 150 and receipt.completed is valid
    assert (receipt.reminder_candidate is not None) is valid
    if not valid:
        assert receipt.answer is None and receipt.failure_code == "reply_schema_invalid"


@pytest.mark.parametrize("preserved", [False, True])
async def test_source_observation_date_is_required_after_verified_usage(preserved: bool) -> None:
    payload = model_payload()
    body = "Дата измерения 2026-10-24." if preserved else "Заряд указан в записи."
    payload["output"][0]["content"][0]["text"] = json.dumps(
        {
            "body": body,
            "question": None,
            "notice_communicated": False,
        },
        ensure_ascii=False,
    )
    prompt = replace(
        PROMPT, structured_reply=True, slot_reply=True, required_observation_dates=("2026-10-24",)
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        adapter = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="fake-key", max_retries=0, http_client=http)
        )
        result = await adapter.respond(prompt, max_output_tokens=512)
        assert result.usage.total == 150 and result.completed is preserved
        assert (result.answer is not None) is preserved


def model_payload() -> dict[str, Any]:
    return {
        "status": "completed",
        "model": "fake-model",
        "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Synthetic answer"}],
            }
        ],
    }


def settings() -> Settings:
    return Settings(
        _env_file=None, openai_api_key=SecretStr("unit-openai-key"), openai_model="fake-model"
    )


async def test_model_counts_exact_same_input_and_disables_storage_and_retries() -> None:
    requests: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        assert "parent_id" not in body
        return httpx.Response(
            200,
            json=(
                {"input_tokens": 100}
                if request.url.path.endswith("/input_tokens")
                else model_payload()
            ),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = AsyncOpenAI(api_key="unit-key", max_retries=0, http_client=http)
        model = OpenAIParentChatModel(settings(), client=client)
        assert await model.count_input(PROMPT) == 100
        receipt = await model.respond(PROMPT, max_output_tokens=512)
        assert receipt.usage.total == 150
        assert receipt.answer == "Synthetic answer"
    count, generation = requests
    assert count == {key: generation[key] for key in count}
    assert generation["store"] is False
    assert generation["max_output_tokens"] == 512
    assert "tools" not in generation and "previous_response_id" not in generation


@pytest.mark.parametrize("value", [True, "100", 1.5, -1, None])
async def test_count_is_strict_not_sdk_coerced(value: object) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"input_tokens": value}))
    ) as http:
        model = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="unit", http_client=http)
        )
        with pytest.raises(ValueError):
            await model.count_input(PROMPT)


@pytest.mark.parametrize("status", ["queued", "in_progress", None, "new-unknown-state"])
async def test_provisional_zero_usage_cannot_settle(status: str | None) -> None:
    payload = model_payload()
    payload["status"] = status
    payload["usage"] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        model = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="unit", http_client=http)
        )
        with pytest.raises(ValueError, match="terminal"):
            await model.respond(PROMPT, max_output_tokens=512)


@pytest.mark.parametrize(
    "bad_usage",
    [
        None,
        {"input_tokens": "100", "output_tokens": 50, "total_tokens": 150},
        {"input_tokens": True, "output_tokens": 50, "total_tokens": 51},
        {"input_tokens": 100, "output_tokens": 50, "total_tokens": 149},
    ],
)
async def test_invalid_raw_usage_never_becomes_a_known_receipt(bad_usage: object) -> None:
    payload = model_payload()
    payload["usage"] = bad_usage
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        model = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="unit", http_client=http)
        )
        with pytest.raises(ValueError, match="usage"):
            await model.respond(PROMPT, max_output_tokens=512)


@pytest.mark.parametrize(
    "change",
    [
        {"output": "invalid"},
        {"model": None},
        {"status": "incomplete"},
        {"output": [{"type": "function_call", "name": "do_something"}]},
    ],
)
async def test_known_usage_survives_invalid_answer(change: dict[str, object]) -> None:
    payload = model_payload() | change
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        model = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="unit", http_client=http)
        )
        receipt = await model.respond(PROMPT, max_output_tokens=512)
        assert receipt.usage.total == 150
        assert receipt.answer is None and receipt.completed is False


async def test_real_sdk_performs_no_transport_retry_on_failure() -> None:
    calls = 0

    def handle(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"error": {"message": "Synthetic failure"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        # Same SDK retry setting as the production adapter constructor.
        model = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="unit", http_client=http, max_retries=0)
        )
        with pytest.raises(InternalServerError):
            await model.respond(PROMPT, max_output_tokens=512)
    assert calls == 1


async def test_definitive_model_rejection_is_separate_from_unknown_usage() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(400, json={"error": {"message": "Synthetic rejection"}})
        )
    ) as http:
        model = OpenAIParentChatModel(
            settings(), client=AsyncOpenAI(api_key="unit", http_client=http)
        )
        with pytest.raises(ChatModelRejected):
            await model.respond(PROMPT, max_output_tokens=512)


def parent_payload() -> dict[str, Any]:
    return {
        "count": 1,
        "next": None,
        "results": [
            {
                "id": 123,
                "phone": "PRIVATE PHONE",
                "fullname": "PRIVATE PARENT",
                "children": [
                    {
                        "id": 456,
                        "fullname": "Synthetic child",
                        "age": 8,
                        "is_connected": True,
                        "avatar": "PRIVATE AVATAR",
                    }
                ],
            }
        ],
    }


async def test_child_source_filters_owner_and_minimizes_data() -> None:
    seen: list[httpx.Request] = []
    token = "unit-backend-token"

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json=({"access": token} if request.method == "POST" else parent_payload()),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        source = ManakidsChatChildrenSource(
            client=http, base_url="https://mana.test", username="unit", password="unit"
        )
        result = await source.read("123")
    assert len(seen) == 2
    assert dict(seen[-1].url.params) == {"parent_id": "123", "limit": "1", "offset": "0"}
    assert seen[-1].headers["authorization"] == f"Bearer {token}"
    assert result.children[0].age == 8
    assert "PRIVATE" not in result.model_dump_json()


@pytest.mark.parametrize("change", ["wrong_owner", "unfiltered", "empty", "duplicate", "truncated"])
async def test_child_source_refuses_foreign_unfiltered_or_ambiguous_families(change: str) -> None:
    payload = deepcopy(parent_payload())
    if change == "wrong_owner":
        payload["results"][0]["id"] = 789
    elif change == "unfiltered":
        payload["count"] = 2000
    elif change == "empty":
        payload = {"count": 0, "results": []}
    elif change == "duplicate":
        payload["results"][0]["children"] *= 2
    else:
        payload["results"][0]["children_count"] = 2
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=({"access": "unit"} if request.method == "POST" else payload)
            )
        )
    ) as http:
        source = ManakidsChatChildrenSource(
            client=http, base_url="https://mana.test", username="unit", password="unit"
        )
        with pytest.raises(ParentChatError):
            await source.read("123")


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
async def test_source_never_retries_or_follows_pagination_or_redirects(status: int) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.method == "POST":
            return httpx.Response(200, json={"access": "unit"})
        return httpx.Response(status, headers={"Location": "https://other.test"}, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        source = ManakidsChatChildrenSource(
            client=http, base_url="https://mana.test", username="unit", password="unit"
        )
        with pytest.raises(ParentChatError):
            await source.read("123")
    assert calls == 2
