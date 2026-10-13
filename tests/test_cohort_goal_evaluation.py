"""An independent historical quality case, offline by default and source-free."""

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI
from pytest import CaptureFixture, MonkeyPatch

from app.core.config import Settings
from app.mana_operation_ai.domain.goals import GoalDecisionBody, GoalTask
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from scripts import operation_cohort_goal_evaluate as exercise
from tests.test_inference_failures import wire


def test_oracle_recomputes_weighted_parent_metrics_without_changing_the_objective() -> None:
    result = exercise.oracle()
    assert result["d1_a_pct"] == "60.00"
    assert result["d7_a_pct"] == "20.00" and result["d7_b_pct"] == "60.00"
    assert result["pooled_d7_pct"] == "24.00" and result["unweighted_mean_is_wrong_pct"] == "40.00"
    assert result["purchase_conversion_pct"] == "15.00"
    assert result["funnel_transitions"] == [
        {"from": 900, "to": 720, "conversion_pct": "80.00", "lost": 180},
        {"from": 720, "to": 360, "conversion_pct": "50.00", "lost": 360},
        {"from": 360, "to": 270, "conversion_pct": "75.00", "lost": 90},
        {"from": 270, "to": 135, "conversion_pct": "50.00", "lost": 135},
    ]
    assert exercise.plan()["analysis_scope"] == "saved_snapshot"
    assert "SYNTHETIC EVALUATION ONLY" in exercise.REPORT
    assert "D7 in [168h,192h)" in exercise.REPORT


def test_default_plan_never_loads_credentials_or_a_model(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    def forbidden() -> None:
        raise AssertionError("Plan-only inspection cannot read credentials")

    monkeypatch.setattr(exercise, "get_settings", forbidden)
    monkeypatch.setattr(sys, "argv", ["operation_cohort_goal_evaluate.py"])
    exercise.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan["max_calls"] == 6 and plan["budget_microusd"] == 490000
    assert plan["source_attempts"] == plan["production_changes"] == 0
    assert not plan["replay"]


async def test_existing_attempt_cannot_reload_settings_or_recreate_a_goal(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    def forbidden() -> None:
        raise AssertionError("Existing exclusive marker cannot reauthenticate")

    monkeypatch.setattr(exercise, "get_settings", forbidden)
    with pytest.raises(FileExistsError):
        await exercise.evaluate(tmp_path)


@pytest.mark.parametrize("failure", [None, "quota", "incomplete"])
async def test_native_sdk_fixture_uses_the_same_goal_scope_and_independent_review(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    failure: str | None,
) -> None:
    settings = Settings(_env_file=None, openai_api_key="test-synthetic-only")
    monkeypatch.setattr(exercise, "get_settings", lambda: settings)
    requests: list[dict[str, Any]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        requests.append(data)
        assert data["model"] == "gpt-6.1-sol" and data["max_output_tokens"] == 8192
        assert data["store"] is False and data["service_tier"] == "default"
        if failure == "quota":
            return httpx.Response(
                429, json={"error": {"code": "insufficient_quota", "message": "PRIVATE quota body"}}
            )
        body = wire("gpt-6.1-sol", "goal")
        if failure == "incomplete":
            body["status"] = "incomplete"
            body["incomplete_details"] = {"reason": "max_output_tokens"}
        elif len(requests) == 1:
            body["output"] = [
                {
                    "id": "fc_fake",
                    "type": "function_call",
                    "name": "read_saved_report",
                    "call_id": "call_fake",
                    "arguments": json.dumps({"report_id": exercise.REPORT_ID}),
                }
            ]
        else:
            review = len(requests) == 4
            decision = GoalDecisionBody(
                update="Synthetic SDK fixture, not a model-quality grade.",
                plan=[
                    GoalTask(
                        title="Analyze all original criteria", status="done" if review else "active"
                    )
                ],
                draft=f"Synthetic dated facts only; {exercise.REPORT_ID}; 2026-09-23.",
                evidence_ids=[exercise.REPORT_ID],
                disposition="accepted" if review else "continue",
                missing_information="",
                requested_capability=None,
            )
            body["output"][0]["content"][0]["text"] = decision.model_dump_json()
        return httpx.Response(200, json=body)

    class SyntheticSDK(OpenAIGoalModel):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            previous = self._client
            self._client = AsyncOpenAI(
                api_key="test-synthetic-only",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
            )
            # It has not dispatched: close both the default client and synthetic one.
            self.unused_client = previous

        async def close(self) -> None:
            await self.unused_client.close()
            await super().close()

    async def forbidden(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("The SDK fixture attempted the real network")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(exercise, "OpenAIGoalModel", SyntheticSDK)
    result = await exercise.evaluate(tmp_path / "party")
    assert result["source_attempts"] == result["production_changes"] == 0
    assert result["original_request_retained"] and result["semantic_review"] == "pending"
    goal = result["goal"]
    assert isinstance(goal, dict) and goal["request"]["analysis_scope"] == "saved_snapshot"
    assert goal["limit_tracking"] and not goal["limit_grants"]
    assert not goal["read_attempted"] and not goal["approved_capability"]
    assert "PRIVATE" not in json.dumps(result)
    accounting = result["accounting"]
    assert isinstance(accounting, dict) and accounting["calls"] == len(requests)
    if failure:
        assert len(requests) == 1 and goal["status"] == "waiting"
        assert (accounting["unknown_hold_microusd"] > 0) == (failure == "quota")
        assert (goal["unsettled_microusd"] > 0) == (failure == "quota")
    else:
        assert len(requests) == 4 and goal["status"] == "completed" and goal["phase"] == "review"
        assert accounting["unknown_hold_microusd"] == goal["unsettled_microusd"] == 0
        assert len(goal["evidence"]) == 1 and not goal["evidence"][0]["shortened"]
        last_input = json.dumps(requests[-1]["input"], ensure_ascii=False)
        assert (
            goal["request"]["objective"] in last_input
            and goal["request"]["constraints"] in last_input
        )
        assert "tools" not in requests[-1]
    assert settings.operation_agent_workspace_enabled is False
