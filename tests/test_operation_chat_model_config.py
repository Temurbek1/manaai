from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.core.config import Settings, get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_service import OperationChatService
from app.mana_operation_ai.infrastructure import chat_model
from app.mana_operation_ai.infrastructure.chat_model import OpenAIConversationModel
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from tests.test_operation_api import configure_operation_env, headers
from tests.test_operation_chat_costs import CONTEXT, policy, response
from tests.test_operation_cost_ledger import Clock

MINI_CARD: dict[str, Any] = {
    "operation_chat_rate_model": "gpt-5.4-mini",
    "operation_chat_input_usd_per_million": Decimal("0.75"),
    "operation_chat_cached_input_usd_per_million": Decimal("0.075"),
    "operation_chat_cache_write_usd_per_million": Decimal("0.75"),
    "operation_chat_output_usd_per_million": Decimal("4.50"),
}


@pytest.mark.parametrize("explicit_blank", [False, True])
def test_chat_overrides_default_to_existing_global_settings(explicit_blank: bool) -> None:
    blanks: dict[str, Any] = (
        {"operation_chat_model": " ", "operation_chat_reasoning_effort": ""}
        if explicit_blank
        else {}
    )
    settings = Settings(
        _env_file=None,
        openai_api_key="fake-config-key",
        openai_model="public-reviewed-model",
        openai_reasoning_effort="high",
        **blanks,
    )
    assert settings.operation_chat_model is None
    assert settings.operation_chat_reasoning_effort is None
    assert settings.effective_operation_chat_model == "public-reviewed-model"
    assert settings.effective_operation_chat_reasoning_effort == "high"
    assert settings.effective_audio_moderation_model == "public-reviewed-model"


def test_explicit_none_effort_does_not_fall_back_to_global_high() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="fake-config-key",
        openai_reasoning_effort="high",
        operation_chat_reasoning_effort="none",
    )
    assert settings.effective_operation_chat_model == settings.openai_model
    assert settings.effective_operation_chat_reasoning_effort == "none"
    assert settings.openai_reasoning_effort == "high"


@pytest.mark.parametrize("missing_field", list(MINI_CARD))
def test_explicit_model_requires_a_complete_explicit_rate_card(
    monkeypatch: MonkeyPatch, missing_field: str
) -> None:
    for field in MINI_CARD:
        monkeypatch.delenv(field.upper(), raising=False)
    incomplete = {field: value for field, value in MINI_CARD.items() if field != missing_field}
    with pytest.raises(ValidationError, match="OPERATION_CHAT_MODEL"):
        Settings(
            _env_file=None,
            openai_api_key="fake-config-key",
            operation_chat_model="gpt-5.4-mini",
            **incomplete,
        )


@pytest.mark.parametrize("model", ["gpt-5.4-mini ", "\ngpt-5.4-mini", "invalid/model"])
def test_explicit_model_identifier_is_not_accepted_with_whitespace_or_paths(model: str) -> None:
    with pytest.raises(ValidationError, match="operation_chat_model"):
        Settings(
            _env_file=None,
            openai_api_key="fake-config-key",
            operation_chat_model=model,
            **MINI_CARD,
        )


def test_unknown_reasoning_profile_is_not_silently_coerced() -> None:
    with pytest.raises(ValidationError, match="operation_chat_reasoning_effort"):
        Settings(
            _env_file=None,
            openai_api_key="fake-config-key",
            operation_chat_reasoning_effort=cast(Any, "maximum"),
        )


def test_configuration_error_does_not_print_other_input_secrets() -> None:
    secret = "synthetic-secret-that-must-not-appear-in-errors"
    with pytest.raises(ValidationError, match="OPERATION_CHAT_MODEL") as failure:
        Settings(
            _env_file=None,
            openai_api_key=secret,
            operation_chat_model="gpt-5.4-mini",
        )
    assert secret not in str(failure.value)
    assert "input_value" not in str(failure.value)


