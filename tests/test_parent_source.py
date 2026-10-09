import gzip
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.mana_operation_ai.application.ports import ProviderPermanentError, ProviderTransientError
from app.mana_operation_ai.infrastructure.retention.manakids import ManakidsAdminActivityAdapter
from app.mana_operation_ai.infrastructure.retention.parents import ManakidsParentSummaryAdapter


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 9, 30, tzinfo=UTC)


def row(identifier: int = 1, **overrides: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "fullname": "PRIVATE PARENT",
        "phone": "+998000000001",
        "age": 0,
        "region": "PRIVATE REGION",
        "district": None,
        "tariff_name": "FREE PRIVATE PLAN",
        "valid_until": "2026-10-02T00:00:00Z",
        "payment_date": "2026-09-29T00:00:00+00:00",
        "children_count": 1,
        "children": [
            {
                "id": 88,
                "fullname": "PRIVATE CHILD",
                "avatar": "https://private.test/avatar",
                "is_connected": True,
            }
        ],
        **overrides,
    }


def adapter(
    client: httpx.AsyncClient, *, limit: int = 10, byte_limit: int = 1048576
) -> ManakidsParentSummaryAdapter:
    clock = Clock()
    reader = ManakidsAdminActivityAdapter(
        client=client,
        base_url="https://manakids.test",
        username="test-user",
        password="test-password",
        clock=clock,
        max_retries=0,
        retry_backoff_seconds=0.01,
        max_pages=1,
        max_response_bytes=byte_limit,
    )
    return ManakidsParentSummaryAdapter(reader, clock, limit)


async def test_parent_summary_is_bounded_minimized_and_not_payment_evidence() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            assert request.url.path == "/api/v1/admin-panel-auth/login/"
            return httpx.Response(200, json={"access": "test-jwt"})
        assert request.url.path == "/api/v1/admin-panel-parent/parent-list/"
        assert dict(request.url.params) == {"limit": "10", "offset": "0"}
        assert request.headers["Authorization"] == "Bearer test-jwt"
        return httpx.Response(
            200,
            json={
                "count": 202881,
                "next": "https://evil.test/exfiltrate",
                "results": [
                    row(),
                    row(
                        2,
                        tariff_name=None,
                        valid_until=None,
                        payment_date=None,
                        children=[],
                        children_count=0,
                    ),
                    row(3, valid_until="unparseable", payment_date="2026-09-29", children_count=2),
                    row(4, valid_until="2026-10-29T00:00:00Z", age=34),
                    row(5, valid_until="2026-09-29T00:00:00Z"),
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        facts = await adapter(client).collect_summary()
    assert len(requests) == 2
    assert facts.product == "mana" and facts.scope_verified
    assert facts.total_parents == 202881 and facts.sampled_parents == 5 and facts.has_more
    assert facts.parents_with_current_tariff == 2
    assert facts.parents_without_current_tariff == 1
    assert facts.parents_with_inconsistent_tariff == 2
    assert facts.tariffs_expiring_within_7_days == 1
    assert facts.tariffs_expiring_within_30_days == 2
    assert facts.parents_with_known_age == 1
    assert facts.connected_child_relationships == 4
    serialized = facts.model_dump_json()
    for private in ["PRIVATE", "+998000000001", "private.test", "test-jwt", "test-password"]:
        assert private not in serialized
    assert "бесплатным" in serialized
    assert "частично" in serialized


@pytest.mark.parametrize("status", [403, 429, 500, 302])
async def test_parent_access_failure_never_loops_or_follows_redirect(status: int) -> None:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return (
            httpx.Response(200, json={"access": "test-jwt"})
            if request.method == "POST"
            else httpx.Response(
                status,
                headers={"Location": "https://evil.test"},
                json={"private": "NEVER LEAK THIS"},
            )
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), follow_redirects=True
    ) as client:
        with pytest.raises((ProviderPermanentError, ProviderTransientError)) as exc:
            await adapter(client).collect_summary()
    assert calls == ["POST", "GET"]
    assert "NEVER LEAK" not in str(exc.value)


async def test_parent_expired_token_has_only_one_refresh() -> None:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return (
            httpx.Response(200, json={"access": "same-test-token"})
            if request.method == "POST"
            else httpx.Response(401)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ProviderPermanentError, match="401"):
            await adapter(client).collect_summary()
    assert calls == ["POST", "GET", "POST", "GET"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"count": 1, "next": None, "results": []},
        {"count": 1, "next": None, "results": [{"id": 1}]},
        {"count": 2, "next": None, "results": [row(), row()]},
        {"count": 2, "next": None, "results": [row(), row(2)]},
        {"count": 1, "next": None, "results": [row(children=[{"id": 1, "is_connected": "true"}])]},
    ],
)
async def test_parent_invalid_or_oversized_page_fails_closed(payload: dict[str, Any]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"access": "test-jwt"} if request.method == "POST" else payload
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ProviderPermanentError):
            await adapter(client, limit=1).collect_summary()


async def test_parent_response_byte_limit_and_empty_inventory() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access": "test-jwt"}
            if request.method == "POST"
            else {
                "count": 0,
                "next": None,
                "results": [],
                "unused": "x" * 2000,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ProviderPermanentError, match="byte limit"):
            await adapter(client, byte_limit=512).collect_summary()
        facts = await adapter(client).collect_summary()
    assert facts.sampled_parents == 0 and facts.total_parents == 0 and not facts.has_more


def test_parent_configuration_is_opt_in_and_limits_are_validated() -> None:
    assert Settings(_env_file=None, openai_api_key="test").manakids_parent_source_enabled is False
    with pytest.raises(ValidationError):
        Settings(_env_file=None, openai_api_key="test", manakids_parent_source_enabled=True)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, openai_api_key="test", manakids_parent_sample_limit=101)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, openai_api_key="test", manakids_parent_min_interval_seconds=60)


async def test_parent_login_denial_stops_before_data_request() -> None:
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(403, json={"private": "DO NOT LEAK"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ProviderPermanentError, match="403") as caught:
            await adapter(client).collect_summary()
    assert calls == ["POST"] and "DO NOT LEAK" not in str(caught.value)


async def test_parent_gzip_response_is_not_decoded_twice() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        body = (
            {"access": "test-jwt"}
            if request.method == "POST"
            else {
                "count": 1,
                "next": None,
                "results": [row()],
            }
        )
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            content=gzip.compress(json.dumps(body).encode()),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        facts = await adapter(client).collect_summary()
    assert facts.sampled_parents == 1
