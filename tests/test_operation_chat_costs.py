import json
import warnings
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import JsonValue, SecretStr
from pytest import MonkeyPatch

from app.core.config import Settings
from app.mana_operation_ai.application.chat_service import _bounded_context
from app.mana_operation_ai.application.cost_control import CostBudgetExceeded
from app.mana_operation_ai.domain.chat import ChatReply
from app.mana_operation_ai.domain.cost_control import CostLimits, LlmRateCard, ResourceUsage
from app.mana_operation_ai.infrastructure.chat_model import OpenAIConversationModel
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from tests.test_operation_cost_ledger import Clock

CONTEXT = json.dumps(
    {"topic": {"product": "mana", "agent_id": "retention-agent"}, "message": "Test"}
)


def response(settings: Settings) -> SimpleNamespace:
    return SimpleNamespace(
        status="completed",
        model=settings.effective_operation_chat_model,
        service_tier="default",
        output_parsed=ChatReply(answer="Нужны подтверждённые данные.", plan=[], next_action="none"),
        usage=SimpleNamespace(
            input_tokens=200,
            output_tokens=100,
            input_tokens_details=SimpleNamespace(cached_tokens=40, cache_write_tokens=30),
        ),
        model_dump_json=lambda **kwargs: "{}",
    )


def policy(calls: int = 1) -> CostLimits:
    usage = ResourceUsage(
        llm_calls=calls,
        provider_requests=calls,
        response_bytes=1_048_576,
        input_tokens=100_000,
        output_tokens=10_000,
        llm_microusd=1_000_000,
    )
    return CostLimits(daily=usage, monthly=usage)


@pytest.mark.asyncio
async def test_llm_admission_settlement_and_rejection_before_sdk_call(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'llm.db'}")
    await db.create_schema()
    ledger = SqlAlchemyCostLedger(db, clock=Clock(), limits=policy())
    settings = Settings(
        _env_file=None, openai_api_key=SecretStr("fake-key"), openai_model="gpt-5.4-nano"
    )
    gateway = OpenAIConversationModel(settings, ledger=ledger)
    parse = AsyncMock(return_value=response(settings))
    monkeypatch.setattr(gateway._client.responses, "parse", parse)
    try:
        result = await gateway.reply(instructions="Test", context=CONTEXT, owner="private-owner")
        assert result.input_tokens == 200
        usage = (await ledger.periods())[0].usage
        assert usage.llm_calls == 1
        assert usage.input_tokens == 200
        assert usage.output_tokens == 100
        assert usage.llm_microusd == 158
        with pytest.raises(CostBudgetExceeded):
            await gateway.reply(instructions="Test", context=CONTEXT, owner="another-owner")
        assert parse.call_count == 1
        assert parse.call_args.kwargs["service_tier"] == "default"
        assert gateway._client.max_retries == 0
    finally:
        await gateway.close()
        await db.dispose()


@pytest.mark.asyncio
async def test_unknown_llm_charge_is_not_refunded_on_timeout(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'uncertain.db'}")
    await db.create_schema()
    ledger = SqlAlchemyCostLedger(db, clock=Clock(), limits=policy())
    settings = Settings(
        _env_file=None, openai_api_key=SecretStr("fake-key"), openai_model="gpt-5.4-nano"
    )
    gateway = OpenAIConversationModel(settings, ledger=ledger)
    parse = AsyncMock(side_effect=TimeoutError("No receipt"))
    monkeypatch.setattr(gateway._client.responses, "parse", parse)
    try:
        with pytest.raises(TimeoutError):
            await gateway.reply(instructions="Test", context=CONTEXT, owner="owner")
        usage = (await ledger.periods())[0].usage
        assert usage.llm_calls == 1
        assert usage.output_tokens == 2048
        assert usage.input_tokens > 200
        with pytest.raises(CostBudgetExceeded):
            await gateway.reply(instructions="Test", context=CONTEXT, owner="owner")
        assert parse.call_count == 1
    finally:
        await gateway.close()
        await db.dispose()


