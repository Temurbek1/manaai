"""The new account contract uses fictional responses and no real service calls."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import pytest

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.conversion_accounts import ConversionAccountSource
from app.services.manakids_conversion_accounts import ManakidsConversionAccountSource
from tests.test_parent_chat import NOW


def account(**changes: Any) -> dict[str, Any]:
    return {
        "id": 123,
        "is_paid": False,
        "created_at": (NOW - timedelta(days=365)).isoformat(),
        "agent_trial_used": False,
        "payment_date": (NOW - timedelta(days=7)).isoformat(),
        "valid_until": (NOW + timedelta(days=1)).isoformat(),
        "tariff_name": "Maxsus",
        "fullname": "Fictional Adult",
        "phone": "fake-phone-not-for-propagation",
        "children": [{"id": 456, "fullname": "Fictional Child"}],
    } | changes


def page(record: dict[str, Any]) -> dict[str, Any]:
    return {"count": 1, "results": [record], "next": None}


def source(client: httpx.AsyncClient, **changes: Any) -> ManakidsConversionAccountSource:
    options: dict[str, Any] = {
        "base_url": "https://synthetic.invalid",
        "username": "fake-user",
        "password": "fake-password",
        "clock": lambda: NOW,
    }
    return ManakidsConversionAccountSource(client=client, **(options | changes))


@pytest.mark.parametrize(("is_paid", "trial_used"), [(True, False), (False, True), (None, None)])
async def test_exact_parent_read_minimizes_fields_without_classifying_or_claiming_a_free_start(
    is_paid: bool | None, trial_used: bool | None
) -> None:
    calls: list[httpx.Request] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.host == "synthetic.invalid"
        if request.url.path.endswith("/login/"):
            assert request.method == "POST"
            assert json.loads(request.content) == {
                "username": "fake-user",
                "password": "fake-password",
            }
            return httpx.Response(200, json={"access": "fake-jwt"})
        assert request.method == "GET"
        assert request.url.path == "/api/v1/admin-panel-parent/parent-list/"
        assert dict(request.url.params) == {"parent_id": "123", "limit": "1", "offset": "0"}
        assert request.headers["Authorization"] == "Bearer fake-jwt"
        return httpx.Response(200, json=page(account(is_paid=is_paid, agent_trial_used=trial_used)))

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        port: ConversionAccountSource = source(client)
        result = await port.read("123")
    assert len(calls) == 2
    assert result.parent_id == "123" and result.collected_at == NOW
    assert result.is_paid is is_paid and result.agent_trial_used is trial_used
    assert result.created_at == NOW - timedelta(days=365)
    assert result.payment_date == NOW - timedelta(days=7)
    dumped = result.model_dump_json()
    for omitted in ("Fictional", "fake-phone", "children", "tariff_name", "free_started_at"):
        assert omitted not in dumped
    assert "subscription" not in type(result).model_fields


@pytest.mark.parametrize("field", ["is_paid", "created_at", "agent_trial_used"])
async def test_announced_but_missing_fields_are_not_defaulted(field: str) -> None:
    record = account()
    del record[field]
    calls = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-jwt"})
        return httpx.Response(200, json=page(record))

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ParentChatError, match="conversion_account_invalid") as caught:
            await source(client).read("123")
    assert caught.value.status_code == 503 and calls == 2
    assert "fake-phone" not in str(caught.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"is_paid": 0},
        {"is_paid": "false"},
        {"agent_trial_used": 1},
        {"agent_trial_used": "true"},
        {"created_at": 1234567890},
        {"created_at": "1234567890"},
        {"created_at": "2026-10-21T09:00:00"},
        {"created_at": ""},
        {"created_at": (NOW + timedelta(seconds=121)).isoformat()},
        {"payment_date": (NOW + timedelta(seconds=121)).isoformat()},
        {"valid_until": "2026-10-21"},
        {"id": True},
        {"id": "123"},
        {"id": 2**63},
    ],
)
async def test_malformed_or_unobserved_values_fail_closed(changes: dict[str, Any]) -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, json={"access": "fake-jwt"})
            if request.url.path.endswith("/login/")
            else httpx.Response(200, json=page(account(**changes)))
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ParentChatError, match="conversion_account_invalid"):
            await source(client).read("123")


async def test_explicit_unknown_dates_and_status_are_preserved_as_unknown() -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, json={"access": "fake-jwt"})
            if request.url.path.endswith("/login/")
            else httpx.Response(
                200,
                json=page(
                    account(
                        is_paid=None,
                        created_at=None,
                        agent_trial_used=None,
                        payment_date=None,
                        valid_until=None,
                    )
                ),
            )
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        result = await source(client).read("123")
    assert result.created_at is None and result.is_paid is None
    assert result.agent_trial_used is None and result.valid_until is None


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"count": 0, "results": [], "next": None}, "parent_not_found"),
        (page(account(id=456)), "conversion_account_owner_mismatch"),
        ({"count": 0, "results": [account()]}, "conversion_account_invalid"),
        ({"count": 1, "results": []}, "conversion_account_invalid"),
        ({"count": 2, "results": [account(), account()]}, "conversion_account_invalid"),
        (page(account()) | {"next": "https://unapproved.invalid/"}, "conversion_account_invalid"),
        (page(account()) | {"next": ""}, "conversion_account_invalid"),
        ({"count": True, "results": [account()]}, "conversion_account_invalid"),
    ],
)
async def test_owner_or_pagination_errors_never_follow_another_page(
    body: dict[str, Any], code: str
) -> None:
    calls = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return (
            httpx.Response(200, json={"access": "fake-jwt"})
            if request.url.path.endswith("/login/")
            else httpx.Response(200, json=body)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ParentChatError, match=code):
            await source(client).read("123")
    assert calls == 2


@pytest.mark.parametrize(
    "identifier", ["", "0", "0123", "+123", " 123", "123 ", "١٢٣", "1/2", str(2**63), "uid"]
)
async def test_invalid_ids_do_not_even_login(identifier: str) -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Invalid ID must not dispatch")

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ParentChatError, match="parent_profile_id_required"):
            await source(client).read(identifier)


@pytest.mark.parametrize("status", [301, 302, 401, 403, 429, 500])
@pytest.mark.parametrize("stage", ["login", "read"])
async def test_http_failures_never_retry_relogin_or_follow_redirects(
    stage: str, status: int
) -> None:
    calls: list[httpx.Request] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        login = request.url.path.endswith("/login/")
        if login and stage == "read":
            return httpx.Response(200, json={"access": "fake-jwt"})
        return httpx.Response(
            status,
            json={"private": "fake-sensitive-upstream-text"},
            headers={"Location": "https://unapproved.invalid/"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(dispatch), follow_redirects=True
    ) as client:
        adapter = source(client)
        with pytest.raises(ParentChatError) as caught:
            await adapter.read("123")
        assert "fake-sensitive" not in str(caught.value)
        assert len(calls) == (1 if stage == "login" else 2)
        if stage == "login" or status in {401, 403}:
            with pytest.raises(ParentChatError, match="cooling_down"):
                await adapter.read("123")
            assert len(calls) == (1 if stage == "login" else 2)


@pytest.mark.parametrize(
    ("stage", "raw"),
    [
        ("login", b'{"access":"fake-jwt","access":"fake-other"}'),
        ("read", b'{"count":0,"count":1,"results":[]}'),
        ("read", b'{"results":[{"id":123,"is_paid":true,"is_paid":false}]}'),
        ("login", b"x" * 16_385),
        ("read", b"x" * 65_537),
        ("login", b"not JSON"),
        ("read", b"\xff"),
        ("read", b"[" * 2000 + b"]" * 2000),
        ("login", b'{"access":"fake-jwt\\r\\nprivate"}'),
    ],
)
async def test_bounded_unambiguous_json_and_tokens(stage: str, raw: bytes) -> None:
    calls = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/login/") and stage == "read":
            return httpx.Response(200, json={"access": "fake-jwt"})
        return httpx.Response(200, content=raw)

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ParentChatError):
            await source(client).read("123")
    assert calls == (1 if stage == "login" else 2)


async def test_streamed_body_ceiling_stops_without_draining_or_retry() -> None:
    class LargeBody(httpx.AsyncByteStream):
        chunks = 0

        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range(30):
                self.chunks += 1
                yield b" " * 4096

    body = LargeBody()

    def dispatch(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-jwt"})
        return httpx.Response(200, stream=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ParentChatError, match="conversion_account_invalid"):
            await source(client).read("123")
    assert body.chunks == 17


@pytest.mark.parametrize("kind", ["timeout", "wall", "cancel"])
async def test_lost_read_does_not_restart_itself(kind: str) -> None:
    calls = 0
    started = asyncio.Event()

    async def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-jwt"})
        started.set()
        if kind == "timeout":
            raise httpx.ReadTimeout("fake-private-error")
        await asyncio.Event().wait()
        raise AssertionError("Unreachable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        adapter = source(client, wall_timeout_seconds=0.05 if kind == "wall" else 30)
        pending = asyncio.create_task(adapter.read("123"))
        await asyncio.wait_for(started.wait(), 1)
        if kind == "cancel":
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            with pytest.raises(ParentChatError, match="conversion_account_unavailable"):
                await pending
    assert calls == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"base_url": "http://synthetic.invalid"},
        {"base_url": "https://fake-user:fake-password@synthetic.invalid"},
        {"base_url": "https://synthetic.invalid/api/v1"},
        {"base_url": "https://synthetic.invalid?query=1"},
        {"base_url": "https://synthetic.invalid#fragment"},
        {"base_url": "not an origin"},
        {"username": ""},
        {"password": ""},
        {"wall_timeout_seconds": 0},
        {"wall_timeout_seconds": float("nan")},
        {"wall_timeout_seconds": 121},
    ],
)
async def test_explicit_configuration_is_validated_without_dispatch(
    changes: dict[str, Any],
) -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError):
            source(client, **changes)
