"""Real SDK boundaries with synthetic HTTP only: no paid calls, reads or retries."""

from pathlib import Path
from typing import Any, Literal
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI
from pytest import LogCaptureFixture, MonkeyPatch
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.goal_ports import GoalModelResponseError
from app.mana_operation_ai.application.inference_errors import (
    InferenceProviderError,
    inference_failure_message,
)
from app.mana_operation_ai.domain.chat import ChatReply, MessageCreate, TopicCreate
from app.mana_operation_ai.domain.goals import GoalCommand, GoalDecisionBody
from app.mana_operation_ai.infrastructure.chat_model import OpenAIConversationModel
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import CostReservationRow
from tests.test_goal_limit_extensions import configure, extension, goal
from tests.test_operation_chat_costs import CONTEXT, policy
from tests.test_operation_cost_ledger import Clock

GOAL_CONTEXT = '{"goal":{"product":"mana","agent_id":"operations-orchestrator"}}'
PRIVATE = "PRIVATE-provider-body-with-child-identity-and-key"


def wire(model: str, lane: str) -> dict[str, Any]:
    decision = GoalDecisionBody(
        update="Only saved synthetic evidence is available.",
        plan=[],
        draft="A complete analysis cannot be claimed.",
        evidence_ids=[],
        disposition="waiting",
        missing_information="No confirmed payments or full funnel were supplied.",
        requested_capability=None,
    )
    answer = (
        ChatReply(answer="Only saved evidence.", plan=[], next_action="none").model_dump_json()
        if lane == "chat"
        else decision.model_dump_json()
    )
    return {
        "id": "resp_synthetic",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": model,
        "service_tier": "default",
        "parallel_tool_calls": False,
        "tool_choice": "none",
        "tools": [],
        "output": [
            {
                "id": "msg_synthetic",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": answer, "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "input_tokens_details": {"cached_tokens": 10, "cache_write_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


@pytest.mark.parametrize("lane", ["chat", "goal"])
@pytest.mark.parametrize(
    "failure",
    [
        None,
        "invalid_json",
        "invalid_metadata",
        "incomplete",
        "private_status",
        "failed_without_usage",
        "missing_usage",
        "wrong_model",
        "wrong_tier",
        "fractional_usage",
        "boolean_usage",
        "bad_body",
        "quota",
        "rate_limit",
        "authentication",
        "permission",
        "invalid_request",
        "unavailable",
        "timeout",
        "connection",
    ],
)
async def test_sdk_receipts_are_independent_of_answer_validation_and_errors_are_safe(
    tmp_path: Path,
    lane: Literal["chat", "goal"],
    failure: str | None,
    caplog: LogCaptureFixture,
) -> None:
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'receipt.db'}")
    await database.create_schema()
    ledger = SqlAlchemyCostLedger(database, clock=Clock(), limits=policy())
    settings = Settings(
        _env_file=None, openai_api_key="synthetic-only", openai_model="gpt-5.4-nano"
    )
    model = (
        settings.effective_operation_chat_model
        if lane == "chat"
        else settings.operation_goals_model
    )
    body = wire(model, lane)
    if failure == "invalid_json":
        body["output"][0]["content"][0]["text"] = "{" + PRIVATE
    elif failure == "invalid_metadata":
        body["output"] = PRIVATE
    elif failure == "incomplete":
        body["status"] = "incomplete"
        body["incomplete_details"] = {"reason": PRIVATE}
    elif failure == "private_status":
        body["status"] = PRIVATE
    elif failure == "failed_without_usage":
        body["status"], body["usage"] = "failed", None
        body["error"] = {"code": "insufficient_quota", "message": PRIVATE}
    elif failure == "missing_usage":
        body["usage"] = None
    elif failure == "wrong_model":
        body["model"] = "unpriced-synthetic-model"
    elif failure == "wrong_tier":
        body["service_tier"] = "priority"
    elif failure == "fractional_usage":
        body["usage"]["input_tokens"] = 100.5
    elif failure == "boolean_usage":
        body["usage"]["output_tokens"] = True
    requests: list[httpx.Request] = []
    status_codes = {
        "quota": 429,
        "rate_limit": 429,
        "authentication": 401,
        "permission": 403,
        "invalid_request": 400,
        "unavailable": 503,
    }

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/v1/responses"
        if failure == "timeout":
            raise httpx.ReadTimeout(PRIVATE, request=request)
        if failure == "connection":
            raise httpx.ConnectError(PRIVATE, request=request)
        if failure == "bad_body":
            return httpx.Response(200, content=("{" + PRIVATE).encode())
        if failure in status_codes:
            return httpx.Response(
                status_codes[failure],
                json={
                    "error": {
                        "message": PRIVATE,
                        "code": "insufficient_quota" if failure == "quota" else PRIVATE,
                    },
                },
            )
        return httpx.Response(200, json=body)

    gateway = (
        OpenAIConversationModel(settings, ledger=ledger)
        if lane == "chat"
        else OpenAIGoalModel(settings, ledger)
    )
    await gateway._client.close()
    gateway._client = AsyncOpenAI(
        api_key="synthetic-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    try:
        if failure is None:
            if isinstance(gateway, OpenAIConversationModel):
                output = await gateway.reply(
                    instructions="Synthetic", context=CONTEXT, owner="owner"
                )
                assert output.answer == "Only saved evidence."
            else:
                decision_output = await gateway.decide(context=GOAL_CONTEXT, owner="owner")
                assert decision_output.decision.disposition == "waiting"
        else:
            with pytest.raises((InferenceProviderError, GoalModelResponseError)) as caught:
                if isinstance(gateway, OpenAIConversationModel):
                    await gateway.reply(instructions="Synthetic", context=CONTEXT, owner="owner")
                else:
                    await gateway.decide(context=GOAL_CONTEXT, owner="owner")
            assert PRIVATE not in str(caught.value)
            if isinstance(caught.value, InferenceProviderError):
                expected = "quota" if failure == "failed_without_usage" else failure
                if failure in {"invalid_json", "invalid_metadata", "incomplete", "private_status"}:
                    expected = "invalid_response"
                elif failure in {
                    "missing_usage",
                    "wrong_model",
                    "wrong_tier",
                    "fractional_usage",
                    "boolean_usage",
                    "bad_body",
                }:
                    expected = "unknown_usage"
                assert caught.value.kind == expected
                assert PRIVATE not in inference_failure_message(caught.value)
                assert caught.value.http_status == status_codes.get(failure)
            else:
                assert isinstance(caught.value, GoalModelResponseError)
                assert caught.value.provider_status in {None, "incomplete"}
                assert caught.value.incomplete_reason is None
        assert len(requests) == 1 and gateway._client.max_retries == 0
        async with database.session_factory() as session:
            receipts = list((await session.scalars(select(CostReservationRow))).all())
        assert len(receipts) == 1
        known = failure in {
            None,
            "invalid_json",
            "invalid_metadata",
            "incomplete",
            "private_status",
        }
        assert (receipts[0].actual is not None) == known
        usage = (await ledger.periods())[0].usage
        reserved_cost = receipts[0].usage["llm_microusd"]
        assert isinstance(reserved_cost, int)
        assert usage.llm_calls == usage.provider_requests == 1
        if known:
            assert usage.input_tokens == 100 and usage.output_tokens == 50
            assert usage.llm_microusd < reserved_cost
        else:
            assert usage.llm_microusd == reserved_cost
        assert PRIVATE not in caplog.text
    finally:
        await gateway.close()
        await database.dispose()


async def test_typed_goal_failure_keeps_durable_hold_and_blocks_controls_without_reissue(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path / "goal.db")
    app = create_app()
    requests: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(
            429, json={"error": {"code": "insufficient_quota", "message": PRIVATE}}
        )

    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        gateway = OpenAIGoalModel(get_settings(), app.state.operation_cost_ledger)
        await gateway._client.close()
        gateway._client = AsyncOpenAI(
            api_key="synthetic-only",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )
        source = AsyncMock(
            side_effect=AssertionError("A failed inference cannot authorize a source")
        )
        monkeypatch.setattr(service._admin, "run_now", source)
        service._model, service._continuing_model = gateway, None
        saved = await goal(service, budget=450000)
        try:
            assert await service.tick()
            stopped = await service.repository.get("alice", saved.goal_id)
            assert stopped.status == "waiting" and stopped.unsettled_microusd > 0
            assert stopped.accounted_microusd == stopped.unsettled_microusd
            assert stopped.request == saved.request and stopped.limit_stop is None
            assert (
                "баланса или расходов" in stopped.waiting_reason
                and PRIVATE not in stopped.model_dump_json()
            )
            with pytest.raises(ChatError):
                await service.command(
                    "alice", stopped.goal_id, extension(stopped, steps=6, budget=450000)
                )
            with pytest.raises(ChatError):
                await service.command(
                    "alice",
                    stopped.goal_id,
                    GoalCommand(
                        request_id=uuid4(),
                        command="resume",
                        expected_revision=stopped.revision,
                    ),
                )
            assert not await service.tick()
            assert requests == ["/v1/responses"]
            source.assert_not_awaited()
        finally:
            await gateway.close()
    get_settings.cache_clear()


async def test_chat_failure_is_private_safe_and_idempotent_without_another_model_call(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path / "chat.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_chat_service
        model = AsyncMock()
        model.reply.side_effect = InferenceProviderError("permission", http_status=403)
        service._model, service._streaming_model = model, None
        topic = await service.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Failure")
        )
        message = MessageCreate(
            request_id=uuid4(), message="Analyze supplied evidence without new sources."
        )
        result = await service.send("alice", topic.topic_id, message)
        assert result.status == "failed" and result.next_action == "none"
        assert "Нужна проверка прав" in result.answer and PRIVATE not in result.model_dump_json()
        assert await service.send("alice", topic.topic_id, message) == result
        assert model.reply.call_count == 1
    get_settings.cache_clear()
