import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import delete

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.ports import ProviderObjectNotFoundError
from app.mana_operation_ai.domain.enums import ActionType
from app.mana_operation_ai.domain.marketing import ProviderActionResult, ProviderObjectState
from app.mana_operation_ai.domain.models import (
    ActionParameters,
    AudienceActionParameters,
    BudgetActionParameters,
)
from app.mana_operation_ai.infrastructure.ads.fake_meta import FakeMetaAdsAdapter
from app.mana_operation_ai.infrastructure.persistence.models import AgentConfigurationRow


def configure_operation_env(
    monkeypatch: MonkeyPatch,
    database_path: Path,
    *,
    dry_run: bool = True,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("META_ACCESS_TOKEN", "")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("OPERATION_ADS_PROVIDER", "fake_meta")
    monkeypatch.setenv("OPERATION_DRY_RUN", "true" if dry_run else "false")
    monkeypatch.setenv("OPERATION_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("OPERATION_ALLOW_SELF_APPROVAL", "false")
    monkeypatch.setenv("OPERATION_VERIFICATION_DELAY_SECONDS", "0")
    get_settings.cache_clear()


def headers(actor_id: str, role: str) -> dict[str, str]:
    return {"X-MANA-Actor-ID": actor_id, "X-MANA-Role": role}


async def run_marketing_agent(client: AsyncClient, actor_id: str) -> str:
    response = await client.post(
        "/api/v1/admin/operation/agents/marketing-agent/run",
        headers=headers(actor_id, "operator"),
        json={
            "job_type": "analysis",
            "correlation_id": f"correlation-{actor_id}",
            "idempotency_key": f"run-{actor_id}",
        },
    )
    assert response.status_code == 202
    runs = await client.get(
        "/api/v1/admin/operation/runs?agent_id=marketing-agent",
        headers=headers(actor_id, "viewer"),
    )
    run_id: object = next(
        item["run_id"]
        for item in runs.json()["items"]
        if item["correlation_id"] == f"correlation-{actor_id}"
    )
    if not isinstance(run_id, str):
        raise AssertionError("Run ID must be a string")
    return run_id


async def scale_proposal(client: AsyncClient, run_id: str) -> dict[str, object]:
    response = await client.get(
        f"/api/v1/admin/operation/action-proposals?run_id={run_id}",
        headers=headers("viewer", "viewer"),
    )
    proposal: object = next(
        item
        for item in response.json()["items"]
        if item["status"] == "awaiting_approval" and item["action_type"] == "scale_audience"
    )
    if not isinstance(proposal, dict):
        raise AssertionError("Proposal must be an object")
    return proposal


async def test_admin_api_rbac_typed_configuration_overview_and_kill_switch(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "operation-admin.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        session = await client.get(
            "/api/v1/admin/operation/session",
            headers=headers("viewer", "viewer"),
        )
        assert session.status_code == 200
        assert session.json() == {
            "actor_id": "viewer",
            "role": "viewer",
            "ads_provider": "fake_meta",
            "provider_mode": "fake_executable",
            "live_meta_read_only": False,
        }

        dashboard = await client.get(
            "/api/v1/admin/operation/dashboard",
            headers=headers("viewer", "viewer"),
        )
        assert dashboard.status_code == 200
        assert dashboard.json()["agents"][0]["health"] == "healthy"

        forbidden = await client.post(
            "/api/v1/admin/operation/agents/marketing-agent/run",
            headers=headers("viewer", "viewer"),
            json={"job_type": "analysis"},
        )
        assert forbidden.status_code == 403

        invalid_configuration = await client.post(
            "/api/v1/admin/operation/agents/marketing-agent/configurations",
            headers=headers("admin", "admin"),
            json={"values": {"maximum_budget_increase_factor": "0.5"}},
        )
        assert invalid_configuration.status_code == 422

        await run_marketing_agent(client, "operator-1")
        overview = await client.get(
            "/api/v1/admin/operation/marketing/overview",
            headers=headers("viewer", "viewer"),
        )
        assert overview.status_code == 200
        body = overview.json()
        assert body["snapshot"]["campaigns"]
        assert {item["dimension"] for item in body["breakdown_performance"]} >= {
            "region",
            "placement",
            "hour",
            "day",
        }

        kill = await client.put(
            "/api/v1/admin/operation/kill-switch/global",
            headers=headers("admin", "admin"),
            json={"enabled": True},
        )
        assert kill.status_code == 200
        blocked = await client.post(
            "/api/v1/admin/operation/agents/marketing-agent/run",
            headers=headers("operator-2", "operator"),
            json={"job_type": "analysis", "idempotency_key": "blocked-run"},
        )
        assert blocked.status_code == 409

    get_settings.cache_clear()


async def test_admin_api_rejects_untrusted_fields_invalid_filters_and_implicit_admin(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "operation-untrusted.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        implicit_role = await client.post(
            "/api/v1/admin/operation/agents/marketing-agent/run",
            json={"job_type": "analysis"},
        )
        too_large = await client.get(
            "/api/v1/admin/operation/runs?limit=1001",
            headers=headers("viewer", "viewer"),
        )
        unknown_status = await client.get(
            "/api/v1/admin/operation/approvals?status=not-a-status",
            headers=headers("viewer", "viewer"),
        )
        schedules = await client.get(
            "/api/v1/admin/operation/schedules",
            headers=headers("viewer", "viewer"),
        )
        schedule = schedules.json()["items"][0]
        mass_assignment = await client.put(
            f"/api/v1/admin/operation/schedules/{schedule['schedule_id']}",
            headers=headers("admin", "admin"),
            json={
                "schedule_id": schedule["schedule_id"],
                "agent_id": "attacker-agent",
                "job_type": "attacker-job",
                "cron_expression": "0 3 * * *",
                "timezone": "UTC",
                "enabled": True,
                "next_run_at": "2099-01-01T00:00:00Z",
            },
        )
        invalid_timezone = await client.put(
            f"/api/v1/admin/operation/schedules/{schedule['schedule_id']}",
            headers=headers("admin", "admin"),
            json={
                "cron_expression": "0 3 * * *",
                "timezone": "Not/A-Timezone",
                "enabled": True,
            },
        )
        valid_update = await client.put(
            f"/api/v1/admin/operation/schedules/{schedule['schedule_id']}",
            headers=headers("admin", "admin"),
            json={
                "cron_expression": "0 3 * * *",
                "timezone": "UTC",
                "enabled": False,
            },
        )

    assert implicit_role.status_code == 403
    assert too_large.status_code == 422
    assert unknown_status.status_code == 422
    assert mass_assignment.status_code == 422
    assert invalid_timezone.status_code == 422
    assert valid_update.status_code == 200
    assert valid_update.json()["agent_id"] == schedule["agent_id"]
    assert valid_update.json()["job_type"] == schedule["job_type"]
    assert valid_update.json()["enabled"] is False
    get_settings.cache_clear()


async def test_self_approval_is_rejected_and_dry_run_does_not_change_provider(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "operation-approval.db", dry_run=True)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        run_id = await run_marketing_agent(client, "same-person")
        proposals_response = await client.get(
            f"/api/v1/admin/operation/action-proposals?run_id={run_id}",
            headers=headers("viewer", "viewer"),
        )
        proposal = next(
            item
            for item in proposals_response.json()["items"]
            if item["status"] == "awaiting_approval" and item["action_type"] == "scale_audience"
        )
        viewer_attempt = await client.post(
            f"/api/v1/admin/operation/approvals/{proposal['proposal_id']}/decision",
            headers=headers("viewer", "viewer"),
            json={
                "approve": True,
                "reason": "Viewer must not approve",
                "correlation_id": "viewer-approval",
            },
        )
        assert viewer_attempt.status_code == 403
        rejected = await client.post(
            f"/api/v1/admin/operation/approvals/{proposal['proposal_id']}/decision",
            headers=headers("same-person", "approver"),
            json={
                "approve": True,
                "reason": "Attempted self approval",
                "correlation_id": "self-approval",
            },
        )
        assert rejected.status_code == 403

        approved = await client.post(
            f"/api/v1/admin/operation/approvals/{proposal['proposal_id']}/decision",
            headers=headers("independent-approver", "approver"),
            json={
                "approve": True,
                "reason": "Safe dry-run validation",
                "correlation_id": "dry-run-approval",
            },
        )
        assert approved.status_code == 200
        assert approved.json()["execution"]["status"] == "dry_run"
        platform = app.state.operation_ads_platforms.get("fake_meta")
        state = await platform.get_object_state("ad_set", "set_cheap")
        assert state.daily_budget == Decimal("60")

    get_settings.cache_clear()


async def test_approved_action_without_active_policy_never_reaches_provider(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "operation-missing-policy.db", dry_run=False)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        run_id = await run_marketing_agent(client, "missing-policy-operator")
        proposal = await scale_proposal(client, run_id)
        await client.put(
            "/api/v1/admin/operation/kill-switch/global",
            headers=headers("admin", "admin"),
            json={"enabled": True},
        )
        blocked = await client.post(
            f"/api/v1/admin/operation/approvals/{proposal['proposal_id']}/decision",
            headers=headers("missing-policy-approver", "approver"),
            json={
                "approve": True,
                "reason": "Reviewed",
                "correlation_id": "missing-policy",
            },
        )
        assert blocked.status_code == 423
        await client.put(
            "/api/v1/admin/operation/kill-switch/global",
            headers=headers("admin", "admin"),
            json={"enabled": False},
        )
        async with app.state.operation_database.session_factory.begin() as session:
            await session.execute(
                delete(AgentConfigurationRow).where(
                    AgentConfigurationRow.agent_id == "growth-agent",
                    AgentConfigurationRow.capability_key == "growth.advertising",
                ),
            )
        provider = app.state.operation_ads_platforms.get("fake_meta")
        assert isinstance(provider, FakeMetaAdsAdapter)
        original_execute = provider.execute
        writes = 0

        async def count_write(
            *,
            object_type: str,
            provider_object_id: str,
            parameters: ActionParameters,
            idempotency_key: str,
        ) -> ProviderActionResult:
            nonlocal writes
            writes += 1
            return await original_execute(
                object_type=object_type,
                provider_object_id=provider_object_id,
                parameters=parameters,
                idempotency_key=idempotency_key,
            )

        monkeypatch.setattr(provider, "execute", count_write)
        denied = await client.post(
            f"/api/v1/admin/operation/action-proposals/{proposal['proposal_id']}/execute",
            headers=headers("missing-policy-approver", "approver"),
            json={"correlation_id": "missing-policy-retry"},
        )

        assert denied.status_code == 423
        assert "No active configuration" in denied.json()["detail"]
        assert writes == 0
    get_settings.cache_clear()


async def test_stale_proposal_is_failed_before_provider_write(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "operation-stale.db", dry_run=False)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        run_id = await run_marketing_agent(client, "stale-operator")
        proposals_response = await client.get(
            f"/api/v1/admin/operation/action-proposals?run_id={run_id}",
            headers=headers("viewer", "viewer"),
        )
        proposal = next(
            item
            for item in proposals_response.json()["items"]
            if item["status"] == "awaiting_approval" and item["action_type"] == "scale_audience"
        )
        platform = app.state.operation_ads_platforms.get("fake_meta")
        await platform.execute(
            object_type="ad_set",
            provider_object_id=proposal["provider_object_id"],
            parameters=BudgetActionParameters(
                kind=ActionType.INCREASE_BUDGET,
                currency="USD",
                current_daily_budget=Decimal("60"),
                proposed_daily_budget=Decimal("61"),
            ),
            idempotency_key="external-provider-change",
        )

        stale = await client.post(
            f"/api/v1/admin/operation/approvals/{proposal['proposal_id']}/decision",
            headers=headers("approver", "approver"),
            json={
                "approve": True,
                "reason": "State was checked before this simulated external change",
                "correlation_id": "stale-decision",
            },
        )
        assert stale.status_code == 409
        proposals_after = await client.get(
            f"/api/v1/admin/operation/action-proposals?run_id={run_id}",
            headers=headers("viewer", "viewer"),
        )
        failed = next(
            item
            for item in proposals_after.json()["items"]
            if item["proposal_id"] == proposal["proposal_id"]
        )
        assert failed["status"] == "failed"
        executions = await client.get(
            "/api/v1/admin/operation/executions?agent_id=marketing-agent",
            headers=headers("viewer", "viewer"),
        )
        assert executions.json()["items"][0]["error_code"] == "stale_proposal"

    get_settings.cache_clear()


async def test_provider_object_lock_blocks_concurrent_approved_action(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "operation-action-lock.db", dry_run=True)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        run_id = await run_marketing_agent(client, "lock-operator")
        proposals_response = await client.get(
            f"/api/v1/admin/operation/action-proposals?run_id={run_id}",
            headers=headers("viewer", "viewer"),
        )
        proposal = next(
            item
            for item in proposals_response.json()["items"]
            if item["status"] == "awaiting_approval" and item["action_type"] == "scale_audience"
        )
        repository = app.state.operation_repository
        lock_key = (
            f"provider-action:fake_meta:{proposal['object_type']}:{proposal['provider_object_id']}"
        )
        now = datetime.now(UTC)
        assert await repository.acquire_lock(
            key=lock_key,
            owner_id="concurrent-worker",
            now=now,
            expires_at=now + timedelta(minutes=5),
        )

        blocked = await client.post(
            f"/api/v1/admin/operation/approvals/{proposal['proposal_id']}/decision",
            headers=headers("lock-approver", "approver"),
            json={
                "approve": True,
                "reason": "Approved while another worker owns the object lock",
                "correlation_id": "concurrent-action",
            },
        )
        assert blocked.status_code == 423
        assert "already executing" in blocked.json()["detail"]
        await repository.release_lock(key=lock_key, owner_id="concurrent-worker")

        retried = await client.post(
            f"/api/v1/admin/operation/action-proposals/{proposal['proposal_id']}/execute",
            headers=headers("lock-approver", "approver"),
            json={"correlation_id": "concurrent-action-retry"},
        )
        assert retried.status_code == 200
        assert retried.json()["execution"]["status"] == "dry_run"

    get_settings.cache_clear()


async def test_nightly_report_completes_with_pending_approvals(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "operation-nightly.db", dry_run=True)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        response = await client.post(
            "/api/v1/admin/operation/agents/marketing-agent/run",
            headers=headers("nightly-scheduler", "operator"),
            json={
                "job_type": "nightly_report",
                "correlation_id": "nightly-correlation",
                "idempotency_key": "nightly-run",
            },
        )
        assert response.status_code == 202
        runs = await client.get(
            "/api/v1/admin/operation/runs?agent_id=marketing-agent",
            headers=headers("viewer", "viewer"),
        )
        run = next(
            item for item in runs.json()["items"] if item["correlation_id"] == "nightly-correlation"
        )
        assert run["status"] == "completed"
        reports = await client.get(
            "/api/v1/admin/operation/reports?agent_id=marketing-agent",
            headers=headers("viewer", "viewer"),
        )
        report = reports.json()["items"][0]
        assert report["report_type"] == "nightly"
        assert report["structured"]["pending_approvals"]

    get_settings.cache_clear()


async def test_expired_proposal_cannot_execute(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "operation-expired.db", dry_run=False)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        run_id = await run_marketing_agent(client, "expiry-operator")
        proposal_data = await scale_proposal(client, run_id)
        proposal_id = str(proposal_data["proposal_id"])
        proposal = await app.state.operation_repository.get_proposal(proposal_id)
        assert proposal is not None
        await app.state.operation_repository.update_proposal(
            proposal.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}),
        )

        decision = await client.post(
            f"/api/v1/admin/operation/approvals/{proposal_id}/decision",
            headers=headers("expiry-approver", "approver"),
            json={
                "approve": True,
                "reason": "This request arrived after expiry",
                "correlation_id": "expired-proposal",
            },
        )

        assert decision.status_code == 200
        assert decision.json()["proposal"]["status"] == "expired"
        assert decision.json()["execution"] is None
        assert await app.state.operation_repository.get_execution_for_proposal(proposal_id) is None
    get_settings.cache_clear()


