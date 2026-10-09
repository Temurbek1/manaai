import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
import pytest
from pytest import MonkeyPatch

import app.main as main_module
from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.agent_service import AgentService
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.chat_service import OperationChatService
from app.mana_operation_ai.application.ports import OperationRepository, ProviderPermanentError
from app.mana_operation_ai.application.retention.overview import RetentionOverviewService
from app.mana_operation_ai.application.shared_data import SharedDataUnavailable
from app.mana_operation_ai.application.shared_sources import SharedBackendActivity
from app.mana_operation_ai.domain.chat import AnalysisRequest, MessageCreate, TopicCreate
from app.mana_operation_ai.domain.enums import TriggerType, UserRole
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from tests.test_operation_api import configure_operation_env
from tests.test_operation_chat import FakeConversation
from tests.test_operation_cost_ledger import Clock


def configure(monkeypatch: MonkeyPatch, path: Path, clock: Clock) -> None:
    configure_operation_env(monkeypatch, path)
    monkeypatch.setenv("OPERATION_PRODUCT_ACTIVITY_PROVIDER", "manakids")
    monkeypatch.setenv("OPERATION_DATA_PRODUCT_SCOPE", "mana")
    monkeypatch.setenv("OPERATION_DATA_BINDING_REVISION", "owner-approved-fixture-v1")
    monkeypatch.setenv("MANAKIDS_API_USERNAME", "fake-service-user")
    monkeypatch.setenv("MANAKIDS_API_PASSWORD", "fake-service-password")
    monkeypatch.setenv("MANAKIDS_MAX_RETRIES", "0")
    monkeypatch.setenv("FIREBASE_OPERATIONAL_TELEMETRY_ENABLED", "true")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "fake-project")
    monkeypatch.setenv("FIREBASE_PUBLIC_READ_ENABLED", "true")
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_FILE", "")
    monkeypatch.setenv(
        "OPERATION_COST_DAILY_LIMITS",
        json.dumps(
            {
                "provider_requests": 6,
                "response_bytes": 10_000_000,
            }
        ),
    )
    monkeypatch.setenv(
        "OPERATION_COST_MONTHLY_LIMITS",
        json.dumps(
            {
                "provider_requests": 20,
                "response_bytes": 100_000_000,
            }
        ),
    )
    monkeypatch.setattr(main_module, "SystemClock", lambda: clock)
    get_settings.cache_clear()


async def run(runner: AgentService, key: str) -> str:
    result = await runner.run_now(
        agent_id="retention-agent",
        capability_key="retention.engagement.analyze",
        job_type="analysis",
        trigger=TriggerType.USER,
        actor_id="operator",
        actor_role=UserRole.OPERATOR,
        idempotency_key=key,
    )
    return result.run_id


