"""New native catalog diagnostic: isolated SQL + real SDK/mock HTTP, never paid tests."""

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI
from pytest import CaptureFixture, MonkeyPatch

from app.core.config import Settings
from app.mana_operation_ai.application.goal_service import OperationGoalService
from app.mana_operation_ai.domain.goals import GoalDecisionBody, GoalTask, OperationGoal
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from scripts import operation_catalog_goal_evaluate as exercise
from tests.test_goal_review_verdict import verdict
from tests.test_inference_failures import wire


def test_new_fixture_is_full_historical_scope_and_oracle_is_not_model_input() -> None:
    oracle = exercise.oracle()
    assert oracle["d1_a_pct"] == "65.00" and oracle["d7_a_pct"] == "25.00"
    assert oracle["d7_b_pct"] == "50.00" and oracle["pooled_d7_pct"] == "30.00"
    assert oracle["purchase_conversion_pct"] == "17.00"
    transitions = oracle["funnel_transitions"]
    assert isinstance(transitions, list)
    assert [row["lost"] for row in transitions] == [120, 340, 68, 136]
    assert len(exercise.REPORT) > 5000
    assert exercise.REPORT.index("520 D1 returns") > 5000
    assert exercise.plan()["workspace_contract"] == "v11/v2"
    assert "30.00" not in exercise.REPORT and "17.00" not in exercise.REPORT


