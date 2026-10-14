"""SDK/SQL review-stage diagnostics are offline unless separately opted in."""

import json
import sys
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from openai import AsyncOpenAI
from pytest import CaptureFixture, MonkeyPatch

from app.core.config import Settings
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from scripts import operation_review_verdict_evaluate as exercise
from scripts.operation_catalog_goal_evaluate import REPORT
from tests.test_goal_review_verdict import verdict
from tests.test_inference_failures import wire


def test_plan_only_never_loads_settings_or_promises_full_acceptance(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    def forbidden() -> None:
        raise AssertionError("Plan-only diagnostics must not load credentials")

    monkeypatch.setattr(exercise, "get_settings", forbidden)
    monkeypatch.setattr(sys, "argv", ["operation_review_verdict_evaluate.py"])
    exercise.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan["shared_budget_microusd"] == 490000 and plan["max_calls"] == 2
    assert plan["stage_only"] and not plan["full_workflow_acceptance"]
    assert plan["source_attempts"] == plan["production_changes"] == 0
    assert not plan["replay"] and plan["semantic_review"] == "pending"


async def test_exclusive_attempt_refuses_before_settings_or_model(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden() -> None:
        raise AssertionError("A stopped attempt cannot load credentials or be resumed")

    monkeypatch.setattr(exercise, "get_settings", forbidden)
    with pytest.raises(FileExistsError):
        await exercise.evaluate(tmp_path)


def test_both_cases_keep_the_entire_original_task_and_source() -> None:
    cases = exercise.cases()
    left, right = (exercise.reviewing_goal(case) for case in cases)
    assert left.request.objective == right.request.objective
    assert left.request.success_criteria == right.request.success_criteria
    assert left.request.constraints == right.request.constraints
    assert left.request.max_steps == right.request.max_steps == 12
    assert left.request.budget_microusd == right.request.budget_microusd == 490000
    assert left.evidence[0].summary == right.evidence[0].summary == REPORT
    assert len(left.evidence[0].summary) == 7607 and not left.evidence[0].shortened
    assert right.result == left.result.replace(exercise.CORRECT_POOLED, exercise.INCORRECT_POOLED)
    assert left.goal_id != right.goal_id and left.request.request_id != right.request.request_id
    assert left.model_continuation is right.model_continuation is None
    for goal in (left, right):
        text = exercise.context(goal)
        assert "expected_verdict" not in text and "oracle" not in text
        assert "EXACT CATALOG QUALITY FOOTER" in text
        assert goal.request.analysis_scope == "saved_snapshot"
        assert goal.review_verdict_enabled and goal.read_attempted is False
        assert goal.approved_capability is None and not goal.limit_grants and not goal.tools


@pytest.mark.parametrize(
    "failure", [None, "false_accept", "bad_hash", "incomplete", "pending", "timeout", "quota"]
)
async def test_shared_budget_full_input_separate_verdict_and_unknown_stop(
    monkeypatch: MonkeyPatch, tmp_path: Path, failure: str | None
) -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="fixture",
        operation_goals_request_timeout_seconds=210,
        operation_goals_model_step_timeout_seconds=240,
    )
    monkeypatch.setattr(exercise, "get_settings", lambda: settings)
    requests: list[dict[str, Any]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openai.com" and request.url.path == "/v1/responses"
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["store"] is False and payload["service_tier"] == "default"
        assert payload["model"] == "gpt-6.1-sol" and payload["reasoning"] == {"effort": "medium"}
        assert payload["max_output_tokens"] == 8192 and "tools" not in payload
        assert payload["text"]["format"]["name"] == "GoalReviewVerdictBody"
        assert request.extensions["timeout"]["read"] == 210
        if failure == "timeout":
            raise httpx.ReadTimeout("PRIVATE timeout body", request=request)
        if failure == "quota":
            return httpx.Response(
                429, json={"error": {"code": "insufficient_quota", "message": "PRIVATE quota"}}
            )
        current = json.loads(payload["input"][-1]["content"])
        assert current["goal"]["evidence"][0]["summary"] == REPORT
        assert current["goal"]["request"]["success_criteria"] == (
            exercise.reviewing_goal(exercise.cases()[0]).request.success_criteria
        )
        assert current["allowed_read_capabilities"] == []
        assert "expected_verdict" not in json.dumps(current) and "oracle" not in current
        descriptors = current.pop("review_contract")
        frozen = json.dumps(current, ensure_ascii=False)
        incorrect = exercise.INCORRECT_POOLED in current["goal"]["result"]
        reviewed = verdict(
            frozen,
            disposition="accepted" if not incorrect or failure == "false_accept" else "revise",
        ).model_dump()
        reviewed["input_sha256"] = descriptors["input_sha256"]
        if failure == "bad_hash":
            reviewed["draft_sha256"] = "0" * 64
        body = wire("gpt-6.1-sol", "goal")
        body["output"][0]["content"][0]["text"] = json.dumps(reviewed)
        if failure == "incomplete":
            body.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        elif failure == "pending":
            body["status"] = "in_progress"
            body["usage"].update(input_tokens=0, output_tokens=0, total_tokens=0)
        return httpx.Response(200, json=body)

    client = AsyncOpenAI(
        api_key="fixture",
        max_retries=0,
        timeout=210,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )

    def model_class(*args: Any, **kwargs: Any) -> OpenAIGoalModel:
        model = actual_class(*args, **kwargs)
        model._client = client
        return model

    actual_class = OpenAIGoalModel
    monkeypatch.setattr(exercise, "OpenAIGoalModel", model_class)
    output = tmp_path / "new-party"
    result = cast(dict[str, Any], await exercise.evaluate(output))
    expected_calls = 1 if failure in {"pending", "timeout", "quota"} else 2
    assert len(requests) == result["receipts"]["calls"] == expected_calls
    assert result["stage_only"] and not result["full_workflow_acceptance"]
    assert result["semantic_review"] == "pending"
    assert result["receipts"]["known_microusd"] <= 490000
    assert (result["receipts"]["unknown_hold_microusd"] > 0) == (expected_calls == 1)
    assert "PRIVATE" not in (output / "result.json").read_text()
    if failure in {None, "false_accept"}:
        assert result["cases"][0]["mechanical_expected_verdict"] is True
        assert result["cases"][1]["mechanical_expected_verdict"] == (failure is None)
        for case in result["cases"]:
            assert "model_continuation" not in case
    elif failure in {"bad_hash", "incomplete"}:
        assert all(case["status"] == "output_failure" for case in result["cases"])
    else:
        assert result["cases"][0]["status"] == "provider_failure"
