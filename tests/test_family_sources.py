"""No source/model requests: durable admission and real HTTP parsing via fakes."""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.domain.chat import ChatChild, ParentChildContext
from app.mana_ai.domain.family_sources import (
    ChildBatteryFacts,
    FamilySourceLimits,
    FamilySourceTarget,
)
from app.services.family_source_store import SqliteFamilySourceStore
from app.services.firestore_child_battery import FirestoreChildBatterySource


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 24, 9, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


class Profiles:
    def __init__(self, clock: Clock) -> None:
        self.clock, self.calls, self.connected = clock, 0, True

    async def read(self, parent_id: str) -> ParentChildContext:
        self.calls += 1
        return ParentChildContext(
            parent_id=parent_id,
            children=[ChatChild(child_id=900002, connected=self.connected)],
            collected_at=self.clock.now(),
            limitations=[],
        )


class Battery:
    def __init__(self, clock: Clock) -> None:
        self.clock, self.calls, self.percent = clock, 0, 42
        self.updated = clock.now() - timedelta(seconds=30)
        self.failure: BaseException | None = None

    async def read(self, child_id: int) -> ChildBatteryFacts:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return ChildBatteryFacts(
            child_id=child_id,
            status="available",
            percent=self.percent,
            observed_at=self.updated,
            source_updated_at=self.updated,
            collected_at=self.clock.now(),
            quality="dated",
        )


def target(parent: str = "900001", child: int = 900002) -> FamilySourceTarget:
    return FamilySourceTarget(parent_id=parent, child_id=child, request_id=uuid4())


async def cache(
    tmp_path: Path, limits: FamilySourceLimits | None = None
) -> SqliteFamilySourceStore:
    store = SqliteFamilySourceStore(
        tmp_path / "sources.sqlite3",
        binding="fake-project/default/mana-battery-v1",
        limits=limits or FamilySourceLimits(),
    )
    await store.initialize()
    return store


async def test_shared_cache_exact_replay_restart_and_changed_only_events(tmp_path: Path) -> None:
    clock, store = Clock(), await cache(tmp_path)
    profiles, battery = Profiles(clock), Battery(clock)
    service = FamilySourceService(store, profiles, battery, clock=clock.now)
    request = target()
    first = await service.read_child_battery(request)
    assert first.status == "completed" and not first.cache_hit and first.facts
    assert first.document_units_reserved == 2 and battery.calls == profiles.calls == 1
    assert await service.read_child_battery(request) == first
    assert battery.calls == profiles.calls == 1
    second = await service.read_child_battery(target())
    assert second.cache_hit and second.snapshot_id == first.snapshot_id
    assert battery.calls == 1 and profiles.calls == 2
    assert second.document_units_reserved == 0
    assert len(await store.changes("900001")) == 1
    assert await store.changes("900003") == []

    restored = await cache(tmp_path)
    service = FamilySourceService(restored, profiles, battery, clock=clock.now)
    assert await service.read_child_battery(request) == first
    clock.value += timedelta(hours=6)
    same = await service.read_child_battery(target())
    assert not same.cache_hit and same.snapshot_id == first.snapshot_id
    assert battery.calls == 2 and len(await restored.changes("900001")) == 1
    assert same.facts == first.facts  # Do not relabel the original measurement as fresh.
    clock.value += timedelta(hours=6)
    battery.percent, battery.updated = 12, clock.now() - timedelta(seconds=10)
    different = await service.read_child_battery(target())
    assert different.snapshot_id != first.snapshot_id
    assert len(await restored.changes("900001")) == 2


async def test_revoked_or_foreign_child_never_receives_a_cached_observation(tmp_path: Path) -> None:
    clock, store = Clock(), await cache(tmp_path)
    profiles, battery = Profiles(clock), Battery(clock)
    service = FamilySourceService(store, profiles, battery, clock=clock.now)
    first = await service.read_child_battery(target())
    profiles.connected = False
    denied = await service.read_child_battery(target())
    assert denied.status == "failed" and denied.facts is None
    assert battery.calls == 1 and first.facts
    denied = await service.read_child_battery(target(child=900004))
    assert denied.status == "failed" and denied.facts is None and battery.calls == 1


