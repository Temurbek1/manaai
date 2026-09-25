import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import JsonValue
from pytest import MonkeyPatch

from app.core.config import Settings
from app.mana_operation_ai.application.ports import WriteOperationForbidden
from app.mana_operation_ai.application.runtime import SystemClock
from app.mana_operation_ai.domain.enums import ActionType, ProviderMode
from app.mana_operation_ai.domain.marketing import (
    AdAccount,
    AdEntityType,
    AdsCollectionRequest,
    Breakdown,
    CompatibilityStatus,
)
from app.mana_operation_ai.domain.models import BudgetActionParameters
from app.mana_operation_ai.infrastructure.ads.meta import (
    MetaAdsAdapter,
    _normalize_insight,
    _query_plans,
)
from app.services.meta_marketing_client import (
    MetaAuthenticationError,
    MetaMarketingClient,
    MetaObjectNotFoundError,
    MetaPaginationLimitError,
    MetaPermissionError,
    MetaReadOnlyViolation,
    MetaRequestBudgetExceeded,
    MetaTransientAPIError,
)

META_FIXTURES = Path(__file__).parent / "fixtures" / "meta"


def meta_fixture(name: str) -> dict[str, JsonValue]:
    payload: object = json.loads((META_FIXTURES / name).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"Meta fixture {name!r} must contain a JSON object")
    return cast(dict[str, JsonValue], payload)


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def settings(monkeypatch: MonkeyPatch, **overrides: str) -> Settings:
    values = {
        "OPENAI_API_KEY": "test-openai-key",
        "META_ACCESS_TOKEN": "test-meta-access-token",
        "META_APP_ID": "",
        "META_BUSINESS_ID": "",
        "META_AD_ACCOUNT_IDS": "[]",
        "META_RETRY_BACKOFF_SECONDS": "0.01",
        "META_MAX_RETRIES": "2",
        "META_MAX_PAGES": "10",
        "META_LIVE_MODE": "read_only",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return Settings()


async def test_meta_client_paginates_and_keeps_token_out_of_diagnostics(
    monkeypatch: MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json=meta_fixture("pagination_page_1.json"),
                headers={"x-fb-request-id": "request-1"},
            )
        return httpx.Response(
            200,
            json=meta_fixture("pagination_page_2.json"),
            headers={"x-fb-request-id": "request-2"},
        )

    client = MetaMarketingClient(
        settings(monkeypatch),
        transport=httpx.MockTransport(handler),
    )
    campaigns = await client.fetch_campaigns("act_1")
    diagnostics = client.consume_diagnostics()

    assert [item["id"] for item in campaigns] == ["campaign-1", "campaign-2"]
    assert len(requests) == 2
    assert requests[0].url.params["access_token"] == "test-meta-access-token"
    assert "test-meta-access-token" not in repr(diagnostics)
    assert [item.request_id for item in diagnostics] == ["request-1", "request-2"]


async def test_meta_client_retries_rate_limit_and_records_diagnostics(
    monkeypatch: MonkeyPatch,
) -> None:
    attempt = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempt
        del request
        attempt += 1
        if attempt == 1:
            return httpx.Response(
                429,
                json={"error": {"message": "rate limited", "code": 4}},
                headers={"x-fb-request-id": "rate-limit-request"},
            )
        return httpx.Response(
            200,
            json={"data": []},
            headers={"x-fb-request-id": "success-request"},
        )

    client = MetaMarketingClient(
        settings(monkeypatch),
        transport=httpx.MockTransport(handler),
    )
    assert await client.fetch_campaigns("act_1") == []
    diagnostics = client.consume_diagnostics()
    assert attempt == 2
    assert diagnostics[0].rate_limit_observed is True
    assert diagnostics[1].retry_count == 1


async def test_meta_client_rejects_silently_truncated_pagination(
    monkeypatch: MonkeyPatch,
) -> None:
    client = MetaMarketingClient(
        settings(monkeypatch, META_MAX_PAGES="1"),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "data": [{"id": "campaign-1"}],
                    "paging": {"next": "https://graph.facebook.com/v25.0/page-2"},
                },
                request=request,
            ),
        ),
    )

    with pytest.raises(MetaPaginationLimitError):
        await client.fetch_campaigns("act_1")
    assert client.consume_diagnostics()[-1].message == "pagination_limit_exceeded"