async def test_policy_change_after_approval_blocks_delayed_execution(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "operation-policy-change.db", dry_run=False)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        run_id = await run_marketing_agent(client, "policy-operator")
        proposal = await scale_proposal(client, run_id)
        proposal_id = str(proposal["proposal_id"])
        kill_on = await client.put(
            "/api/v1/admin/operation/kill-switch/global",
            headers=headers("admin", "admin"),
            json={"enabled": True},
        )
        assert kill_on.status_code == 200
        approved_but_blocked = await client.post(
            f"/api/v1/admin/operation/approvals/{proposal_id}/decision",
            headers=headers("policy-approver", "approver"),
            json={
                "approve": True,
                "reason": "Reviewed before policy change",
                "correlation_id": "policy-change",
            },
        )
        assert approved_but_blocked.status_code == 423
        persisted = await app.state.operation_repository.get_proposal(proposal_id)
        assert persisted is not None and persisted.status.value == "approved"

        await client.put(
            "/api/v1/admin/operation/kill-switch/global",
            headers=headers("admin", "admin"),
            json={"enabled": False},
        )
        detail = await client.get(
            "/api/v1/admin/operation/agents/marketing-agent",
            headers=headers("admin", "admin"),
        )
        values = detail.json()["configuration"]["values"]
        values["allowed_action_types"] = [
            action for action in values["allowed_action_types"] if action != "scale_audience"
        ]
        changed = await client.post(
            "/api/v1/admin/operation/agents/marketing-agent/configurations",
            headers=headers("admin", "admin"),
            json={"values": values},
        )
        assert changed.status_code == 201

        denied = await client.post(
            f"/api/v1/admin/operation/action-proposals/{proposal_id}/execute",
            headers=headers("policy-approver", "approver"),
            json={"correlation_id": "policy-change-retry"},
        )
        assert denied.status_code == 423
        assert "not allowed" in denied.json()["detail"]
        assert await app.state.operation_repository.get_execution_for_proposal(proposal_id) is None
    get_settings.cache_clear()


