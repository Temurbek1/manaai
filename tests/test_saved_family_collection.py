"""Existing collection -> authorized operation -> durable minimized report, no provider I/O."""

import json
import sqlite3
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.main import create_app
from app.mana_ai.application.family_collection import FamilyCollectionService
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.domain.family_collection import FamilyCollectionPolicy
from app.mana_ai.domain.family_sources import FamilySourceLimits
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.mana_operation_ai.application.ports import ProviderPermanentError
from app.mana_operation_ai.application.retention.family_collection import COLLECTION_CAPABILITY
from app.services.family_collection_store import SqliteFamilyCollectionStore
from app.services.multi_family_source_store import SqliteMultiFamilySourceStore
from app.services.operation_family_collection import SavedFamilyCollectionAdapter
from tests.test_family_collection import Battery, Clock, Inventory, Profiles, Usage, drain
from tests.test_retention_agent import configure_retention_test_env

BINDING = "mana:synthetic-project:(default):manakids-v1"


async def fixture(path: Path, *, two_windows: bool = False) -> tuple[Path, Clock]:
    clock = Clock()
    store = SqliteFamilyCollectionStore(
        path / "collection.sqlite3",
        binding=BINDING,
        policy=FamilyCollectionPolicy(page_size=2),
        sources=("firebase.child_battery.v1", "manakids.child_app_usage.v1"),
    )
    await store.initialize(clock.now())
    sources = SqliteMultiFamilySourceStore(
        path / "sources.sqlite3",
        binding=BINDING,
        limits=FamilySourceLimits(),
        policy=SourceSafetyPolicy(),
        enabled=False,
    )
    await sources.initialize()
    service = FamilyCollectionService(
        store,
        Inventory(clock),
        FamilySourceService(
            sources, Profiles(clock), Battery(clock), clock=clock.now, app_usage=Usage(clock)
        ),
        sources,
        clock=clock.now,
    )
    clock.value = datetime(2026, 10, 25, 4, tzinfo=UTC)
    window = await drain(service)
    assert window.status == "completed" and window.parents_seen == 3
    if two_windows:
        clock.value = datetime(2026, 10, 25, 10, tzinfo=UTC)
        later = await drain(service)
        assert later.status == "completed" and later.window_id != window.window_id
    return store._path, clock


def cells(path: Path) -> dict[str, list[Any]]:
    with sqlite3.connect(path) as db:
        return {
            name: db.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


def replace_publication(path: Path, edit: Any) -> None:
    with sqlite3.connect(path) as db:
        window_id, payload = db.execute(
            "SELECT window_id,publication FROM collection_windows WHERE publication IS NOT NULL "
            "ORDER BY scheduled_at DESC LIMIT 1"
        ).fetchone()
        data = json.loads(payload)
        edit(data)
        db.execute(
            "UPDATE collection_windows SET publication=? WHERE window_id=?",
            (json.dumps(data), window_id),
        )


async def test_adapter_reuses_saved_manifest_and_preserves_all_private_cells(
    tmp_path: Path,
) -> None:
    path, clock = await fixture(tmp_path)
    # Free-form fields must never enter the operational projection.
    replace_publication(
        path,
        lambda data: data.update(reason="private-phone-sentinel", limitations=["private-chat"]),
    )
    before = cells(path)
    adapter = SavedFamilyCollectionAdapter(path, expected_binding=BINDING)
    first = await adapter.collect(clock.now(), maximum_age_seconds=86400)
    second = await adapter.collect(clock.now(), maximum_age_seconds=86400)
    assert first == second and first.parents_seen == 3 and first.targets == 6
    assert first.counts[0].completed == 3 and first.counts[0].low_battery_records == 3
    assert first.population_complete is False and first.external_reads == first.inference_calls == 0
    raw = first.model_dump_json()
    assert all(
        value not in raw for value in ("private-phone", "private-chat", "parent_id", "child_id")
    )
    assert cells(path) == before


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data.update(population_complete=True),
        lambda data: data.update(status="collecting"),
        lambda data: data.update(parents_seen=-1),
        lambda data: data.update(parents_seen="3"),
        lambda data: data.update(targets=7),
        lambda data: data.update(published_at="2027-01-01T00:00:00Z"),
        lambda data: data["counts"][0].update(completed=4),
        lambda data: data["counts"][0].update(target_scope="family"),
        lambda data: data["counts"][0].update(last_observation_at="2027-01-01T00:00:00Z"),
    ],
)
async def test_invalid_latest_publication_refuses_without_fallback_or_changes(
    tmp_path: Path, change: Any
) -> None:
    path, clock = await fixture(tmp_path)
    replace_publication(path, change)
    before = cells(path)
    with pytest.raises(ProviderPermanentError, match="^saved_family_collection_unavailable$"):
        await SavedFamilyCollectionAdapter(path, expected_binding=BINDING).collect(
            clock.now(), maximum_age_seconds=86400
        )
    assert cells(path) == before


