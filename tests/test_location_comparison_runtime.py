"""Current factory selects new comparison readers without idle provider calls."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.services import parent_chat_runtime as runtime
from app.services.lab_workspace import workspace_options
from app.services.location_comparison_cache import SqliteLocationComparisonCache
from app.services.location_comparison_safety_store import SqliteLocationComparisonSafetyStore
from app.services.mana_chat_lab import ChatLab
from tests.test_family_source_runtime import config, make_credential_file


def comparison_settings(path: Path, *, enabled: bool = True) -> Settings:
    return config(
        path,
        make_credential_file(path),
        mana_parent_touch_review_first_enabled=True,
        mana_child_safety_enabled=True,
        mana_child_safety_source_tools_enabled=True,
        mana_family_source_safety_enabled=True,
        mana_family_app_usage_enabled=True,
        mana_family_source_reviews_enabled=True,
        mana_parent_reminders_enabled=True,
        mana_client_retention_enabled=True,
        mana_client_upsell_enabled=True,
        mana_retention_expiry_enabled=True,
        mana_parent_touch_manager_enabled=True,
        mana_client_upsell_currency_enabled=True,
        mana_upsell_inline_results_enabled=True,
        mana_parent_touch_tariff_handoff_enabled=True,
        mana_family_compact_inputs_enabled=True,
        mana_parent_touch_compact_publication_enabled=True,
        mana_parent_touch_compact_manager_enabled=True,
        mana_family_day_usage_enabled=True,
        mana_family_day_reviews_enabled=True,
        mana_family_location_enabled=True,
        mana_family_location_comparisons_enabled=enabled,
        mana_child_safety_limits=ChildSafetyLimits(
            job_tokens=2000,
            server_daily_tokens=2000,
            parent_daily_tokens=2000,
            lease_seconds=360,
        ),
    )


@pytest.mark.parametrize("enabled", [False, True])
async def test_actual_factory_and_closed_reader_preserve_comparison_schema_without_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    attempted: list[str] = []

    def denied(request: httpx.Request) -> httpx.Response:
        attempted.append(request.url.host)
        raise AssertionError("Startup and closed observation cannot call a provider")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_: httpx.MockTransport(denied))
    active = comparison_settings(tmp_path, enabled=enabled)
    async with runtime.parent_chat_runtime(active) as service:
        assert isinstance(service, ParentTouchService) and service.sources is not None
        assert isinstance(service.store, SqliteLocationComparisonSafetyStore) is enabled
        assert isinstance(service.sources._store, SqliteLocationComparisonCache) is enabled
    versions = (
        (active.mana_parent_chat_database_path, 37 if enabled else 36),
        (active.mana_family_source_database_path, 9 if enabled else 7),
    )
    for path, version in versions:
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == version
    values = active.model_dump()
    for key, value in tuple(values.items()):
        if key.startswith("mana_") and type(value) is bool:
            values[key] = False
    values.update(mana_parent_chat_enabled=True, mana_parent_touch_enabled=True)
    async with runtime.parent_chat_runtime(Settings(_env_file=None, **values)) as service:
        assert service is not None
        assert (await service.history("123", before=None, limit=20)).messages == []
    for path, version in versions:
        with sqlite3.connect(path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == version
    assert attempted == []


@pytest.mark.parametrize(
    "missing", ["mana_family_location_enabled", "mana_parent_touch_compact_publication_enabled"]
)
def test_comparison_setting_refuses_incomplete_runtime(tmp_path: Path, missing: str) -> None:
    active = comparison_settings(tmp_path)
    with pytest.raises(ValidationError, match="Saved location comparisons require"):
        Settings(_env_file=None, **(active.model_dump() | {missing: False}))


async def test_explicit_fake_lab_uses_same_comparison_readers(tmp_path: Path) -> None:
    options = replace(
        workspace_options(tmp_path, worker_enabled=False),
        tariff_handoff=True,
        compact_inputs=True,
        compact_publication=True,
        compact_manager=True,
        location_comparisons=True,
    )
    lab = ChatLab(options)
    await lab.start()
    try:
        assert isinstance(lab.store, SqliteLocationComparisonSafetyStore)
        assert isinstance(lab.source_store, SqliteLocationComparisonCache)
        assert lab.location.calls == lab.battery.calls == lab.catalog.calls == 0
        assert lab.bootstrap().parent_id
    finally:
        await lab.close()