async def test_deleted_provider_object_after_approval_fails_terminally(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "operation-deleted.db", dry_run=False)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        run_id = await run_marketing_agent(client, "deleted-operator")
        proposal = await scale_proposal(client, run_id)
        proposal_id = str(proposal["proposal_id"])
        await client.put(
            "/api/v1/admin/operation/kill-switch/global",
            headers=headers("admin", "admin"),
            json={"enabled": True},
        )
        blocked = await client.post(
            f"/api/v1/admin/operation/approvals/{proposal_id}/decision",
            headers=headers("deleted-approver", "approver"),
            json={
                "approve": True,
                "reason": "Reviewed",
                "correlation_id": "deleted-object",
            },
        )
        assert blocked.status_code == 423
        await client.put(
            "/api/v1/admin/operation/kill-switch/global",
            headers=headers("admin", "admin"),
            json={"enabled": False},
        )
        provider = app.state.operation_ads_platforms.get("fake_meta")
        assert isinstance(provider, FakeMetaAdsAdapter)

        async def missing_object(
            object_type: str,
            provider_object_id: str,
        ) -> ProviderObjectState:
            del object_type, provider_object_id
            raise ProviderObjectNotFoundError("simulated deleted object")

        monkeypatch.setattr(provider, "get_object_state", missing_object)
        deleted = await client.post(
            f"/api/v1/admin/operation/action-proposals/{proposal_id}/execute",
            headers=headers("deleted-approver", "approver"),
            json={"correlation_id": "deleted-object-retry"},
        )

        assert deleted.status_code == 409
        persisted = await app.state.operation_repository.get_proposal(proposal_id)
        execution = await app.state.operation_repository.get_execution_for_proposal(proposal_id)
        assert persisted is not None and persisted.status.value == "failed"
        assert execution is not None and execution.error_code == "provider_object_not_found"
    get_settings.cache_clear()


