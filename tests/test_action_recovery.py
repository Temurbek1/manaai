from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.ports import ProviderWriteUncertainError
from app.mana_operation_ai.domain.marketing import ProviderActionResult
from app.mana_operation_ai.domain.models import ActionParameters
from app.mana_operation_ai.infrastructure.ads.fake_meta import FakeMetaAdsAdapter


def configure_recovery_test_env(monkeypatch: MonkeyPatch, database_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("META_ACCESS_TOKEN", "")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("OPERATION_ADS_PROVIDER", "fake_meta")
    monkeypatch.setenv("OPERATION_DRY_RUN", "false")
    monkeypatch.setenv("OPERATION_VERIFICATION_DELAY_SECONDS", "0")
    get_settings.cache_clear()


async def test_timeout_after_applied_write_is_reconciled_without_duplicate(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_recovery_test_env(monkeypatch, tmp_path / "uncertain-write.db")
    app = create_app()
    operator = {"X-MANA-Actor-ID": "operator-1", "X-MANA-Role": "operator"}
    approver = {"X-MANA-Actor-ID": "approver-1", "X-MANA-Role": "approver"}

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        run_response = await client.post(
            "/api/v1/admin/operation/agents/marketing-agent/run",
            headers=operator,
            json={
                "job_type": "analysis",
                "correlation_id": "uncertain-write-run",
                "idempotency_key": "uncertain-write-run",
            },
        )
        assert run_response.status_code == 202
        runs = await client.get(
            "/api/v1/admin/operation/runs?agent_id=marketing-agent",
            headers=operator,
        )
        run_id = next(
            item["run_id"]
            for item in runs.json()["items"]
            if item["correlation_id"] == "uncertain-write-run"
        )
        proposals_response = await client.get(
            f"/api/v1/admin/operation/action-proposals?run_id={run_id}",
            headers=operator,
        )
        scale = next(
            item
            for item in proposals_response.json()["items"]
            if item["action_type"] == "scale_audience"
        )

        provider = app.state.operation_ads_platforms.get("fake_meta")
        assert isinstance(provider, FakeMetaAdsAdapter)
        original_execute = provider.execute
        write_count = 0

        async def apply_then_lose_response(
            *,
            object_type: str,
            provider_object_id: str,
            parameters: ActionParameters,
            idempotency_key: str,
        ) -> ProviderActionResult:
            nonlocal write_count
            write_count += 1
            await original_execute(
                object_type=object_type,
                provider_object_id=provider_object_id,
                parameters=parameters,
                idempotency_key=idempotency_key,
            )
            raise ProviderWriteUncertainError("simulated lost response")

        monkeypatch.setattr(provider, "execute", apply_then_lose_response)
        approval = await client.post(
            f"/api/v1/admin/operation/approvals/{scale['proposal_id']}/decision",
            headers=approver,
            json={
                "approve": True,
                "reason": "Reviewed",
                "correlation_id": "uncertain-write-run",
            },
        )
        assert approval.status_code == 202
        assert "do not retry" in approval.json()["detail"]

        persisted = await app.state.operation_repository.get_proposal(scale["proposal_id"])
        execution = await app.state.operation_repository.get_execution_for_proposal(
            scale["proposal_id"],
        )
        assert persisted is not None and persisted.status.value == "executing"
        assert execution is not None and execution.status.value == "executing"
        assert execution.error_code == "write_outcome_uncertain"
        assert write_count == 1

        monkeypatch.setattr(provider, "execute", original_execute)
        assert await app.state.operation_maintenance_service.reconcile_actions() == 1
        reconciled = await app.state.operation_repository.get_proposal(scale["proposal_id"])
        final_execution = await app.state.operation_repository.get_execution_for_proposal(
            scale["proposal_id"],
        )
        assert reconciled is not None and reconciled.status.value == "succeeded"
        assert final_execution is not None and final_execution.status.value == "succeeded"
        assert write_count == 1

    get_settings.cache_clear()
