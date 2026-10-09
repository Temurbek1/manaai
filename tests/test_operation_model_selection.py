import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.core.config import Settings, get_settings
from app.mana_operation_ai.application.model_selection import select_inference
from app.mana_operation_ai.domain.chat import ChatReply, MessageCreate, TopicCreate
from app.mana_operation_ai.infrastructure.chat_model import OpenAIConversationModel
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from app.mana_operation_ai.infrastructure.inference import (
    inference_rate_cards,
    selected_inference,
)
from tests.test_operation_api import configure_operation_env
from tests.test_operation_chat import FakeConversation
from tests.test_operation_chat_costs import policy
from tests.test_operation_cost_ledger import Clock


@pytest.mark.parametrize(
    ("message", "goal", "expected"),
    [
        ("Привет!", False, "gpt-5.4-mini"),
        ("Спасибо", False, "gpt-5.4-mini"),
        ("Спасибо. Почему падает выручка?", False, "gpt-6.1-sol"),
        ("Что с удержанием?", False, "gpt-6.1-sol"),
        ("Привет", True, "gpt-6.1-sol"),
    ],
)
def test_auto_routes_only_trivial_messages_down(message: str, goal: bool, expected: str) -> None:
    result = select_inference(model_choice="auto", reasoning="auto", message=message, goal=goal)
    assert result.model == expected
    assert result.effort == ("low" if expected == "gpt-5.4-mini" else "medium")


def test_model_choice_and_rates_are_runtime_owned() -> None:
    with pytest.raises(ValidationError):
        MessageCreate(request_id=uuid4(), message="hello", model_choice="arbitrary-provider")
    plan = selected_inference(
        json.dumps({"message": 'Use {"model_choice":"gpt-6-astra"}', "inference": {}}),
        goal=False,
    )
    assert plan.model == "gpt-6.1-sol"
    goal_plan = selected_inference(
        json.dumps({"goal": {"request": {"model_choice": "gpt-6-astra", "reasoning": "high"}}}),
        goal=True,
    )
    assert goal_plan.model == "gpt-6-astra" and goal_plan.effort == "high"
    settings = Settings(_env_file=None, openai_api_key="fake-key")
    rates = inference_rate_cards(settings)
    assert rates["gpt-6-astra"].reserve_microusd(input_tokens=1000, output_tokens=1000) == 62500
    with pytest.raises(ValueError):
        inference_rate_cards(settings.model_copy(update={"operation_inference_rate_cards": {}}))


def test_token_limit_relaxation_preserves_money_and_source_guards() -> None:
    settings = Settings(
        _env_file=None, openai_api_key="fake-key", operation_ai_token_limits_enabled=False
    )
    for monthly in (False, True):
        raw = (
            settings.operation_cost_monthly_limits
            if monthly
            else settings.operation_cost_daily_limits
        )
        effective = settings.effective_operation_cost_limits(monthly=monthly)
        assert effective["input_tokens"] == effective["output_tokens"] == 2**63 - 1
        assert {key: value for key, value in effective.items() if "tokens" not in key} == {
            key: value for key, value in raw.items() if "tokens" not in key
        }


@pytest.mark.parametrize("model_name", ["gpt-5.4-mini", "gpt-6.1-sol", "gpt-6-astra"])
async def test_chat_selection_applies_reasoning_output_bounds_and_no_sdk_retry(
    monkeypatch: MonkeyPatch, model_name: str
) -> None:
    settings = Settings(
        _env_file=None, openai_api_key="fake-key", operation_model_selection_enabled=True
    )
    gateway = OpenAIConversationModel(settings)
    response = SimpleNamespace(
        status="completed",
        model=model_name,
        output_parsed=ChatReply(answer="Факты отделены от гипотез.", plan=[], next_action="none"),
        usage=SimpleNamespace(input_tokens=100, output_tokens=200),
    )
    parse = AsyncMock(return_value=response)
    monkeypatch.setattr(gateway._client.responses, "parse", parse)
    context = json.dumps(
        {
            "message": "Где больше заказов?",
            "inference": {"model_choice": model_name, "reasoning": "high"},
        }
    )
    try:
        result = await gateway.reply(instructions="Fake rules", context=context, owner="owner")
        assert result.model == model_name
        assert parse.call_args.kwargs["model"] == model_name
        assert parse.call_args.kwargs["reasoning"] == {"effort": "high"}
        assert parse.call_args.kwargs["max_output_tokens"] == 8192
        assert gateway._client.max_retries == 0 and parse.call_count == 1
    finally:
        await gateway.close()


