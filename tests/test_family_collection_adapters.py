"""Finite inventory and proactive token-cache expiry, with mocked backend only."""

import asyncio
import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from pytest import MonkeyPatch

from app.mana_ai.application.chat_ports import ParentChatError
from app.services import parent_chat_children as profile_module
from app.services.manakids_family_inventory import ManakidsFamilyInventory
from app.services.parent_chat_children import ManakidsChatChildrenSource

NOW = datetime(2026, 10, 25, 4, tzinfo=UTC)


def page() -> dict[str, object]:
    return {
        "count": 3,
        "next": "https://untrusted.invalid/not-followed",
        "results": [
            {
                "id": 1,
                "phone": "fake-private-phone",
                "fullname": "Fictional adult",
                "children": [{"id": 11, "fullname": "Fictional child", "is_connected": True}],
            },
            {"id": 2, "children": [{"id": 12, "is_connected": False}]},
        ],
    }


class Auth:
    async def access_token(self) -> str:
        return "fake-service-token"


async def test_inventory_is_one_minimized_page_not_provider_link_following() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "api.manakids.uz"
        assert dict(request.url.params) == {"limit": "2", "offset": "0"}
        return httpx.Response(200, json=page())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = ManakidsFamilyInventory(
            client, Auth(), base_url="https://api.manakids.uz", clock=lambda: NOW
        )
        result = await source.read(0, 2)
    assert len(requests) == 1 and result.total_parents == 3 and not result.exhausted
    assert (
        result.families[0].connected_child_ids == (11,)
        and result.families[1].connected_child_ids == ()
    )
    assert "Fictional" not in result.model_dump_json() and "phone" not in result.model_dump_json()


@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_inventory_errors_have_one_attempt_and_no_raw_message(status: int) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json={"detail": "fake-private-provider-content"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        source = ManakidsFamilyInventory(
            client, Auth(), base_url="https://api.manakids.uz", clock=lambda: NOW
        )
        with pytest.raises(ParentChatError) as caught:
            await source.read(0, 2)
    assert len(requests) == 1 and "private-provider" not in str(caught.value)


async def test_jwt_expiry_refreshes_before_next_distinct_read_without_retry(
    monkeypatch: MonkeyPatch,
) -> None:
    clocks = {"mono": 0.0, "wall": 1800000000.0}
    monkeypatch.setattr(
        profile_module,
        "time",
        SimpleNamespace(monotonic=lambda: clocks["mono"], time=lambda: clocks["wall"]),
    )
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        claims = (
            base64.urlsafe_b64encode(json.dumps({"exp": int(clocks["wall"]) + 3600}).encode())
            .decode()
            .rstrip("=")
        )
        return httpx.Response(200, json={"access": f"fake-header.{claims}.fake-signature"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        auth = ManakidsChatChildrenSource(
            client=client,
            base_url="https://api.manakids.uz",
            username="fake-user",
            password="fake-password",
        )
        original = await auth.access_token()
        assert await auth.access_token() == original and len(requests) == 1
        clocks["mono"] += 21600
        clocks["wall"] += 21600
        first, second = await asyncio.gather(auth.access_token(), auth.access_token())
        assert first == second and first != original and len(requests) == 2


async def test_failed_profile_get_is_not_retried_in_same_invocation(
    monkeypatch: MonkeyPatch,
) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return (
            httpx.Response(200, json={"access": "fake-opaque-token"})
            if request.method == "POST"
            else httpx.Response(401, json={"detail": "fake-denied"})
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        auth = ManakidsChatChildrenSource(
            client=client,
            base_url="https://api.manakids.uz",
            username="fake-user",
            password="fake-password",
        )
        with pytest.raises(ParentChatError, match="child_source_auth_denied"):
            await auth.read("1")
    assert [r.method for r in requests] == ["POST", "GET"]