@pytest.mark.parametrize("complete_but_mismatched", [False, True])
def test_invalid_copied_configuration_is_refused_before_sdk_construction(
    monkeypatch: MonkeyPatch, complete_but_mismatched: bool
) -> None:
    for field in MINI_CARD:
        monkeypatch.delenv(field.upper(), raising=False)
    original = Settings(_env_file=None, openai_api_key="fake-config-key")
    overrides = {
        "operation_chat_model": "gpt-5.4-mini",
        "operation_chat_rate_model": "gpt-5.4-mini",
    }
    if complete_but_mismatched:
        overrides = {**MINI_CARD, "operation_chat_model": "another-model"}
    copied = original.model_copy(update=overrides)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("An invalid chat rate card constructed an SDK client")

    monkeypatch.setattr(chat_model, "AsyncOpenAI", forbidden)
    with pytest.raises(ValueError, match="OPERATION_CHAT_MODEL"):
        OpenAIConversationModel(copied)
    assert original.operation_chat_model is None


@pytest.mark.asyncio
async def test_override_controls_dispatch_and_accounting_without_mutating_global_settings(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="fake-config-key",
        openai_model="public-reviewed-model",
        openai_reasoning_effort="none",
        operation_chat_model="gpt-5.4-mini",
        operation_chat_reasoning_effort="low",
        **MINI_CARD,
    )
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'model-isolation.db'}")
    await database.create_schema()
    ledger = SqlAlchemyCostLedger(database, clock=Clock(), limits=policy())
    gateway = OpenAIConversationModel(settings, ledger=ledger)
    parse = AsyncMock(return_value=response(settings))
    monkeypatch.setattr(gateway._client.responses, "parse", parse)
    try:
        output = await gateway.reply(instructions="Test", context=CONTEXT, owner="private-owner")
        assert output.model == "gpt-5.4-mini"
        kwargs = parse.call_args.kwargs
        assert kwargs["model"] == "gpt-5.4-mini"
        assert kwargs["reasoning"] == {"effort": "low"}
        assert kwargs["max_output_tokens"] == 2048
        assert kwargs["store"] is False and kwargs["service_tier"] == "default"
        assert gateway._client.max_retries == 0 and "tools" not in kwargs
        usage = (await ledger.periods())[0].usage
        assert usage.llm_calls == 1 and usage.llm_microusd == 573
        assert usage.document_reads == 0
        assert settings.openai_model == "public-reviewed-model"
        assert settings.openai_reasoning_effort == "none"
        assert settings.effective_audio_moderation_model == "public-reviewed-model"
    finally:
        await gateway.close()
        await database.dispose()


@pytest.mark.asyncio
async def test_real_chat_route_uses_override_but_public_service_retains_global_model(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "configured-chat.db")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.4-nano")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "none")
    monkeypatch.setenv("OPERATION_CHAT_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("OPERATION_CHAT_REASONING_EFFORT", "low")
    for field, value in MINI_CARD.items():
        monkeypatch.setenv(field.upper(), str(value))
    get_settings.cache_clear()
    app = create_app()

    async def forbidden_network(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("Configuration isolation test attempted external I/O")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden_network)
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client,
        ):
            service = cast(OperationChatService, app.state.operation_chat_service)
            gateway = cast(OpenAIConversationModel, service._model)
            settings = cast(Settings, app.state.settings)
            parse = AsyncMock(return_value=response(settings))
            monkeypatch.setattr(gateway._client.responses, "parse", parse)
            created = await client.post(
                "/api/v1/admin/operation/chat/topics",
                headers=headers("operator", "viewer"),
                json={"agent_id": "retention-agent", "product": "mana", "title": "Test"},
            )
            assert created.status_code == 201
            topic = created.json()["topic_id"]
            payload = {"request_id": str(uuid4()), "message": "Explain available evidence."}
            result = await client.post(
                f"/api/v1/admin/operation/chat/topics/{topic}/messages",
                headers=headers("operator", "viewer"),
                json=payload,
            )
            assert result.status_code == 200 and result.json()["status"] == "completed"
            assert result.json()["model"] == "gpt-5.4-mini"
            assert parse.call_count == 1
            assert parse.call_args.kwargs["reasoning"] == {"effort": "low"}
            assert app.state.openai_service.model_name == "gpt-5.4-nano"
            assert settings.openai_reasoning_effort == "none"
            assert settings.effective_audio_moderation_model == "gpt-5.4-nano"
    finally:
        get_settings.cache_clear()
