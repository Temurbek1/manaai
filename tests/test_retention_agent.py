from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app


def configure_retention_test_env(monkeypatch: MonkeyPatch, database_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("META_ACCESS_TOKEN", "")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("OPERATION_ADS_PROVIDER", "fake_meta")
    monkeypatch.setenv("OPERATION_PRODUCT_ACTIVITY_PROVIDER", "fake")
    monkeypatch.setenv("OPERATION_DRY_RUN", "true")
    get_settings.cache_clear()


async def test_retention_agent_runs_first_party_engagement_analysis_without_pii(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_retention_test_env(monkeypatch, tmp_path / "retention.db")
    app = create_app()
    viewer = {"X-MANA-Actor-ID": "viewer-1", "X-MANA-Role": "viewer"}
    operator = {"X-MANA-Actor-ID": "operator-1", "X-MANA-Role": "operator"}

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        agents = await client.get("/api/v1/admin/operation/agents", headers=viewer)
        assert agents.status_code == 200
        assert [item["agent_id"] for item in agents.json()["items"]] == [
            "growth-agent",
            "retention-agent",
        ]

        detail = await client.get(
            "/api/v1/admin/operation/agents/retention-agent",
            headers=viewer,
        )
        assert detail.status_code == 200
        assert detail.json()["agent"]["default_capability_key"] == ("retention.engagement.analyze")
        assert detail.json()["schedules"][0]["schedule_id"] == ("retention-engagement-analysis")
        assert {item["integration_id"] for item in detail.json()["integration_health"]} == {
            "fake_manakids_admin_api",
            "fake_firestore_activity",
        }

        started = await client.post(
            "/api/v1/admin/operation/agents/retention-agent/run",
            headers=operator,
            json={
                "capability_key": "retention.engagement.analyze",
                "job_type": "analysis",
                "correlation_id": "retention-first-party-data",
                "idempotency_key": "retention-first-party-data",
            },
        )
        assert started.status_code == 202
        runs = await client.get(
            "/api/v1/admin/operation/runs?agent_id=retention-agent"
            "&capability_key=retention.engagement.analyze",
            headers=viewer,
        )
        run_id = next(
            item["run_id"]
            for item in runs.json()["items"]
            if item["correlation_id"] == "retention-first-party-data"
        )
        run_detail = await client.get(
            f"/api/v1/admin/operation/runs/{run_id}",
            headers=viewer,
        )
        assert run_detail.status_code == 200
        body = run_detail.json()
        assert body["run"]["status"] == "completed"
        assert body["run"]["capability_key"] == "retention.engagement.analyze"
        assert body["recommendations"] == []
        assert body["proposals"] == []
        snapshot = body["snapshots"][0]
        assert snapshot["schema_version"] == "retention-engagement-v1"
        assert snapshot["payload"]["total_children"] == 2_400
        assert snapshot["payload"]["mobile_event_counts"]["app_open"] == 8_900
        assert snapshot["payload"]["mobile_dimension_counts"]["screen_views"] == {
            "dashboard": 12_100,
            "child_profile": 8_300,
        }
        assert snapshot["payload"]["mobile_sequence_counts"]["app_open>screen_view"] == 8_500
        serialized = str(body)
        assert "phone" not in serialized.lower()
        assert "fullname" not in serialized.lower()
        assert "subject_id" not in serialized.lower()
        reports = await client.get(
            "/api/v1/admin/operation/reports?agent_id=retention-agent"
            "&capability_key=retention.engagement.analyze",
            headers=viewer,
        )
        assert reports.json()["items"][0]["report_type"] == ("retention_engagement_analysis")

    get_settings.cache_clear()
