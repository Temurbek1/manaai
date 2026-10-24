"""Exact-child provider parsing and shared acquisition, using fictional HTTP only."""

from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.domain.family_sources import (
    ChildAppUsageFacts,
    FamilySourceLimits,
    FamilySourceTarget,
)
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services.manakids_child_usage import ManakidsChildUsageSource
from app.services.multi_family_source_store import SqliteMultiFamilySourceStore
from app.services.source_safety_store import SqliteSourceSafetyStore
from tests.test_family_sources import Battery, Clock, Profiles, target


def page() -> dict[str, object]:
    return {
        "success": True,
        "results": [
            {
                "id": 17,
                "app": "Fictional lessons",
                "icon": "https://example.invalid/icon",
                "daily_usage": [
                    {"date": "2026-10-23 23:43:43", "total_time": "23:24:50", "percentage": 38.95}
                ],
                "average_time": "Do not infer a baseline",
            },
            {
                "id": 18,
                "app": "Fictional games",
                "daily_usage": [{"date": "2026-10-23 23:43:43", "total_time": "21:20:24"}],
            },
        ],
        "total_count": 3,
        "current_page": 1,
        "page_count": 2,
        "per_page": 2,
    }


class Token:
    async def access_token(self) -> str:
        return "fake-backend-token"


async def test_counter_page_preserves_unknown_period_and_partial_coverage() -> None:
    clock = Clock()
    requests = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert (
            str(request.url)
            == "https://api.manakids.uz/api/v1/admin-panel-child/app-usage-statistics/900002/"
        )
        return httpx.Response(200, json=page())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        source = ManakidsChildUsageSource(
            client, Token(), base_url="https://api.manakids.uz", clock=clock.now
        )
        facts = await source.read(900002)
    assert facts.returned_apps == 2 and facts.total_apps == 3 and not facts.complete
    assert facts.entries[0].reported_seconds == 84290
    assert sum(e.reported_seconds for e in facts.entries) > 86400
    assert facts.observed_at is None and facts.source_updated_at is None
    assert facts.quality == "unverified_period" and len(requests) == 1
    assert "icon" not in facts.model_dump_json() and "percentage" not in facts.model_dump_json()
    assert (
        facts.model_copy(update={"collected_at": clock.now() + timedelta(hours=1)}).fingerprint()
        == facts.fingerprint()
    )


@pytest.mark.parametrize("change", ["duration", "date", "page", "count", "duplicate", "success"])
async def test_invalid_provider_page_never_becomes_daily_usage(change: str) -> None:
    payload = page()
    if change == "duration":
        payload["results"][0]["daily_usage"][0]["total_time"] = "23:99:00"  # type: ignore[index]
    elif change == "date":
        payload["results"][0]["daily_usage"][0]["date"] = "2026-02-30 23:43:43"  # type: ignore[index]
    elif change == "page":
        payload["current_page"] = 2
    elif change == "count":
        payload["total_count"] = 1
    elif change == "duplicate":
        payload["results"][1] = payload["results"][0]  # type: ignore[index]
    else:
        payload["success"] = False
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        source = ManakidsChildUsageSource(
            client, Token(), base_url="https://api.manakids.uz", clock=Clock().now
        )
        with pytest.raises(ValueError):
            await source.read(900002)


class Usage:
    def __init__(self, clock: Clock) -> None:
        self.clock, self.calls = clock, 0
        self.failure: BaseException | None = None

    async def read(self, child_id: int) -> ChildAppUsageFacts:
        self.calls += 1
        if self.failure:
            raise self.failure
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=page()))
        ) as client:
            return await ManakidsChildUsageSource(
                client, Token(), base_url="https://api.manakids.uz", clock=self.clock.now
            ).read(child_id)


def usage_target() -> FamilySourceTarget:
    return target().model_copy(update={"source": "manakids.child_app_usage.v1"})


async def source_cache(
    path: Path, limits: FamilySourceLimits | None = None
) -> SqliteMultiFamilySourceStore:
    store = SqliteMultiFamilySourceStore(
        path / "source.sqlite3",
        binding="fake-mana",
        limits=limits or FamilySourceLimits(),
        policy=SourceSafetyPolicy(),
    )
    await store.initialize()
    return store