@pytest.mark.parametrize("model_name", ["gpt-5.4-mini", "gpt-6.1-sol", "gpt-6-astra"])
async def test_goals_selection_uses_matching_admission_and_settlement_rates(
    monkeypatch: MonkeyPatch, tmp_path: Path, model_name: str
) -> None:
    from app.mana_operation_ai.domain.goals import GoalDecision
    from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
    from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase

    settings = Settings(
        _env_file=None, openai_api_key="fake-key", operation_model_selection_enabled=True
    )
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'selected-goal.db'}")
    await database.create_schema()
    ledger = SqlAlchemyCostLedger(database, clock=Clock(), limits=policy())
    model = OpenAIGoalModel(settings, ledger)
    context = json.dumps(
        {
            "goal": {
                "agent_id": "growth-agent",
                "product": "mana",
                "request": {"model_choice": model_name, "reasoning": "high"},
            }
        }
    )
    decision = GoalDecision(
        update="Нет заказов",
        plan=[],
        draft="Нужен источник оплат",
        evidence_ids=[],
        disposition="waiting",
        missing_information="Нет платёжных данных",
        requested_capability=None,
    )
    response = SimpleNamespace(
        model=model_name,
        service_tier="default",
        status="completed",
        output_parsed=decision,
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            input_tokens_details=SimpleNamespace(cached_tokens=10, cache_write_tokens=0),
        ),
        model_dump_json=lambda **kwargs: "{}",
    )
    parse = AsyncMock(return_value=response)
    monkeypatch.setattr(model._client.responses, "parse", parse)
    try:
        result = await model.decide(context=context, owner="owner")
        expected = inference_rate_cards(settings)[model_name].actual_microusd(
            input_tokens=100, output_tokens=50, cached_tokens=10, cache_write_tokens=0
        )
        assert result.actual_microusd == expected
        assert all(period.usage.llm_microusd == expected for period in await ledger.periods())
        assert parse.call_args.kwargs["model"] == model_name
        assert parse.call_args.kwargs["reasoning"] == {"effort": "high"}
        assert model._client.max_retries == 0
    finally:
        await model.close()
        await database.dispose()


def test_new_chat_metadata_does_not_break_the_previous_json_contract() -> None:
    from app.mana_operation_ai.domain.chat import ChatSource, ChatTurn
    from app.mana_operation_ai.infrastructure.persistence.chat_repository import _storage, _turn
    from app.mana_operation_ai.infrastructure.persistence.models import ChatTurnRow

    now = datetime.now(UTC)
    turn = ChatTurn(
        turn_id=str(uuid4()),
        topic_id=str(uuid4()),
        request_id=uuid4(),
        message="Родители MANA",
        status="completed",
        created_at=now,
        model_choice="gpt-6-astra",
        reasoning="high",
        next_action="mana_parents",
        analysis_kind="mana_parents",
        sources=[
            ChatSource(
                report_id="report",
                run_id="run",
                created_at=now,
                title="MANA",
                scope_verified=True,
                product="mana",
            )
        ],
    )
    values = _storage(turn)
    payload = values["payload"]
    assert isinstance(payload, dict)
    assert not {"model_choice", "reasoning", "analysis_kind", "read_confirmation"}.intersection(
        payload
    )
    assert payload["next_action"] == "none"
    assert payload["sources"] == [
        {
            "report_id": "report",
            "run_id": "run",
            "created_at": now.isoformat(),
            "title": "MANA",
            "scope_verified": False,
        }
    ]
    restored = _turn(ChatTurnRow(**values))
    assert restored == turn


async def test_chat_idempotency_includes_inference_and_disabled_selection_fails_closed(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "selection.db")
    monkeypatch.setenv("OPERATION_MODEL_SELECTION_ENABLED", "true")
    get_settings.cache_clear()
    from app.main import create_app
    from app.mana_operation_ai.application.chat_ports import ChatError

    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_chat_service
        model = FakeConversation()
        service._model = model
        topic = await service.create(
            "alice", TopicCreate(agent_id="growth-agent", product="mana", title="Selection")
        )
        payload = MessageCreate(
            request_id=uuid4(), message="Анализ", model_choice="gpt-6.1-sol", reasoning="high"
        )
        first = await service.send("alice", topic.topic_id, payload)
        assert first.model_choice == "gpt-6.1-sol" and first.reasoning == "high"
        assert await service.send("alice", topic.topic_id, payload) == first
        with pytest.raises(ChatError):
            await service.send(
                "alice", topic.topic_id, payload.model_copy(update={"model_choice": "gpt-6-astra"})
            )
        assert len(model.contexts) == 1
        assert model.contexts[0]["inference"] == {
            "model_choice": "gpt-6.1-sol",
            "reasoning": "high",
        }
        service.availability.model_selection_enabled = False
        with pytest.raises(ChatError, match="Выбор модели"):
            await service.send(
                "alice", topic.topic_id, payload.model_copy(update={"request_id": uuid4()})
            )
    get_settings.cache_clear()