async def test_meta_page_budget_blocks_before_an_extra_transport_request(
    monkeypatch: MonkeyPatch,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, json={"data": []}, request=request)

    client = MetaMarketingClient(
        settings(
            monkeypatch,
            META_MAX_PAGES="1",
            META_LIVE_MAX_PAGES="1",
            META_LIVE_MAX_REQUESTS="2",
        ),
        transport=httpx.MockTransport(handler),
    )
    async with client.request_budget():
        assert await client.fetch_campaigns("act_1") == []
        with pytest.raises(MetaRequestBudgetExceeded, match="page budget"):
            await client.fetch_ads("act_1")
    assert attempts == 1


async def test_meta_health_reports_expiration_and_permissions_without_secret(
    monkeypatch: MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/debug_token"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "is_valid": True,
                        "expires_at": 2_000_000_000,
                        "data_access_expires_at": 2_000_000_100,
                        "scopes": ["ads_read", "business_management"],
                        "granular_scopes": [
                            {"scope": "ads_read", "target_ids": ["act_private"]},
                        ],
                        "user_id": "private-user-id",
                    },
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "act_1",
                        "name": "Private account name",
                        "currency": "USD",
                        "timezone_name": "UTC",
                    },
                ],
            },
            request=request,
        )

    configured = settings(monkeypatch, META_ACCESS_TOKEN="test-secret-value")
    adapter = MetaAdsAdapter(
        client=MetaMarketingClient(configured, transport=httpx.MockTransport(handler)),
        settings=configured,
        clock=SystemClock(),
    )
    health = await adapter.health()

    assert health.status.value == "healthy"
    token_health = health.diagnostics["token"]
    assert isinstance(token_health, dict)
    assert token_health["expires_at"] == 2_000_000_000
    assert token_health["scopes"] == ["ads_read", "business_management"]
    assert "target_ids" not in repr(token_health)
    assert "private-user-id" not in repr(health)
    assert "test-secret-value" not in repr(health)


async def test_async_insights_polling_and_results_remain_get_only(
    monkeypatch: MonkeyPatch,
) -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path.endswith("/report-run-1"):
            return httpx.Response(
                200,
                json={
                    "id": "report-run-1",
                    "async_status": "Job Completed",
                    "async_percent_completion": 100,
                },
                request=request,
            )
        return httpx.Response(
            200,
            json={"data": [{"id": "insight-row-1", "spend": "10.00"}]},
            request=request,
        )

    client = MetaMarketingClient(
        settings(monkeypatch),
        transport=httpx.MockTransport(handler),
    )
    status = await client.fetch_insights_async_job_status("report-run-1")
    rows = await client.fetch_insights_async_job_results(report_run_id="report-run-1")

    assert status["async_status"] == "Job Completed"
    assert rows == [{"id": "insight-row-1", "spend": "10.00"}]
    assert methods == ["GET", "GET"]


async def test_meta_collection_preserves_partial_breakdown_as_unavailable(
    monkeypatch: MonkeyPatch,
) -> None:
    # The adapter rejects reporting periods that are not complete in its own UTC clock,
    # so the fixture day must be derived from UTC rather than the local calendar date.
    completed_day = datetime.now(UTC).date() - timedelta(days=1)
    insight = meta_fixture("insight_region.json")
    insight["date_start"] = completed_day.isoformat()
    insight["date_stop"] = completed_day.isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/me/adaccounts"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "act_1",
                            "name": "Account",
                            "currency": "USD",
                            "timezone_name": "UTC",
                            "account_status": 1,
                        },
                    ],
                },
                request=request,
            )
        if request.url.path.endswith("/insights"):
            if request.url.params.get("breakdowns") == "region":
                return httpx.Response(
                    400,
                    json={"error": {"message": "invalid combination", "code": 100}},
                    request=request,
                )
            rows = [insight] if request.url.params.get("level") == "ad" else []
            return httpx.Response(200, json={"data": rows}, request=request)
        return httpx.Response(200, json={"data": []}, request=request)

    configured = settings(monkeypatch)
    adapter = MetaAdsAdapter(
        client=MetaMarketingClient(configured, transport=httpx.MockTransport(handler)),
        settings=configured,
        clock=SystemClock(),
    )
    snapshot = await adapter.collect(
        AdsCollectionRequest(
            date_start=completed_day,
            date_stop=completed_day,
            attribution_window="7d_click",
            requested_breakdowns=[Breakdown.REGION],
        ),
    )

    region = next(
        item
        for item in snapshot.compatibility_matrix
        if item.operation == "insights" and item.breakdowns == ["region"]
    )
    assert region.status is CompatibilityStatus.INVALID_COMBINATION
    assert region.row_count == 0
    assert len(snapshot.insights) == 1
    assert any("region" in note for note in snapshot.data_quality_notes)


