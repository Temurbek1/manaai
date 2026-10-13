"""Typed schema facts across the SDK/SQL boundary; never paid calls or raw input."""

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticCustomError
from pytest import MonkeyPatch
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import create_app
from app.mana_operation_ai.application.goal_ports import (
    DecisionField,
    DecisionIssueCode,
    GoalDecisionIssue,
    GoalModelResponseError,
)
from app.mana_operation_ai.domain.chat import TopicCreate
from app.mana_operation_ai.domain.goals import GoalCreate, GoalDecisionBody
from app.mana_operation_ai.infrastructure.decision_validation import (
    decision_issues,
    is_decision_validation,
)
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import CostReservationRow, GoalRow
from tests.test_inference_failures import wire
from tests.test_operation_agent_workspace import configure_workspace

PRIVATE = "PRIVATE-input-secret-identity"


def valid_decision() -> dict[str, Any]:
    return {
        "update": "Only synthetic evidence.",
        "plan": [{"title": "Retain the original request", "status": "active"}],
        "draft": "No new source or action has been executed.",
        "evidence_ids": [],
        "disposition": "continue",
        "missing_information": "",
        "requested_capability": None,
    }


@pytest.mark.parametrize(
    ("field", "value", "expected_field", "expected_code"),
    [
        ("draft", PRIVATE * 900, "draft", "string_too_long"),
        ("draft", {PRIVATE: PRIVATE}, "draft", "string_type"),
        ("plan", [{"title": PRIVATE * 40, "status": "active"}], "plan.title", "string_too_long"),
        ("plan", [{"title": "Task", "status": PRIVATE}], "plan.status", "literal_error"),
        ("plan", valid_decision()["plan"] * 9, "plan", "too_long"),
        ("disposition", PRIVATE, "disposition", "literal_error"),
        ("requested_capability", PRIVATE, "requested_capability", "literal_error"),
        (PRIVATE, PRIVATE, "decision", "extra_forbidden"),
    ],
)
def test_feedback_has_only_closed_fields_and_error_codes(
    field: str, value: object, expected_field: str, expected_code: str
) -> None:
    values = {**valid_decision(), field: value}
    with pytest.raises(ValidationError) as caught:
        GoalDecisionBody.model_validate(values)
    issues = decision_issues(caught.value)
    assert issues == (
        GoalDecisionIssue(
            cast(DecisionField, expected_field), cast(DecisionIssueCode, expected_code)
        ),
    )
    error = GoalModelResponseError(
        "Safe failure.", 123, output_failure="invalid_decision", validation_issues=issues
    )
    assert PRIVATE not in error.validation_feedback
    assert (
        expected_field in error.validation_feedback and expected_code in error.validation_feedback
    )


def test_missing_fields_are_bounded_and_invalid_json_does_not_leak() -> None:
    with pytest.raises(ValidationError) as caught:
        GoalDecisionBody.model_validate({})
    assert len(decision_issues(caught.value)) == 3
    with pytest.raises(ValidationError) as caught:
        GoalDecisionBody.model_validate_json(PRIVATE)
    assert decision_issues(caught.value) == (GoalDecisionIssue("decision", "json_invalid"),)
    custom = ValidationError.from_exception_data(
        "Synthetic",
        [{"type": PydanticCustomError(PRIVATE, PRIVATE), "loc": (PRIVATE,), "input": PRIVATE}],
    )
    assert decision_issues(custom) == ()


def test_feedback_contract_refuses_untrusted_fields_codes_and_oversized_batches() -> None:
    with pytest.raises(ValueError, match="Unrecognized"):
        GoalDecisionIssue(cast(DecisionField, PRIVATE), "missing")
    with pytest.raises(ValueError, match="Unrecognized"):
        GoalDecisionIssue("draft", cast(DecisionIssueCode, PRIVATE))
    issue = GoalDecisionIssue("draft", "string_too_long")
    with pytest.raises(ValueError):
        GoalModelResponseError(
            "Safe", 1, output_failure="invalid_decision", validation_issues=(issue,) * 4
        )
    with pytest.raises(ValueError):
        GoalModelResponseError("Safe", 1, validation_issues=(issue,))
    with pytest.raises(ValueError):
        GoalModelResponseError(
            "Safe",
            1,
            output_failure="invalid_decision",
            validation_issues=cast(tuple[GoalDecisionIssue, ...], (PRIVATE,)),
        )


async def test_sdk_metadata_validation_is_priced_but_never_queued_as_decision_correction(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    from unittest.mock import Mock

    from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
    from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
    from tests.test_goal_continuation import decision, raw_reply
    from tests.test_operation_chat_costs import policy
    from tests.test_operation_cost_ledger import Clock

    class ProviderMetadata(BaseModel):
        draft: int

    with pytest.raises(ValidationError) as caught:
        ProviderMetadata.model_validate({"draft": PRIVATE})
    assert not is_decision_validation(caught.value) and decision_issues(caught.value) == ()
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'metadata.db'}")
    await db.create_schema()
    ledger = SqlAlchemyCostLedger(db, clock=Clock(), limits=policy())
    model = OpenAIGoalModel(Settings(_env_file=None, openai_api_key="test-feedback-key"), ledger)
    raw = raw_reply(decision())
    raw.parse = Mock(side_effect=caught.value)
    parser = AsyncMock(return_value=raw)
    monkeypatch.setattr(model._client.responses.with_raw_response, "parse", parser)
    try:
        with pytest.raises(GoalModelResponseError) as failure:
            await model.decide(
                context='{"goal":{"product":"mana","agent_id":"operations-orchestrator"}}',
                owner="alice",
            )
        assert failure.value.actual_microusd > 0 and failure.value.output_failure is None
        assert failure.value.validation_issues == () and PRIVATE not in str(failure.value)
        assert parser.call_count == 1
    finally:
        await model.close()
        await db.dispose()