async def test_new_nonce_restart_and_midnight_never_repeat_unknown_source(tmp_path: Path) -> None:
    clock, store = Clock(), await cache(tmp_path)
    profiles, battery = Profiles(clock), Battery(clock)
    battery.failure = TimeoutError("fake-private-upstream-error")
    service = FamilySourceService(store, profiles, battery, clock=clock.now)
    request = target()
    lost = await service.read_child_battery(request)
    assert lost.status == "unknown" and lost.document_units_reserved == 2
    assert "private" not in lost.model_dump_json()
    clock.value += timedelta(days=3)
    restored = await cache(tmp_path)
    service = FamilySourceService(restored, profiles, battery, clock=clock.now)
    assert await service.read_child_battery(request) == lost
    with pytest.raises(ParentChatError, match="family_source_read_unresolved"):
        await service.read_child_battery(target())
    assert battery.calls == profiles.calls == 1


async def test_access_failure_opens_source_circuit_without_repeating_other_work(
    tmp_path: Path,
) -> None:
    clock, store = Clock(), await cache(tmp_path)
    profiles, battery = Profiles(clock), Battery(clock)
    battery.failure = ParentChatError("family_source_auth_denied", 503)
    service = FamilySourceService(store, profiles, battery, clock=clock.now)
    request = target()
    failed = await service.read_child_battery(request)
    assert failed.status == "failed" and failed.error_code == "family_source_auth_denied"
    assert await service.read_child_battery(request) == failed
    with pytest.raises(ParentChatError, match="family_source_circuit_open"):
        await service.read_child_battery(target(child=900003))
    restored = await cache(tmp_path)
    with pytest.raises(ParentChatError, match="family_source_circuit_open"):
        await restored.claim(target(), clock.now() + timedelta(days=3))
    assert battery.calls == 1


async def test_atomic_claim_across_connections_and_cancelled_submission(tmp_path: Path) -> None:
    clock, first = Clock(), await cache(tmp_path)
    second = await cache(tmp_path)
    a, b = target(), target()
    results = await asyncio.gather(
        first.claim(a, clock.now()), second.claim(b, clock.now()), return_exceptions=True
    )
    assert sum(isinstance(result, ParentChatError) for result in results) == 1
    winner = a if not isinstance(results[0], Exception) else b
    assert (await second.observation(winner)).status == "pending"

    other = await cache(tmp_path / "cancelled")
    profiles, battery = Profiles(clock), Battery(clock)
    battery.failure = asyncio.CancelledError()
    service = FamilySourceService(other, profiles, battery, clock=clock.now)
    request = target()
    with pytest.raises(asyncio.CancelledError):
        await service.read_child_battery(request)
    assert (await other.observation(request)).status == "unknown"
    with pytest.raises(ParentChatError, match="family_source_read_unresolved"):
        await other.claim(target(), clock.now())


