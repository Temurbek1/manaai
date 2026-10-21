"""Isolated push protocol tests; no credentials, external calls or real contacts."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.mana_ai.application.parent_notifications import (
    ParentPushGateway,
    ParentPushRejected,
    ParentPushUnknown,
)
from app.mana_ai.domain.parent_notifications import ParentPushMessage, ParentPushReceipt
from app.services.manakids_parent_push import ManakidsParentPushGateway


def message(**changes: Any) -> ParentPushMessage:
    return ParentPushMessage.model_validate(
        {"parent_id": "123", "title": "MANA", "description": "В чате новое сообщение."} | changes
    )


def receipt(*, devices: int = 1, **changes: Any) -> dict[str, object]:
    return {
        "message": f"Notification queued for {devices} devices",
        "results": {
            "parent_id": 123,
            "phone": "private-upstream-phone",
            "title": "MANA",
            "type": "ai_agent",
            "description": "В чате новое сообщение.",
        }
        | changes,
    }


def gateway(client: httpx.AsyncClient, **changes: Any) -> ManakidsParentPushGateway:
    return ManakidsParentPushGateway(
        client=client,
        base_url="https://synthetic.invalid",
        username="synthetic-user",
        password="fake-push-password",
        **changes,
    )


@pytest.mark.parametrize("devices", [0, 1, 5])
async def test_verified_queue_receipt_is_minimized_and_never_claims_delivery(devices: int) -> None:
    calls: list[httpx.Request] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "POST"
        assert request.headers["User-Agent"] == "MANA-Parent-Touch/1.0"
        if request.url.path == "/api/v1/admin-panel-auth/login/":
            assert json.loads(request.content) == {
                "username": "synthetic-user",
                "password": "fake-push-password",
            }
            assert "Authorization" not in request.headers
            return httpx.Response(200, json={"access": "fake-push-jwt"})
        assert request.url.path == "/api/v1/parent/notify-parent/123/"
        assert request.headers["Authorization"] == "Bearer fake-push-jwt"
        assert json.loads(request.content) == {
            "title": "MANA",
            "description": "В чате новое сообщение.",
        }
        return httpx.Response(201, json=receipt(devices=devices))

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        port: ParentPushGateway = gateway(client)
        result = await port.send(message())
        assert result == ParentPushReceipt(status="queued", queued_devices=devices)
        assert result.model_dump() == {"status": "queued", "queued_devices": devices}
        assert "private-upstream-phone" not in result.model_dump_json()
        assert "delivered" not in result.model_dump_json()
        assert len(calls) == 2


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "parent_push_invalid_message"),
        (401, "parent_push_not_authorized"),
        (403, "parent_push_not_authorized"),
        (404, "parent_push_parent_not_found"),
    ],
)
async def test_documented_refusal_does_not_retry_relogin_or_expose_body(
    status: int, code: str
) -> None:
    calls: list[httpx.Request] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-push-jwt"})
        return httpx.Response(status, content=b"private-upstream-stacktrace-and-phone")

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ParentPushRejected) as error:
            await gateway(client).send(message())
        assert error.value.status_code == status and error.value.code == code
        assert str(error.value) == code
        assert len(calls) == 2


@pytest.mark.parametrize("status", [200, 202, 204, 301, 302, 307, 308, 409, 429, 500, 502, 503])
async def test_unverified_status_is_unknown_even_when_client_follows_redirects(status: int) -> None:
    calls: list[httpx.Request] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-push-jwt"})
        return httpx.Response(
            status,
            json=receipt(),
            headers={"Location": "https://other-synthetic.invalid/should-not-be-called"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(dispatch), follow_redirects=True
    ) as client:
        with pytest.raises(ParentPushUnknown, match="^parent_push_outcome_unknown$"):
            await gateway(client).send(message())
        assert len(calls) == 2 and all(call.url.host == "synthetic.invalid" for call in calls)


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        {},
        {"message": "Notification queued for 1 devices"},
        receipt(parent_id=456),
        receipt(parent_id="123"),
        receipt(parent_id=True),
        receipt(title="different"),
        receipt(description="different"),
        receipt(type="other"),
        receipt() | {"message": "Notification sent to 1 devices"},
        receipt() | {"message": "Notification queued for -1 devices"},
        receipt() | {"message": "Notification queued for 01 devices"},
        receipt() | {"message": "Notification queued for ١ devices"},
        receipt() | {"message": "Notification queued for 1 devices\n"},
        receipt() | {"message": "Notification queued for 1 devices; delivered"},
    ],
)
async def test_malformed_or_mismatched_201_never_proves_queueing(body: object) -> None:
    calls = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-push-jwt"})
        return httpx.Response(201, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ParentPushUnknown, match="^parent_push_outcome_unknown$"):
            await gateway(client).send(message())
        assert calls == 2


@pytest.mark.parametrize(
    "content",
    [
        b"private-non-json-receipt",
        b"\xff",
        b'{"message":"private-first", "message":"private-second"}',
        b'{"results":{"parent_id":123, "parent_id":456}}',
        b"[" * 2000,
    ],
)
async def test_invalid_json_is_controlled_without_private_response_prose(content: bytes) -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-push-jwt"})
        return httpx.Response(201, content=content)

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ParentPushUnknown, match="^parent_push_outcome_unknown$") as error:
            await gateway(client).send(message())
        assert error.value.__cause__ is None


class ReceiptStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.read_chunks = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(100):
            self.read_chunks += 1
            yield b"x" * 4096

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize("oversize_login", [False, True])
async def test_streamed_receipts_have_hard_size_bound_and_close(oversize_login: bool) -> None:
    stream = ReceiptStream()
    calls = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/login/") and not oversize_login:
            return httpx.Response(200, json={"access": "fake-push-jwt"})
        return httpx.Response(200 if oversize_login else 201, stream=stream)

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        expected = (
            "parent_push_auth_unavailable" if oversize_login else "parent_push_outcome_unknown"
        )
        with pytest.raises(ParentPushUnknown, match=f"^{expected}$"):
            await gateway(client).send(message())
        assert stream.read_chunks == 5 and stream.closed
        assert calls == (1 if oversize_login else 2)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 302, 429, 500])
async def test_login_refusal_or_uncertainty_never_calls_notify(status: int) -> None:
    calls = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path.endswith("/login/")
        return httpx.Response(
            status, content=b"private-login-failure", headers={"Location": "/redirect"}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(dispatch), follow_redirects=True
    ) as client:
        port = gateway(client)
        if status in {400, 401, 403, 404}:
            with pytest.raises(ParentPushRejected, match="^parent_push_auth_rejected$"):
                await port.send(message())
        else:
            with pytest.raises(ParentPushUnknown, match="^parent_push_auth_unavailable$"):
                await port.send(message())
        assert calls == 1
        with pytest.raises(ParentPushUnknown, match="^parent_push_auth_unavailable$"):
            await port.send(message())
        assert calls == 1  # Separate jobs cannot create a login hot loop.


@pytest.mark.parametrize("token", [None, "", True, 123, "x\r\nInjected: header", "x" * 8193])
async def test_unverified_login_token_never_dispatches(token: object) -> None:
    calls = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"access": token})

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ParentPushUnknown, match="^parent_push_auth_unavailable$"):
            await gateway(client).send(message())
        assert calls == 1


@pytest.mark.parametrize("during_login", [False, True])
async def test_transport_timeout_never_retries(during_login: bool) -> None:
    calls = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/login/") and not during_login:
            return httpx.Response(200, json={"access": "fake-push-jwt"})
        raise httpx.ReadTimeout("private-transport-host-phone-and-secrets")

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        expected = "parent_push_auth_unavailable" if during_login else "parent_push_outcome_unknown"
        with pytest.raises(ParentPushUnknown, match=f"^{expected}$"):
            await gateway(client).send(message())
        assert calls == (1 if during_login else 2)


async def test_whole_send_wall_timeout_is_bounded_without_retry() -> None:
    calls = 0

    async def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-push-jwt"})
        await asyncio.Event().wait()
        raise AssertionError("Unreachable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch), timeout=None) as client:
        with pytest.raises(ParentPushUnknown, match="^parent_push_outcome_unknown$"):
            await gateway(client, wall_timeout_seconds=0.01).send(message())
        assert calls == 2


async def test_concurrent_distinct_messages_login_freshly_without_replaying_send() -> None:
    logins, sends = 0, 0
    entered, release = asyncio.Event(), asyncio.Event()

    async def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal logins, sends
        if request.url.path.endswith("/login/"):
            logins += 1
            token = f"fake-push-jwt-{logins}"
            entered.set()
            await release.wait()
            return httpx.Response(200, json={"access": token})
        sends += 1
        assert request.headers["Authorization"] == f"Bearer fake-push-jwt-{sends}"
        return httpx.Response(201, json=receipt())

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        port = gateway(client)
        first = asyncio.create_task(port.send(message()))
        await asyncio.wait_for(entered.wait(), timeout=1)
        second = asyncio.create_task(port.send(message()))
        release.set()
        assert all(item.status == "queued" for item in await asyncio.gather(first, second))
        assert logins == 2 and sends == 2


async def test_each_distinct_job_gets_fresh_login_without_assuming_a_jwt_lifetime() -> None:
    paths: list[str] = []
    logins = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal logins
        paths.append(request.url.path)
        if request.url.path.endswith("/login/"):
            logins += 1
            return httpx.Response(200, json={"access": f"fake-push-jwt-{logins}"})
        assert request.headers["Authorization"] == f"Bearer fake-push-jwt-{logins}"
        return httpx.Response(201, json=receipt())

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        port = gateway(client)
        assert (await port.send(message())).status == "queued"
        assert (await port.send(message())).status == "queued"
        assert paths == [
            "/api/v1/admin-panel-auth/login/",
            "/api/v1/parent/notify-parent/123/",
            "/api/v1/admin-panel-auth/login/",
            "/api/v1/parent/notify-parent/123/",
        ]


async def test_unknown_send_does_not_perform_second_login_or_write() -> None:
    paths: list[str] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-push-jwt"})
        return httpx.Response(500, content=b"private-upstream-error")

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ParentPushUnknown, match="^parent_push_outcome_unknown$"):
            await gateway(client).send(message())
        assert paths == ["/api/v1/admin-panel-auth/login/", "/api/v1/parent/notify-parent/123/"]


async def test_unauthorized_token_is_not_relogged_in_or_replayed_and_later_jobs_cool_down() -> None:
    paths: list[str] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-push-jwt"})
        return httpx.Response(401, json={"private": "untrusted details"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        port = gateway(client)
        with pytest.raises(ParentPushRejected, match="^parent_push_not_authorized$"):
            await port.send(message())
        with pytest.raises(ParentPushUnknown, match="^parent_push_auth_unavailable$"):
            await port.send(message())
        assert paths == ["/api/v1/admin-panel-auth/login/", "/api/v1/parent/notify-parent/123/"]


@pytest.mark.parametrize(
    "changes",
    [
        {"parent_id": "00123"},
        {"parent_id": "0"},
        {"parent_id": "١٢٣"},
        {"parent_id": "../123"},
        {"parent_id": str(2**63)},
        {"parent_id": 123},
        {"title": ""},
        {"title": "  \n "},
        {"title": "x" * 121},
        {"description": ""},
        {"description": "  \t "},
        {"description": "x" * 501},
        {"title": 123},
        {"description": True},
    ],
)
async def test_strict_request_and_unchecked_copy_refuse_before_any_http(
    changes: dict[str, Any],
) -> None:
    def dispatch(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Invalid push input must not reach HTTP")

    with pytest.raises(ValidationError):
        message(**changes)
    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        with pytest.raises(ValidationError):
            await gateway(client).send(message().model_copy(update=changes))


@pytest.mark.parametrize("devices", [-1, True, "1", 1.0])
def test_queue_receipt_strictly_rejects_negative_coerced_or_boolean_count(devices: object) -> None:
    with pytest.raises(ValidationError):
        ParentPushReceipt.model_validate({"queued_devices": devices})


@pytest.mark.parametrize(
    "base_url",
    [
        "http://synthetic.invalid",
        "https://username:password@synthetic.invalid",
        "https://synthetic.invalid/api/v1",
        "https://synthetic.invalid?private=secret",
        "https://synthetic.invalid/#private",
        "not-a-url",
    ],
)
async def test_gateway_requires_unambiguous_https_origin(base_url: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ) as client:
        with pytest.raises(ValueError, match="^A valid HTTPS push API origin is required$"):
            ManakidsParentPushGateway(
                client=client, base_url=base_url, username="synthetic", password="synthetic"
            )
