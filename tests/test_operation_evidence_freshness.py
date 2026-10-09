from datetime import timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from pytest import MonkeyPatch

import app.main as main_module
from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.action_lifecycle import (
    ActionLifecycleService,
    ActionSafetyError,
)
from app.mana_operation_ai.application.evidence_freshness import evidence_freshness_failure
from app.mana_operation_ai.application.ports import OperationRepository
from app.mana_operation_ai.domain.enums import ActionStatus
from app.mana_operation_ai.domain.models import DataSnapshot
from app.mana_operation_ai.infrastructure.ads.fake_meta import FakeMetaAdsAdapter
from tests.test_operation_api import (
    configure_operation_env,
    headers,
    run_marketing_agent,
    scale_proposal,
)
from tests.test_operation_cost_ledger import Clock


def snapshot() -> DataSnapshot:
    now = Clock().now()
    return DataSnapshot(
        snapshot_id="evidence-fixture",
        run_id="run-fixture",
        agent_id="growth-agent",
        capability_key="growth.funnel.analyze",
        provider="fake_product_analytics",
        schema_version="fixture",
        period_start=now - timedelta(days=7),
        period_end=now,
        collected_at=now,
        checksum="fixture",
        provider_request_ids=[],
        completeness=1,
        payload={
            "product_scope": "mana",
            "refresh_status": "cached",
            "fresh_until": (now + timedelta(hours=6)).isoformat(),
        },
    )


def test_fresh_cache_is_not_confused_with_stale_refresh_failure() -> None:
    saved = snapshot()
    now = saved.collected_at + timedelta(hours=1)
    assert evidence_freshness_failure([saved], now=now, maximum_age_seconds=21600) is None
    saved.payload["refresh_status"] = "stale"
    assert "stale" in str(evidence_freshness_failure([saved], now=now, maximum_age_seconds=21600))


def test_rebuilding_a_report_does_not_extend_evidence_deadline() -> None:
    saved = snapshot()
    now = saved.collected_at + timedelta(hours=6)
    assert "too old" in str(evidence_freshness_failure([saved], now=now, maximum_age_seconds=21600))
    saved.payload["fresh_until"] = (now + timedelta(days=100)).isoformat()
    assert "too old" in str(evidence_freshness_failure([saved], now=now, maximum_age_seconds=21600))


def test_missing_unverified_mixed_and_future_evidence_is_refused() -> None:
    saved = snapshot()
    now = saved.collected_at
    assert evidence_freshness_failure([], now=now, maximum_age_seconds=21600)
    saved.payload["product_scope"] = "unverified"
    assert "scope" in str(evidence_freshness_failure([saved], now=now, maximum_age_seconds=21600))
    saved.payload["product_scope"] = "360rec"
    assert "mixes" in str(
        evidence_freshness_failure([snapshot(), saved], now=now, maximum_age_seconds=21600)
    )
    saved.collected_at = now + timedelta(seconds=1)
    assert "time" in str(evidence_freshness_failure([saved], now=now, maximum_age_seconds=21600))


@pytest.mark.asyncio
@pytest.mark.parametrize("age_hours", [1, 6])
async def test_http_action_freshness_precedes_provider_io_and_survives_restart(
    tmp_path: Path, monkeypatch: MonkeyPatch, age_hours: int
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "action-freshness.db", dry_run=False)
    clock = Clock()
    monkeypatch.setattr(main_module, "SystemClock", lambda: clock)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        run_id = await run_marketing_agent(client, "operator")
        proposed = await scale_proposal(client, run_id)
        proposal_id = cast(str, proposed["proposal_id"])
        provider = cast(FakeMetaAdsAdapter, app.state.operation_ads_platforms.get("fake_meta"))
        read = AsyncMock(wraps=provider.get_object_state)
        write = AsyncMock(wraps=provider.execute)
        monkeypatch.setattr(provider, "get_object_state", read)
        monkeypatch.setattr(provider, "execute", write)
        clock.value += timedelta(hours=age_hours)
        decision = await client.post(
            f"/api/v1/admin/operation/approvals/{proposal_id}/decision",
            headers=headers("approver", "approver"),
            json={"approve": True, "reason": "Reviewed", "correlation_id": "freshness-fixture"},
        )
        if age_hours == 1:
            assert decision.status_code == 200
            assert decision.json()["verification"]["status"] == "verified"
            assert read.await_count >= 1 and write.await_count == 1
            get_settings.cache_clear()
            return
        assert decision.status_code == 423 and "Source evidence is too old" in decision.text
        assert read.await_count == write.await_count == 0
        repository = cast(OperationRepository, app.state.operation_repository)
        persisted = await repository.get_proposal(proposal_id)
        assert persisted is not None and persisted.status is ActionStatus.APPROVED
        assert persisted.expires_at > clock.now()  # Evidence, not proposal expiry, blocked it.
        assert await repository.get_execution_for_proposal(proposal_id) is None
        recommendations, _ = await repository.list_recommendations(run_id=run_id)
        recommendation = next(
            item
            for item in recommendations
            if item.recommendation_id == persisted.recommendation_id
        )
        configuration = await repository.latest_configuration("growth-agent", "growth.advertising")
        assert configuration is not None
        lifecycle = cast(ActionLifecycleService, app.state.operation_action_lifecycle)
        with pytest.raises(ActionSafetyError, match="Source evidence is too old"):
            await lifecycle.create_proposal(
                agent_id="growth-agent",
                provider_name="fake_meta",
                run_id=run_id,
                correlation_id="stale-proposal-fixture",
                recommendation=recommendation,
                configuration=configuration.values,
                configuration_version=configuration.version,
                requested_by="operator",
            )
        assert read.await_count == write.await_count == 0

    # Reopening the app cannot turn the saved evidence into a fresh observation.
    restarted = create_app()
    async with (
        restarted.router.lifespan_context(restarted),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://test"
        ) as client,
    ):
        provider = cast(
            FakeMetaAdsAdapter, restarted.state.operation_ads_platforms.get("fake_meta")
        )
        forbidden = AsyncMock(side_effect=AssertionError("Stale evidence reached the provider"))
        monkeypatch.setattr(provider, "get_object_state", forbidden)
        monkeypatch.setattr(provider, "execute", forbidden)
        execution = await client.post(
            f"/api/v1/admin/operation/action-proposals/{proposal_id}/execute",
            headers=headers("approver", "approver"),
            json={"correlation_id": "stale-restart-fixture"},
        )
        assert execution.status_code == 423 and "Source evidence is too old" in execution.text
        assert forbidden.await_count == 0
    get_settings.cache_clear()