@pytest.mark.asyncio
async def test_runtime_shared_cache_limits_restart_scope_and_freshness(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    clock = Clock(datetime(2026, 10, 8, tzinfo=UTC))
    configure(monkeypatch, tmp_path / "runtime.db", clock)
    requests: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        assert "firestore" not in request.url.host
        if request.url.path.endswith("login/"):
            return httpx.Response(200, json={"access": "fixture-access"})
        if "app-usage-statistics" in request.url.path:
            row: dict[str, object] = {
                "app_usage_statistics": {
                    "count": 1,
                    "results": [{"private": "raw-child-detail"}],
                }
            }
        elif "camera-audio-usage-logs" in request.url.path:
            row = {"camera_audio_usage_logs": [{"private": "raw-child-detail"}]}
        else:
            row = {"private": "raw-child-detail"}
        return httpx.Response(200, json={"count": 1, "results": [row]})

    for index in range(2):
        app = create_app()
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client,
        ):
            backend = cast(SharedBackendActivity, app.state.operation_backend_activity)
            monkeypatch.setattr(backend._provider, "_client", client)
            runner = cast(AgentService, app.state.operation_agent_service)
            repository = cast(OperationRepository, app.state.operation_repository)
            ledger = cast(SqlAlchemyCostLedger, app.state.operation_cost_ledger)
            await run(runner, f"runtime-{index}")
            overview = await RetentionOverviewService(repository, clock).overview()
            assert overview.snapshot is not None
            assert overview.snapshot.product_scope.value == "mana"
            assert overview.snapshot.mobile_population == "parents"
            assert overview.snapshot.collected_at == datetime(2026, 10, 8, tzinfo=UTC)
            assert "prefix scans are disabled" in str(overview.snapshot.limitations)
            assert "raw-child-detail" not in overview.model_dump_json()
            assert len(requests) == 6
            assert (await ledger.periods())[0].usage.provider_requests == 6
            if index == 0:
                assert overview.snapshot.refresh_status == "live"
                clock.value += timedelta(hours=1)
                # Configuration status polling is strictly local, not another login/read.
                await backend.health()
                assert len(requests) == 6
                continue
            assert overview.snapshot.refresh_status == "cached"
            assert overview.snapshot_age_seconds == 3600
            clock.value += timedelta(hours=6)
            await run(runner, "runtime-exhausted")
            stale = await RetentionOverviewService(repository, clock).overview()
            assert stale.snapshot is not None
            assert stale.snapshot.refresh_status == "stale"
            assert stale.snapshot_age_seconds == 7 * 3600
            assert len(requests) == 6  # The durable quota rejects BEFORE HTTP after restart.

            model = FakeConversation()
            service = cast(OperationChatService, app.state.operation_chat_service)
            service._model = model
            for product in ("mana", "360rec"):
                topic = await service.create(
                    "operator",
                    TopicCreate(
                        agent_id="retention-agent",
                        product=product,
                        title="Scope fixture",
                    ),
                )
                answer = await service.send(
                    "operator",
                    topic.topic_id,
                    MessageCreate(
                        request_id=uuid4(),
                        message="Какие данные подтверждены?",
                    ),
                )
                context = model.contexts[-1]
                if product == "mana":
                    reports = context["saved_reports"]
                    assert isinstance(reports, list) and reports
                    assert reports[0]["product"] == "mana"
                    assert reports[0]["refresh_status"] == "stale"
                    assert reports[0]["collected_at"].startswith("2026-10-08T00:00:00")
                    assert answer.sources and answer.sources[0].scope_verified
                else:
                    assert context["saved_reports"] == [] and answer.sources == []
                    with pytest.raises(ChatError, match="другого приложения"):
                        await service.prepare_analysis(
                            "operator",
                            topic.topic_id,
                            AnalysisRequest(
                                request_id=uuid4(),
                                confirmed=True,
                            ),
                        )
            assert len(requests) == 6
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_unverified_live_bundle_refuses_before_authentication(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    clock = Clock()
    configure(monkeypatch, tmp_path / "unverified.db", clock)
    monkeypatch.setenv("OPERATION_DATA_BINDING_REVISION", "unverified")
    get_settings.cache_clear()
    app = create_app()

    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Unverified sources must not dispatch HTTP")

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client,
    ):
        backend = cast(SharedBackendActivity, app.state.operation_backend_activity)
        monkeypatch.setattr(backend._provider, "_client", client)
        runner = cast(AgentService, app.state.operation_agent_service)
        with pytest.raises(SharedDataUnavailable, match="ownership"):
            await run(runner, "unverified")
        ledger = cast(SqlAlchemyCostLedger, app.state.operation_cost_ledger)
        assert (await ledger.periods())[0].usage.provider_requests == 0
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_runtime_auth_403_blocks_new_run_keys_and_restart_without_other_reads(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    clock = Clock(datetime(2026, 10, 8, tzinfo=UTC))
    configure(monkeypatch, tmp_path / "403.db", clock)
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.url.path.endswith("login/")
        return httpx.Response(403, json={"detail": "private-authentication-detail"})

    for index in range(2):
        app = create_app()
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client,
        ):
            backend = cast(SharedBackendActivity, app.state.operation_backend_activity)
            monkeypatch.setattr(backend._provider, "_client", client)
            runner = cast(AgentService, app.state.operation_agent_service)
            with pytest.raises(ProviderPermanentError):
                await run(runner, f"auth-denied-{index}")
            assert len(calls) == 1
            repository = cast(OperationRepository, app.state.operation_repository)
            runs, _ = await repository.list_runs(agent_id="retention-agent")
            assert "private-authentication-detail" not in str(runs[0].error_message)
        clock.value += timedelta(hours=6)
    get_settings.cache_clear()
