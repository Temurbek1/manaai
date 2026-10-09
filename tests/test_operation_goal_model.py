from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.core.config import Settings, get_settings
from app.mana_operation_ai.domain.cost_control import ResourceUsage
from app.mana_operation_ai.domain.goals import GoalDecision
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from tests.test_operation_api import configure_operation_env

CONTEXT = '{"goal":{"product":"mana","agent_id":"operations-orchestrator"}}'


@pytest.mark.parametrize(
    "failure", [None, "timeout", "unknown_model", "unknown_tier", "missing_usage", "incomplete"]
)
async def test_goal_model_admission_usage_unknown_holds_and_no_retry(
    monkeypatch: MonkeyPatch, tmp_path: Path, failure: str | None
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "model.db")
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        model = OpenAIGoalModel(get_settings(), app.state.operation_cost_ledger)
        usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            input_tokens_details=SimpleNamespace(cached_tokens=10, cache_write_tokens=0),
        )
        decision = GoalDecision(
            update="Проверяю факты",
            plan=[],
            draft="",
            evidence_ids=[],
            disposition="waiting",
            missing_information="Нет источников",
            requested_capability=None,
        )
        response = SimpleNamespace(
            model="gpt-6.1-sol",
            service_tier="default",
            usage=usage,
            status="completed",
            output_parsed=decision,
            model_dump_json=lambda **kwargs: "{}",
        )
        if failure == "unknown_model":
            response.model = "other-model"
        if failure == "unknown_tier":
            response.service_tier = "priority"
        if failure == "missing_usage":
            response.usage = None
        if failure == "incomplete":
            response.status = "incomplete"
        parse = AsyncMock(
            side_effect=TimeoutError("private-body") if failure == "timeout" else None,
            return_value=response,
        )
        monkeypatch.setattr(model._client.responses, "parse", parse)
        try:
            if failure:
                with pytest.raises((RuntimeError, TimeoutError)):
                    await model.decide(context=CONTEXT, owner="owner")
            else:
                result = await model.decide(context=CONTEXT, owner="owner")
                assert result.actual_microusd == 681 and result.decision == decision
            assert parse.call_count == 1 and model._client.max_retries == 0
            request = parse.call_args.kwargs
            assert request["store"] is False and request["service_tier"] == "default"
            assert request["reasoning"] == {"effort": "medium"}
            assert request["max_output_tokens"] == 4096 and request["text_format"] is GoalDecision
            assert request["safety_identifier"] != "owner" and "tools" not in request
            periods = await app.state.operation_cost_ledger.periods()
            expected = 681 if failure in (None, "incomplete") else model.reservation(CONTEXT)
            assert all(period.usage.llm_microusd == expected for period in periods)
        finally:
            await model.close()
    get_settings.cache_clear()


async def test_goal_global_budget_refuses_before_sdk(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "budget.db")
    from app.main import create_app
    from app.mana_operation_ai.application.cost_control import CostBudgetExceeded

    app = create_app()
    async with app.router.lifespan_context(app):
        model = OpenAIGoalModel(get_settings(), app.state.operation_cost_ledger)
        monkeypatch.setattr(
            model._ledger, "reserve", AsyncMock(side_effect=CostBudgetExceeded("fixture"))
        )
        parse = AsyncMock(side_effect=AssertionError("An over-budget goal called OpenAI"))
        monkeypatch.setattr(model._client.responses, "parse", parse)
        try:
            with pytest.raises(CostBudgetExceeded):
                await model.decide(context=CONTEXT, owner="owner")
            assert parse.call_count == 0
        finally:
            await model.close()
    get_settings.cache_clear()


def test_goal_model_overrides_require_explicit_matching_rate_card() -> None:
    with pytest.raises(ValidationError, match="rate card"):
        Settings(_env_file=None, openai_api_key="fixture", operation_goals_model="other")
    with pytest.raises(ValidationError, match="rate-card"):
        Settings(
            _env_file=None,
            openai_api_key="fixture",
            operation_goals_model="other",
            operation_goals_rate_model="other",
        )
    assert ResourceUsage().llm_calls == 0
