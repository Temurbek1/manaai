from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.growth.agent import GrowthAgent
from app.mana_operation_ai.application.retention.agent import RetentionAgent
from app.mana_operation_ai.domain.enums import IntegrationStatus
from app.mana_operation_ai.domain.models import IntegrationHealth
from app.mana_operation_ai.infrastructure.ads.fake_meta import FakeMetaAdsAdapter


def configure(monkeypatch: MonkeyPatch, path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPERATION_DATABASE_URL", "")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(path))
    monkeypatch.setenv("OPERATION_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("OPERATION_ALLOW_INSECURE_DEV_HEADERS", "false")
    monkeypatch.setenv("OPERATION_VIEWER_API_KEY", "test-viewer-key")
    monkeypatch.setenv("OPERATION_OPERATOR_API_KEY", "test-operator-key")
    get_settings.cache_clear()


async def test_all_administrative_views_never_probe_providers(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path / "saved-views.db")
    forbidden = AsyncMock(side_effect=AssertionError("External health probe from GET"))
    for adapter in (FakeMetaAdsAdapter, GrowthAgent, RetentionAgent):
        monkeypatch.setattr(adapter, "health", forbidden)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        headers = {"X-API-Key": "test-viewer-key"}
        for _ in range(3):
            for path in (
                "dashboard",
                "agents/growth-agent",
                "agents/retention-agent",
                "marketing/overview",
                "retention/overview",
                "integrations/fake_meta/health",
            ):
                response = await client.get(f"/api/v1/admin/operation/{path}", headers=headers)
                assert response.status_code == 200, response.text
        forbidden.assert_not_called()
        empty = (
            await client.get(
                "/api/v1/admin/operation/retention/overview",
                headers=headers,
            )
        ).json()
        assert empty["snapshot"] is None
        assert empty["mode"] == "unavailable"
        assert empty["external_reads_on_view"] is False
        health = (
            await client.get(
                "/api/v1/admin/operation/integrations/fake_meta/health",
                headers=headers,
            )
        ).json()
        assert health["status"] == "unknown"
        assert health["diagnostics"]["observation"] == "missing"
        old_time = datetime.now(UTC) - timedelta(days=2)
        await app.state.operation_repository.save_integration_health(
            IntegrationHealth(
                integration_id="fake_meta",
                status=IntegrationStatus.HEALTHY,
                checked_at=old_time,
            )
        )
        health = (
            await client.get(
                "/api/v1/admin/operation/integrations/fake_meta/health",
                headers=headers,
            )
        ).json()
        assert health["status"] == "unknown"
        assert health["diagnostics"]["stale"] is True
        assert datetime.fromisoformat(health["checked_at"]) == old_time
        forbidden.assert_not_called()
    get_settings.cache_clear()


async def test_retention_view_uses_completed_evidence_without_new_collection(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path / "retention-overview.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        headers = {"X-API-Key": "test-operator-key"}
        path = "/api/v1/admin/operation/retention/overview"
        assert (await client.get(path)).status_code == 401
        started = await client.post(
            "/api/v1/admin/operation/agents/retention-agent/run",
            headers=headers,
            json={"job_type": "analysis", "idempotency_key": "overview-test"},
        )
        assert started.status_code == 202
        forbidden = AsyncMock(side_effect=AssertionError("External collection from GET"))
        monkeypatch.setattr(app.state.operation_backend_activity, "collect_activity", forbidden)
        result = (await client.get(path, headers=headers)).json()
        assert result["mode"] == "demo"
        assert result["snapshot"]["total_children"] > 0
        assert result["snapshot_run_id"] == result["latest_run"]["run_id"]
        assert result["mobile_analytics_available"] is True
        assert result["reports"]
        snapshot = (
            await app.state.operation_repository.list_snapshots(
                result["snapshot_run_id"],
            )
        )[0]
        unavailable = snapshot.model_copy(deep=True)
        unavailable.snapshot_id = "new-live-snapshot"
        unavailable.collected_at = snapshot.collected_at + timedelta(seconds=1)
        unavailable.payload["evidence_refs"] = [
            {
                **ref.model_dump(mode="json"),
                "source": "mobile_product_analytics_unconfigured"
                if "firestore_activity" in ref.source
                else ref.source.replace("fake_", ""),
                "completeness": "0" if "firestore_activity" in ref.source else "0.01",
            }
            for ref in snapshot.evidence_refs
        ]
        await app.state.operation_repository.save_snapshot(unavailable)
        live = (await client.get(path, headers=headers)).json()
        assert live["mode"] == "live"
        assert live["mobile_analytics_available"] is False
        assert live["snapshot_age_seconds"] >= 0
        forbidden.assert_not_called()
    get_settings.cache_clear()
