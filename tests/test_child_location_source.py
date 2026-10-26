"""Exact projected Firestore GET and shared durable ownership/metering; no live I/O."""

import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pytest import MonkeyPatch

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.domain.child_location import LOCATION_SOURCE
from app.mana_ai.domain.family_sources import FamilySourceLimits, FamilySourceTarget
from app.mana_ai.domain.source_reviews import SourceReviewPolicy
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services.firestore_child_location import LOCATION_FIELDS, FirestoreChildLocationSource
from app.services.lab_location import LabLocationSource
from app.services.location_source_cache import SqliteLocationSourceCache
from tests.test_family_sources import Battery, Clock, Profiles


class Auth:
    async def token(self) -> str:
        return "fake-scoped-google-token"


def document(clock: Clock) -> dict[str, object]:
    observed = clock.now() - timedelta(days=10)
    return {
        "name": "projects/test-project/databases/(default)/documents/children_location/900002",
        "updateTime": (observed + timedelta(seconds=1)).isoformat(),
        "fields": {
            "coords": {
                "mapValue": {
                    "fields": {
                        "latitude": {"doubleValue": 12.3456789},
                        "longitude": {"doubleValue": 45.6789123},
                        "accuracy": {"doubleValue": 15.2},
                    }
                }
            },
            "location": {
                "mapValue": {
                    "fields": {
                        "timestamp": {"stringValue": observed.isoformat()},
                        "mock": {"booleanValue": False},
                        "sample": {"booleanValue": False},
                        "isMoving": {"booleanValue": True},
                    }
                }
            },
        },
    }


async def test_exact_document_projection_preserves_stale_date_and_discards_coordinates() -> None:
    clock = Clock()
    calls = []

    async def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET" and request.url.path.endswith("/children_location/900002")
        assert request.url.params.get_list("mask.fieldPaths") == list(LOCATION_FIELDS)
        assert not request.content
        return httpx.Response(200, json=document(clock))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = FirestoreChildLocationSource(
            client, Auth(), project_id="test-project", clock=clock.now
        )
        facts = await adapter.read(900002)
    assert len(calls) == 1 and facts.status == "available" and facts.is_moving is True
    assert facts.observed_at == clock.now() - timedelta(days=10)
    assert facts.quality == "dated" and facts.mock is False and facts.sample is False
    text = facts.model_dump_json()
    assert not any(value in text for value in ("12.3456789", "45.6789123", "latitude", "longitude"))
    assert facts.position_fingerprint and facts.accuracy_reported


@pytest.mark.parametrize("change", ["foreign", "nan", "range", "bool", "duplicate", "oversize"])
async def test_invalid_projected_points_are_refused_without_retry(change: str) -> None:
    clock = Clock()
    data = json.dumps(document(clock))
    if change == "foreign":
        data = data.replace("children_location/900002", "children_location/900003")
    if change == "nan":
        data = data.replace("12.3456789", "NaN")
    if change == "range":
        data = data.replace("12.3456789", "91")
    if change == "bool":
        data = data.replace('"booleanValue": false', '"booleanValue": 0')
    if change == "duplicate":
        data = data.replace('"latitude":', '"latitude": {}, "latitude":')
    if change == "oversize":
        data = data[:-1] + ', "padding":"' + "x" * 70000 + '"}'
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError):
            await FirestoreChildLocationSource(
                client, Auth(), project_id="test-project", clock=clock.now
            ).read(900002)
    assert len(calls) == 1


@pytest.mark.parametrize("date", ["2026-10-24T09:00:00", "2030-01-01T00:00:00Z", "invalid"])
async def test_unknown_or_future_device_date_is_not_the_collection_date(date: str) -> None:
    clock = Clock()
    data = document(clock)
    body = json.dumps(data).replace((clock.now() - timedelta(days=10)).isoformat(), date)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    ) as client:
        facts = await FirestoreChildLocationSource(
            client, Auth(), project_id="test-project", clock=clock.now
        ).read(900002)
    assert facts.observed_at is None and facts.quality == "unknown_measurement_time"