async def test_rolling_global_budgets_and_nonce_scope_are_not_reset_by_cache(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = await cache(tmp_path, FamilySourceLimits(requests_per_24h=2, document_units_per_24h=2))
    profiles, battery = Profiles(clock), Battery(clock)
    service = FamilySourceService(store, profiles, battery, clock=clock.now)
    request = target()
    await service.read_child_battery(request)
    with pytest.raises(ParentChatError, match="family_source_request_conflict"):
        await store.claim(request.model_copy(update={"child_id": 900003}), clock.now())
    with pytest.raises(ParentChatError, match="family_source_document_limit"):
        await store.claim(target(child=900003), clock.now())
    await service.read_child_battery(target())  # Authenticated cache read reserves no documents.
    with pytest.raises(ParentChatError, match="family_source_request_limit"):
        await store.claim(target(), clock.now())
    assert battery.calls == 1


async def test_storage_refuses_unrelated_schema_symlink_and_policy_replacement(
    tmp_path: Path,
) -> None:
    store = await cache(tmp_path)
    before = (tmp_path / "sources.sqlite3").read_bytes()
    changed = SqliteFamilySourceStore(
        tmp_path / "sources.sqlite3", binding="fake-replacement", limits=FamilySourceLimits()
    )
    with pytest.raises(ValueError, match="binding/limits"):
        await changed.initialize()
    assert (tmp_path / "sources.sqlite3").read_bytes() == before
    unrelated = tmp_path / "parent-chat.sqlite3"
    with sqlite3.connect(unrelated) as connection:
        connection.execute("CREATE TABLE parent_chat_turns (id INTEGER)")
    digest = unrelated.read_bytes()
    with pytest.raises(ValueError, match="dedicated"):
        await SqliteFamilySourceStore(
            unrelated, binding="fake-binding", limits=FamilySourceLimits()
        ).initialize()
    assert unrelated.read_bytes() == digest
    linked = tmp_path / "linked.sqlite3"
    linked.symlink_to(tmp_path / "sources.sqlite3")
    with pytest.raises(ValueError, match="symlink"):
        await SqliteFamilySourceStore(
            linked, binding="fake-binding", limits=FamilySourceLimits()
        ).initialize()
    assert await store.changes("900001") == []


async def test_same_event_snapshots_are_family_scoped_historical_and_read_only(
    tmp_path: Path,
) -> None:
    clock, store = Clock(), await cache(tmp_path)
    profiles, battery = Profiles(clock), Battery(clock)
    receipt = await FamilySourceService(
        store, profiles, battery, clock=clock.now
    ).read_child_battery(target())
    [(cursor, event)] = await store.changes("900001")
    assert event.snapshot_id == receipt.snapshot_id
    assert await store.snapshot("900001", 900002, event.snapshot_id) == receipt.facts
    assert await store.changes("900001", after=cursor) == []
    for parent, child in (("900003", 900002), ("900001", 900004)):
        with pytest.raises(ParentChatError, match="family_source_snapshot_not_found"):
            await store.snapshot(parent, child, event.snapshot_id)
    assert battery.calls == profiles.calls == 1


async def test_failed_admission_fences_late_result_without_refunding_reserved_reads(
    tmp_path: Path,
) -> None:
    clock, store = Clock(), await cache(tmp_path)
    request, battery = target(), Battery(clock)
    await store.claim(request, clock.now())
    stopped = await store.fail(
        request, clock.now(), code="family_source_cancelled", unknown=True, close_source=False
    )
    assert await store.complete(request, await battery.read(900002), clock.now()) == stopped
    assert await store.changes("900001") == []
    with sqlite3.connect(tmp_path / "sources.sqlite3") as connection:
        assert connection.execute("SELECT SUM(units) FROM source_reads").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM source_snapshots").fetchone()[0] == 0


async def test_corrupt_cached_facts_stop_before_any_new_profile_or_source_call(
    tmp_path: Path,
) -> None:
    clock, store = Clock(), await cache(tmp_path)
    profiles, battery = Profiles(clock), Battery(clock)
    service = FamilySourceService(store, profiles, battery, clock=clock.now)
    await service.read_child_battery(target())
    with sqlite3.connect(tmp_path / "sources.sqlite3") as connection:
        raw = json.loads(connection.execute("SELECT payload FROM source_snapshots").fetchone()[0])
        raw["percent"] = 99
        connection.execute("UPDATE source_snapshots SET payload=?", (json.dumps(raw),))
    with pytest.raises(ParentChatError, match="family_source_cache_invalid"):
        await service.read_child_battery(target())
    assert battery.calls == profiles.calls == 1


async def test_repeated_requests_cannot_cross_parent_scope_or_bypass_cooldown(
    tmp_path: Path,
) -> None:
    clock, store = Clock(), await cache(tmp_path)
    request = target()
    await store.claim(request, clock.now())
    with pytest.raises(ParentChatError, match="family_source_read_unresolved"):
        await store.claim(target(parent="900003"), clock.now())
    await store.fail(
        request, clock.now(), code="family_source_invalid", unknown=False, close_source=False
    )
    with pytest.raises(ParentChatError, match="family_source_read_cooldown"):
        await store.claim(target(), clock.now() + timedelta(hours=5))
    clock.value += timedelta(hours=6)
    assert (await store.claim(target(), clock.now())).admitted


class Token:
    async def token(self) -> str:
        return "fake-google-read-token"


def document(clock: Clock, *, name: str = "one", child: str = "900002") -> dict[str, object]:
    updated = (clock.now() - timedelta(seconds=30)).isoformat()
    return {
        "readTime": clock.now().isoformat(),
        "document": {
            "name": "projects/fake-project/databases/(default)/documents/battery/" + name,
            "updateTime": updated,
            "fields": {
                "childId": {"integerValue": child},
                "percent": {"stringValue": "42%"},
                "created_at": {"stringValue": updated},
            },
        },
    }


async def test_real_http_adapter_has_only_exact_child_filter_mask_and_two_document_limit() -> None:
    clock, calls = Clock(), []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.host == "firestore.googleapis.com" and request.method == "POST"
        assert request.url.path.endswith("/documents:runQuery")
        assert request.headers["accept-encoding"] == "identity"
        query = json.loads(request.content)["structuredQuery"]
        assert query["limit"] == 2 and query["from"] == [
            {"collectionId": "battery", "allDescendants": False}
        ]
        assert query["where"] == {
            "fieldFilter": {
                "field": {"fieldPath": "childId"},
                "op": "EQUAL",
                "value": {"integerValue": "900002"},
            }
        }
        assert {item["fieldPath"] for item in query["select"]["fields"]} == {
            "childId",
            "percent",
            "created_at",
        }
        return httpx.Response(200, json=[document(clock)])

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        source = FirestoreChildBatterySource(
            client, Token(), project_id="fake-project", clock=clock.now
        )
        facts = await source.read(900002)
        assert facts.percent == 42 and facts.quality == "dated" and len(calls) == 1
        assert "battery/one" not in facts.model_dump_json()


@pytest.mark.parametrize("date", ["2026-10-24T09:00:00", "2037-01-01T00:00:00Z", "invalid"])
async def test_naive_or_future_device_dates_never_become_current_measurements(date: str) -> None:
    clock = Clock()
    row = document(clock)
    row["document"]["fields"]["created_at"] = {"stringValue": date}  # type: ignore[index]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[row]))
    ) as client:
        source = FirestoreChildBatterySource(
            client, Token(), project_id="fake-project", clock=clock.now
        )
        facts = await source.read(900002)
        assert facts.percent == 42 and facts.observed_at is None
        assert facts.quality == "unknown_measurement_time"