async def test_meta_data_freshness_is_measured_against_the_utc_clock(
    monkeypatch: MonkeyPatch,
) -> None:
    """Freshness must follow the adapter clock, not the host's local calendar date."""
    reported_day = date(2026, 7, 22)
    insight = meta_fixture("insight_region.json")
    insight["date_start"] = reported_day.isoformat()
    insight["date_stop"] = reported_day.isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/me/adaccounts"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "act_1",
                            "name": "Account",
                            "currency": "USD",
                            "timezone_name": "UTC",
                            "account_status": 1,
                        },
                    ],
                },
                request=request,
            )
        if request.url.path.endswith("/insights"):
            rows = [insight] if request.url.params.get("level") == "ad" else []
            return httpx.Response(200, json={"data": rows}, request=request)
        return httpx.Response(200, json={"data": []}, request=request)

    configured = settings(monkeypatch)
    # 2026-07-25 in UTC is still 2026-07-24 in UTC-11 and already 2026-07-25 in UTC+14,
    # so a local-calendar implementation would report 2 or 4 days instead of 3.
    adapter = MetaAdsAdapter(
        client=MetaMarketingClient(configured, transport=httpx.MockTransport(handler)),
        settings=configured,
        clock=FixedClock(datetime(2026, 7, 25, 3, 0, tzinfo=UTC)),
    )
    snapshot = await adapter.collect(
        AdsCollectionRequest(
            date_start=reported_day,
            date_stop=reported_day,
            attribution_window="7d_click",
            requested_breakdowns=[],
        ),
    )

    assert snapshot.observability is not None
    assert snapshot.observability.data_freshness_days == 3


def test_meta_normalization_tracks_query_scope_and_explicit_unavailable_metrics() -> None:
    account = AdAccount(
        provider_id="act_1",
        name="Account",
        currency="USD",
        timezone="UTC",
        status="ACTIVE",
    )
    insight = _normalize_insight(
        payload=meta_fixture("insight_region.json"),
        account=account,
        attribution_window="7d_click",
        query_scope="region",
        creative_by_ad={"ad-1": "creative-1"},
        audience_by_ad_set={"set-1": "audience-1"},
        conversion_action_types={"lead"},
        value_action_types={"purchase"},
    )

    assert insight.entity_type is AdEntityType.AD
    assert insight.dimensions == {
        "region": "Tashkent",
        "_query_scope": "region",
        "day": date(2026, 7, 22).strftime("%A"),
    }
    assert insight.metrics.cpl.value == Decimal("2.5")
    assert insight.metrics.roas.value is None
    assert _query_plans([Breakdown.AGE, Breakdown.GENDER]) == [(), ("age", "gender")]


async def test_live_meta_adapter_rejects_write_without_transport(
    monkeypatch: MonkeyPatch,
) -> None:
    attempts = 0

    def forbidden_transport(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise AssertionError(f"Unexpected provider request: {request.method}")

    configured = settings(monkeypatch)
    adapter = MetaAdsAdapter(
        client=MetaMarketingClient(
            configured,
            transport=httpx.MockTransport(forbidden_transport),
        ),
        settings=configured,
        clock=SystemClock(),
    )
    assert adapter.provider_mode is ProviderMode.LIVE_READ_ONLY
    with pytest.raises(WriteOperationForbidden):
        await adapter.execute(
            object_type="ad_set",
            provider_object_id="set-1",
            parameters=BudgetActionParameters(
                kind=ActionType.INCREASE_BUDGET,
                currency="USD",
                current_daily_budget=Decimal("50"),
                proposed_daily_budget=Decimal("55"),
            ),
            idempotency_key="never-sent",
        )
    assert attempts == 0


@pytest.mark.parametrize(
    ("error", "expected_type"),
    [
        ({"message": "invalid token", "code": 190}, MetaAuthenticationError),
        ({"message": "permission denied", "code": 200}, MetaPermissionError),
        (
            {"message": "object unavailable", "code": 100, "error_subcode": 33},
            MetaObjectNotFoundError,
        ),
    ],
)
async def test_meta_client_classifies_permanent_graph_errors(
    monkeypatch: MonkeyPatch,
    error: dict[str, object],
    expected_type: type[Exception],
) -> None:
    client = MetaMarketingClient(
        settings(monkeypatch),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                400,
                json={"error": error},
                request=request,
            ),
        ),
    )

    with pytest.raises(expected_type):
        await client.fetch_object_state("set-1")


