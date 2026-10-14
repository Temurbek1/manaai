"""The workspace quality harness is offline by default and cannot resume a paid party."""

import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI
from pytest import MonkeyPatch

from app.core.config import Settings
from app.mana_operation_ai.domain.goals import GoalDecisionBody, GoalTask, OperationGoal
from app.mana_operation_ai.infrastructure.chat_model import OpenAIConversationModel
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from scripts import operation_workspace_evaluate as benchmark
from tests.test_inference_failures import wire


def test_pinned_workspace_cases_cover_routing_grounding_and_full_objective() -> None:
    cases = benchmark.cases()
    assert len(cases) == 8 and len({case.case_id for case in cases}) == 8
    assert sum(case.expected_action == "start_goal" for case in cases) == 2
    full = [case for case in cases if case.full_goal]
    assert len(full) == 1 and "Нужен полный анализ" in full[0].message
    assert "verified payment" in full[0].report_text
    assert any("not complete the full objective" in check for check in full[0].review_checks)
    assert sum(case.product == "360rec" for case in cases) == 1
    assert all(case.review_checks for case in cases)


def test_cli_defaults_to_pinned_plan_without_settings_sdk_or_io(
    monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden() -> None:
        raise AssertionError("Offline inspection must not load credentials or SDK clients")

    monkeypatch.setattr(benchmark, "get_settings", forbidden)
    monkeypatch.setattr(sys, "argv", ["operation_workspace_evaluate.py"])
    benchmark.main()
    result = json.loads(capsys.readouterr().out)
    assert len(result["cases"]) == 8
    assert result["max_calls"] == 16 and result["cap_microusd"] == 490000
    assert result["sources"] == 0
    assert result["tracked_limits"] is False


def test_v10_plan_is_still_offline_and_never_activates_application_flags(
    monkeypatch: MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden() -> None:
        raise AssertionError("Plan-only v10 inspection cannot load secrets or execute a source")

    monkeypatch.setattr(benchmark, "get_settings", forbidden)
    monkeypatch.setattr(sys, "argv", ["operation_workspace_evaluate.py", "--tracked-limits"])
    benchmark.main()
    result = json.loads(capsys.readouterr().out)
    assert result["tracked_limits"] is True and result["sources"] == 0
    assert result["max_calls"] == 16 and result["cap_microusd"] == 490000


@pytest.mark.parametrize("candidate_native", [False, True])
async def test_an_attempted_paid_output_cannot_be_restarted(
    monkeypatch: MonkeyPatch, tmp_path: Path, candidate_native: bool
) -> None:
    def forbidden() -> None:
        raise AssertionError("An existing attempt must stop before model construction")

    monkeypatch.setattr(benchmark, "get_settings", forbidden)
    with pytest.raises(FileExistsError):
        await benchmark.evaluate(
            tmp_path, tracked_limits=candidate_native, candidate_native=candidate_native
        )


def test_candidate_profile_is_offline_explicit_and_not_an_automatic_upgrade(
    monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden() -> None:
        raise AssertionError("Candidate plan inspection must not load settings")

    monkeypatch.setattr(benchmark, "get_settings", forbidden)
    with pytest.raises(ValueError, match="tracked limits"):
        benchmark.profile(candidate_native=True)
    monkeypatch.setattr(
        sys, "argv", ["operation_workspace_evaluate.py", "--tracked-limits", "--candidate-native"]
    )
    benchmark.main()
    result = json.loads(capsys.readouterr().out)
    assert result["workspace_contract"] == "v14/v5" and result["isolated_case_databases"]
    assert result["compact_threshold"] == 24000 and result["sources"] == 0
    assert result["max_calls"] == 16 and result["cap_microusd"] == 490000


@pytest.mark.parametrize("failure", [None, "invalid", "incomplete", "pending", "timeout", "quota"])
async def test_candidate_matrix_real_sdk_sql_sources_isolation_and_receipt_fences(
    monkeypatch: MonkeyPatch, tmp_path: Path, failure: str | None
) -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="fixture",
        operation_goals_request_timeout_seconds=210,
        operation_goals_model_step_timeout_seconds=240,
    )
    monkeypatch.setattr(benchmark, "get_settings", lambda: settings)
    requests: list[dict[str, Any]] = []
    transport_errors: list[Exception] = []
    fixed = benchmark.cases()

    def transport(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url.host == "api.openai.com" and request.url.path == "/v1/responses"
        assert payload["model"] == "gpt-6.1-sol" and payload["reasoning"] == {"effort": "medium"}
        assert payload["max_output_tokens"] == 8192 and payload["store"] is False
        serialized = json.dumps(payload, ensure_ascii=False)
        assert "review_checks" not in serialized and "expected_action" not in serialized
        assert all(case.case_id not in serialized for case in fixed)
        if failure == "timeout":
            raise httpx.ReadTimeout("PRIVATE timeout body", request=request)
        if failure == "quota":
            return httpx.Response(
                429, json={"error": {"code": "insufficient_quota", "message": "PRIVATE quota"}}
            )
        chat = isinstance(payload["input"], str)
        body = wire("gpt-6.1-sol", "chat" if chat else "goal")
        if chat:
            context = json.loads(payload["input"])
            case = next(case for case in fixed if case.message == context["message"])
            assert context["topic"]["title"] == "Independent administrative task"
            for other in fixed:
                if other != case and other.report_text:
                    assert other.report_text not in serialized
            answer = {
                "answer": "Synthetic bounded answer, not a real application measurement.",
                "plan": [],
                "next_action": case.expected_action,
            }
            body["output"][0]["content"][0]["text"] = json.dumps(answer)
        else:
            assert payload["context_management"] == [
                {"type": "compaction", "compact_threshold": 24000}
            ]
            current = next(
                item for item in reversed(payload["input"]) if item.get("role") == "user"
            )
            goal = OperationGoal.model_validate(json.loads(current["content"])["goal"])
            assert goal.review_verdict_enabled and goal.request.analysis_scope == "current"
            assert goal.request.objective == fixed[-1].message
            name, arguments = "", {}
            if not goal.tools:
                name = "inspect_sources"
            elif not goal.evidence:
                last = json.loads(goal.tools[-1].result)
                assert len(last["saved_reports"]) == 1
                name = "read_saved_report"
                arguments = {"report_id": last["saved_reports"][0]["report_id"]}
                assert arguments["report_id"].startswith("synthetic-evidence-")
            if name:
                body["output"] = [
                    {
                        "type": "function_call",
                        "id": f"fc-{len(requests)}",
                        "call_id": f"call-{len(requests)}",
                        "name": name,
                        "arguments": json.dumps(arguments),
                        "status": "completed",
                    }
                ]
            else:
                assert len(goal.evidence) == 1 and goal.evidence[0].summary == fixed[-1].report_text
                decision = GoalDecisionBody(
                    update="Partial synthetic evidence checked; original full objective retained.",
                    plan=[
                        GoalTask(title="Verified payments and complete funnel", status="blocked")
                    ],
                    draft="D1=60%; D7=28%; previous D7=40%; -12pp/-30%. No payment/funnel proof.",
                    evidence_ids=[goal.evidence[0].report_id],
                    disposition="waiting",
                    missing_information="Missing verified payments and ordered funnel.",
                    requested_capability=None,
                )
                body["output"][0]["content"][0]["text"] = decision.model_dump_json()
        if failure == "invalid":
            body["output"][0]["content"][0]["text"] = "PRIVATE invalid JSON"
        elif failure == "incomplete":
            body.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        elif failure == "pending":
            body["status"] = "in_progress"
            body["usage"].update(input_tokens=0, output_tokens=0, total_tokens=0)
        if payload.get("stream"):
            answer_text = body["output"][0]["content"][0]["text"]
            events = [
                {"type": "response.output_text.delta", "delta": answer_text},
                {
                    "type": "response.incomplete"
                    if failure == "incomplete"
                    else "response.completed",
                    "response": body,
                },
            ]
            content = "".join(
                f"event: {item['type']}\ndata: {json.dumps(item)}\n\n" for item in events
            )
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=content.encode()
            )
        return httpx.Response(200, json=body)

    def checked_transport(request: httpx.Request) -> httpx.Response:
        try:
            return transport(request)
        except Exception as exc:
            transport_errors.append(exc)
            raise

    class ChatSDK(OpenAIConversationModel):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.unused_client = self._client
            self._client = AsyncOpenAI(
                api_key="fixture",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(checked_transport)),
            )

        async def close(self) -> None:
            await self.unused_client.close()
            await super().close()

    class GoalSDK(OpenAIGoalModel):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.unused_client = self._client
            self._client = AsyncOpenAI(
                api_key="fixture",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(checked_transport)),
            )

        async def close(self) -> None:
            await self.unused_client.close()
            await super().close()

    async def forbidden(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("A test attempted a real provider")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(benchmark, "OpenAIConversationModel", ChatSDK)
    monkeypatch.setattr(benchmark, "OpenAIGoalModel", GoalSDK)
    directory = tmp_path / "new-matrix"
    await benchmark.evaluate(directory, tracked_limits=True, candidate_native=True)
    if transport_errors and failure not in {"timeout"}:
        raise transport_errors[0]
    result = json.loads((directory / "results.json").read_text())
    runtime = json.loads((directory / "runtime-configuration.json").read_text())
    assert runtime == {
        "goal_request_timeout_seconds": 210,
        "goal_step_timeout_seconds": 240,
        "goal_output_tokens": 8192,
        "chat_output_tokens": 8192,
        "compact_threshold": 24000,
        "model_window_bytes": 192000,
        "goal_context_bytes": 64000,
        "chat_context_bytes": 24000,
        "sdk_max_retries": 0,
    }
    assert result["source_attempts"] == result["production_changes"] == 0
    assert result["candidate_native"] and result["tracked_limits"]
    assert result["manual_review_required"] is True
    assert "PRIVATE" not in (directory / "results.json").read_text()
    assert result["accounting"]["calls"] == len(requests)
    if failure:
        assert len(result["results"]) == len(requests) == 1
        assert (result["accounting"]["unknown_hold_microusd"] > 0) == (
            failure in {"pending", "timeout", "quota"}
        )
    else:
        assert len(result["results"]) == 8 and len(requests) == 11
        assert result["accounting"]["unknown_hold_microusd"] == 0
        assert all(case["routing_matches"] for case in result["results"])
        assert result["results"][0]["route_goal_created_then_cancelled"]
        final = result["results"][-1]["goal"]
        assert final["status"] == "waiting" and final["request"]["objective"] == fixed[-1].message
        assert final["review_verdict_enabled"] and not final["read_attempted"]
        assert [tool["call"]["name"] for tool in final["tools"]] == [
            "inspect_sources",
            "read_saved_report",
        ]
        assert len(list(directory.glob("*.db"))) == 9
    assert settings.operation_workspace_report_discovery_enabled is False
    assert settings.operation_workspace_compact_threshold == 8000
