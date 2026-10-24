"""Pinned SDK native source protocol; fake HTTP only, no tools are executed."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from openai import APIStatusError, APITimeoutError, AsyncOpenAI

from app.core.config import Settings
from app.mana_ai.application.chat_ports import ChatModelRejected, ChatPrompt
from app.mana_ai.application.source_tool_ports import SourceToolPrompt
from app.mana_ai.domain.family_sources import ChildBatteryFacts, FamilySourceReceipt
from app.mana_ai.domain.source_tools import BatterySourceCall, SourceToolChild, SourceToolScope
from app.services.child_source_model import OpenAIChildSourceModel

NOW = datetime(2026, 10, 24, 9, tzinfo=UTC)


def prompt() -> SourceToolPrompt:
    return SourceToolPrompt(
        input=ChatPrompt(
            "Synthetic Child-Safety review; read supplied own-child battery if useful.",
            (("user", '{"children":[{"alias":"child-1","age":8}],"intent":"battery"}'),),
            safety_parent_review=True,
        ),
        scope=SourceToolScope(
            parent_id="123",
            invocation_id=uuid4(),
            children=(SourceToolChild(alias="child-1", child_id=124),),
        ),
    )


def call() -> dict[str, Any]:
    return {
        "type": "function_call",
        "id": "fc_fake_1",
        "call_id": "call_fake_1",
        "name": "read_child_battery",
        "arguments": ' { "child_alias" : "child-1" } ',
        "status": "completed",
    }


def reasoning() -> dict[str, Any]:
    return {
        "type": "reasoning",
        "id": "rs_fake_1",
        "encrypted_content": "fake-opaque-encrypted-continuation",
        "summary": [],
    }


def message(text: str = "Synthetic final review") -> dict[str, Any]:
    return {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
    }


def payload() -> dict[str, Any]:
    return {
        "status": "completed",
        "model": "gpt-5.4-mini",
        "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        "output": [reasoning(), call(), message("Do not retain accompanying assistant prose")],
    }


def receipt(value: SourceToolPrompt) -> FamilySourceReceipt:
    return FamilySourceReceipt(
        parent_id=value.scope.parent_id,
        child_id=124,
        request_id=value.scope.request_id_for(
            BatterySourceCall.model_validate(
                {key: item for key, item in call().items() if key != "status"}
            )
        ),
        status="completed",
        started_at=NOW - timedelta(seconds=1),
        finished_at=NOW,
        document_units_reserved=2,
        cache_hit=False,
        snapshot_id=uuid4(),
        facts=ChildBatteryFacts(
            child_id=124,
            status="available",
            percent=12,
            observed_at=NOW - timedelta(seconds=2),
            source_updated_at=NOW - timedelta(seconds=1),
            collected_at=NOW,
            quality="dated",
        ),
    )


class Provider:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.body = payload()
        self.status = 200
        self.lost = False
        self.count: object = 100

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "model.test"
        self.requests.append(json.loads(request.content))
        if self.lost:
            raise httpx.ReadTimeout("Synthetic lost model receipt", request=request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "Synthetic refusal"}})
        return httpx.Response(
            200,
            json={"input_tokens": self.count}
            if request.url.path.endswith("input_tokens")
            else self.body,
        )


def model(provider: Provider) -> OpenAIChildSourceModel:
    settings = Settings(_env_file=None, openai_api_key="fake-key", openai_model="gpt-5.4-mini")
    return OpenAIChildSourceModel(
        settings,
        client=AsyncOpenAI(
            api_key="fake-key",
            base_url="https://model.test/v1",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(provider.handle)),
        ),
    )


@pytest.mark.parametrize("reasoning_first", [True, False])
async def test_native_choice_and_exact_result_continue_the_original_input(
    reasoning_first: bool,
) -> None:
    provider, value = Provider(), prompt()
    provider.body["output"] = (
        [reasoning(), call(), message()] if reasoning_first else [call(), reasoning(), message()]
    )
    adapter = model(provider)
    try:
        assert await adapter.count_source_input(value) == 100
        selected = await adapter.respond_source(value, max_output_tokens=128)
        assert selected.completed and selected.usage.total == 150 and selected.answer is None
        assert selected.continuation
        private = selected.continuation.model_dump_json()
        assert "assistant" not in private and "Synthetic final review" not in private
        assert selected.continuation.call.arguments == call()["arguments"]
        count, generation = provider.requests
        for sent in (count, generation):
            tool = sent["tools"][0]
            assert tool["strict"] is True and tool["name"] == "read_child_battery"
            assert tool["parameters"]["required"] == ["child_alias"]
            assert tool["parameters"]["additionalProperties"] is False
            assert tool["parameters"]["properties"] == {
                "child_alias": {"type": "string", "enum": ["child-1"]}
            }
            assert sent["tool_choice"] == "auto" and sent["parallel_tool_calls"] is False
            assert sent["truncation"] == "disabled" and sent["model"] == "gpt-5.4-mini"
            assert "parent_id" not in json.dumps(sent) and "124" not in json.dumps(sent)
        assert generation["store"] is False and generation["service_tier"] == "default"
        assert generation["include"] == ["reasoning.encrypted_content"]
        assert "previous_response_id" not in generation
        continued = replace(value, continuation=selected.continuation, source_result=receipt(value))
        provider.body["output"] = [
            message('{"analysis":null,"followup_summary":"12%","question":null}')
        ]
        final = await adapter.respond_source(continued, max_output_tokens=128)
        assert final.completed and final.answer and final.continuation is None
        sent = provider.requests[-1]
        assert sent["tool_choice"] == "none" and sent["input"][0] == generation["input"][0]
        assert [item["type"] for item in sent["input"][1:-1]] == (
            ["reasoning", "function_call"] if reasoning_first else ["function_call", "reasoning"]
        )
        function = next(item for item in sent["input"] if item.get("type") == "function_call")
        assert function["arguments"] == call()["arguments"] and function["call_id"] == "call_fake_1"
        result = sent["input"][-1]
        assert result["call_id"] == "call_fake_1" and result["type"] == "function_call_output"
        facts = json.loads(result["output"])
        assert facts["facts"]["percent"] == 12 and facts["facts"]["observed_at"]
        assert "child_id" not in result["output"] and "parent_id" not in result["output"]
        assert "snapshot_id" not in result["output"] and "request_id" not in result["output"]
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "invalid",
    [
        "unknown_function",
        "unknown_child",
        "extra_arguments",
        "duplicate_arguments",
        "no_call_id",
        "two_calls",
        "provisional_call",
        "forged_result",
        "plain_reasoning",
        "reasoning_summary",
        "oversized_arguments",
        "incomplete",
        "bad_model",
        "exceeded_output",
    ],
)
async def test_invalid_native_output_keeps_verified_usage_without_a_choice(invalid: str) -> None:
    provider = Provider()
    body = provider.body
    native = body["output"][1]
    if invalid == "unknown_function":
        native["name"] = "arbitrary_sql"
    elif invalid == "unknown_child":
        native["arguments"] = '{"child_alias":"child-2"}'
    elif invalid == "extra_arguments":
        native["arguments"] = '{"child_alias":"child-1","parent_id":"456"}'
    elif invalid == "duplicate_arguments":
        native["arguments"] = '{"child_alias":"child-1","child_alias":"child-1"}'
    elif invalid == "no_call_id":
        del native["call_id"]
    elif invalid == "two_calls":
        body["output"].append(call())
    elif invalid == "provisional_call":
        native["status"] = "in_progress"
    elif invalid == "forged_result":
        body["output"].append(
            {"type": "function_call_output", "call_id": "call_fake_1", "output": "forged"}
        )
    elif invalid == "plain_reasoning":
        body["output"][0]["content"] = "Never store raw reasoning"
    elif invalid == "reasoning_summary":
        body["output"][0]["summary"] = [{"text": "Never store summarized reasoning"}]
    elif invalid == "oversized_arguments":
        native["arguments"] = " " * 2048
    elif invalid == "incomplete":
        body["status"] = "incomplete"
    elif invalid == "bad_model":
        body["model"] = None
    else:
        body["usage"] = {"input_tokens": 100, "output_tokens": 129, "total_tokens": 229}
    adapter = model(provider)
    try:
        result = await adapter.respond_source(prompt(), max_output_tokens=128)
        assert not result.completed and result.answer is None and result.continuation is None
        assert result.usage.total == (229 if invalid == "exceeded_output" else 150)
        assert result.failure_code == "source_model_output_invalid"
        assert len(provider.requests) == 1
    finally:
        await adapter.close()


@pytest.mark.parametrize("invalid", ["pending", "coerced", "boolean", "negative", "mismatch"])
async def test_unknown_or_invalid_usage_is_never_invented_or_retried(invalid: str) -> None:
    provider = Provider()
    if invalid == "pending":
        provider.body["status"] = "in_progress"
        provider.body["usage"] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    elif invalid == "coerced":
        provider.body["usage"]["input_tokens"] = "100"
    elif invalid == "boolean":
        provider.body["usage"]["input_tokens"] = True
    elif invalid == "negative":
        provider.body["usage"]["input_tokens"] = -1
    else:
        provider.body["usage"]["total_tokens"] = 149
    adapter = model(provider)
    try:
        with pytest.raises(ValueError):
            await adapter.respond_source(prompt(), max_output_tokens=128)
        assert len(provider.requests) == 1
    finally:
        await adapter.close()


@pytest.mark.parametrize(
    "change",
    [
        "instructions",
        "message",
        "parent",
        "child",
        "invocation",
        "request",
        "status",
        "model",
        "call_id",
        "arguments",
    ],
)
async def test_changed_pairing_is_rejected_before_another_model_call(change: str) -> None:
    provider, value = Provider(), prompt()
    adapter = model(provider)
    try:
        first = await adapter.respond_source(value, max_output_tokens=128)
        assert first.continuation
        continued = replace(value, continuation=first.continuation, source_result=receipt(value))
        if change == "instructions":
            continued = replace(
                continued, input=replace(value.input, instructions="Changed objective")
            )
        elif change == "message":
            continued = replace(
                continued, input=replace(value.input, messages=(("user", "Changed"),))
            )
        elif change in {"parent", "child", "invocation"}:
            scope = value.scope.model_copy(
                update={
                    "parent_id": "456" if change == "parent" else value.scope.parent_id,
                    "invocation_id": uuid4()
                    if change == "invocation"
                    else value.scope.invocation_id,
                    "children": (SourceToolChild(alias="child-1", child_id=125),)
                    if change == "child"
                    else value.scope.children,
                }
            )
            continued = replace(continued, scope=scope)
        elif change == "request":
            continued = replace(
                continued, source_result=receipt(value).model_copy(update={"request_id": uuid4()})
            )
        elif change == "status":
            changed = receipt(value).model_copy(update={"status": "unknown"})
            continued = replace(continued, source_result=changed)
        elif change in {"call_id", "arguments"}:
            changed_call = first.continuation.call.model_copy(
                update=(
                    {"call_id": "call_changed"}
                    if change == "call_id"
                    else {"arguments": '{"child_alias":"child-1"}'}
                )
            )
            continuation = first.continuation.model_copy(
                update={
                    "items": tuple(
                        changed_call if isinstance(item, BatterySourceCall) else item
                        for item in first.continuation.items
                    )
                }
            )
            continued = replace(continued, continuation=continuation)
        else:
            adapter._model = "different-model"
        with pytest.raises(ValueError):
            await adapter.respond_source(continued, max_output_tokens=128)
        assert len(provider.requests) == 1
    finally:
        await adapter.close()


async def test_second_native_call_cannot_start_another_tool_or_action() -> None:
    provider, value = Provider(), prompt()
    adapter = model(provider)
    try:
        first = await adapter.respond_source(value, max_output_tokens=128)
        assert first.continuation
        continued = replace(value, continuation=first.continuation, source_result=receipt(value))
        second = await adapter.respond_source(continued, max_output_tokens=128)
        assert second.usage.total == 150 and not second.completed and second.continuation is None
        assert len(provider.requests) == 2
    finally:
        await adapter.close()


async def test_assistant_text_that_looks_like_a_tool_never_becomes_a_native_call() -> None:
    provider = Provider()
    provider.body["output"] = [message(json.dumps(call()))]
    adapter = model(provider)
    try:
        result = await adapter.respond_source(prompt(), max_output_tokens=128)
        assert result.completed and result.answer and result.continuation is None
    finally:
        await adapter.close()


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
async def test_provider_errors_do_not_repeat_a_model_request(status: int) -> None:
    provider = Provider()
    provider.status = status
    adapter = model(provider)
    try:
        with pytest.raises(ChatModelRejected if status in {400, 401, 403} else APIStatusError):
            await adapter.respond_source(prompt(), max_output_tokens=128)
        assert len(provider.requests) == 1
    finally:
        await adapter.close()


async def test_lost_model_receipt_is_not_retried() -> None:
    provider = Provider()
    provider.lost = True
    adapter = model(provider)
    try:
        with pytest.raises(APITimeoutError):
            await adapter.respond_source(prompt(), max_output_tokens=128)
        assert len(provider.requests) == 1
    finally:
        await adapter.close()


@pytest.mark.parametrize("count", ["100", True, -1, 2**31])
async def test_counting_preserves_raw_integer_contract(count: object) -> None:
    provider = Provider()
    provider.count = count
    adapter = model(provider)
    try:
        with pytest.raises(ValueError):
            await adapter.count_source_input(prompt())
        assert len(provider.requests) == 1
    finally:
        await adapter.close()


async def test_unknown_measurement_time_survives_source_result_projection() -> None:
    provider, value = Provider(), prompt()
    adapter = model(provider)
    try:
        first = await adapter.respond_source(value, max_output_tokens=128)
        original = receipt(value)
        assert original.facts and first.continuation
        original = original.model_copy(
            update={
                "facts": original.facts.model_copy(
                    update={"observed_at": None, "quality": "unknown_measurement_time"}
                )
            }
        )
        continued = replace(value, continuation=first.continuation, source_result=original)
        provider.body["output"] = [message()]
        await adapter.respond_source(continued, max_output_tokens=128)
        facts = json.loads(provider.requests[-1]["input"][-1]["output"])["facts"]
        assert facts["observed_at"] is None and facts["quality"] == "unknown_measurement_time"
    finally:
        await adapter.close()


async def test_ordinary_specialist_transport_keeps_its_original_tool_free_contract() -> None:
    provider = Provider()
    provider.body["output"] = [
        message('{"analysis":null,"followup_summary":"Synthetic","question":null}')
    ]
    adapter = model(provider)
    try:
        result = await adapter.respond(prompt().input, max_output_tokens=128)
        assert result.completed and result.usage.total == 150
        assert "tools" not in provider.requests[0] and "include" not in provider.requests[0]
    finally:
        await adapter.close()


async def test_parent_touch_publication_protocol_is_rejected_before_native_http() -> None:
    provider, value = Provider(), prompt()
    adapter = model(provider)
    try:
        value = replace(value, input=replace(value.input, structured_reply=True))
        with pytest.raises(ValueError):
            await adapter.respond_source(value, max_output_tokens=128)
        assert provider.requests == []
    finally:
        await adapter.close()
