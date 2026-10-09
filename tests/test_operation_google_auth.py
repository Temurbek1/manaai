import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs

import httpx
import pytest
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.agent_service import AgentService
from app.mana_operation_ai.application.cost_control import CostBudgetExceeded
from app.mana_operation_ai.application.ports import (
    OperationRepository,
    ProviderPermanentError,
    ProviderTransientError,
)
from app.mana_operation_ai.application.shared_sources import SharedMobileActivity
from app.mana_operation_ai.domain.cost_control import CostLimits, DataRateCard, ResourceUsage
from app.mana_operation_ai.infrastructure import google_auth
from app.mana_operation_ai.infrastructure.google_auth import GoogleServiceAccountTokenProvider
from app.mana_operation_ai.infrastructure.metered_http import MeteredReadHttp
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.retention.ga4 import Ga4MobileActivityAdapter
from tests.test_operation_cost_ledger import Clock, attribution
from tests.test_operation_data_runtime import configure, run

SCOPE = "https://www.googleapis.com/auth/analytics.readonly"


@pytest.fixture
async def accounting(
    tmp_path: Path,
) -> AsyncIterator[tuple[SqlAlchemyCostLedger, Clock]]:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'oauth.db'}")
    await db.create_schema()
    clock = Clock(datetime(2026, 10, 8, 12, tzinfo=UTC))
    usage = ResourceUsage(provider_requests=2, response_bytes=1_000_000)
    ledger = SqlAlchemyCostLedger(
        db,
        clock=clock,
        limits=CostLimits(daily=usage, monthly=usage.model_copy(update={"provider_requests": 4})),
    )
    try:
        yield ledger, clock
    finally:
        await db.dispose()


@pytest.fixture
def signed_claims(monkeypatch: MonkeyPatch) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    signer = object()

    def load(path: str, *, scopes: list[str]) -> SimpleNamespace:
        assert path in {"unused-fixture.json", "tests/fixtures/google-oauth-stub.json"}
        assert scopes == [SCOPE]

        # SDK transport refresh must never be used, even after token expiry.
        def refresh(*args: object) -> None:
            raise AssertionError("Unmetered SDK refresh was invoked")

        return SimpleNamespace(
            service_account_email="fixture@example.iam.gserviceaccount.com",
            signer=signer,
            token_uri="https://untrusted-token-host.test/steal",
            refresh=refresh,
        )

    def encode(actual_signer: object, payload: dict[str, Any]) -> bytes:
        assert actual_signer is signer
        claims.append(payload)
        return b"fixture.signed.jwt"

    modules = {
        "google.oauth2.service_account": SimpleNamespace(
            Credentials=SimpleNamespace(from_service_account_file=load)
        ),
        "google.auth.jwt": SimpleNamespace(encode=encode),
    }
    monkeypatch.setattr(
        google_auth, "importlib", SimpleNamespace(import_module=lambda name: modules[name])
    )
    return claims


def provider(
    client: httpx.AsyncClient, ledger: SqlAlchemyCostLedger, clock: Clock, *, maximum: int = 4096
) -> GoogleServiceAccountTokenProvider:
    return GoogleServiceAccountTokenProvider(
        "unused-fixture.json",
        scopes=[SCOPE],
        client=client,
        clock=clock,
        metered_http=MeteredReadHttp(
            ledger=ledger,
            attribution=attribution().model_copy(update={"source": "google_oauth"}),
            maximum_response_bytes=maximum,
            rates=DataRateCard(),
        ),
    )


@pytest.mark.asyncio
async def test_oauth_single_flight_expiry_claims_and_global_admission(
    accounting: tuple[SqlAlchemyCostLedger, Clock], signed_claims: list[dict[str, Any]]
) -> None:
    ledger, clock = accounting
    calls = 0

    async def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert str(request.url) == "https://oauth2.googleapis.com/token"
        assert request.method == "POST"
        assert (await ledger.periods())[-1].usage.provider_requests == calls
        assert parse_qs(request.content.decode()) == {
            "grant_type": ["urn:ietf:params:oauth:grant-type:jwt-bearer"],
            "assertion": ["fixture.signed.jwt"],
        }
        return httpx.Response(
            200,
            json={
                "access_token": f"fixture-token-{calls}",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        tokens = provider(client, ledger, clock)
        assert (
            await asyncio.gather(*[tokens.access_token() for _ in range(20)])
            == ["fixture-token-1"] * 20
        )
        assert calls == 1
        first = signed_claims[0]
        assert first == {
            "iss": "fixture@example.iam.gserviceaccount.com",
            "scope": SCOPE,
            "aud": "https://oauth2.googleapis.com/token",
            "iat": int(clock.now().timestamp()),
            "exp": int(clock.now().timestamp()) + 3600,
        }
        clock.value += timedelta(seconds=3540)
        assert await tokens.access_token() == "fixture-token-2"
        assert calls == 2
        # Another process/provider cannot bypass the same durable budget.
        reopened = provider(client, ledger, clock)
        with pytest.raises(CostBudgetExceeded):
            await reopened.access_token()
        assert calls == 2
        assert await tokens.access_token() == "fixture-token-2"
        clock.value += timedelta(days=1)
        # Budget exhaustion must not turn into a permanent credential block.
        assert await reopened.access_token() == "fixture-token-3"
    usage = (await ledger.periods())[0].usage
    assert usage.provider_requests == 1 and 0 < usage.response_bytes < 4096
    assert usage.document_reads == usage.data_microusd == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403])
