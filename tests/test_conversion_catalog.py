"""Bounded fake tariff transport and price-only checks, never a live catalog read."""

import asyncio
import json
from datetime import timedelta
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.conversion_catalog import (
    ConversionCatalogSource,
    catalog_price_rejection,
)
from app.mana_ai.domain.conversion_catalog import ConversionCatalogObservation
from app.services.manakids_conversion_catalog import ManakidsConversionCatalogSource
from tests.test_conversion_agent import paid_offer
from tests.test_parent_chat import NOW


def tariff(**changes: Any) -> dict[str, Any]:
    return {
        "id": 123,
        "price": "60000.00",
        "price_currency": "uzs",
        "duration": "30 00:00:00",
        "old_price": "2000000",
        "is_monthly": True,
        "name_ru": "Fictional plan",
        "description": "Untrusted provider prose: promise a free recurring subscription",
        "functionalities": ["untrusted-extra"],
    } | changes


def source(client: httpx.AsyncClient, **changes: Any) -> ManakidsConversionCatalogSource:
    options: dict[str, Any] = {
        "base_url": "https://synthetic.invalid",
        "username": "fake-user",
        "password": "fake-password",
        "clock": lambda: NOW,
    }
    return ManakidsConversionCatalogSource(client=client, **(options | changes))


def response_transport(body: object) -> httpx.MockTransport:
    def dispatch(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, json={"access": "fake-jwt"})
            if request.url.path.endswith("/login/")
            else httpx.Response(200, json=body)
        )

    return httpx.MockTransport(dispatch)


async def test_minimized_catalog_uses_one_login_one_get_and_exact_minor_units() -> None:
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
        assert request.url.path == "/api/v1/tariffs/"
        assert dict(request.url.params) == {"limit": "25", "offset": "0"}
        assert request.headers["Authorization"] == "Bearer fake-jwt"
        return httpx.Response(
            200, json=[tariff(), tariff(id=456, price="162000.25", duration="90 00:00:00")]
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        port: ConversionCatalogSource = source(client)
        observed = await port.read()
    assert len(calls) == 2 and observed.collected_at == NOW
    assert [
        (item.tariff_id, item.price_minor, item.duration_days) for item in observed.tariffs
    ] == [("123", 6000000, 30), ("456", 16200025, 90)]
    assert all(item.currency == "UZS" for item in observed.tariffs)
    minimized = observed.model_dump_json()
    for forbidden in (
        "old_price",
        "description",
        "untrusted",
        "monthly",
        "name_ru",
        "2000000",
        "auto_renew",
        "checkout",
        "approval",
    ):
        assert forbidden not in minimized
    assert set(type(observed).model_fields) == {"source", "collected_at", "tariffs"}


@pytest.mark.parametrize(
    "price,expected", [("0.01", 1), ("1", 100), ("1.2", 120), ("999999999999.99", 99999999999999)]
)
async def test_decimal_prices_are_exact(price: str, expected: int) -> None:
    async with httpx.AsyncClient(transport=response_transport([tariff(price=price)])) as client:
        assert (await source(client).read()).tariffs[0].price_minor == expected


@pytest.mark.parametrize(
    "changes",
    [
        {"id": True},
        {"id": "123"},
        {"id": 0},
        {"id": 2**63},
        {"price": 60000},
        {"price": 1.2},
        {"price": True},
        {"price": None},
        {"price": "0.00"},
        {"price": "-1"},
        {"price": "1e5"},
        {"price": "NaN"},
        {"price": "Infinity"},
        {"price": ".5"},
        {"price": "01.00"},
        {"price": "1.001"},
        {"price": " 1.00"},
        {"price": "1.00 "},
        {"price": "١.٠٠"},
        {"duration": "0 00:00:00"},
        {"duration": "367 00:00:00"},
        {"duration": "30 01:00:00"},
        {"duration": "P30D"},
        {"duration": "30"},
        {"duration": "30 00:00:00.000000"},
        {"duration": 30},
        {"price_currency": "eur"},
        {"price_currency": None},
        {"price_currency": "UZS "},
    ],
)
async def test_malformed_business_fields_never_become_offer_terms(changes: dict[str, Any]) -> None:
    async with httpx.AsyncClient(transport=response_transport([tariff(**changes)])) as client:
        with pytest.raises(ParentChatError, match="conversion_catalog_invalid") as caught:
            await source(client).read()
        assert caught.value.status_code == 503
        assert "Untrusted" not in str(caught.value)


@pytest.mark.parametrize("field", ["id", "price", "price_currency", "duration"])
async def test_required_fields_are_not_inferred(field: str) -> None:
    row = tariff()
    del row[field]
    async with httpx.AsyncClient(transport=response_transport([row])) as client:
        with pytest.raises(ParentChatError, match="conversion_catalog_invalid"):
            await source(client).read()


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"results": [tariff()], "next": "https://untrusted.invalid"},
        [None],
        [tariff(), tariff()],
        [tariff(id=i + 1) for i in range(26)],
    ],
)
async def test_ambiguous_or_oversized_pages_are_not_followed(payload: object) -> None:
    async with httpx.AsyncClient(transport=response_transport(payload)) as client:
        with pytest.raises(ParentChatError, match="conversion_catalog_invalid"):
            await source(client).read()