async def test_stale_foreign_and_future_version_never_refresh_or_create_storage(
    tmp_path: Path,
) -> None:
    path, clock = await fixture(tmp_path)
    before = cells(path)
    adapter = SavedFamilyCollectionAdapter(path, expected_binding=BINDING)
    with pytest.raises(ProviderPermanentError):
        await adapter.collect(clock.now() + timedelta(days=2), maximum_age_seconds=86400)
    with pytest.raises(ProviderPermanentError):
        await SavedFamilyCollectionAdapter(
            path, expected_binding=BINDING.replace("synthetic", "other")
        ).collect(clock.now(), maximum_age_seconds=86400)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=100")
    with pytest.raises(ProviderPermanentError):
        await adapter.collect(clock.now(), maximum_age_seconds=86400)
    missing = tmp_path / "absent.sqlite3"
    with pytest.raises(ProviderPermanentError):
        await SavedFamilyCollectionAdapter(missing, expected_binding=BINDING).collect(
            clock.now(), maximum_age_seconds=86400
        )
    link = tmp_path / "linked.sqlite3"
    link.symlink_to(path)
    with pytest.raises(ProviderPermanentError):
        await SavedFamilyCollectionAdapter(link, expected_binding=BINDING).collect(
            clock.now(), maximum_age_seconds=86400
        )
    assert not missing.exists() and cells(path) == before


async def test_bad_latest_window_cannot_fall_back_to_earlier_valid_window(tmp_path: Path) -> None:
    path, clock = await fixture(tmp_path, two_windows=True)
    replace_publication(path, lambda data: data.update(targets=999))
    before = cells(path)
    with pytest.raises(ProviderPermanentError):
        await SavedFamilyCollectionAdapter(path, expected_binding=BINDING).collect(
            clock.now(), maximum_age_seconds=86400
        )
    assert cells(path) == before


async def test_invalid_source_error_suppresses_private_validation_context(tmp_path: Path) -> None:
    path, clock = await fixture(tmp_path)
    replace_publication(path, lambda data: data.update(private_phone="never-log-this-value"))
    with pytest.raises(ProviderPermanentError) as caught:
        await SavedFamilyCollectionAdapter(path, expected_binding=BINDING).collect(
            clock.now(), maximum_age_seconds=86400
        )
    rendered = "".join(traceback.format_exception(caught.value))
    assert "never-log-this-value" not in rendered and "ValidationError" not in rendered


def test_explicit_saved_source_configuration_is_required() -> None:
    for path in (None, Path("relative.sqlite3"), Path("/private/collection.sqlite3")):
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                operation_family_collection_enabled=True,
                operation_family_collection_database_path=path,
            )
    settings = Settings(
        _env_file=None,
        operation_family_collection_enabled=True,
        operation_family_collection_database_path=Path("/private/collection.sqlite3"),
        operation_family_collection_binding=BINDING,
    )
    assert settings.operation_family_collection_enabled


async def test_operation_api_report_replay_and_reconstruction_never_touch_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, clock = await fixture(tmp_path / "collector")
    before = cells(path)
    configure_retention_test_env(monkeypatch, tmp_path / "operations.sqlite3")
    monkeypatch.setenv("OPERATION_FAMILY_COLLECTION_ENABLED", "true")
    monkeypatch.setenv("OPERATION_FAMILY_COLLECTION_DATABASE_PATH", str(path))
    monkeypatch.setenv("OPERATION_FAMILY_COLLECTION_BINDING", BINDING)
    monkeypatch.setattr("app.main.SystemClock.now", lambda _: clock.now())
    calls: list[str] = []

    def denied(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        raise AssertionError("No provider request belongs to saved collection analysis")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_: httpx.MockTransport(denied))
    reads: list[datetime] = []
    original = SavedFamilyCollectionAdapter.collect

    async def recorded(
        self: SavedFamilyCollectionAdapter, now: datetime, *, maximum_age_seconds: int
    ) -> Any:
        reads.append(now)
        return await original(self, now, maximum_age_seconds=maximum_age_seconds)

    monkeypatch.setattr(SavedFamilyCollectionAdapter, "collect", recorded)
    viewer = {"X-MANA-Actor-ID": "viewer", "X-MANA-Role": "viewer"}
    operator = {"X-MANA-Actor-ID": "operator", "X-MANA-Role": "operator"}
    body = {"capability_key": COLLECTION_CAPABILITY, "idempotency_key": "saved-source-once"}
    try:
        for iteration in range(2):
            app = create_app()
            async with (
                app.router.lifespan_context(app),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://saved.local"
                ) as client,
            ):
                assert len(reads) == iteration
                denied_run = await client.post(
                    "/api/v1/admin/operation/agents/retention-agent/run",
                    json=body,
                    headers=viewer,
                )
                assert denied_run.status_code == 403
                result = await client.post(
                    "/api/v1/admin/operation/agents/retention-agent/run",
                    json=body,
                    headers=operator,
                )
                assert result.status_code == 202
                assert len(reads) == 1
                reports = await client.get("/api/v1/admin/operation/reports", headers=viewer)
                assert reports.status_code == 200
                matched = [
                    r
                    for r in reports.json()["items"]
                    if r["capability_key"] == COLLECTION_CAPABILITY
                ]
                assert len(matched) == 1
                report = matched[0]
                assert report["structured"]["parents_seen"] == 3
                assert report["structured"]["counts"][0]["low_battery_records"] == 3
                assert report["structured"]["external_reads"] == 0
                assert report["structured"]["population_complete"] is False
                if iteration == 0:
                    saved = report
                else:
                    assert report == saved
                assert "parent_id" not in json.dumps(report) and "child_id" not in json.dumps(
                    report
                )
                schedules = await app.state.operation_repository.list_schedules(
                    "retention-agent", COLLECTION_CAPABILITY
                )
                assert schedules == [] and cells(path) == before and not calls
    finally:
        get_settings.cache_clear()