async def test_oauth_authorization_denial_does_not_retry_concurrent_callers(
    accounting: tuple[SqlAlchemyCostLedger, Clock], signed_claims: list[dict[str, Any]], status: int
) -> None:
    ledger, clock = accounting
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": "secret-provider-detail"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        tokens = provider(client, ledger, clock)
        results = await asyncio.gather(
            *[tokens.access_token() for _ in range(20)], return_exceptions=True
        )
        assert all(isinstance(result, ProviderPermanentError) for result in results)
        assert "secret-provider-detail" not in str(results)
        clock.value += timedelta(hours=7)
        with pytest.raises(ProviderPermanentError, match="blocked"):
            await tokens.access_token()
    assert calls == 1 and len(signed_claims) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [408, 429, 503])
async def test_oauth_transient_failures_are_one_attempt_and_cool_down(
    accounting: tuple[SqlAlchemyCostLedger, Clock], signed_claims: list[dict[str, Any]], status: int
) -> None:
    ledger, clock = accounting
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": "temporary"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        tokens = provider(client, ledger, clock)
        results = await asyncio.gather(
            *[tokens.access_token() for _ in range(20)], return_exceptions=True
        )
        assert all(isinstance(result, ProviderTransientError) for result in results)
        assert calls == 1
        clock.value += timedelta(seconds=60)
        with pytest.raises(ProviderTransientError):
            await tokens.access_token()
    assert calls == 2
    assert (await ledger.periods())[0].usage.provider_requests == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_uncertain_oauth_attempt_retains_reservation(
    accounting: tuple[SqlAlchemyCostLedger, Clock],
    signed_claims: list[dict[str, Any]],
    cancel: bool,
) -> None:
    ledger, clock = accounting
    started = asyncio.Event()
    calls = 0

    async def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        started.set()
        if cancel:
            await asyncio.Event().wait()
        raise httpx.ReadTimeout("No receipt", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        tokens = provider(client, ledger, clock)
        task = asyncio.create_task(tokens.access_token())
        await started.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(ProviderTransientError, match="request failed"):
                await task
        with pytest.raises(ProviderTransientError, match="cooling down"):
            await tokens.access_token()
    usage = (await ledger.periods())[0].usage
    assert calls == 1 and usage.provider_requests == 1
    assert usage.response_bytes == 4096 + 65_536


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"access_token": "fake-token", "expires_in": True, "token_type": "Bearer"},
        {"access_token": "fake-token", "expires_in": 3601, "token_type": "Bearer"},
        {"access_token": "fake-token", "expires_in": 0, "token_type": "Bearer"},
        {"access_token": "fake-token", "expires_in": "3600", "token_type": "Bearer"},
        {"access_token": "fake-token", "expires_in": 3600, "token_type": "Basic"},
        {"access_token": "fake-bad\r\ntoken", "expires_in": 3600, "token_type": "Bearer"},
        {"access_token": "не-ascii", "expires_in": 3600, "token_type": "Bearer"},
    ],
)
async def test_invalid_oauth_receipt_is_rejected_without_token_leak(
    accounting: tuple[SqlAlchemyCostLedger, Clock],
    signed_claims: list[dict[str, Any]],
    payload: Any,
) -> None:
    ledger, clock = accounting
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        tokens = provider(client, ledger, clock)
        with pytest.raises(ProviderPermanentError, match="response is invalid"):
            await tokens.access_token()
        with pytest.raises(ProviderPermanentError, match="blocked"):
            await tokens.access_token()
    assert (await ledger.periods())[0].usage.provider_requests == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect", [False, True])
