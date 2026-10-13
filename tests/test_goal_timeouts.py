"""Explicit model deadlines, isolated fake I/O and durable unknown-cost safety."""

import asyncio
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.core.config import Settings, get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.cost_control import CostLedger
from app.mana_operation_ai.application.goal_ports import ContinuingGoalModel
from app.mana_operation_ai.application.goal_service import OperationGoalService
from app.mana_operation_ai.domain.enums import AgentRunStatus
from app.mana_operation_ai.domain.models import AgentRunResult
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from tests.test_goal_limit_extensions import configure, extension, goal
from tests.test_operation_goals import GoalFake, command, new_goal, seed


def test_default_deadlines_preserve_the_existing_runtime(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("OPERATION_GOALS_REQUEST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("OPERATION_GOALS_MODEL_STEP_TIMEOUT_SECONDS", raising=False)
    settings = Settings(_env_file=None, openai_api_key="fixture")
    assert settings.operation_goals_request_timeout_seconds == 120
    assert settings.operation_goals_model_step_timeout_seconds == 180


@pytest.mark.parametrize("seconds", [10, 241, float("nan")])
def test_direct_service_constructor_cannot_exceed_lease_margin(seconds: float) -> None:
    with pytest.raises(ValueError, match="between 11 and 240"):
        OperationGoalService(
            repository=Mock(),
            chats=Mock(),
            model=Mock(),
            admin=Mock(),
            clock=Mock(),
            availability=Mock(),
            model_step_timeout_seconds=seconds,
        )


@pytest.mark.parametrize(
    ("request_seconds", "step_seconds", "valid"),
    [
        (120, 180, True),
        (210, 240, True),
        (230, 240, True),
        (1, 11, True),
        (120.5, 130.5, True),
        (0, 180, False),
        (231, 240, False),
        (120, 241, False),
        (120, 120, False),
        (120, 129, False),
        (float("inf"), 240, False),
        (120, float("nan"), False),
    ],
)
def test_deadline_bounds_and_request_settlement_margin(
    request_seconds: float, step_seconds: float, valid: bool
) -> None:
    if not valid:
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                openai_api_key="fixture",
                operation_goals_request_timeout_seconds=request_seconds,
                operation_goals_model_step_timeout_seconds=step_seconds,
            )
        return
    settings = Settings(
        _env_file=None,
        openai_api_key="fixture",
        operation_goals_request_timeout_seconds=request_seconds,
        operation_goals_model_step_timeout_seconds=step_seconds,
    )
    assert settings.operation_goals_request_timeout_seconds == request_seconds
    assert settings.operation_goals_model_step_timeout_seconds == step_seconds


@pytest.mark.parametrize("request_seconds", [120, 210, 230])
async def test_sdk_request_deadline_is_explicit_without_enabling_retries(
    request_seconds: float,
) -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="fixture",
        operation_goals_request_timeout_seconds=request_seconds,
        operation_goals_model_step_timeout_seconds=240,
    )
    model = OpenAIGoalModel(settings, cast(CostLedger, Mock()))
    try:
        assert model._client.timeout == request_seconds
        assert model._client.max_retries == 0
    finally:
        await model.close()


@pytest.mark.parametrize("continuation", [False, True])
async def test_outer_deadline_stops_once_and_cannot_release_unknown_hold_after_restart(
    monkeypatch: MonkeyPatch, tmp_path: Path, continuation: bool
) -> None:
    configure(monkeypatch, tmp_path / "deadline.db")
    monkeypatch.setenv("OPERATION_GOALS_REQUEST_TIMEOUT_SECONDS", "210")
    monkeypatch.setenv("OPERATION_GOALS_MODEL_STEP_TIMEOUT_SECONDS", "240")
    get_settings.cache_clear()
    timeout = asyncio.timeout
    deadlines: list[float | None] = []

    def fast_deadline(delay: float | None) -> asyncio.Timeout:
        deadlines.append(delay)
        # Exercise real task cancellation without a four-minute fake test wait.
        return timeout(0.01 if delay == 240 else delay)

    app = create_app()
    async with app.router.lifespan_context(app):
        service: OperationGoalService = app.state.operation_goal_service
        assert service._model_step_timeout_seconds == 240
        model = GoalFake()
        model.release.clear()
        service._model = model
        native = Mock()
        native.continuation_reservation.return_value = 20000
        native.continue_decide = AsyncMock(side_effect=TimeoutError("PRIVATE body"))
        service._continuing_model = cast(ContinuingGoalModel, native) if continuation else None
        saved = await goal(service)
        monkeypatch.setattr(asyncio, "timeout", fast_deadline)
        assert await service.tick()
        saved = await service.repository.get("alice", saved.goal_id)
        assert saved.status == "waiting" and saved.limit_stop is None
        assert saved.unsettled_microusd == saved.accounted_microusd == 20000
        assert saved.steps_used == 1 and saved.model_recoveries == 0
        assert "не завершился вовремя" in saved.waiting_reason
        assert "PRIVATE" not in saved.model_dump_json()
        assert not saved.read_attempted and saved.approved_capability is None
        assert not saved.result and not saved.limit_grants
        assert deadlines == [240]
        assert native.continue_decide.call_count == int(continuation)
        assert len(model.contexts) == int(not continuation)
        for request in (command(saved, "resume"), extension(saved, budget=100000)):
            with pytest.raises(ChatError):
                await service.command("alice", saved.goal_id, request)
        assert not await service.tick()
        assert native.continue_decide.call_count == int(continuation)
        assert len(model.contexts) == int(not continuation)
    restarted = create_app()
    async with restarted.router.lifespan_context(restarted):
        service = restarted.state.operation_goal_service
        restored = await service.repository.get("alice", saved.goal_id)
        assert restored.request == saved.request and restored.evidence == saved.evidence
        assert restored.status == "waiting" and restored.unsettled_microusd == 20000
        assert restored.accounted_microusd == 20000 and not restored.read_attempted
        assert not await service.tick()


async def test_model_deadline_does_not_change_separately_approved_source_deadline(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure(monkeypatch, tmp_path / "source.db")
    monkeypatch.setenv("OPERATION_GOALS_REQUEST_TIMEOUT_SECONDS", "210")
    monkeypatch.setenv("OPERATION_GOALS_MODEL_STEP_TIMEOUT_SECONDS", "240")
    get_settings.cache_clear()
    timeout = asyncio.timeout
    deadlines: list[float | None] = []

    def capture(delay: float | None) -> asyncio.Timeout:
        deadlines.append(delay)
        return timeout(delay)

    app = create_app()
    async with app.router.lifespan_context(app):
        service: OperationGoalService = app.state.operation_goal_service
        model = GoalFake()
        model.ask_read = True
        service._model = model
        service.availability.read_capabilities = ["retention.engagement.analyze"]
        service.availability.read_product = "mana"
        read = AsyncMock(
            return_value=AgentRunResult(run_id="fake-read", status=AgentRunStatus.COMPLETED)
        )
        monkeypatch.setattr(service._admin, "run_now", read)
        await seed(service)
        saved = await new_goal(service)
        monkeypatch.setattr(asyncio, "timeout", capture)
        assert await service.tick()
        saved = await service.repository.get("alice", saved.goal_id)
        assert saved.status == "waiting" and read.call_count == 0
        await service.command("alice", saved.goal_id, command(saved, "approve_read"))
        assert await service.tick()
        saved = await service.repository.get("alice", saved.goal_id)
        assert deadlines == [240, 180]
        assert read.call_count == 1 and saved.read_attempted
        assert not saved.approved_capability
