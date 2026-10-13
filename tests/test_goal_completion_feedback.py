"""Closed completion facts, durable public stop and no inference/source replay."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncOpenAI
from pytest import MonkeyPatch
from sqlalchemy import select

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.goal_ports import GoalModelResponseError
from app.mana_operation_ai.domain.cost_control import ResourceUsage
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from app.mana_operation_ai.infrastructure.persistence.models import CostReservationRow
from tests.test_goal_limit_extensions import configure, extension, goal
from tests.test_inference_failures import wire
from tests.test_operation_api import headers
from tests.test_operation_goals import command

PRIVATE = "PRIVATE-completion-body-identity-and-credential"


@pytest.mark.parametrize(
    ("status", "reason", "facts"),
    [
        (
            "incomplete",
            "max_output_tokens",
            "provider_status=incomplete; incomplete_reason=max_output_tokens",
        ),
        (
            "incomplete",
            "content_filter",
            "provider_status=incomplete; incomplete_reason=content_filter",
        ),
        ("incomplete", PRIVATE, "provider_status=incomplete"),
        ("failed", "max_output_tokens", "provider_status=failed"),
        ("cancelled", None, "provider_status=cancelled"),
        ("queued", None, "provider_status=queued"),
        ("in_progress", None, "provider_status=in_progress"),
        (None, "max_output_tokens", ""),
        (PRIVATE, "content_filter", ""),
        ("completed", "max_output_tokens", ""),
    ],
)
def test_completion_feedback_contains_only_closed_coherent_facts(
    status: str | None, reason: str | None, facts: str
) -> None:
    error = GoalModelResponseError(
        "Safe output failure.", 0, provider_status=status, incomplete_reason=reason
    )
    assert error.completion_feedback == (f" Проверка завершения: {facts}." if facts else "")
    assert PRIVATE not in error.completion_feedback
    assert len(error.completion_feedback) < 140
    assert error.output_failure is None and not error.validation_issues


@pytest.mark.parametrize("zero_usage", [False, True])
@pytest.mark.parametrize(
    "failure",
    [
        "max_output_tokens",
        "content_filter",
        "private_reason",
        "private_status",
        "failed",
        "queued",
        "in_progress",
    ],
)
async def test_sdk_known_noncomplete_receipt_survives_sql_http_restart_without_recovery(
    monkeypatch: MonkeyPatch, tmp_path: Path, zero_usage: bool, failure: str
) -> None:
    configure(monkeypatch, tmp_path / "completion.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED", "true")
    get_settings.cache_clear()
    requests: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        body = wire("gpt-6.1-sol", "goal")
        body["status"] = (
            PRIVATE
            if failure == "private_status"
            else (failure if failure in {"failed", "queued", "in_progress"} else "incomplete")
        )
        body["incomplete_details"] = {
            "reason": failure if failure in {"max_output_tokens", "content_filter"} else PRIVATE
        }
        body["error"] = {"code": PRIVATE, "message": PRIVATE}
        # An unusable body must stop before parsing structured output/reasoning.
        body["output"][0]["content"][0]["text"] = "{" + PRIVATE
        if zero_usage:
            body["usage"] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            }
        return httpx.Response(200, json=body)

    async def forbidden(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("A test attempted the real network")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        gateway = service._continuing_model
        assert isinstance(gateway, OpenAIGoalModel)
        await gateway._client.close()
        gateway._client = AsyncOpenAI(
            api_key="fixture",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )
        source = AsyncMock()
        monkeypatch.setattr(service._admin, "run_now", source)
        saved = await goal(service, budget=490000)
        assert await service.tick()
        stopped = await service.repository.get("alice", saved.goal_id)
        pending = failure in {"queued", "in_progress"}
        assert stopped.status == "waiting" and stopped.limit_stop is None
        assert stopped.request == saved.request and stopped.steps_used == 1
        assert stopped.model_recoveries == 0 and stopped.model_feedback is None
        if pending:
            assert stopped.accounted_microusd == stopped.unsettled_microusd > 0
            assert "Резерв сохранён" in stopped.waiting_reason
        else:
            assert stopped.accounted_microusd == (0 if zero_usage else 681)
            assert stopped.unsettled_microusd == 0
            assert "не завершён" in stopped.waiting_reason
        assert stopped.model_continuation is None and not stopped.read_attempted
        assert PRIVATE not in stopped.model_dump_json()
        if failure != "private_status":
            expected_status = failure if pending or failure == "failed" else "incomplete"
            assert f"provider_status={expected_status}" in stopped.waiting_reason
        else:
            assert "provider_status=" not in stopped.waiting_reason
        assert ("incomplete_reason=" in stopped.waiting_reason) == (
            failure in {"max_output_tokens", "content_filter"}
        )
        assert stopped.events[-1].message == stopped.waiting_reason
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/v1/admin/operation/goals/{saved.goal_id}",
                headers=headers("alice", "operator"),
            )
            assert response.status_code == 200
            assert response.json()["waiting_reason"] == stopped.waiting_reason
            assert PRIVATE not in response.text
        async with app.state.operation_database.session_factory() as session:
            rows = list(await session.scalars(select(CostReservationRow)))
        assert len(rows) == 1
        if pending:
            assert rows[0].actual is None
            assert (
                ResourceUsage.model_validate(rows[0].usage).llm_microusd
                == stopped.unsettled_microusd
            )
        else:
            assert rows[0].actual is not None
            actual = ResourceUsage.model_validate(rows[0].actual)
            assert actual.llm_microusd == stopped.accounted_microusd
            assert actual.llm_calls == actual.provider_requests == 1
        periods = await app.state.operation_cost_ledger.periods()
        assert all(period.usage.llm_microusd == stopped.accounted_microusd for period in periods)
        assert requests == ["/v1/responses"] and gateway._client.max_retries == 0
        assert not await service.tick() and requests == ["/v1/responses"]
        source.assert_not_awaited()
    restarted = create_app()
    async with restarted.router.lifespan_context(restarted):
        service = restarted.state.operation_goal_service
        probe = AsyncMock()
        service._model = service._continuing_model = probe
        restored = await service.repository.get("alice", saved.goal_id)
        assert restored.request == saved.request
        assert restored.waiting_reason == stopped.waiting_reason
        assert restored.accounted_microusd == stopped.accounted_microusd
        assert restored.unsettled_microusd == stopped.unsettled_microusd
        assert restored.status == "waiting"
        if pending:
            for request in (command(restored, "resume"), extension(restored, budget=500000)):
                with pytest.raises(ChatError):
                    await service.command("alice", saved.goal_id, request)
        assert not await service.tick()
        probe.decide.assert_not_awaited()
        probe.continue_decide.assert_not_awaited()
        assert PRIVATE not in json.dumps(restored.model_dump(mode="json"))
