"""Nonterminal provider usage is not a final receipt in any operational lane."""

import json
from pathlib import Path
from typing import Literal, cast

import httpx
import pytest
from openai import AsyncOpenAI
from sqlalchemy import select

from app.core.config import Settings
from app.mana_operation_ai.application.goal_ports import GoalModelResponseError
from app.mana_operation_ai.application.inference_errors import (
    InferencePendingStatus,
    InferenceProviderError,
    inference_failure_message,
)
from app.mana_operation_ai.domain.cost_control import ResourceUsage
from app.mana_operation_ai.infrastructure.chat_model import OpenAIConversationModel
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from app.mana_operation_ai.infrastructure.inference_usage import pending_usage_status
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import CostReservationRow
from tests.test_inference_failures import GOAL_CONTEXT, PRIVATE, wire
from tests.test_operation_chat_costs import CONTEXT, policy
from tests.test_operation_cost_ledger import Clock


@pytest.mark.parametrize("untrusted", [PRIVATE, "completed", True, {"status": "queued"}, None])
def test_pending_diagnostic_refuses_nonclosed_values(untrusted: object) -> None:
    error = InferenceProviderError(
        "unknown_usage", pending_status=cast(InferencePendingStatus | None, untrusted)
    )
    assert error.pending_status is None
    assert "provider_status=" not in inference_failure_message(error)
    assert PRIVATE not in inference_failure_message(error)
    assert pending_usage_status({"status": untrusted}) is None


def test_pending_diagnostic_does_not_relabel_other_failure_kinds() -> None:
    error = InferenceProviderError("permission", pending_status="queued")
    assert error.pending_status is None
    assert "provider_status=" not in inference_failure_message(error)
    assert pending_usage_status({"status": "queued"}) == "queued"
    assert pending_usage_status({"status": "in_progress"}) == "in_progress"


@pytest.mark.parametrize("lane", ["goal", "chat", "stream"])
@pytest.mark.parametrize("status", ["queued", "in_progress"])
@pytest.mark.parametrize("zero_usage", [False, True])
async def test_pending_receipt_never_settles_or_refunds_any_operational_request(
    tmp_path: Path, lane: Literal["goal", "chat", "stream"], status: str, zero_usage: bool
) -> None:
    database = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'pending.db'}")
    await database.create_schema()
    ledger = SqlAlchemyCostLedger(database, clock=Clock(), limits=policy())
    settings = Settings(_env_file=None, openai_api_key="fixture")
    gateway = (
        OpenAIGoalModel(settings, ledger)
        if lane == "goal"
        else OpenAIConversationModel(settings, ledger=ledger)
    )
    model = (
        settings.operation_goals_model
        if lane == "goal"
        else settings.effective_operation_chat_model
    )
    body = wire(model, "goal" if lane == "goal" else "chat")
    body["status"] = status
    body["error"] = {"message": PRIVATE, "code": PRIVATE}
    if zero_usage:
        body["usage"] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }
    requests: list[str] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if lane == "stream":
            # A named completion event cannot make its nonterminal payload final.
            event = {"type": "response.completed", "sequence_number": 0, "response": body}
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=("event: response.completed\ndata: " + json.dumps(event) + "\n\n").encode(),
            )
        return httpx.Response(200, json=body)

    await gateway._client.close()
    gateway._client = AsyncOpenAI(
        api_key="fixture",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    try:
        with pytest.raises((InferenceProviderError, GoalModelResponseError)) as caught:
            if isinstance(gateway, OpenAIGoalModel):
                await gateway.decide(context=GOAL_CONTEXT, owner="owner")
            elif lane == "chat":
                await gateway.reply(instructions="Synthetic", context=CONTEXT, owner="owner")
            else:
                async for _ in gateway.stream_reply(
                    instructions="Synthetic", context=CONTEXT, owner="owner"
                ):
                    pytest.fail("A pending receipt must not publish a final answer")
        assert isinstance(caught.value, InferenceProviderError)
        assert caught.value.kind == "unknown_usage" and PRIVATE not in str(caught.value)
        assert caught.value.pending_status == status
        async with database.session_factory() as session:
            rows = list(await session.scalars(select(CostReservationRow)))
        assert len(rows) == 1 and rows[0].actual is None
        hold = ResourceUsage.model_validate(rows[0].usage)
        assert hold.llm_microusd > 0
        periods = await ledger.periods()
        assert all(period.usage.llm_microusd == hold.llm_microusd for period in periods)
        assert requests == ["/v1/responses"] and gateway._client.max_retries == 0
    finally:
        await gateway.close()
        await database.dispose()
