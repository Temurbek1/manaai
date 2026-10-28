"""Actual runtime selection for captured SQL inspection and contextual tariff refinement."""

import sqlite3
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.application.source_tool_workflow import SourceToolWorkflow
from app.services import parent_chat_runtime as runtime
from app.services.saved_observation_safety_store import SqliteSavedObservationSafetyStore
from app.services.tariff_followup_store import SqliteTariffFollowupStore
from tests.test_location_comparison_runtime import comparison_settings


@pytest.mark.parametrize(
    "saved,followups,labels",
    [(False, False, True), (True, False, False), (False, True, False), (True, True, True)],
)
async def test_captured_runtime_stopped_runtime_and_closed_reader_do_no_idle_http(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    saved: bool,
    followups: bool,
    labels: bool,
) -> None:
    attempts: list[str] = []

    def denied(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.host)
        raise AssertionError("Configuration/startup/status must not call a provider")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_: httpx.MockTransport(denied))
    base = comparison_settings(tmp_path)
    active = Settings(
        _env_file=None,
        **(
            base.model_dump()
            | {
                "mana_family_saved_observations_enabled": saved,
                "mana_upsell_followups_enabled": followups,
                "mana_family_location_time_labels_enabled": labels,
            }
        ),
    )
    expected = 39 if followups else 38 if saved else 37
    async with runtime.parent_chat_runtime(active) as service:
        assert isinstance(service, ParentTouchService) and service.safety
        assert isinstance(service.store, SqliteSavedObservationSafetyStore) is (saved or followups)
        assert isinstance(service.store, SqliteTariffFollowupStore) is followups
        workflow = service.safety._native_sources
        assert isinstance(workflow, SourceToolWorkflow)
        assert (workflow._saved_observations is not None) is saved
    stopped = active.model_dump() | {
        "mana_family_saved_observations_enabled": False,
        "mana_upsell_followups_enabled": False,
        "mana_family_location_time_labels_enabled": False,
    }
    async with runtime.parent_chat_runtime(Settings(_env_file=None, **stopped)) as service:
        assert isinstance(service, ParentTouchService)
        assert (await service.history("123", before=None, limit=20)).messages == []
    values = active.model_dump()
    for key, value in tuple(values.items()):
        if key.startswith("mana_") and type(value) is bool:
            values[key] = False
    values.update(mana_parent_chat_enabled=True, mana_parent_touch_enabled=True)
    async with runtime.parent_chat_runtime(Settings(_env_file=None, **values)) as service:
        assert service is not None
        assert (await service.history("123", before=None, limit=20)).messages == []
    with sqlite3.connect(active.mana_parent_chat_database_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == expected
    with sqlite3.connect(active.mana_family_source_database_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == (10 if labels else 9)
    assert attempts == []


@pytest.mark.parametrize(
    "flag",
    [
        "mana_family_saved_observations_enabled",
        "mana_upsell_followups_enabled",
        "mana_family_location_time_labels_enabled",
    ],
)
def test_new_flags_fail_closed_on_missing_required_profiles(flag: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"openai_api_key": "fake-unused-key", flag: True})
