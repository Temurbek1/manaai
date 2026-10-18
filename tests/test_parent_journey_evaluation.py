"""Two saved SQL sources and the real SDK boundary, always mock HTTP in tests."""

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI
from pytest import CaptureFixture, MonkeyPatch

from app.core.config import Settings
from app.mana_operation_ai.domain.goals import GoalDecisionBody, GoalTask, OperationGoal
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from scripts import operation_parent_journey_evaluate as exercise
from tests.test_goal_review_verdict import verdict
from tests.test_inference_failures import wire


def test_two_report_oracle_requires_weighted_cohorts_and_noncausal_payment_join() -> None:
    result = exercise.oracle()
    assert result["payment_conversion_pct"] == "15.00"
    assert result["d1_a_pct"] == "60.00" and result["d7_a_pct"] == "30.00"
    assert result["d7_b_pct"] == "60.00" and result["pooled_d7_pct"] == "37.50"
    assert result["payer_d7_pct"] == "59.26" and result["nonpayer_d7_pct"] == "24.84"
    assert result["payer_nonpayer_difference_pp"] == "34.42"
    assert "59.26" not in exercise.RETENTION and "37.50" not in exercise.RETENTION
    assert exercise.COHORT in exercise.FUNNEL and exercise.COHORT in exercise.RETENTION
    assert "FICTIONAL transaction ledger" in exercise.FUNNEL
    assert "selection/confounding" in exercise.RETENTION
    assert exercise.request().analysis_scope == "saved_snapshot"
    fixtures = exercise.plan()["fixtures"]
    assert isinstance(fixtures, dict) and len(fixtures) == 2