async def test_oauth_oversize_or_redirect_is_not_retried(
    accounting: tuple[SqlAlchemyCostLedger, Clock],
    signed_claims: list[dict[str, Any]],
    redirect: bool,
) -> None:
    ledger, clock = accounting
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if redirect:
            return httpx.Response(302, headers={"location": "https://steal.test"})
        return httpx.Response(200, content=b"x" * 513)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        tokens = provider(client, ledger, clock, maximum=512)
        with pytest.raises(ProviderPermanentError):
            await tokens.access_token()
        with pytest.raises(ProviderPermanentError, match="blocked"):
            await tokens.access_token()
    assert calls == 1
    usage = (await ledger.periods())[0].usage
    assert usage.provider_requests == 1
    assert usage.response_bytes == (0 if redirect else 512 + 65_536)


@pytest.mark.asyncio
async def test_late_oauth_response_does_not_extend_token_lifetime(
    accounting: tuple[SqlAlchemyCostLedger, Clock], signed_claims: list[dict[str, Any]]
) -> None:
    ledger, clock = accounting

    def handle(request: httpx.Request) -> httpx.Response:
        clock.value += timedelta(seconds=3540)
        return httpx.Response(
            200, json={"access_token": "fake-token", "expires_in": 3600, "token_type": "Bearer"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ProviderTransientError, match="arrived too late"):
            await provider(client, ledger, clock).access_token()
    assert (await ledger.periods())[0].usage.provider_requests == 1


@pytest.mark.asyncio
async def test_runtime_ga4_refresh_and_reports_share_budget_after_restart(
    tmp_path: Path, monkeypatch: MonkeyPatch, signed_claims: list[dict[str, Any]]
) -> None:
    clock = Clock(datetime(2026, 10, 8, 12, tzinfo=UTC))
    configure(monkeypatch, tmp_path / "ga4-runtime.db", clock)
    monkeypatch.setenv("OPERATION_PRODUCT_ACTIVITY_PROVIDER", "manakids_ga4")
    monkeypatch.setenv("GA4_PROPERTY_ID", "123456789")
    monkeypatch.setenv("GA4_SERVICE_ACCOUNT_FILE", "tests/fixtures/google-oauth-stub.json")
    monkeypatch.setenv("GA4_PRODUCT_STREAM_IDS", '["123"]')
    monkeypatch.setenv("GA4_MAX_RETRIES", "0")
    monkeypatch.setenv(
        "OPERATION_COST_DAILY_LIMITS", '{"provider_requests":21,"response_bytes":30000000}'
    )
    monkeypatch.setenv(
        "OPERATION_COST_MONTHLY_LIMITS", '{"provider_requests":42,"response_bytes":60000000}'
    )
    get_settings.cache_clear()
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200,
                json={"access_token": "fake-token", "expires_in": 3600, "token_type": "Bearer"},
            )
        if "runReport" in request.url.path:
            return httpx.Response(200, json={"rows": []})
        if request.url.path.endswith("login/"):
            return httpx.Response(200, json={"access": "fixture-access"})
        return httpx.Response(200, json={"count": 0, "results": []})

    for index in range(2):
        app = create_app()
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client,
        ):
            backend = app.state.operation_backend_activity
            mobile = cast(SharedMobileActivity, app.state.operation_mobile_activity)
            ga4 = cast(Ga4MobileActivityAdapter, mobile._provider)
            token = cast(GoogleServiceAccountTokenProvider, ga4._token_provider)
            monkeypatch.setattr(backend._provider, "_client", client)
            monkeypatch.setattr(ga4, "_client", client)
            monkeypatch.setattr(token, "_client", client)
            run_id = await run(
                cast(AgentService, app.state.operation_agent_service), f"oauth-runtime-{index}"
            )
            repository = cast(OperationRepository, app.state.operation_repository)
            reports, _ = await repository.list_reports(agent_id="retention-agent")
            report = next(item for item in reports if item.run_id == run_id)
            assert report.structured["analysis_reused"] is bool(index)
            assert (
                report.structured["analysis_calculated_at"]
                == datetime(2026, 10, 8, 12, tzinfo=UTC).isoformat()
            )
            ledger = cast(SqlAlchemyCostLedger, app.state.operation_cost_ledger)
            assert len(calls) == 21
            assert calls.count("/token") == 1
            assert (await ledger.periods())[0].usage.provider_requests == 21
        clock.value += timedelta(hours=1)
    get_settings.cache_clear()