async def cache(path: Path, clock: Clock, **limits: int) -> SqliteLocationSourceCache:
    store = SqliteLocationSourceCache(
        path,
        location_enabled=True,
        binding="test-location-shared-v1",
        limits=FamilySourceLimits(**limits),
        policy=SourceSafetyPolicy(),
        review_policy=SourceReviewPolicy(),
        enabled=True,
    )
    await store.initialize()
    return store


def target(child_id: int = 900002) -> FamilySourceTarget:
    return FamilySourceTarget(
        parent_id="4", child_id=child_id, request_id=uuid4(), source=LOCATION_SOURCE
    )


async def test_shared_cache_ownership_replay_budget_and_unchanged_recollection(
    tmp_path: Path,
) -> None:
    clock = Clock()
    store = await cache(tmp_path / "sources.sqlite3", clock)
    profiles, battery, location = Profiles(clock), Battery(clock), LabLocationSource(clock.now)
    service = FamilySourceService(store, profiles, battery, clock=clock.now, location=location)
    first = target()
    one = await service.read(first)
    assert one.status == "completed" and one.document_units_reserved == 2
    assert await service.read(first) == one and profiles.calls == location.calls == 1
    second = await service.read(target())
    assert second.status == "completed" and second.cache_hit and second.document_units_reserved == 0
    assert profiles.calls == 2 and location.calls == 1
    foreign = await service.read(target(900003))
    assert foreign.status == "failed" and location.calls == 1
    clock.value += timedelta(hours=6)
    three = await service.read(target())
    assert three.status == "completed" and location.calls == 2
    assert three.snapshot_id == one.snapshot_id and three.facts
    assert three.facts.observed_at == one.facts.observed_at if one.facts else False
    assert len(await store.changes("4")) == 1
    store = await cache(tmp_path / "sources.sqlite3", clock)
    assert await store.observation(first) == one
    with store._connection() as db:
        assert db.execute("SELECT SUM(units) FROM source_reads").fetchone()[0] == 6
    # A separate battery request shares that document ceiling with GPS.
    limited = await cache(tmp_path / "small.sqlite3", clock, document_units_per_24h=2)
    service = FamilySourceService(limited, profiles, battery, clock=clock.now, location=location)
    await service.read(target())
    with pytest.raises(ParentChatError, match="family_source_document_limit"):
        await service.read(FamilySourceTarget(parent_id="4", child_id=900002, request_id=uuid4()))


async def test_unknown_location_retains_hold_and_auth_denial_does_not_close_battery(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    clock = Clock()
    store = await cache(tmp_path / "lost.sqlite3", clock)
    profiles, battery, location = Profiles(clock), Battery(clock), LabLocationSource(clock.now)
    service = FamilySourceService(store, profiles, battery, clock=clock.now, location=location)

    async def lost(child_id: int) -> object:
        raise TimeoutError("fictional lost response")

    monkeypatch.setattr(location, "read", lost)
    req = target()
    unknown = await service.read(req)
    assert unknown.status == "unknown" and await service.read(req) == unknown
    with pytest.raises(ParentChatError, match="family_source_read_unresolved"):
        await service.read(target())
    store = await cache(tmp_path / "denied.sqlite3", clock)
    service = FamilySourceService(store, profiles, battery, clock=clock.now, location=location)

    async def denied(child_id: int) -> object:
        raise ParentChatError("family_source_auth_denied", 503)

    monkeypatch.setattr(location, "read", denied)
    failure = await service.read(target())
    assert failure.status == "failed" and failure.error_code == "family_source_auth_denied"
    with pytest.raises(ParentChatError, match="family_source_circuit_open"):
        await service.read(target())
    assert (
        await service.read(FamilySourceTarget(parent_id="4", child_id=900002, request_id=uuid4()))
    ).status == "completed"