@pytest.mark.parametrize("bad_json", [False, True])
async def test_actual_sdk_schema_failure_keeps_known_usage_without_any_retry(
    tmp_path: Path, bad_json: bool
) -> None:
    from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
    from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
    from tests.test_operation_chat_costs import policy
    from tests.test_operation_cost_ledger import Clock

    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'sdk.db'}")
    await db.create_schema()
    ledger = SqlAlchemyCostLedger(db, clock=Clock(), limits=policy())
    model = OpenAIGoalModel(Settings(_env_file=None, openai_api_key="test-feedback-key"), ledger)
    calls = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        payload = wire("gpt-6.1-sol", "goal")
        payload["output"][0]["content"][0]["text"] = (
            PRIVATE if bad_json else json.dumps({**valid_decision(), "draft": PRIVATE * 900})
        )
        return httpx.Response(200, json=payload)

    await model._client.close()
    model._client = AsyncOpenAI(
        api_key="test-feedback-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    try:
        with pytest.raises(GoalModelResponseError) as caught:
            await model.decide(
                context='{"goal":{"product":"mana","agent_id":"operations-orchestrator"}}',
                owner="alice",
            )
        error = caught.value
        assert error.output_failure == "invalid_decision" and error.actual_microusd > 0
        assert error.validation_issues == (
            GoalDecisionIssue("decision", "json_invalid")
            if bad_json
            else GoalDecisionIssue("draft", "string_too_long"),
        )
        assert PRIVATE not in error.validation_feedback and PRIVATE not in str(error)
        async with db.session_factory() as session:
            rows = (await session.scalars(select(CostReservationRow))).all()
        assert len(rows) == len(calls) == 1 and rows[0].actual is not None
        assert rows[0].actual["llm_microusd"] == error.actual_microusd
    finally:
        await model.close()
        await db.dispose()


async def test_schema_feedback_survives_sql_restart_and_independent_review_without_authority(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "feedback.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    calls: list[dict[str, Any]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        calls.append(data)
        payload = wire("gpt-6.1-sol", "goal")
        if len(calls) == 1:
            payload["output"] = [
                {
                    "type": "function_call",
                    "id": "fc_fake",
                    "call_id": "call_fake",
                    "name": "inspect_sources",
                    "arguments": "{}",
                }
            ]
        else:
            body = (
                {**valid_decision(), "draft": PRIVATE * 900}
                if len(calls) == 2
                else valid_decision()
            )
            payload["output"][0]["content"][0]["text"] = json.dumps(body)
        return httpx.Response(200, json=payload)

    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        model = service._continuing_model
        assert isinstance(model, OpenAIGoalModel)
        await model._client.close()
        model._client = AsyncOpenAI(
            api_key="test-feedback-key",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )
        source = AsyncMock(side_effect=AssertionError("Schema correction cannot collect data"))
        monkeypatch.setattr(service._admin, "run_now", source)
        topic = await service._chats.create(
            "alice",
            TopicCreate(
                agent_id="operations-orchestrator", product="mana", title="Schema feedback"
            ),
        )
        original = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(),
                objective="Preserve the full analysis objective and every original condition.",
                constraints="No source reads, actions or budget changes.",
                execution_mode="agent",
            ),
        )
        assert await service.tick() and await service.tick()
        stopped = await service.repository.get("alice", original.goal_id)
        assert stopped.status == "queued" and stopped.model_recoveries == 1
        assert stopped.model_feedback and "draft: string_too_long" in stopped.model_feedback.message
        assert (
            PRIVATE not in stopped.model_dump_json() and len(stopped.model_feedback.message) <= 1000
        )
        reopened = SqlAlchemyGoalRepository(app.state.operation_database, service._clock)
        assert (
            await reopened.get("alice", original.goal_id)
        ).model_feedback == stopped.model_feedback
        async with app.state.operation_database.session_factory() as session:
            row = await session.get(GoalRow, original.goal_id)
            assert row is not None and row.workspace_payload["version"] == 7
        assert await service.tick() and await service.tick()
        final = await service.repository.get("alice", original.goal_id)
        assert final.request == original.request and final.phase == "review"
        assert await service.tick()
        final = await service.repository.get("alice", original.goal_id)
        assert len(calls) == final.steps_used == 5 and final.model_recoveries == 1
        assert not final.read_attempted and not final.approved_capability and final.evidence == []
        correction = json.dumps(calls[2]["input"], ensure_ascii=False)
        assert "draft: string_too_long" in correction and original.request.constraints in correction
        assert calls[-1]["input"] and len(calls[-1]["input"]) == 1 and "tools" not in calls[-1]
        assert original.request.objective in json.dumps(calls[-1]["input"], ensure_ascii=False)
        source.assert_not_awaited()
        assert all(row["store"] is False for row in calls)
    get_settings.cache_clear()
