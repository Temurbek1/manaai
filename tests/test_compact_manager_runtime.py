"""Actual family44 factories remain lazy and never upgrade old manager turns."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.family_agents import ParentTouchReviewedTurn
from app.services import parent_chat_runtime as runtime
from app.services.compact_manager_decision_store import (
    SqliteClosedCompactManagerDecisionStore,
    SqliteCompactManagerDecisionStore,
)
from app.services.direct_reminder_store import SqliteDirectReminderStore
from tests.test_family_source_runtime import config, make_credential_file


def compact_settings(path: Path, *, enabled: bool = True) -> Settings:
    flags = (
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
    )
    return config(
        path,
        make_credential_file(path),
        **dict.fromkeys(flags, True),
        mana_parent_touch_compact_decisions_enabled=enabled,
        openai_timeout_seconds=30,
        mana_child_safety_limits=ChildSafetyLimits(
            server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=2000, lease_seconds=360
        ),
    )


@pytest.fixture
def denied_provider_requests(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    requests: list[str] = []

    def deny(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.host)
        raise AssertionError("Runtime selection and SQL observation cannot call providers")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_: httpx.MockTransport(deny))
    return requests


async def test_active_disabled_and_closed44_keep_current_reader_without_idle_provider_reads(
    tmp_path: Path, denied_provider_requests: list[str]
) -> None:
    settings = compact_settings(tmp_path)
    for enabled in (True, False):
        async with runtime.parent_chat_runtime(
            settings.model_copy(update={"mana_parent_touch_compact_decisions_enabled": enabled})
        ) as service:
            assert isinstance(service, ParentTouchService)
            assert type(service.store) is SqliteCompactManagerDecisionStore
            assert service.store._compact_decisions_enabled is enabled
            with service.store._connect() as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 44
                assert not db.execute("SELECT 1 FROM compact_manager_admissions").fetchone()
                assert not db.execute("SELECT 1 FROM compact_manager_decisions").fetchone()
                assert not db.execute("SELECT 1 FROM compact_manager_rejections").fetchone()
            assert (await service.history("123", before=None, limit=20)).messages == []
    credentials = settings.firebase_service_account_file
    assert credentials is not None
    closed = config(
        tmp_path,
        credentials,
        mana_parent_touch_enabled=False,
        mana_family_sources_enabled=False,
    )
    async with runtime.parent_chat_runtime(closed) as service:
        assert service and type(service.store) is SqliteClosedCompactManagerDecisionStore
        assert (await service.history("123", before=None, limit=20)).messages == []
        with service.store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 44
            assert not db.execute("SELECT 1 FROM compact_manager_admissions").fetchone()
    assert denied_provider_requests == []


@pytest.mark.parametrize("initial_version", [43, 44])
async def test_rearmed44_preserves_old43_or_disabled44_request_protocol(
    tmp_path: Path, denied_provider_requests: list[str], initial_version: int
) -> None:
    settings = compact_settings(tmp_path, enabled=initial_version == 44)
    async with runtime.parent_chat_runtime(settings) as service:
        assert isinstance(service, ParentTouchService)
        assert isinstance(service.store, SqliteDirectReminderStore)
        with service.store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == initial_version
    disabled = settings.model_copy(update={"mana_parent_touch_compact_decisions_enabled": False})
    async with runtime.parent_chat_runtime(disabled) as service:
        assert isinstance(service, ParentTouchService)
        store = service.store
        assert isinstance(store, SqliteDirectReminderStore)
        assert (type(store) is SqliteCompactManagerDecisionStore) is (initial_version == 44)
    # The actual runtime's worker has closed. Admit/claim only through SQL, never
    # let a background workflow race the protocol observation with inference.
    now = datetime.now(UTC)
    request = ParentTouchReviewedTurn(parent_id="123", request_id=uuid4(), message="Привет")
    admitted = await store.admit_reviewed(request, now, allow_new=True)
    claimed = await store.claim_reviewed_response(now)
    assert claimed and claimed[0].turn.turn_id == admitted.turn.turn_id
    original_scope = await store.manager_scope(request.parent_id, admitted.turn.turn_id)
    assert original_scope and original_scope.compact_decision_protocol is None
    with store._connect() as db:
        original_capture = tuple(
            db.execute(
                "SELECT t.request_digest,m.binding,m.phase,p.manager_binding,r.request "
                "FROM parent_chat_turns t JOIN parent_touch_manager_turns m "
                "ON m.turn_id=t.id "
                "JOIN parent_publication_captures p ON p.turn_id=t.id "
                "JOIN family_reviewed_messages r ON r.turn_id=t.id WHERE t.id=?",
                (admitted.turn.turn_id,),
            ).fetchone()
        )
        assert not original_capture[3].startswith("native-manager-")
    async with runtime.parent_chat_runtime(
        settings.model_copy(update={"mana_parent_touch_compact_decisions_enabled": True})
    ) as rearmed:
        assert isinstance(rearmed, ParentTouchService)
        assert type(rearmed.store) is SqliteCompactManagerDecisionStore
        scope = await rearmed.store.manager_scope(request.parent_id, admitted.turn.turn_id)
        assert scope == original_scope and scope.compact_decision_protocol is None
        replay = await rearmed.store.admit_reviewed(request, now, allow_new=True)
        assert replay.turn.turn_id == admitted.turn.turn_id
        with rearmed.store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 44
            assert not db.execute("SELECT 1 FROM compact_manager_admissions").fetchone()
            assert not db.execute("SELECT 1 FROM compact_manager_decisions").fetchone()
            assert (
                tuple(
                    db.execute(
                        "SELECT t.request_digest,m.binding,m.phase,p.manager_binding,r.request "
                        "FROM parent_chat_turns t JOIN parent_touch_manager_turns m "
                        "ON m.turn_id=t.id "
                        "JOIN parent_publication_captures p ON p.turn_id=t.id "
                        "JOIN family_reviewed_messages r ON r.turn_id=t.id WHERE t.id=?",
                        (admitted.turn.turn_id,),
                    ).fetchone()
                )
                == original_capture
            )
    assert denied_provider_requests == []


@pytest.mark.parametrize(
    "missing,message",
    [
        (
            "mana_family_compact_source_tools_enabled",
            "Compact native decisions require the complete captured manager runtime",
        ),
        (
            "mana_family_saved_observations_enabled",
            "Compact source tools require the captured saved-observation runtime",
        ),
        (
            "mana_parent_touch_compact_manager_enabled",
            "Saved observations require captured manager and location cache runtimes",
        ),
    ],
)
def test_compact_native_configuration_refuses_incomplete_manager_runtime(
    tmp_path: Path, missing: str, message: str
) -> None:
    settings = compact_settings(tmp_path)
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **(settings.model_dump() | {missing: False}))