async def test_wrong_provider_value_is_partially_applied_and_eventual_value_retries(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "operation-verification.db", dry_run=False)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        run_id = await run_marketing_agent(client, "verification-operator")
        proposal = await scale_proposal(client, run_id)
        provider = app.state.operation_ads_platforms.get("fake_meta")
        assert isinstance(provider, FakeMetaAdsAdapter)
        original_execute = provider.execute

        async def apply_wrong_value(
            *,
            object_type: str,
            provider_object_id: str,
            parameters: ActionParameters,
            idempotency_key: str,
        ) -> ProviderActionResult:
            assert isinstance(parameters, AudienceActionParameters)
            assert parameters.budget_change is not None
            wrong = parameters.model_copy(
                update={
                    "budget_change": parameters.budget_change.model_copy(
                        update={"proposed_daily_budget": Decimal("71")},
                    ),
                },
            )
            return await original_execute(
                object_type=object_type,
                provider_object_id=provider_object_id,
                parameters=wrong,
                idempotency_key=idempotency_key,
            )

        monkeypatch.setattr(provider, "execute", apply_wrong_value)
        wrong = await client.post(
            f"/api/v1/admin/operation/approvals/{proposal['proposal_id']}/decision",
            headers=headers("verification-approver", "approver"),
            json={
                "approve": True,
                "reason": "Reviewed",
                "correlation_id": "wrong-value",
            },
        )

        assert wrong.status_code == 200
        assert wrong.json()["proposal"]["status"] == "partially_applied"
        assert wrong.json()["execution"]["status"] == "partially_applied"
        assert wrong.json()["verification"]["status"] == "mismatch"
        assert "daily_budget" in wrong.json()["verification"]["differences"][0]
    get_settings.cache_clear()


