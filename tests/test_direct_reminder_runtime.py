"""Actual43 factory selection stays lazy and retains its closed read path."""

from pathlib import Path

import httpx
import pytest

from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.services import parent_chat_runtime as runtime
from app.services.direct_reminder_store import (
    SqliteClosedDirectReminderStore,
    SqliteDirectReminderStore,
)
from tests.test_family_source_runtime import config, make_credential_file


async def test_active_disabled_and_closed43_keep_state_without_idle_provider_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []

    def deny(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.host)
        raise AssertionError("Unexpected idle provider call")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(deny))
    credentials = make_credential_file(tmp_path)
    flags = [
        "mana_parent_touch_review_first_enabled",
        "mana_child_safety_enabled",
        "mana_child_safety_source_tools_enabled",
        "mana_family_source_safety_enabled",
        "mana_family_app_usage_enabled",
        "mana_family_source_reviews_enabled",
        "mana_parent_reminders_enabled",
        "mana_client_retention_enabled",
        "mana_client_upsell_enabled",
        "mana_retention_expiry_enabled",
        "mana_parent_touch_manager_enabled",
        "mana_parent_touch_clarifications_enabled",
        "mana_client_upsell_currency_enabled",
        "mana_upsell_inline_results_enabled",
        "mana_parent_touch_tariff_handoff_enabled",
        "mana_family_compact_inputs_enabled",
        "mana_parent_touch_compact_publication_enabled",
        "mana_parent_touch_compact_manager_enabled",
        "mana_family_day_usage_enabled",
        "mana_family_location_enabled",
        "mana_family_saved_observations_enabled",
        "mana_family_compact_source_tools_enabled",
        "mana_parent_touch_direct_reminders_enabled",
    ]
    settings = config(
        tmp_path,
        credentials,
        **dict.fromkeys(flags, True),
        openai_timeout_seconds=30,
        mana_child_safety_limits=ChildSafetyLimits(
            server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=2000, lease_seconds=360
        ),
    )
    for enabled in (True, False):
        async with runtime.parent_chat_runtime(
            settings.model_copy(update={"mana_parent_touch_direct_reminders_enabled": enabled})
        ) as service:
            assert service and isinstance(service.store, SqliteDirectReminderStore)
            with service.store._connect() as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 43
                assert not db.execute("SELECT 1 FROM direct_reminder_routes").fetchone()
    closed = config(
        tmp_path, credentials, mana_parent_touch_enabled=False, mana_family_sources_enabled=False
    )
    async with runtime.parent_chat_runtime(closed) as service:
        assert service and isinstance(service.store, SqliteClosedDirectReminderStore)
    assert not requests