@pytest.mark.parametrize(
    "kind", ["foreign", "duplicate", "over_limit", "invalid_percent", "wrong_project"]
)
async def test_adapter_refuses_foreign_duplicate_oversized_or_invalid_rows(kind: str) -> None:
    clock = Clock()
    row = document(clock, child="900003" if kind == "foreign" else "900002")
    if kind == "invalid_percent":
        row["document"]["fields"]["percent"] = {"doubleValue": 42.5}  # type: ignore[index]
    if kind == "wrong_project":
        row["document"]["name"] = "projects/other-project/databases/(default)/documents/battery/x"  # type: ignore[index]
    payload = [row, row] if kind == "duplicate" else [row]
    if kind == "over_limit":
        payload = [document(clock, name=str(index)) for index in range(3)]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        source = FirestoreChildBatterySource(
            client, Token(), project_id="fake-project", clock=clock.now
        )
        with pytest.raises(ValueError):
            await source.read(900002)


@pytest.mark.parametrize("status", [302, 400, 401, 403, 404, 429, 500])
async def test_no_http_auth_retry_redirect_or_query_fallback(status: int) -> None:
    clock, calls = Clock(), []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, headers={"Location": "https://example.invalid"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        source = FirestoreChildBatterySource(
            client, Token(), project_id="fake-project", clock=clock.now
        )
        with pytest.raises(ParentChatError):
            await source.read(900002)
        assert len(calls) == 1


async def test_missing_ambiguous_and_byte_limits_are_explicit_not_selected_arbitrarily() -> None:
    clock = Clock()
    cases = (
        ([{"readTime": clock.now().isoformat()}], "missing"),
        ([document(clock), document(clock, name="two")], "ambiguous"),
    )
    for payload, status in cases:
        response = httpx.Response(200, json=payload)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _, result=response: result)
        ) as client:
            source = FirestoreChildBatterySource(
                client, Token(), project_id="fake-project", clock=clock.now
            )
            facts = await source.read(900002)
            assert facts.status == status and facts.percent is None
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 65537))
    ) as client:
        source = FirestoreChildBatterySource(
            client, Token(), project_id="fake-project", clock=clock.now
        )
        with pytest.raises(ValueError, match="byte ceiling"):
            await source.read(900002)