def test_context_bound_preserves_question_scope_and_evidence_identity() -> None:
    payload: dict[str, JsonValue] = {
        "topic": {"product": "360rec"},
        "message": "Какие данные подтверждены?",
        "history": [{"user": "я" * 3000, "assistant": "ответ" * 3000} for _ in range(6)],
        "saved_reports": [
            {
                "id": "report-1",
                "report_created_at": datetime.now(UTC).isoformat(),
                "scope_verified": False,
                "product": None,
                "summary": "история" * 4000,
                "limitations": ["unverified"],
            }
        ],
        "older_turns_omitted": 0,
        "report_text_shortened": False,
    }
    encoded = _bounded_context(payload, maximum_bytes=8192)
    assert len(encoded.encode()) <= 8192
    context = json.loads(encoded)
    assert context["message"] == payload["message"]
    assert context["topic"]["product"] == "360rec"
    assert context["saved_reports"][0]["id"] == "report-1"
    assert context["saved_reports"][0]["scope_verified"] is False
    assert context["older_turns_omitted"] > 0
    assert context["report_text_shortened"] is True


def test_rate_card_does_not_double_charge_cache_or_reasoning() -> None:
    rates = LlmRateCard(
        model="example",
        input_usd_per_million=2,
        cached_input_usd_per_million=1,
        cache_write_usd_per_million=3,
        output_usd_per_million=10,
    )
    assert (
        rates.actual_microusd(
            input_tokens=100, output_tokens=50, cached_tokens=20, cache_write_tokens=30
        )
        == 710
    )
    with pytest.raises(ValueError):
        rates.actual_microusd(
            input_tokens=1, output_tokens=50, cached_tokens=20, cache_write_tokens=30
        )


@pytest.mark.asyncio
async def test_sdk_parsed_size_accounting_does_not_log_private_answer_warnings(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None, openai_api_key=SecretStr("fake-key"), openai_model="gpt-5.4-nano"
    )
    reply = ChatReply(answer="PII-synthetic-answer", plan=[], next_action="none")

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        return httpx.Response(
            200,
            json={
                "id": "synthetic-response",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": settings.openai_model,
                "service_tier": "default",
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": [],
                "output": [
                    {
                        "id": "synthetic-message",
                        "role": "assistant",
                        "status": "completed",
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": reply.model_dump_json(),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 200,
                    "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                    "output_tokens": 100,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 300,
                },
            },
        )

    # Exercise the actual SDK parser against a fake HTTP response, never the API.
    async with AsyncOpenAI(
        api_key="fake-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    ) as fake_sdk:
        sdk_response = await fake_sdk.responses.parse(
            model=settings.openai_model, input="synthetic", store=False, text_format=ChatReply
        )
    with warnings.catch_warnings(record=True) as baseline:
        warnings.simplefilter("always")
        baseline_json = sdk_response.model_dump_json()
    assert any("PII" in str(item.message) for item in baseline)
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'serialization.db'}")
    await db.create_schema()
    ledger = SqlAlchemyCostLedger(db, clock=Clock(), limits=policy())
    gateway = OpenAIConversationModel(settings, ledger=ledger)
    parse = AsyncMock(return_value=sdk_response)
    monkeypatch.setattr(gateway._client.responses, "parse", parse)
    try:
        with warnings.catch_warnings(record=True) as emitted:
            warnings.simplefilter("always")
            result = await gateway.reply(instructions="Test", context=CONTEXT, owner="owner")
        assert result.answer == reply.answer and not emitted
        usage = (await ledger.periods())[0].usage
        assert usage.response_bytes == len(baseline_json.encode())
        assert usage.llm_microusd == 165 and usage.llm_calls == 1
        assert parse.call_count == 1
    finally:
        await gateway.close()
        await db.dispose()
