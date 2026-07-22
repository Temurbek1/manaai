from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app


def configure_operation_test_env(monkeypatch: MonkeyPatch, database_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("META_ACCESS_TOKEN", "")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("OPERATION_ADS_PROVIDER", "fake_meta")
    monkeypatch.setenv("OPERATION_DRY_RUN", "false")
    monkeypatch.setenv("OPERATION_ALLOW_SELF_APPROVAL", "false")
    get_settings.cache_clear()


async def test_fake_meta_complete_marketing_agent_lifecycle(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_test_env(monkeypatch, tmp_path / "operation-e2e.db")
    app = create_app()
    operator_headers = {
        "X-MANA-Actor-ID": "operator-1",
        "X-MANA-Role": "operator",
    }
    approver_headers = {
        "X-MANA-Actor-ID": "approver-1",
        "X-MANA-Role": "approver",
    }

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        agents = await client.get("/api/v1/admin/operation/agents", headers=operator_headers)
        assert agents.status_code == 200
        assert agents.json()["items"][0]["agent_id"] == "marketing-agent"

        run_response = await client.post(
            "/api/v1/admin/operation/agents/marketing-agent/run",
            headers=operator_headers,
            json={
                "job_type": "analysis",
                "correlation_id": "e2e-correlation",
                "idempotency_key": "e2e-run",
            },
        )
        assert run_response.status_code == 202
        accepted = run_response.json()
        assert accepted["status"] == "accepted"
        runs_response = await client.get(
            "/api/v1/admin/operation/runs?agent_id=marketing-agent&limit=20",
            headers=operator_headers,
        )
        run = next(
            item
            for item in runs_response.json()["items"]
            if item["correlation_id"] == "e2e-correlation"
        )
        assert run["status"] == "waiting_approval"
        run_id = run["run_id"]

        findings_response = await client.get(
            f"/api/v1/admin/operation/findings?run_id={run_id}",
            headers=operator_headers,
        )
        finding_types = {item["finding_type"] for item in findings_response.json()["items"]}
        assert {"best_creative", "weak_creative", "cheap_audience", "expensive_audience"} <= (
            finding_types
        )

        recommendations_response = await client.get(
            f"/api/v1/admin/operation/recommendations?run_id={run_id}",
            headers=operator_headers,
        )
        recommendation_types = {
            item["action_type"] for item in recommendations_response.json()["items"]
        }
        assert {"pause", "scale_audience", "disable_audience"} <= recommendation_types

        proposals_response = await client.get(
            f"/api/v1/admin/operation/action-proposals?run_id={run_id}",
            headers=operator_headers,
        )
        proposals = proposals_response.json()["items"]
        pending = [item for item in proposals if item["status"] == "awaiting_approval"]
        scale = next(item for item in pending if item["action_type"] == "scale_audience")

        approval_response = await client.post(
            f"/api/v1/admin/operation/approvals/{scale['proposal_id']}/decision",
            headers=approver_headers,
            json={
                "approve": True,
                "reason": "Evidence and limits reviewed",
                "correlation_id": "e2e-correlation",
            },
        )
        assert approval_response.status_code == 200
        approved = approval_response.json()
        assert approved["execution"]["status"] == "succeeded"
        assert approved["verification"]["status"] == "verified"
        assert approved["execution"]["before_state"]["daily_budget"] == "60"
        assert approved["verification"]["observed_state"]["daily_budget"] == "72.00"
        persisted_verification = (
            await app.state.operation_repository.get_verification_for_execution(
                approved["execution"]["execution_id"],
            )
        )
        assert persisted_verification is not None
        assert persisted_verification.status.value == "verified"

        for item in pending:
            if item["proposal_id"] == scale["proposal_id"]:
                continue
            rejection = await client.post(
                f"/api/v1/admin/operation/approvals/{item['proposal_id']}/decision",
                headers=approver_headers,
                json={
                    "approve": False,
                    "reason": "Only the selected safe scale action is approved",
                    "correlation_id": "e2e-correlation",
                },
            )
            assert rejection.status_code == 200

        run_detail = await client.get(
            f"/api/v1/admin/operation/runs/{run_id}",
            headers=operator_headers,
        )
        assert run_detail.status_code == 200
        assert run_detail.json()["run"]["status"] == "completed"

        reports_response = await client.get(
            "/api/v1/admin/operation/reports?agent_id=marketing-agent",
            headers=operator_headers,
        )
        reports = reports_response.json()["items"]
        assert reports
        structured = reports[0]["structured"]
        assert structured["best_creative"]
        assert structured["weak_creatives"]
        assert structured["best_audiences"]
        assert structured["expensive_audiences"]
        workflow = structured["workflow_observability"]
        assert workflow["findings_count"] > 0
        assert workflow["recommendations_count"] > 0
        assert workflow["report_generation_duration_ms"] >= 0

        audit_response = await client.get(
            f"/api/v1/admin/operation/audit-events?run_id={run_id}",
            headers=operator_headers,
        )
        event_types = {item["event_type"] for item in audit_response.json()["items"]}
        assert {
            "action_proposed",
            "approval_decided",
            "action_executed",
            "action_verified",
            "report_created",
            "run_stage_changed",
        } <= event_types

    get_settings.cache_clear()
