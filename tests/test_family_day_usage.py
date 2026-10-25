"""Owned date-filtered batch reads with real adapters and fictional HTTP only."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.family_day_usage import ParentUsageLookup
from app.services.manakids_family_day_usage import ManakidsFamilyDayUsageSource
from app.services.parent_chat_children import ManakidsChatChildrenSource
from tests.test_child_app_usage import Token, page

NOW = datetime(2026, 10, 24, 9, tzinfo=UTC)
DAY = date(2026, 10, 23)


class Provider:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.parent: dict[str, Any] = {
            "count": 1,
            "next": None,
            "results": [
                {
                    "id": 4,
                    "phone": "fake-parent-login",
                    "children": [
                        {"id": 11, "fullname": "Fictional child", "is_connected": True},
                        {"id": 12, "fullname": "Another fictional child", "is_connected": True},
                    ],
                }
            ],
        }
        self.payload: dict[str, Any] = {
            "success": True,
            "results": [
                {"id": 11, "fullname": "Fictional child", "app_usage_statistics": page()},
                {"id": 12, "fullname": "Another fictional child", "app_usage_statistics": page()},
            ],
            "total_count": 2,
            "current_page": 1,
            "page_count": 1,
            "per_page": 10,
        }
        self.usage_status = 200
        self.profile_status = 200
        self.raw: bytes | None = None
        self.timeout = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "api.manakids.uz"
        if request.method == "POST":
            assert request.url.path == "/api/v1/admin-panel-auth/login/"
            return httpx.Response(200, json={"access": "fake-server-token"})
        if request.url.path.endswith("/parent-list/"):
            assert dict(request.url.params) == {"parent_id": "4", "limit": "1", "offset": "0"}
            return httpx.Response(self.profile_status, json=self.parent)
        assert request.url.path == "/api/v1/admin-panel-child/app-usage-statistics/"
        assert dict(request.url.params) == {
            "username": "fake-parent-login",
            "start_date": "2026-10-23",
            "end_date": "2026-10-23",
            "page": "1",
        }
        if self.timeout:
            raise httpx.ReadTimeout("fictional lost response")
        if self.raw is not None:
            return httpx.Response(self.usage_status, content=self.raw)
        return httpx.Response(self.usage_status, json=self.payload)


def source(client: httpx.AsyncClient) -> ManakidsFamilyDayUsageSource:
    identity = ManakidsChatChildrenSource(
        client=client,
        base_url="https://api.manakids.uz",
        username="fake-user",
        password="fake-password",
        clock=lambda: NOW,
    )
    return ManakidsFamilyDayUsageSource(
        client, identity, identity, base_url="https://api.manakids.uz", clock=lambda: NOW
    )


async def test_one_owned_family_page_reuses_auth_and_omits_lookup_and_names() -> None:
    provider = Provider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await source(client).read("4", DAY)
    assert len(provider.requests) == 3
    assert result.parent_id == "4" and result.requested_day == DAY and result.complete_family
    assert {c.child_id for c in result.children} == {11, 12}
    assert result.provider_timezone is result.verified_measurement_period is None
    assert all(
        c.quality == "unverified_period" and c.observed_at is None and not c.complete
        for c in result.children
    )
    # Reported counters may overlap; even a date-filtered page is not screen time.
    assert sum(e.reported_seconds for e in result.children[0].entries) > 86400
    serialized = result.model_dump_json()
    assert "fake-parent-login" not in serialized and "Fictional child" not in serialized
    assert "phone" not in serialized and "average_time" not in serialized


@pytest.mark.parametrize(
    "case", ["foreign", "duplicate", "other_day", "bad_time", "outer_count", "nested_count"]
)
async def test_scope_dates_and_pagination_fail_without_fallback(case: str) -> None:
    provider = Provider()
    if case == "foreign":
        provider.payload["results"][0]["id"] = 99
    if case == "duplicate":
        provider.payload["results"][1]["id"] = 11
    if case == "other_day":
        provider.payload["results"][0]["app_usage_statistics"]["results"][0]["daily_usage"][0][
            "date"
        ] = "2026-10-22 09:00:00"
    if case == "bad_time":
        provider.payload["results"][0]["app_usage_statistics"]["results"][0]["daily_usage"][0][
            "date"
        ] = "2026-10-23 99:00:00"
    if case == "outer_count":
        provider.payload["total_count"] = 1
    if case == "nested_count":
        provider.payload["results"][0]["app_usage_statistics"]["total_count"] = 1
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(ParentChatError) as failure:
            await source(client).read("4", DAY)
    assert len(provider.requests) == 3
    assert failure.value.code in {
        "family_day_usage_invalid",
        "family_day_usage_child_not_authorized",
    }
    assert "fake-parent-login" not in str(failure.value)


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
async def test_upstream_error_has_one_attempt_and_no_relogin(status: int) -> None:
    provider = Provider()
    provider.usage_status = status
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(ParentChatError):
            await source(client).read("4", DAY)
    assert [r.method for r in provider.requests] == ["POST", "GET", "GET"]


@pytest.mark.parametrize(
    "case", ["foreign_parent", "disconnected", "missing_lookup", "profile_denied"]
)
async def test_bad_ownership_stops_before_usage_get(case: str) -> None:
    provider = Provider()
    if case == "foreign_parent":
        provider.parent["results"][0]["id"] = 5
    if case == "disconnected":
        for child in provider.parent["results"][0]["children"]:
            child["is_connected"] = False
    if case == "missing_lookup":
        provider.parent["results"][0].pop("phone")
    if case == "profile_denied":
        provider.profile_status = 403
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(ParentChatError):
            await source(client).read("4", DAY)
    assert len(provider.requests) == 2


async def test_first_page_does_not_invent_missing_child_data_or_follow_a_cursor() -> None:
    provider = Provider()
    provider.parent["results"][0]["children"].append({"id": 13, "is_connected": True})
    provider.payload.update(total_count=3, per_page=2, page_count=2)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await source(client).read("4", DAY)
    assert not result.complete_family and result.owned_children_count == 3
    assert result.provider_children_count == 3 and len(result.children) == 2
    assert len(provider.requests) == 3


@pytest.mark.parametrize("empty_pages", [0, 1])
async def test_empty_nested_page_is_missing_evidence_not_zero_screen_time(empty_pages: int) -> None:
    provider = Provider()
    for row in provider.payload["results"]:
        row["app_usage_statistics"].update(results=[], total_count=0, page_count=empty_pages)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await source(client).read("4", DAY)
    assert result.complete_family and len(result.children) == 2
    assert all(
        c.status == "missing" and c.entries == () and c.observed_at is None for c in result.children
    )
    assert result.verified_measurement_period is None
    assert len(provider.requests) == 3


async def test_empty_page_cannot_claim_multiple_pages() -> None:
    provider = Provider()
    provider.payload["results"][0]["app_usage_statistics"].update(
        results=[], total_count=0, page_count=2
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(ParentChatError):
            await source(client).read("4", DAY)
    assert len(provider.requests) == 3


@pytest.mark.parametrize("empty_pages", [0, 1])
async def test_empty_family_page_does_not_zero_the_known_child_inventory(empty_pages: int) -> None:
    provider = Provider()
    provider.payload.update(results=[], total_count=0, page_count=empty_pages)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        result = await source(client).read("4", DAY)
    assert result.owned_children_count == 2 and result.provider_children_count == 0
    assert result.children == () and not result.complete_family
    assert result.verified_measurement_period is None
    assert len(provider.requests) == 3


@pytest.mark.parametrize("case", ["today", "future", "old", "datetime"])
async def test_unbounded_or_incomplete_day_refuses_before_provider_io(case: str) -> None:
    provider = Provider()
    chosen = {
        "today": NOW.date(),
        "future": NOW.date() + timedelta(days=1),
        "old": NOW.date() - timedelta(days=32),
        "datetime": NOW,
    }[case]
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(ParentChatError):
            await source(client).read("4", chosen)
    assert provider.requests == []


@pytest.mark.parametrize("case", ["timeout", "duplicate_json", "oversize"])
async def test_unusable_response_never_enters_fallback_or_exports_raw_data(case: str) -> None:
    provider = Provider()
    if case == "timeout":
        provider.timeout = True
    if case == "duplicate_json":
        provider.raw = b'{"success":true,"success":false}'
    if case == "oversize":
        provider.raw = b" " * 262145
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(ParentChatError):
            await source(client).read("4", DAY)
    assert len(provider.requests) == 3


async def test_lookup_is_ephemeral_and_ordinary_profile_read_keeps_its_original_contract() -> None:
    provider = Provider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        identity = ManakidsChatChildrenSource(
            client=client,
            base_url="https://api.manakids.uz",
            username="fake-user",
            password="fake-password",
            clock=lambda: NOW,
        )
        lookup = await identity.read_usage_lookup("4")
        assert lookup.username.get_secret_value() == "fake-parent-login"
        assert "fake-parent-login" not in repr(lookup) + lookup.model_dump_json()
        assert lookup.connected_child_ids == (11, 12) and lookup.collected_at == NOW
        provider.parent["results"][0].pop("phone")
        context = await identity.read("4")
        assert context.parent_id == "4" and len(context.children) == 2
        assert len(provider.requests) == 3  # One login and two distinct profile reads.


@pytest.mark.parametrize("case", ["foreign", "stale", "future"])
async def test_unchecked_identity_annotation_cannot_grant_a_read(case: str) -> None:
    class Lookup:
        async def read_usage_lookup(self, parent_id: str) -> ParentUsageLookup:
            lookup = ParentUsageLookup(
                parent_id="4",
                username=SecretStr("fake-parent-login"),
                connected_child_ids=(11, 12),
                collected_at=NOW,
            )
            return lookup.model_copy(
                update={"parent_id": "5"}
                if case == "foreign"
                else {
                    "collected_at": NOW + timedelta(seconds=1)
                    if case == "future"
                    else NOW - timedelta(seconds=181)
                }
            )

    provider = Provider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        reader = ManakidsFamilyDayUsageSource(
            client, Token(), Lookup(), base_url="https://api.manakids.uz", clock=lambda: NOW
        )
        with pytest.raises(ParentChatError):
            await reader.read("4", DAY)
    assert provider.requests == []