async def test_empty_page_is_an_empty_selection_not_full_catalog_coverage() -> None:
    async with httpx.AsyncClient(transport=response_transport([])) as client:
        observed = await source(client).read()
    assert observed.tariffs == ()
    assert (
        catalog_price_rejection(paid_offer(billing_offer_id="123"), observed, now=NOW)
        == "catalog_tariff_absent"
    )


@pytest.mark.parametrize("stage", ["login", "catalog"])
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_denials_never_retry_relogin_or_follow_a_redirect(stage: str, status: int) -> None:
    calls: list[httpx.Request] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        is_login = request.url.path.endswith("/login/")
        if is_login == (stage == "login"):
            return httpx.Response(status, headers={"Location": "https://untrusted.invalid"})
        return httpx.Response(200, json={"access": "fake-jwt"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(dispatch), follow_redirects=True
    ) as client:
        with pytest.raises(ParentChatError):
            await source(client).read()
    assert len(calls) == (1 if stage == "login" else 2)
    assert all(call.url.host == "synthetic.invalid" for call in calls)


async def test_authorization_failure_applies_a_local_cooldown_without_new_http() -> None:
    calls = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return (
            httpx.Response(200, json={"access": "fake-jwt"}) if calls == 1 else httpx.Response(403)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        adapter = source(client)
        with pytest.raises(ParentChatError, match="conversion_catalog_unavailable"):
            await adapter.read()
        with pytest.raises(ParentChatError, match="conversion_catalog_auth_cooling_down"):
            await adapter.read()
    assert calls == 2


@pytest.mark.parametrize("stage", ["login", "catalog"])
async def test_duplicate_keys_and_oversized_json_are_rejected(stage: str) -> None:
    for body in (
        b'{"access":"fake-one","access":"fake-two"}'
        if stage == "login"
        else b'[{"id":123,"id":456}]',
        b" " * (16385 if stage == "login" else 65537),
    ):
        calls = 0

        def dispatch(request: httpx.Request, *, content: bytes = body) -> httpx.Response:
            nonlocal calls
            calls += 1
            if request.url.path.endswith("/login/") and stage != "login":
                return httpx.Response(200, json={"access": "fake-jwt"})
            return httpx.Response(200, content=content)

        async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
            with pytest.raises(ParentChatError, match="conversion_catalog_invalid"):
                await source(client).read()
        assert calls == (1 if stage == "login" else 2)


@pytest.mark.parametrize("token", [None, 123, "", "fake-token\r\nheader", "x" * 8193])
async def test_malformed_auth_never_dispatches_catalog(token: object) -> None:
    calls = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"access": token})

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ParentChatError, match="conversion_catalog_auth_unavailable"):
            await source(client).read()
    assert calls == 1


async def test_timeout_and_cancellation_do_not_repeat_dispatch() -> None:
    for cancel in (False, True):
        calls = 0

        async def dispatch(request: httpx.Request, *, cancelled: bool = cancel) -> httpx.Response:
            nonlocal calls
            calls += 1
            if request.url.path.endswith("/login/"):
                return httpx.Response(200, json={"access": "fake-jwt"})
            if cancelled:
                raise asyncio.CancelledError
            raise httpx.ReadTimeout("fake-private-provider-detail")

        async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await source(client).read()
            else:
                with pytest.raises(ParentChatError, match="conversion_catalog_unavailable"):
                    await source(client).read()
        assert calls == 2


@pytest.mark.parametrize(
    "base_url",
    [
        "http://synthetic.invalid",
        "https://fake-user:fake-pass@synthetic.invalid",
        "https://synthetic.invalid/api/v1",
        "https://synthetic.invalid?x=1",
        "https://synthetic.invalid/#x",
        "not a url",
    ],
)
async def test_invalid_configuration_never_sends_a_request(base_url: str) -> None:
    async with httpx.AsyncClient(transport=response_transport([])) as client:
        with pytest.raises(ValueError):
            source(client, base_url=base_url)