def test_default_plan_cannot_load_credentials_or_dispatch(
    monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    def forbidden() -> None:
        raise AssertionError("Offline plan cannot authenticate")

    monkeypatch.setattr(exercise, "get_settings", forbidden)
    monkeypatch.setattr(sys, "argv", ["operation_parent_journey_evaluate.py"])
    exercise.main()
    result = json.loads(capsys.readouterr().out)
    assert result["max_calls"] == 8 and result["budget_microusd"] == 490000
    assert result["source_attempts"] == result["production_changes"] == 0
    assert result["workspace_contract"] == "v14/v5" and not result["replay"]


async def test_old_or_lost_attempt_cannot_authenticate_or_recreate_a_goal(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden() -> None:
        raise AssertionError("Existing exclusive marker must stop first")

    monkeypatch.setattr(exercise, "get_settings", forbidden)
    with pytest.raises(FileExistsError):
        await exercise.evaluate(tmp_path)


@pytest.mark.parametrize("failure", [None, "timeout", "pending", "incomplete", "quota"])
async def test_two_source_native_sql_sdk_loop_keeps_review_costs_and_replay_bound(
    monkeypatch: MonkeyPatch, tmp_path: Path, failure: str | None
) -> None:
    settings = Settings(_env_file=None, openai_api_key="test-journey-only")
    monkeypatch.setattr(exercise, "get_settings", lambda: settings)
    requests: list[dict[str, Any]] = []
    transport_errors: list[Exception] = []
    loaded: list[str] = []
    review_drafts: list[str] = []

    def reply(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url.host == "api.openai.com" and request.url.path == "/v1/responses"
        assert payload["model"] == "gpt-6.1-sol"
        assert payload["reasoning"] == {"effort": "medium"}
        assert payload["store"] is False and payload["service_tier"] == "default"
        assert payload["max_output_tokens"] == 8192
        assert payload["context_management"] == [{"type": "compaction", "compact_threshold": 24000}]
        text = json.dumps(payload, ensure_ascii=False)
        assert "oracle_not_model_input" not in text and "semantic_checks" not in text
        if failure == "timeout":
            raise httpx.ReadTimeout("PRIVATE synthetic timeout", request=request)
        if failure == "quota":
            return httpx.Response(
                429, json={"error": {"code": "insufficient_quota", "message": "PRIVATE"}}
            )
        body = wire("gpt-6.1-sol", "goal")
        if failure in {"pending", "incomplete"}:
            body["status"] = "in_progress" if failure == "pending" else "incomplete"
            if failure == "incomplete":
                body["incomplete_details"] = {"reason": "max_output_tokens"}
            return httpx.Response(200, json=body)
        current = next(item for item in reversed(payload["input"]) if item.get("role") == "user")
        context = json.loads(current["content"])
        goal = OperationGoal.model_validate(context["goal"])
        assert goal.review_verdict_enabled and goal.request.analysis_scope == "saved_snapshot"
        assert goal.request.objective == exercise.request().objective
        name, arguments = "", {}
        if not goal.tools:
            name = "inspect_sources"
        elif len(goal.evidence) < 2:
            catalog = json.loads(goal.tools[0].result)
            assert {item["report_id"] for item in catalog["saved_reports"]} == {
                exercise.FUNNEL_ID,
                exercise.RETENTION_ID,
            }
            report_id = next(
                identifier
                for identifier in (exercise.FUNNEL_ID, exercise.RETENTION_ID)
                if identifier not in loaded
            )
            name, arguments = "read_saved_report", {"report_id": report_id}
            loaded.append(report_id)
        if name:
            body["output"] = [
                {
                    "type": "function_call",
                    "id": f"fc-{len(requests)}",
                    "call_id": f"call-{len(requests)}",
                    "name": name,
                    "arguments": json.dumps(arguments),
                }
            ]
        elif goal.phase == "review":
            assert {item.report_id: item.summary for item in goal.evidence} == {
                exercise.FUNNEL_ID: exercise.FUNNEL,
                exercise.RETENTION_ID: exercise.RETENTION,
            }
            assert all(not item.shortened for item in goal.evidence)
            review_drafts.append(goal.result)
            assert "tools" not in payload
            context.pop("review_contract")
            body["output"][0]["content"][0]["text"] = verdict(
                json.dumps(context, ensure_ascii=False)
            ).model_dump_json()
        else:
            body["output"][0]["content"][0]["text"] = GoalDecisionBody(
                update="Synthetic protocol only, not semantic acceptance.",
                plan=[
                    GoalTask(title=title, status="active")
                    for title in [
                        "Read both reports",
                        "Analyze complete journey",
                        "Review every criterion",
                    ]
                ],
                draft="Synthetic 2026-09-29 journey; no measured lift. Both saved source IDs: "
                + exercise.FUNNEL_ID
                + ", "
                + exercise.RETENTION_ID,
                evidence_ids=[exercise.FUNNEL_ID, exercise.RETENTION_ID],
                disposition="continue",
                missing_information="",
                requested_capability=None,
            ).model_dump_json()
        return httpx.Response(200, json=body)

    def transport(request: httpx.Request) -> httpx.Response:
        try:
            return reply(request)
        except httpx.ReadTimeout:
            raise
        except Exception as error:
            transport_errors.append(error)
            raise

    class SyntheticSDK(OpenAIGoalModel):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.unused_client = self._client
            self._client = AsyncOpenAI(
                api_key="test-journey-only",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
            )

        async def close(self) -> None:
            await self.unused_client.close()
            await super().close()

    async def forbidden(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("Unit tests cannot use the real network")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(exercise, "OpenAIGoalModel", SyntheticSDK)
    result = await exercise.evaluate(tmp_path / "new-party")
    assert not transport_errors, transport_errors
    assert result["semantic_review"] == "pending" and result["exact_replay_observed"]
    assert result["original_request_retained"]
    assert result["source_attempts"] == result["production_changes"] == 0
    assert "PRIVATE" not in json.dumps(result)
    goal, accounting = result["goal"], result["accounting"]
    assert isinstance(goal, dict) and isinstance(accounting, dict)
    assert accounting["calls"] == len(requests) <= 8
    assert goal["limit_tracking"] and not goal["limit_grants"]
    assert not goal["read_attempted"] and not goal["approved_capability"]
    if failure:
        assert len(requests) == 1 and goal["status"] == "waiting"
        assert (accounting["unknown_hold_microusd"] > 0) == (failure != "incomplete")
        assert (goal["unsettled_microusd"] > 0) == (failure != "incomplete")
    else:
        assert len(requests) == 6 and goal["status"] == "completed"
        assert goal["review_receipt"] is not None and len(review_drafts) == 1
        assert goal["result"] == review_drafts[0]
        assert len(goal["evidence"]) == 2 and not accounting["unknown_hold_microusd"]
        assert not goal["unsettled_microusd"]
    assert settings.operation_agent_workspace_enabled is False