async def test_eventually_consistent_provider_state_is_retried_before_mismatch(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "operation-eventual.db", dry_run=False)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        run_id = await run_marketing_agent(client, "eventual-operator")
        proposal = await scale_proposal(client, run_id)
        provider = app.state.operation_ads_platforms.get("fake_meta")
        assert isinstance(provider, FakeMetaAdsAdapter)
        original_execute = provider.execute
        original_get_state = provider.get_object_state
        before = await original_get_state(
            str(proposal["object_type"]),
            str(proposal["provider_object_id"]),
        )
        applied = False
        verification_reads = 0

        async def execute_with_delayed_read_visibility(
            *,
            object_type: str,
            provider_object_id: str,
            parameters: ActionParameters,
            idempotency_key: str,
        ) -> ProviderActionResult:
            nonlocal applied
            result = await original_execute(
                object_type=object_type,
                provider_object_id=provider_object_id,
                parameters=parameters,
                idempotency_key=idempotency_key,
            )
            applied = True
            return result

        async def delayed_get_state(
            object_type: str,
            provider_object_id: str,
        ) -> ProviderObjectState:
            nonlocal verification_reads
            if applied and verification_reads < 2:
                verification_reads += 1
                return before.model_copy(deep=True)
            if applied:
                verification_reads += 1
            return await original_get_state(object_type, provider_object_id)

        monkeypatch.setattr(provider, "execute", execute_with_delayed_read_visibility)
        monkeypatch.setattr(provider, "get_object_state", delayed_get_state)
        approved = await client.post(
            f"/api/v1/admin/operation/approvals/{proposal['proposal_id']}/decision",
            headers=headers("eventual-approver", "approver"),
            json={
                "approve": True,
                "reason": "Reviewed",
                "correlation_id": "eventual-consistency",
            },
        )

        assert approved.status_code == 200
        assert approved.json()["execution"]["status"] == "succeeded"
        assert approved.json()["verification"]["status"] == "verified"
        assert verification_reads == 3
    get_settings.cache_clear()