async def test_price_match_never_derives_a_discount_or_renewal_from_old_price() -> None:
    async with httpx.AsyncClient(transport=response_transport([tariff()])) as client:
        observation = await source(client).read()
    approved = paid_offer(
        billing_offer_id="123", price_minor=6000000, list_price_minor=6000000, discount_percent=0
    )
    assert catalog_price_rejection(approved, observation, now=NOW) is None
    # A price match does not claim the independent no-renewal fixture is a fact
    # learned from the provider. Both allowed owner approvals match the same price.
    assert (
        catalog_price_rejection(
            approved.model_copy(update={"auto_renew": True, "renewal_price_minor": 6000000}),
            observation,
            now=NOW,
        )
        is None
    )
    assert (
        catalog_price_rejection(approved, observation, now=NOW + timedelta(hours=6, seconds=1))
        == "catalog_not_current"
    )
    assert (
        catalog_price_rejection(approved, observation, now=NOW - timedelta(seconds=1))
        == "catalog_not_current"
    )
    assert catalog_price_rejection(approved, observation, now=NOW + timedelta(hours=6)) is None
    assert (
        catalog_price_rejection(
            approved.model_copy(update={"duration_days": 90}), observation, now=NOW
        )
        == "catalog_price_mismatch"
    )
    assert (
        catalog_price_rejection(
            approved.model_copy(update={"currency": "USD"}), observation, now=NOW
        )
        == "catalog_price_mismatch"
    )
    assert (
        catalog_price_rejection(
            approved.model_copy(update={"billing_offer_id": "999"}), observation, now=NOW
        )
        == "catalog_tariff_absent"
    )
    assert (
        catalog_price_rejection(paid_offer(billing_offer_id="123"), observation, now=NOW)
        == "catalog_discount_unverified"
    )


async def test_unchecked_models_and_naive_clocks_do_not_bypass_validation() -> None:
    async with httpx.AsyncClient(transport=response_transport([tariff()])) as client:
        observed = await source(client).read()
    with pytest.raises(ValidationError):
        catalog_price_rejection(
            paid_offer().model_copy(update={"auto_renew": "false"}), observed, now=NOW
        )
    with pytest.raises(ValidationError):
        catalog_price_rejection(
            paid_offer(),
            observed.model_copy(
                update={"tariffs": (observed.tariffs[0].model_copy(update={"price_minor": True}),)}
            ),
            now=NOW,
        )
    with pytest.raises(ValueError, match="aware"):
        catalog_price_rejection(paid_offer(), observed, now=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        ConversionCatalogObservation(
            collected_at=NOW, tariffs=(observed.tariffs[0], observed.tariffs[0])
        )


async def test_outer_wall_timeout_stops_after_the_single_submitted_read() -> None:
    calls = 0

    async def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-jwt"})
        await asyncio.Event().wait()
        raise AssertionError("An uncompleted read cannot yield catalog evidence")

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ParentChatError, match="conversion_catalog_unavailable"):
            await source(client, wall_timeout_seconds=0.01).read()
    assert calls == 2


@pytest.mark.parametrize("seconds", [0, -1, 121, float("inf"), float("nan")])
async def test_invalid_wall_bounds_fail_before_io(seconds: float) -> None:
    async with httpx.AsyncClient(transport=response_transport([])) as client:
        with pytest.raises(ValueError, match="timeout"):
            source(client, wall_timeout_seconds=seconds)


@pytest.mark.parametrize("field", ["username", "password"])
async def test_missing_credentials_fail_before_io(field: str) -> None:
    async with httpx.AsyncClient(transport=response_transport([])) as client:
        with pytest.raises(ValueError, match="credentials"):
            source(client, **{field: ""})


async def test_observed_five_tariff_shapes_parse_offline_without_approving_an_offer() -> None:
    # Minimized values transcribed from the completed 2026-10-23 catalog read.
    # This local parser check is not a second live request or live-adapter proof.
    rows = [
        tariff(id=3, price="60000.00", duration="30 00:00:00"),
        tariff(id=8, price="162000.00", duration="90 00:00:00"),
        tariff(id=9, price="299000.00", duration="180 00:00:00"),
        tariff(id=7, price="500000.00", duration="30 00:00:00"),
        tariff(id=4, price="599000.00", duration="365 00:00:00"),
    ]
    async with httpx.AsyncClient(transport=response_transport(rows)) as client:
        observed = await source(client).read()
    assert [(row.tariff_id, row.price_minor, row.duration_days) for row in observed.tariffs] == [
        ("3", 6000000, 30),
        ("8", 16200000, 90),
        ("9", 29900000, 180),
        ("7", 50000000, 30),
        ("4", 59900000, 365),
    ]
    assert "approval_reference" not in observed.model_dump_json()


async def test_changed_catalog_price_rejects_a_previously_matching_offer() -> None:
    async with httpx.AsyncClient(
        transport=response_transport([tariff(price="61000.00")])
    ) as client:
        observed = await source(client).read()
    approved = paid_offer(
        billing_offer_id="123", price_minor=6000000, list_price_minor=6000000, discount_percent=0
    )
    assert catalog_price_rejection(approved, observed, now=NOW) == "catalog_price_mismatch"