async def test_shared_request_budget_separate_heads_circuits_unknown_and_restart(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = await source_cache(tmp_path)
    profiles, battery, usage = Profiles(clock), Battery(clock), Usage(clock)
    service = FamilySourceService(store, profiles, battery, clock=clock.now, app_usage=usage)
    first = await service.read_child_battery(target())
    req = usage_target()
    used = await service.read_child_app_usage(req)
    assert used.status == "completed" and used.document_units_reserved == 0 and not used.cache_hit
    assert first.document_units_reserved == 2 and isinstance(used.facts, ChildAppUsageFacts)
    cached = await service.read_child_app_usage(usage_target())
    assert cached.cache_hit and cached.facts == used.facts and usage.calls == 1
    changes = await store.changes("900001")
    assert len(changes) == 2 and changes[1][1].source == "manakids.child_app_usage.v1"
    assert used.snapshot_id is not None
    assert (
        await store.snapshot("900001", 900002, used.snapshot_id, source=used.source) == used.facts
    )
    # A usage-specific circuit must leave the independent Firebase lane open.
    clock.value += timedelta(hours=7)
    usage.failure = ParentChatError("family_source_auth_denied", 503)
    failed = await service.read_child_app_usage(usage_target())
    assert failed.status == "failed"
    assert (await service.read_child_battery(target())).status == "completed"
    restarted = await source_cache(tmp_path)
    with pytest.raises(ParentChatError, match="family_source_circuit_open"):
        await FamilySourceService(
            restarted, profiles, battery, clock=clock.now, app_usage=usage
        ).read_child_app_usage(usage_target())
    assert await service.read_child_app_usage(req) == used and usage.calls == 2
    with pytest.raises(ValueError):
        await SqliteSourceSafetyStore(
            tmp_path / "source.sqlite3",
            binding="fake-mana",
            limits=FamilySourceLimits(),
            policy=SourceSafetyPolicy(),
        ).initialize()


async def test_unknown_usage_read_does_not_block_battery_or_refund_on_midnight(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = await source_cache(tmp_path)
    usage = Usage(clock)
    usage.failure = httpx.ReadTimeout("Synthetic lost usage result")
    service = FamilySourceService(
        store, Profiles(clock), Battery(clock), clock=clock.now, app_usage=usage
    )
    req = usage_target()
    unknown = await service.read_child_app_usage(req)
    assert unknown.status == "unknown"
    assert (await service.read_child_battery(target())).status == "completed"
    clock.value += timedelta(days=1)
    with pytest.raises(ParentChatError, match="family_source_read_unresolved"):
        await service.read_child_app_usage(usage_target())
    assert await service.read_child_app_usage(req) == unknown and usage.calls == 1


async def test_both_sources_use_same_rolling_request_ceiling_and_fresh_ownership(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = await source_cache(tmp_path, FamilySourceLimits(requests_per_24h=2))
    profiles, usage = Profiles(clock), Usage(clock)
    service = FamilySourceService(store, profiles, Battery(clock), clock=clock.now, app_usage=usage)
    await service.read_child_battery(target())
    await service.read_child_app_usage(usage_target())
    with pytest.raises(ParentChatError, match="family_source_request_limit"):
        await service.read_child_app_usage(usage_target())
    assert usage.calls == 1


async def test_populated_v2_upgrade_preserves_unknown_battery_and_legacy_payloads(
    tmp_path: Path,
) -> None:
    clock = Clock()
    old = SqliteSourceSafetyStore(
        tmp_path / "source.sqlite3",
        binding="fake-mana",
        limits=FamilySourceLimits(),
        policy=SourceSafetyPolicy(),
    )
    await old.initialize()
    battery = Battery(clock)
    battery.failure = httpx.ReadTimeout("Synthetic battery receipt lost")
    req = target()
    unknown = await FamilySourceService(
        old, Profiles(clock), battery, clock=clock.now
    ).read_child_battery(req)
    assert unknown.status == "unknown"
    with old._connection() as db:
        before = db.execute("SELECT * FROM source_reads").fetchall()
        saved = [tuple(r) for r in before]
    new = await source_cache(tmp_path)
    with new._connection() as db:
        assert [tuple(r) for r in db.execute("SELECT * FROM source_reads").fetchall()] == saved
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
    usage = Usage(clock)
    service = FamilySourceService(new, Profiles(clock), battery, clock=clock.now, app_usage=usage)
    assert await service.read_child_battery(req) == unknown
    assert (await service.read_child_app_usage(usage_target())).status == "completed"
    assert battery.calls == 1 and usage.calls == 1