async def test_concurrent_approval_requests_commit_one_decision_and_one_write(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_operation_env(
        monkeypatch,
        tmp_path / "operation-concurrent-approval.db",
        dry_run=False,
    )
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        run_id = await run_marketing_agent(client, "concurrent-operator")
        proposal = await scale_proposal(client, run_id)
        provider = app.state.operation_ads_platforms.get("fake_meta")
        assert isinstance(provider, FakeMetaAdsAdapter)
        original_execute = provider.execute
        writes = 0

        async def count_write(
            *,
            object_type: str,
            provider_object_id: str,
            parameters: ActionParameters,
            idempotency_key: str,
        ) -> ProviderActionResult:
            nonlocal writes
            writes += 1
            return await original_execute(
                object_type=object_type,
                provider_object_id=provider_object_id,
                parameters=parameters,
                idempotency_key=idempotency_key,
            )

        monkeypatch.setattr(provider, "execute", count_write)

        async def approve(actor_id: str) -> int:
            response = await client.post(
                f"/api/v1/admin/operation/approvals/{proposal['proposal_id']}/decision",
                headers=headers(actor_id, "approver"),
                json={
                    "approve": True,
                    "reason": "Concurrent review",
                    "correlation_id": "concurrent-approval",
                },
            )
            return response.status_code

        statuses = await asyncio.gather(approve("approver-a"), approve("approver-b"))

        assert statuses.count(200) == 1
        assert any(status in {403, 409} for status in statuses)
        assert writes == 1
    get_settings.cache_clear()