def test_offline_default_does_not_load_credentials_or_start_a_workflow(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    def forbidden() -> None:
        raise AssertionError("Plan-only inspection must not load settings")

    monkeypatch.setattr(exercise, "get_settings", forbidden)
    monkeypatch.setattr(sys, "argv", ["operation_catalog_goal_evaluate.py"])
    exercise.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan["budget_microusd"] == 490000 and plan["max_calls"] == 12
    assert plan["source_attempts"] == plan["production_changes"] == 0
    assert not plan["replay"]


async def test_exclusive_attempt_marker_prevents_settings_or_model_recreation(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden() -> None:
        raise AssertionError("An existing attempt must not be reused")

    monkeypatch.setattr(exercise, "get_settings", forbidden)
    with pytest.raises(FileExistsError):
        await exercise.evaluate(tmp_path)


@pytest.mark.parametrize("contract", ["legacy", "pages", "verdicts"])
@pytest.mark.parametrize("failure", [None, "quota", "incomplete", "timeout"])
async def test_native_catalog_sdk_diagnostic_retains_full_scope_and_usage_fences(
    monkeypatch: MonkeyPatch, tmp_path: Path, failure: str | None, contract: str
) -> None:
    project_pages = contract != "legacy"
    review_verdicts = contract == "verdicts"
    settings = Settings(
        _env_file=None,
        openai_api_key="fixture",
        operation_goals_request_timeout_seconds=210,
        operation_goals_model_step_timeout_seconds=240,
    )
    monkeypatch.setattr(exercise, "get_settings", lambda: settings)
    requests: list[dict[str, Any]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.openai.com"
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.extensions["timeout"]["read"] == 210
        if failure == "timeout":
            raise httpx.ReadTimeout("PRIVATE timeout body", request=request)
        if failure == "quota":
            return httpx.Response(
                429,
                json={"error": {"code": "insufficient_quota", "message": "PRIVATE quota message"}},
            )
        body = wire("gpt-6.1-sol", "goal")
        if failure == "incomplete":
            body.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
            return httpx.Response(200, json=body)
        current = next(item for item in reversed(payload["input"]) if item.get("role") == "user")
        goal = OperationGoal.model_validate(json.loads(current["content"])["goal"])
        assert goal.report_discovery_enabled and goal.request.analysis_scope == "saved_snapshot"
        assert "oracle_not_model_input" not in current["content"]
        name, arguments = "", {}
        if not goal.tools:
            name = "inspect_sources"
        elif not goal.evidence:
            last = json.loads(goal.tools[-1].result)
            if last["saved_reports"]:
                name = "read_saved_report"
                arguments = {"report_id": last["saved_reports"][0]["report_id"]}
            else:
                name = "find_saved_reports"
                arguments = {"query": "", "cursor": last["next_cursor"], "catalog_capability": None}
        elif goal.evidence[0].shortened:
            progress = goal.evidence[0].report_read_progress
            name = "read_saved_report_page"
            arguments = {
                "report_id": exercise.REPORT_ID,
                "offset": progress.next_offset if progress else 0,
            }
        if name:
            body["output"] = [
                {
                    "id": f"fc-{len(requests)}",
                    "type": "function_call",
                    "name": name,
                    "call_id": f"call-{len(requests)}",
                    "arguments": json.dumps(arguments),
                }
            ]
        elif goal.review_verdict_enabled and goal.phase == "review":
            original = json.loads(current["content"])
            original.pop("review_contract")
            reviewed = verdict(json.dumps(original, ensure_ascii=False))
            body["output"][0]["content"][0]["text"] = reviewed.model_dump_json()
        else:
            assert goal.evidence[0].summary == exercise.REPORT
            review = goal.phase == "review"
            decision = GoalDecisionBody(
                update="Fake workflow, not a quality grade.",
                plan=[
                    GoalTask(title=title, status="done" if review else "active")
                    for title in [
                        "Read full report",
                        "Compute all metrics",
                        "Review original criteria",
                    ]
                ],
                draft=f"Dated synthetic analysis only; {exercise.REPORT_ID}; 2026-09-25.",
                evidence_ids=[exercise.REPORT_ID],
                disposition="accepted" if review else "continue",
                missing_information="",
                requested_capability=None,
            )
            body["output"][0]["content"][0]["text"] = decision.model_dump_json()
        body["output"].insert(
            0,
            {
                "type": "compaction",
                "id": f"cmp-{len(requests)}",
                "encrypted_content": "fixture-private-continuation",
            },
        )
        return httpx.Response(200, json=body)

    class SyntheticSDK(OpenAIGoalModel):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.unused_client = self._client
            self._client = AsyncOpenAI(
                api_key="fixture",
                max_retries=0,
                timeout=self._settings.operation_goals_request_timeout_seconds,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
            )

        async def close(self) -> None:
            await self.unused_client.close()
            await super().close()

    async def forbidden(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("A test attempted the real network")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(exercise, "OpenAIGoalModel", SyntheticSDK)

    class CapturedService(OperationGoalService):
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["model_step_timeout_seconds"] == 240
            super().__init__(**kwargs)

    monkeypatch.setattr(exercise, "OperationGoalService", CapturedService)
    result = await exercise.evaluate(
        tmp_path / "independent", project_pages=project_pages, review_verdicts=review_verdicts
    )
    configuration = json.loads((tmp_path / "independent/runtime-configuration.json").read_text())
    assert configuration == {
        "model_request_timeout_seconds": 210,
        "model_step_timeout_seconds": 240,
        "sdk_max_retries": 0,
    }
    assert result["semantic_review"] == "pending" and result["original_request_retained"]
    assert result["production_changes"] == result["source_attempts"] == 0
    assert "PRIVATE" not in json.dumps(result)
    goal = result["goal"]
    assert isinstance(goal, dict) and goal["report_discovery_enabled"]
    assert goal["page_projection_enabled"] == project_pages
    assert (
        not goal["read_attempted"] and not goal["approved_capability"] and not goal["limit_grants"]
    )
    accounting = result["accounting"]
    assert isinstance(accounting, dict) and accounting["calls"] == len(requests)
    if failure:
        assert len(requests) == 1 and goal["status"] == "waiting"
        assert (accounting["unknown_hold_microusd"] > 0) == (failure in {"quota", "timeout"})
        assert (goal["unsettled_microusd"] > 0) == (failure in {"quota", "timeout"})
        if failure == "timeout":
            assert "не завершился вовремя" in goal["waiting_reason"]
    else:
        assert goal["status"] == "completed" and goal["phase"] == "review"
        assert accounting["unknown_hold_microusd"] == goal["unsettled_microusd"] == 0
        assert not goal["evidence"][0]["shortened"]
        assert goal["evidence"][0]["summary"] == exercise.REPORT
        assert [tool["call"]["name"] for tool in goal["tools"]].count("find_saved_reports") == 2
        assert "tools" not in requests[-1]
    assert settings.operation_workspace_report_discovery_enabled is False
