from datetime import UTC, datetime
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.marketing.calibration import calibrate_account
from app.mana_operation_ai.domain.enums import ActionStatus, AuditEventType, ProviderMode
from app.mana_operation_ai.domain.marketing import (
    MarketingAgentConfiguration,
    MarketingThresholdOverrides,
)
from app.mana_operation_ai.infrastructure.ads.fake_meta import build_demo_snapshot


def _configure_app(monkeypatch: MonkeyPatch, database_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("META_ACCESS_TOKEN", "")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(database_path))
    monkeypatch.setenv("OPERATION_ADS_PROVIDER", "fake_meta")
    monkeypatch.setenv("OPERATION_DRY_RUN", "true")
    monkeypatch.setenv("OPERATION_VERIFICATION_DELAY_SECONDS", "0")
    get_settings.cache_clear()


async def test_executor_returns_typed_forbidden_and_audits_without_provider_call(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure_app(monkeypatch, tmp_path / "live-executor.db")
    app = create_app()
    operator = {"X-MANA-Actor-ID": "operator-1", "X-MANA-Role": "operator"}
    admin_headers = {"X-MANA-Actor-ID": "admin-1", "X-MANA-Role": "admin"}

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        started = await client.post(
            "/api/v1/admin/operation/agents/marketing-agent/run",
            headers=operator,
            json={
                "job_type": "analysis",
                "correlation_id": "live-boundary-source",
                "idempotency_key": "live-boundary-source",
            },
        )
        assert started.status_code == 202
        runs = await client.get(
            "/api/v1/admin/operation/runs?agent_id=marketing-agent",
            headers=operator,
        )
        run_id = next(
            item["run_id"]
            for item in runs.json()["items"]
            if item["correlation_id"] == "live-boundary-source"
        )
        page = await client.get(
            f"/api/v1/admin/operation/action-proposals?run_id={run_id}",
            headers=operator,
        )
        proposal_id = next(
            item["proposal_id"]
            for item in page.json()["items"]
            if item["status"] == "awaiting_approval"
        )
        repository = app.state.operation_repository
        proposal = await repository.get_proposal(proposal_id)
        assert proposal is not None
        live_proposal = proposal.model_copy(
            update={
                "provider": "meta",
                "provider_mode": ProviderMode.LIVE_READ_ONLY,
                "execution_forbidden": True,
                "status": ActionStatus.APPROVED,
            },
        )
        await repository.update_proposal(live_proposal)
        provider_calls = 0
        meta = app.state.operation_ads_platforms.get("meta")

        async def unexpected_provider_call(**_: object) -> object:
            nonlocal provider_calls
            provider_calls += 1
            raise AssertionError("Live provider execute must not be invoked")

        monkeypatch.setattr(meta, "execute", unexpected_provider_call)
        response = await client.post(
            f"/api/v1/admin/operation/action-proposals/{proposal_id}/execute",
            headers=admin_headers,
            json={"correlation_id": "live-write-forbidden"},
        )
        assert response.status_code == 403
        assert response.json() == {
            "detail": {
                "code": "write_operation_forbidden",
                "message": (
                    "LIVE Meta is read-only; execution is forbidden and no provider request "
                    "was sent"
                ),
                "provider_mode": "live_read_only",
                "provider_request_sent": False,
            },
        }
        assert provider_calls == 0
        audit, _ = await repository.list_audit_events(run_id=run_id)
        forbidden = [item for item in audit if item.event_type is AuditEventType.WRITE_FORBIDDEN]
        assert len(forbidden) == 1
        assert forbidden[0].details == {
            "provider_mode": "live_read_only",
            "action_type": live_proposal.action_type.value,
            "provider_request_sent": False,
        }

    get_settings.cache_clear()


def test_account_calibration_is_typed_layered_and_reversible() -> None:
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    snapshot = build_demo_snapshot(now)
    result = calibrate_account(
        snapshot=snapshot,
        source_snapshot_id="snapshot-live-1",
        objective=MarketingAgentConfiguration().primary_objective,
        calibrated_at=now,
    )
    account_id = snapshot.accounts[0].provider_id
    configuration = MarketingAgentConfiguration.model_validate(
        {
            **MarketingAgentConfiguration().model_dump(),
            "provider_defaults": {"fake_meta": {"minimum_clicks": 50}},
            "account_calibrations": {account_id: result.calibration},
            "objective_overrides": {"leads": {"minimum_clicks": 7}},
            "campaign_overrides": {"campaign-override": {"minimum_clicks": 3}},
        },
    )

    account_effective = configuration.effective_for(
        provider="fake_meta",
        account_id=account_id,
    )
    campaign_effective = configuration.effective_for(
        provider="fake_meta",
        account_id=account_id,
        campaign_id="campaign-override",
    )
    reverted = configuration.model_copy(update={"account_calibrations": {}}).effective_for(
        provider="fake_meta",
        account_id=account_id,
    )

    assert result.calibration.source_snapshot_id == "snapshot-live-1"
    assert account_effective.minimum_clicks == 7
    assert campaign_effective.minimum_clicks == 3
    assert reverted.minimum_clicks == 7


def test_empty_account_calibration_inherits_every_lower_layer_threshold() -> None:
    now = datetime(2026, 7, 22, 12, tzinfo=UTC)
    snapshot = build_demo_snapshot(now).model_copy(update={"insights": []})

    result = calibrate_account(
        snapshot=snapshot,
        source_snapshot_id="snapshot-empty-live-1",
        objective=MarketingAgentConfiguration().primary_objective,
        calibrated_at=now,
    )

    assert result.base_row_count == 0
    assert result.represented_days == 0
    assert result.unavailable_thresholds == sorted(MarketingThresholdOverrides.model_fields)
    assert all(value is None for value in result.calibration.thresholds.model_dump().values())
    assert "inherits" in " ".join(result.calibration.rationale)
