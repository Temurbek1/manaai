"""Family45 factories remain lazy, isolated and capture only new reminder reviews."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.core.config import Settings
from app.mana_ai.application.bound_reminder_review import BOUND_REMINDER_PREPARE_ACK
from app.mana_ai.application.chat_ports import ChatPrompt
from app.mana_ai.application.direct_reminders import direct_reminder_request
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.bound_reminder_review import BoundReminderDecision
from app.mana_ai.domain.family_agents import ParentTouchReviewedTurn
from app.services import parent_chat_runtime as runtime
from app.services.bound_reminder_review_store import (
    SqliteBoundReminderReviewStore,
    SqliteClosedBoundReminderReviewStore,
)
from app.services.compact_manager_decision_store import SqliteCompactManagerDecisionStore
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import ChatLab, LabOptions, SimulatedModel
from scripts import mana_chat_lab as lab_script
from tests.test_compact_manager_runtime import compact_settings
from tests.test_family_source_runtime import config
from tests.test_mana_chat_lab import Clock


def bound_settings(path: Path, *, enabled: bool = True) -> Settings:
    previous = compact_settings(path)
    return Settings(
        _env_file=None,
        **(previous.model_dump() | {"mana_parent_touch_bound_reminder_reviews_enabled": enabled}),
    )


@pytest.fixture
def denied_provider_requests(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    requests: list[str] = []

    def deny(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.host)
        raise AssertionError("Runtime selection and observation cannot call a provider")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **_: httpx.MockTransport(deny))
    return requests


async def test_active_disabled_and_closed45_retain_the_current_reader_without_http(
    tmp_path: Path, denied_provider_requests: list[str]
) -> None:
    settings = bound_settings(tmp_path)
    for enabled in (True, False):
        async with runtime.parent_chat_runtime(
            settings.model_copy(
                update={"mana_parent_touch_bound_reminder_reviews_enabled": enabled}
            )
        ) as service:
            assert isinstance(service, ParentTouchService)
            assert type(service.store) is SqliteBoundReminderReviewStore
            assert service.store._bound_reminder_reviews_enabled is enabled
            with service.store._connect() as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 45
            assert (await service.history("123", before=None, limit=20)).messages == []
    credentials = settings.firebase_service_account_file
    assert credentials is not None
    closed = config(
        tmp_path, credentials, mana_parent_touch_enabled=False, mana_family_sources_enabled=False
    )
    async with runtime.parent_chat_runtime(closed) as service:
        assert service and type(service.store) is SqliteClosedBoundReminderReviewStore
        assert (await service.history("123", before=None, limit=20)).messages == []
        with service.store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 45
    assert denied_provider_requests == []


async def test_enabling45_keeps_an_old44_literal_turn_on_its_original_contract(
    tmp_path: Path, denied_provider_requests: list[str]
) -> None:
    previous = bound_settings(tmp_path, enabled=False)
    async with runtime.parent_chat_runtime(previous) as service:
        assert isinstance(service, ParentTouchService)
        old_store = service.store
        assert type(old_store) is SqliteCompactManagerDecisionStore
        with old_store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 44
    # Admit/claim after the actual runtime worker closes; no generation can race
    # the old capture while the new runtime is being selected.
    now = datetime.now(UTC)
    request = ParentTouchReviewedTurn(
        parent_id="123", request_id=uuid4(), message="Напомни завтра в 09:00 купить тетради"
    )
    admitted = await old_store.admit_reviewed(request, now, allow_new=True)
    claimed = await old_store.claim_reviewed_response(now)
    assert claimed and claimed[0].turn.turn_id == admitted.turn.turn_id
    original_scope = await old_store.manager_scope("123", admitted.turn.turn_id)
    assert original_scope and original_scope.stage == "reminder"
    with old_store._connect() as db:
        original = tuple(
            db.execute(
                "SELECT r.payload,r.fingerprint,m.binding,m.phase FROM direct_reminder_routes r "
                "JOIN parent_touch_manager_turns m ON m.turn_id=r.turn_id WHERE r.turn_id=?",
                (admitted.turn.turn_id,),
            ).fetchone()
        )
    async with runtime.parent_chat_runtime(
        previous.model_copy(update={"mana_parent_touch_bound_reminder_reviews_enabled": True})
    ) as rearmed:
        assert isinstance(rearmed, ParentTouchService)
        assert type(rearmed.store) is SqliteBoundReminderReviewStore
        assert (
            await rearmed.store.bound_reminder_review_request("123", admitted.turn.turn_id) is None
        )
        assert await rearmed.store.manager_scope("123", admitted.turn.turn_id) == original_scope
        replay = await rearmed.store.admit_reviewed(request, now, allow_new=True)
        assert replay.turn.turn_id == admitted.turn.turn_id
        with rearmed.store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 45
            assert (
                tuple(
                    db.execute(
                        "SELECT r.payload,r.fingerprint,m.binding,m.phase "
                        "FROM direct_reminder_routes r JOIN parent_touch_manager_turns m "
                        "ON m.turn_id=r.turn_id WHERE r.turn_id=?",
                        (admitted.turn.turn_id,),
                    ).fetchone()
                )
                == original
            )
    assert denied_provider_requests == []


@pytest.mark.parametrize(
    "missing",
    ["mana_parent_touch_direct_reminders_enabled", "mana_parent_touch_compact_decisions_enabled"],
)
def test_bound_review_configuration_requires_both_captured_protocols(
    tmp_path: Path, missing: str
) -> None:
    settings = bound_settings(tmp_path)
    with pytest.raises(ValidationError, match="Bound reminder reviews require"):
        Settings(_env_file=None, **(settings.model_dump() | {missing: False}))


@pytest.mark.parametrize("missing", ["direct_reminders", "compact_decisions"])
def test_bound_review_lab_requires_its_full_separate_profile(tmp_path: Path, missing: str) -> None:
    options = LabOptions(
        tmp_path, direct_reminders=True, compact_decisions=True, bound_reminder_reviews=True
    )
    invalid = (
        replace(options, direct_reminders=False)
        if missing == "direct_reminders"
        else replace(options, compact_decisions=False)
    )
    with pytest.raises(ValueError, match="Bound reminder reviews require"):
        ChatLab(invalid)


async def test_simulated_bound_review_reuses_the_exact_frozen_candidate() -> None:
    frozen = direct_reminder_request(
        "Напомни завтра в 09:00 купить тетради для обоих детей",
        now=Clock.value,
        timezone="Asia/Samarkand",
        timezone_basis="verified_contact",
    )
    assert frozen is not None
    prompt = ChatPrompt("Fictional bound protocol", (), bound_reminder_request=frozen)
    receipt = await SimulatedModel("speaker").respond(prompt, max_output_tokens=256)
    assert receipt.completed and receipt.usage.total == 150
    assert receipt.reminder_candidate == frozen.candidate
    assert receipt.answer == BOUND_REMINDER_PREPARE_ACK
    assert receipt.bound_reminder_decision == BoundReminderDecision(
        kind="prepare", body=None, question=None
    )
    assert receipt.manager_handoff is None
    assert receipt.clarification_question is None


async def test_simulated45_wiring_prepares_once_and_still_requires_parent_confirmation(
    tmp_path: Path,
) -> None:
    lab = ChatLab(
        replace(
            workspace_options(tmp_path, clock=Clock(), worker_enabled=False),
            tariff_handoff=True,
            compact_inputs=True,
            compact_publication=True,
            compact_manager=True,
            saved_observations=True,
            compact_source_tools=True,
            direct_reminders=True,
            compact_decisions=True,
            bound_reminder_reviews=True,
        )
    )
    await lab.start()
    try:
        from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
        from app.services.mana_chat_lab import LAB_PARENT

        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Напомни завтра в 09:00 купить тетради для обоих детей",
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        assert not await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "completed" and state.response and state.response.usage.total == 150
        history = (await lab.state()).history
        assert history.active_confirmation is not None
        assert history.active_confirmation.candidate.content == "купить тетради для обоих детей"
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM assistant_reminders").fetchone()[0] == "draft"
            assert not db.execute("SELECT 1 FROM child_safety_parent_events").fetchone()
        assert (await lab.state()).safety_budget.server_used_tokens == 0
        assert lab.battery.calls == lab.app_usage.calls == lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_bound_review_app_and_marker_use_a_separate45_simulation_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[LabOptions] = []

    def app(*, options: LabOptions | None = None) -> FastAPI:
        assert options is not None
        captured.append(options)
        return FastAPI()

    monkeypatch.setattr(lab_script, "create_app", app)
    lab_script.create_bound_reminder_reviews_app()
    options = captured[0]
    assert options.directory.name == "bound-reminder-v45-simulation"
    assert options.bound_reminder_reviews and options.direct_reminders and options.compact_decisions
    assert not options.real_model
    local_options = replace(
        options, directory=tmp_path / "bound45", clock=Clock(), worker_enabled=False
    )
    lab = ChatLab(local_options)
    await lab.start()
    try:
        assert isinstance(lab.store, SqliteBoundReminderReviewStore)
        marker = json.loads((local_options.directory / "lab-state.json").read_text())
        assert marker["bound_reminder_reviews"] is True
        with lab.store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 45
        assert lab.battery.calls == lab.catalog.calls == lab.app_usage.calls == 0
    finally:
        await lab.close()
    previous_lab = ChatLab(replace(local_options, bound_reminder_reviews=False))
    with pytest.raises(ValueError, match="different lab mode"):
        await previous_lab.start()