async def test_meta_contract_error_fixtures_cover_transient_and_permanent_variants(
    monkeypatch: MonkeyPatch,
) -> None:
    variants = meta_fixture("graph_error_variants.json")
    expectations: dict[str, type[Exception]] = {
        "authentication": MetaAuthenticationError,
        "permission": MetaPermissionError,
        "object_not_found": MetaObjectNotFoundError,
        "transient": MetaTransientAPIError,
        "rate_limit": MetaTransientAPIError,
    }
    for name, expected_type in expectations.items():
        payload = variants[name]
        if not isinstance(payload, dict):
            raise AssertionError(f"Meta error fixture {name!r} must be an object")
        client = MetaMarketingClient(
            settings(monkeypatch, META_MAX_RETRIES="0"),
            transport=httpx.MockTransport(
                lambda request, response_payload=payload: httpx.Response(
                    400,
                    json=response_payload,
                    request=request,
                ),
            ),
        )
        with pytest.raises(expected_type):
            await client.fetch_object_state("set-1")


async def test_meta_client_blocks_async_insights_post_before_transport(
    monkeypatch: MonkeyPatch,
) -> None:
    attempts = 0

    def forbidden_transport(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise AssertionError(f"Unexpected provider request: {request.method}")

    client = MetaMarketingClient(
        settings(monkeypatch),
        transport=httpx.MockTransport(forbidden_transport),
    )

    with pytest.raises(MetaReadOnlyViolation):
        await client.create_insights_async_job(
            account_id="act_1",
            level="ad",
            date_start=date(2026, 7, 1),
            date_stop=date(2026, 7, 3),
        )
    assert attempts == 0


async def test_meta_transport_exception_text_cannot_enter_diagnostics(
    monkeypatch: MonkeyPatch,
) -> None:
    token = "test-meta-access-token"

    def leak_attempt(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(str(request.url), request=request)

    client = MetaMarketingClient(
        settings(monkeypatch, META_MAX_RETRIES="0"),
        transport=httpx.MockTransport(leak_attempt),
    )

    with pytest.raises(MetaTransientAPIError):
        await client.fetch_campaigns("act_1")
    assert token not in repr(client.consume_diagnostics())


async def test_meta_account_currency_and_minimum_budget_are_normalized(
    monkeypatch: MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/set-1"):
            return httpx.Response(
                200,
                json=meta_fixture("adset_state.json"),
                request=request,
            )
        return httpx.Response(
            200,
            json=meta_fixture("ad_account.json"),
            request=request,
        )

    configured = settings(monkeypatch)
    adapter = MetaAdsAdapter(
        client=MetaMarketingClient(configured, transport=httpx.MockTransport(handler)),
        settings=configured,
        clock=SystemClock(),
    )

    state = await adapter.get_object_state("ad_set", "set-1")

    assert state.currency == "EUR"
    assert state.daily_budget == Decimal("50")
    assert state.raw_safe["minimum_daily_budget"] == "2.5"


def test_startup_configuration_rejects_every_live_write_gate(
    monkeypatch: MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="META_REAL_WRITES_ENABLED"):
        settings(monkeypatch, META_REAL_WRITES_ENABLED="true")
    with pytest.raises(ValueError, match="OPERATION_DRY_RUN"):
        settings(
            monkeypatch,
            META_REAL_WRITES_ENABLED="false",
            OPERATION_ADS_PROVIDER="meta",
            OPERATION_DRY_RUN="false",
        )
