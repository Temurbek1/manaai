import asyncio
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.admin_service import ActorContext, OperationAdminService
from app.mana_operation_ai.application.agent_service import AgentService, AgentUnavailableError
from app.mana_operation_ai.application.ports import OperationRepository, ProviderPermanentError
from app.mana_operation_ai.application.read_budget import FirestoreReadBudget
from app.mana_operation_ai.domain.enums import AgentRunStatus, TriggerType, UserRole
from app.mana_operation_ai.domain.retention import BackendActivityFacts, OperationalTelemetryFacts
from app.mana_operation_ai.infrastructure.retention.fake import FakeOperationalTelemetryAdapter


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


async def test_retention_failure_drains_source_and_is_terminal_for_idempotency_key(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_retention_test_env(monkeypatch, tmp_path / "retention-failure.db")
    app = create_app()
    started = asyncio.Event()
    drained = asyncio.Event()
    backend_calls = 0

    async def denied_backend(
        *, period_start: datetime, period_end: datetime
    ) -> BackendActivityFacts:
        nonlocal backend_calls
        backend_calls += 1
        await started.wait()
        raise ProviderPermanentError("Admin API read failed with HTTP 403")

    async def pending_firestore(
        self: FakeOperationalTelemetryAdapter,
        *,
        read_budget: FirestoreReadBudget | None = None,
    ) -> OperationalTelemetryFacts:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            drained.set()
        raise AssertionError("Expected cancellation")

    monkeypatch.setattr(FakeOperationalTelemetryAdapter, "collect_telemetry", pending_firestore)
    async with app.router.lifespan_context(app):
        monkeypatch.setattr(
            app.state.operation_backend_activity,
            "collect_activity",
            denied_backend,
        )
        runner = cast(AgentService, app.state.operation_agent_service)
        repository = cast(OperationRepository, app.state.operation_repository)
        with pytest.raises(ProviderPermanentError, match="403"):
            await runner.run_now(
                agent_id="retention-agent",
                capability_key="retention.engagement.analyze",
                job_type="analysis",
                trigger=TriggerType.USER,
                actor_id="operator",
                actor_role=UserRole.OPERATOR,
                idempotency_key="failed-once",
            )
        assert drained.is_set()
        for _ in range(3):
            result = await runner.run_now(
                agent_id="retention-agent",
                capability_key="retention.engagement.analyze",
                job_type="analysis",
                trigger=TriggerType.USER,
                actor_id="operator",
                actor_role=UserRole.OPERATOR,
                idempotency_key="failed-once",
            )
            assert result.status is AgentRunStatus.FAILED
        runs, total = await repository.list_runs(agent_id="retention-agent")
        assert backend_calls == total == 1
        assert runs[0].retry_count == 0
        assert runs[0].error_code == "ProviderPermanentError"
    get_settings.cache_clear()


async def test_retention_circuit_blocks_manual_runs_until_explicit_schedule_recovery(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_retention_test_env(monkeypatch, tmp_path / "retention-circuit.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        repository = cast(OperationRepository, app.state.operation_repository)
        runner = cast(AgentService, app.state.operation_agent_service)
        admin = cast(OperationAdminService, app.state.operation_admin_service)
        actor = ActorContext(actor_id="test-admin", role=UserRole.ADMIN)
        schedule = (await repository.list_schedules("retention-agent"))[0]
        assert not schedule.enabled
        await repository.save_schedule(
            schedule.model_copy(
                update={
                    "circuit_open": True,
                    "consecutive_permanent_failures": 3,
                }
            )
        )
        await admin.create_configuration(
            agent_id="retention-agent",
            capability_key="retention.engagement.analyze",
            values={"lookback_days": 1},
            actor=actor,
        )
        with pytest.raises(AgentUnavailableError, match="circuit breaker"):
            await runner.validate_run("retention-agent", "retention.engagement.analyze")
        restored = await admin.update_schedule(
            schedule_id=schedule.schedule_id,
            cron_expression="20 */6 * * *",
            timezone="UTC",
            enabled=True,
            actor=actor,
        )
        assert not restored.circuit_open
        assert restored.consecutive_permanent_failures == 0
        await runner.validate_run("retention-agent", "retention.engagement.analyze")
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
            "fake_firebase_operational_telemetry",
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
        assert snapshot["schema_version"] == "retention-engagement-v2"
        assert snapshot["payload"]["total_children"] == 2_400
        assert snapshot["payload"]["mobile_event_counts"]["app_open"] == 8_900
        assert snapshot["payload"]["mobile_dimension_counts"]["screen_views"] == {
            "dashboard": 12_100,
            "child_profile": 8_300,
        }
        assert snapshot["payload"]["mobile_sequence_counts"]["app_open>screen_view"] == 8_500
        assert snapshot["payload"]["mobile_active_users_by_window"] == {
            "1d": 520,
            "7d": 1_820,
            "30d": 2_180,
        }
        assert snapshot["payload"]["operational_telemetry"]["battery_devices"] == 2_100
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


async def test_unexpected_retention_run_error_is_persisted_as_failed(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_retention_test_env(monkeypatch, tmp_path / "retention-failed-run.db")
    app = create_app()
    operator = {"X-MANA-Actor-ID": "operator-1", "X-MANA-Role": "operator"}

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        started = await client.post(
            "/api/v1/admin/operation/agents/retention-agent/run",
            headers=operator,
            json={
                "capability_key": "retention.engagement.analyze",
                "job_type": "unsupported",
                "correlation_id": "retention-invalid-job-type",
                "idempotency_key": "retention-invalid-job-type",
            },
        )
        assert started.status_code == 202

        runs = await client.get(
            "/api/v1/admin/operation/runs?agent_id=retention-agent"
            "&capability_key=retention.engagement.analyze",
            headers=operator,
        )
        run = next(
            item
            for item in runs.json()["items"]
            if item["correlation_id"] == "retention-invalid-job-type"
        )
        assert run["status"] == "failed"
        assert run["error_code"] == "unexpected_run_error"
        assert run["error_message"] == ("The agent job failed before reaching a terminal state.")
        assert run["completed_at"] is not None

    get_settings.cache_clear()
