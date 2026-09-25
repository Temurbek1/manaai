from datetime import UTC, datetime
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.domain.enums import AgentRunStatus, TriggerType
from app.mana_operation_ai.domain.models import AgentRun


def configure_growth_test_env(monkeypatch: MonkeyPatch, database_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("META_ACCESS_TOKEN", "")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("OPERATION_ADS_PROVIDER", "fake_meta")
    monkeypatch.setenv("OPERATION_DRY_RUN", "false")
    monkeypatch.setenv("OPERATION_VERIFICATION_DELAY_SECONDS", "0")
    get_settings.cache_clear()


async def test_growth_capabilities_are_independent_and_marketing_alias_cuts_over(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_growth_test_env(monkeypatch, tmp_path / "growth-capabilities.db")
    app = create_app()
    viewer = {"X-MANA-Actor-ID": "viewer-1", "X-MANA-Role": "viewer"}
    operator = {"X-MANA-Actor-ID": "operator-1", "X-MANA-Role": "operator"}
    admin = {"X-MANA-Actor-ID": "admin-1", "X-MANA-Role": "admin"}

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        detail = await client.get(
            "/api/v1/admin/operation/agents/marketing-agent",
            headers=viewer,
        )
        assert detail.status_code == 200
        assert detail.json()["agent"]["agent_id"] == "growth-agent"
        configurations = detail.json()["configurations"]
        assert {(item["capability_key"], item["version"]) for item in configurations} == {
            ("growth.advertising", 1),
            ("growth.funnel.analyze", 1),
        }
        schedules = detail.json()["schedules"]
        assert {item["schedule_id"] for item in schedules} == {
            "growth-advertising-analysis",
            "growth-advertising-nightly-report",
            "growth-funnel-analysis",
        }

        shadow_started = await client.post(
            "/api/v1/admin/operation/agents/growth-agent/run",
            headers=operator,
            json={
                "capability_key": "growth.funnel.analyze",
                "job_type": "analysis",
                "correlation_id": "growth-funnel-shadow",
                "idempotency_key": "growth-funnel-shadow",
            },
        )
        assert shadow_started.status_code == 202
        shadow_runs = await client.get(
            "/api/v1/admin/operation/runs?agent_id=growth-agent"
            "&capability_key=growth.funnel.analyze",
            headers=viewer,
        )
        shadow_run = next(
            item
            for item in shadow_runs.json()["items"]
            if item["correlation_id"] == "growth-funnel-shadow"
        )
        assert shadow_run["status"] == "completed"
        shadow_proposals = await client.get(
            f"/api/v1/admin/operation/action-proposals?run_id={shadow_run['run_id']}",
            headers=viewer,
        )
        assert shadow_proposals.json()["items"] == []

        funnel_configuration = next(
            item for item in configurations if item["capability_key"] == "growth.funnel.analyze"
        )["values"]
        funnel_configuration["experiment_mode"] = "sandbox"
        funnel_configuration["schedule"] = "15 */8 * * *"
        updated = await client.post(
            "/api/v1/admin/operation/agents/growth-agent/configurations"
            "?capability_key=growth.funnel.analyze",
            headers=admin,
            json={"values": funnel_configuration},
        )
        assert updated.status_code == 201
        assert updated.json()["version"] == 2
        assert updated.json()["capability_key"] == "growth.funnel.analyze"
        advertising_configurations = await client.get(
            "/api/v1/admin/operation/agents/growth-agent/configurations"
            "?capability_key=growth.advertising",
            headers=viewer,
        )
        assert [item["version"] for item in advertising_configurations.json()["items"]] == [1]
        refreshed_detail = await client.get(
            "/api/v1/admin/operation/agents/growth-agent",
            headers=viewer,
        )
        schedules_by_id = {
            item["schedule_id"]: item["cron_expression"]
            for item in refreshed_detail.json()["schedules"]
        }
        assert schedules_by_id["growth-funnel-analysis"] == "15 */8 * * *"
        assert schedules_by_id["growth-advertising-analysis"] == "0 */6 * * *"
        assert schedules_by_id["growth-advertising-nightly-report"] == "0 2 * * *"

        accepted = await client.post(
            "/api/v1/admin/operation/agents/growth-agent/run",
            headers=operator,
            json={
                "capability_key": "growth.funnel.analyze",
                "job_type": "analysis",
                "correlation_id": "growth-funnel-sandbox",
                "idempotency_key": "growth-funnel-sandbox",
            },
        )
        assert accepted.status_code == 202
        assert accepted.json()["capability_key"] == "growth.funnel.analyze"
        runs = await client.get(
            "/api/v1/admin/operation/runs?agent_id=growth-agent"
            "&capability_key=growth.funnel.analyze",
            headers=viewer,
        )
        run = next(
            item
            for item in runs.json()["items"]
            if item["correlation_id"] == "growth-funnel-sandbox"
        )
        assert run["status"] == "waiting_approval"
        proposals = await client.get(
            f"/api/v1/admin/operation/action-proposals?run_id={run['run_id']}",
            headers=viewer,
        )
        proposal = proposals.json()["items"][0]
        assert proposal["capability_key"] == "growth.funnel.analyze"
        assert proposal["action_family"] == "growth_experiment"
        assert proposal["action_type"] == "create_experiment"
        assert proposal["status"] == "awaiting_approval"

    get_settings.cache_clear()


async def test_growth_experiment_reconciles_uncertain_write_and_persists_outcome(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_growth_test_env(monkeypatch, tmp_path / "growth-action.db")
    app = create_app()
    operator = {"X-MANA-Actor-ID": "operator-1", "X-MANA-Role": "operator"}
    approver = {"X-MANA-Actor-ID": "approver-1", "X-MANA-Role": "approver"}
    admin = {"X-MANA-Actor-ID": "admin-1", "X-MANA-Role": "admin"}

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        experiment_platform = app.state.operation_experiment_platform
        experiment_platform.simulate_uncertain_response_once()
        configurations = await client.get(
            "/api/v1/admin/operation/agents/growth-agent/configurations"
            "?capability_key=growth.funnel.analyze",
            headers=operator,
        )
        values = configurations.json()["items"][0]["values"]
        values["experiment_mode"] = "sandbox"
        configured = await client.post(
            "/api/v1/admin/operation/agents/growth-agent/configurations"
            "?capability_key=growth.funnel.analyze",
            headers=admin,
            json={"values": values},
        )
        assert configured.status_code == 201

        started = await client.post(
            "/api/v1/admin/operation/agents/growth-agent/run",
            headers=operator,
            json={
                "capability_key": "growth.funnel.analyze",
                "job_type": "analysis",
                "correlation_id": "growth-action-lifecycle",
                "idempotency_key": "growth-action-lifecycle",
            },
        )
        assert started.status_code == 202
        runs = await client.get(
            "/api/v1/admin/operation/runs?capability_key=growth.funnel.analyze",
            headers=operator,
        )
        run = next(
            item
            for item in runs.json()["items"]
            if item["correlation_id"] == "growth-action-lifecycle"
        )
        proposals = await client.get(
            f"/api/v1/admin/operation/action-proposals?run_id={run['run_id']}",
            headers=operator,
        )
        proposal = proposals.json()["items"][0]
        decision = await client.post(
            f"/api/v1/admin/operation/approvals/{proposal['proposal_id']}/decision",
            headers=approver,
            json={
                "approve": True,
                "reason": "Bounded sandbox experiment reviewed",
                "correlation_id": "growth-action-lifecycle",
            },
        )
        assert decision.status_code == 200
        lifecycle = decision.json()
        assert lifecycle["execution"]["status"] == "succeeded"
        assert lifecycle["execution"]["provider_response"] == {
            "reconciled_after_uncertain_dispatch": True,
        }
        assert lifecycle["verification"]["status"] == "verified"
        assert lifecycle["verification"]["observed_state"]["status"] == "DRAFT"
        assert lifecycle["run"]["status"] == "completed"

        detail = await client.get(
            f"/api/v1/admin/operation/runs/{run['run_id']}",
            headers=operator,
        )
        assert detail.json()["run"]["status"] == "completed"
        assert detail.json()["snapshots"][0]["evidence_refs"]
        outcomes = detail.json()["outcomes"]
        assert len(outcomes) == 1
        assert outcomes[0]["status"] == "pending"
        assert outcomes[0]["proposal_id"] == proposal["proposal_id"]
        assert any(
            event["event_type"] == "action_verified"
            and event["capability_key"] == "growth.funnel.analyze"
            for event in detail.json()["timeline"]
        )
        assert experiment_platform.dispatch_count == 1

    get_settings.cache_clear()


async def test_capability_kill_switch_is_scoped_and_marketing_alias_is_canonical(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_growth_test_env(monkeypatch, tmp_path / "growth-capability-control.db")
    app = create_app()
    viewer = {"X-MANA-Actor-ID": "viewer-1", "X-MANA-Role": "viewer"}
    operator = {"X-MANA-Actor-ID": "operator-1", "X-MANA-Role": "operator"}
    admin = {"X-MANA-Actor-ID": "admin-1", "X-MANA-Role": "admin"}

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        agents = await client.get("/api/v1/admin/operation/agents", headers=viewer)
        assert [item["agent_id"] for item in agents.json()["items"]] == [
            "growth-agent",
            "retention-agent",
        ]

        stopped = await client.put(
            "/api/v1/admin/operation/kill-switch/agents/marketing-agent/capabilities/"
            "growth.funnel.analyze",
            headers=admin,
            json={"enabled": True},
        )
        assert stopped.status_code == 200
        assert stopped.json() == {
            "scope": "growth-agent/growth.funnel.analyze",
            "enabled": True,
        }
        assert await app.state.operation_repository.get_control(
            "capability_kill_switch:marketing-agent:growth.funnel.analyze",
        )

        detail = await client.get(
            "/api/v1/admin/operation/agents/growth-agent",
            headers=viewer,
        )
        assert detail.json()["capability_kill_switches"] == {
            "growth.advertising": False,
            "growth.funnel.analyze": True,
        }

        blocked = await client.post(
            "/api/v1/admin/operation/agents/growth-agent/run",
            headers=operator,
            json={
                "capability_key": "growth.funnel.analyze",
                "job_type": "analysis",
                "idempotency_key": "blocked-funnel",
            },
        )
        assert blocked.status_code == 409

        advertising = await client.post(
            "/api/v1/admin/operation/agents/marketing-agent/run",
            headers=operator,
            json={
                "job_type": "analysis",
                "correlation_id": "advertising-remains-available",
                "idempotency_key": "advertising-remains-available",
            },
        )
        assert advertising.status_code == 202
        assert advertising.json()["agent_id"] == "growth-agent"
        assert advertising.json()["capability_key"] == "growth.advertising"

    get_settings.cache_clear()


async def test_growth_history_combines_legacy_marketing_and_canonical_runs(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_growth_test_env(monkeypatch, tmp_path / "growth-history.db")
    app = create_app()
    viewer = {"X-MANA-Actor-ID": "viewer-1", "X-MANA-Role": "viewer"}
    now = datetime.now(UTC)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        growth_definition = app.state.operation_agent_registry.get("growth-agent").definition
        legacy_definition = growth_definition.model_copy(
            update={
                "agent_id": "marketing-agent",
                "display_name": "Marketing Agent (historical)",
                "capabilities": [
                    capability.model_copy(update={"agent_id": "marketing-agent"})
                    for capability in growth_definition.capabilities
                ],
            },
        )
        await app.state.operation_repository.register_agent(legacy_definition)
        await app.state.operation_repository.create_run(
            AgentRun(
                run_id="legacy-marketing-run",
                agent_id="marketing-agent",
                capability_key="growth.advertising",
                correlation_id="legacy-marketing-correlation",
                trigger=TriggerType.SCHEDULE,
                initiated_by="legacy-scheduler",
                status=AgentRunStatus.COMPLETED,
                configuration_version=1,
                idempotency_key="legacy-marketing-idempotency",
                started_at=now,
                updated_at=now,
                completed_at=now,
            ),
        )

        for agent_id in ("growth-agent", "marketing-agent"):
            history = await client.get(
                f"/api/v1/admin/operation/runs?agent_id={agent_id}"
                "&capability_key=growth.advertising",
                headers=viewer,
            )
            assert history.status_code == 200
            assert "legacy-marketing-run" in {item["run_id"] for item in history.json()["items"]}

        agents = await client.get("/api/v1/admin/operation/agents", headers=viewer)
        assert [item["agent_id"] for item in agents.json()["items"]] == [
            "growth-agent",
            "retention-agent",
        ]

    get_settings.cache_clear()
