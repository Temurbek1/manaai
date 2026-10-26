"""Source-confirmed end notices without invented activity, offers or new reads."""

import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.family_agents import AgentQuestionRequest, ParentTouchMessageRequest
from app.mana_ai.domain.proactive_parent import ParentContactContext
from app.mana_ai.domain.retention_expiry import RetentionTariffFact
from app.services import mana_chat_lab as runtime
from app.services import parent_chat_runtime as runtime_module
from app.services.lab_trial_end import LabTrialEndClock
from app.services.location_safety_store import (
    SqliteClosedLocationSafetyStore,
    SqliteLocationSafetyStore,
)
from app.services.mana_chat_lab import LAB_CHILD, LAB_PARENT, ChatLab
from app.services.trial_end_store import SqliteClosedTrialEndStore, SqliteTrialEndStore
from scripts.mana_chat_lab import create_app
from tests.test_family_source_runtime import config, make_credential_file
from tests.test_lab_chat_actions import BASE, Clock, options, session
from tests.test_trial_action_cards import snapshot


async def start(directory: Path) -> tuple[ChatLab, Clock, SqliteTrialEndStore]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        replace(options(directory, clock), trial_periods=True, trial_end=True, action_cards=False)
    )
    await lab.start()
    assert isinstance(lab.store, SqliteTrialEndStore)
    return lab, clock, lab.store


async def fresh_contact(lab: ChatLab, clock: Clock, **changes: object) -> None:
    with lab.store._connect() as db:
        prior = ParentContactContext.model_validate_json(
            db.execute(
                "SELECT payload FROM parent_contact_contexts WHERE parent_id=?", (LAB_PARENT,)
            ).fetchone()[0]
        )
    assert lab.touch.proactive
    await lab.touch.proactive.register(
        ParentContactContext.model_validate(
            prior.model_dump()
            | {
                "event_id": uuid4(),
                "revision": prior.revision + 1,
                "observed_at": clock.now(),
                "valid_until": clock.now() + timedelta(days=1),
            }
            | changes
        )
    )


async def ended(lab: ChatLab, clock: Clock) -> None:
    clock.value += timedelta(days=2)
    await fresh_contact(lab, clock)
    await lab._profiles.read(LAB_PARENT)


async def test_known_end_notice_then_tariff_enquiry_keeps_one_chat_and_one_grant(
    tmp_path: Path,
) -> None:
    lab, clock, store = await start(tmp_path / "flow")
    try:
        grant = await store.trial_grant(LAB_PARENT)
        before = len((await lab.state()).history.messages)
        await ended(lab, clock)
        assert await lab.touch.process_retention()
        assert not await lab.touch.process_retention()
        state = await lab.state()
        assert len(state.history.messages) == before + 1
        notice = state.history.messages[-1]
        assert notice.role == "assistant" and "завершился" in notice.content
        assert "Выданный бесплатный период" in notice.content
        assert "27.10.2026" in notice.content
        assert state.history.quota.used_tokens == state.safety_budget.server_used_tokens == 0
        assert await store.trial_grant(LAB_PARENT) == grant
        with store._connect() as db:
            assert db.execute("SELECT count(*) FROM trial_end_notices").fetchone()[0] == 1
        await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT,
                request_id=uuid4(),
                message="Покажи самый дешёвый тариф на 90 дней в UZS",
            )
        )
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_upsell()
        state = await lab.state()
        assert "162 000.00 UZS" in state.history.messages[-1].content
        assert (
            state.history.quota.used_tokens == 300 and state.safety_budget.server_used_tokens == 0
        )
        assert await store.trial_grant(LAB_PARENT) == grant
    finally:
        await lab.close()


@pytest.mark.parametrize(
    "missing",
    [
        "fresh_source",
        "consent",
        "paid",
        "changed_term",
        "source_closed",
        "disabled",
        "priority",
        "opt_out",
    ],
)
async def test_unknown_or_changed_conditions_cannot_publish(missing: str, tmp_path: Path) -> None:
    lab, clock, store = await start(tmp_path / missing)
    try:
        clock.value += timedelta(days=2)
        await fresh_contact(
            lab, clock, **({"retention_chat_consent": False} if missing == "consent" else {})
        )
        if missing != "fresh_source":
            await lab._profiles.read(LAB_PARENT)
        if missing in {"paid", "changed_term"}:
            grant = await store.trial_grant(LAB_PARENT)
            assert grant.result
            await store.observe_inventory_tariffs(
                (
                    RetentionTariffFact(
                        parent_id=LAB_PARENT,
                        collected_at=clock.now(),
                        is_paid=missing == "paid",
                        valid_until=grant.result.valid_until
                        + timedelta(hours=1 if missing == "changed_term" else 0),
                    ),
                ),
                clock.now(),
            )
        if missing == "source_closed":
            await store.close_expiry_source()
        if missing == "disabled":
            store._trial_end_enabled = False
        if missing == "priority":
            await lab.touch.request_question(
                AgentQuestionRequest(
                    parent_id=LAB_PARENT,
                    child_id=LAB_CHILD,
                    agent_id="child-safety",
                    request_id=uuid4(),
                    information_key="routine.sleep",
                    question="Уточните режим ребёнка?",
                    reason="Fictional safety need",
                    source_revision="trial-end-test-v1",
                    priority=3,
                    observed_at=clock.now(),
                    expires_at=clock.now() + timedelta(hours=1),
                )
            )
        if missing == "opt_out":
            await store.retention_opt_out(
                ParentTouchMessageRequest(
                    parent_id=LAB_PARENT, request_id=uuid4(), message="не пиши первым"
                ),
                clock.now(),
            )
        before = len((await lab.state()).history.messages)
        assert not await lab.touch.process_retention()
        assert len((await lab.state()).history.messages) == before
        with store._connect() as db:
            assert db.execute("SELECT count(*) FROM trial_end_notices").fetchone()[0] == 0
    finally:
        await lab.close()


async def test_notice_and_its_proof_rollback_together_without_regrant(tmp_path: Path) -> None:
    lab, clock, store = await start(tmp_path / "atomic")
    try:
        await ended(lab, clock)
        before = len((await lab.state()).history.messages)
        with store._transaction() as db:
            db.execute(
                "CREATE TRIGGER reject_end BEFORE INSERT ON trial_end_notices "
                "BEGIN SELECT RAISE(ABORT,'synthetic SQL failure'); END"
            )
        with pytest.raises(sqlite3.IntegrityError):
            await lab.touch.process_retention()
        assert len((await lab.state()).history.messages) == before
        with store._connect() as db:
            assert db.execute("SELECT count(*) FROM trial_end_notices").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM conversion_trial_grants").fetchone()[0] == 1
    finally:
        await lab.close()


async def test_current_closed_reader_and_old_refusal_preserve_notices(tmp_path: Path) -> None:
    lab, clock, store = await start(tmp_path / "closed")
    try:
        await ended(lab, clock)
        assert await lab.touch.process_retention()
        await lab.touch.process_retention()  # Settle the purely local scan cursor before freezing.
        before = snapshot(store)
        closed = SqliteClosedTrialEndStore(
            store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        await closed.touch_history(LAB_PARENT, before=None, limit=100, now=clock.now())
        assert snapshot(store) == before
        with pytest.raises(RuntimeError, match="dedicated database"):
            await SqliteClosedLocationSafetyStore(
                store._path, daily_limit=2000, timezone="Asia/Samarkand"
            ).initialize()
        assert snapshot(store) == before
    finally:
        await lab.close()


async def test_v23_period_never_recaptures_on_v26_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    settings = replace(
        options(tmp_path / "upgrade", clock), trial_periods=True, trial_end=True, action_cards=False
    )

    def legacy(path: Path, *, trial_end_enabled: bool, **family: Any) -> SqliteLocationSafetyStore:
        return SqliteLocationSafetyStore(path, **family)

    with monkeypatch.context() as patcher:
        patcher.setattr(runtime, "SqliteTrialEndStore", legacy)
        lab = ChatLab(settings)
        await lab.start()
        before = snapshot(lab.store)
        await lab.close()
    lab = ChatLab(settings)
    await lab.start()
    try:
        assert isinstance(lab.store, SqliteTrialEndStore)
        after = snapshot(lab.store)
        assert {key: after[key] for key in before} == before
        with lab.store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 26
            assert db.execute("SELECT count(*) FROM trial_end_admissions").fetchone()[0] == 0
        await ended(lab, clock)
        assert not await lab.touch.process_retention()
    finally:
        await lab.close()


async def test_dedicated_clock_scenario_and_restart_keep_the_grant_and_notice(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "factory"
    options_ = replace(
        options(directory, Clock()),
        clock=LabTrialEndClock(),
        trial_periods=True,
        trial_end=True,
        action_cards=False,
    )
    app = create_app(options=options_)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        body = {"parent_id": LAB_PARENT}
        assert (await client.post("/lab/trial-end", headers=headers, json=body)).status_code == 200
        lab = app.state.chat_lab
        assert await lab.touch.process_retention()
        assert (await client.post("/lab/trial-end", headers=headers, json=body)).status_code == 200
        grant = await lab.store.trial_grant(LAB_PARENT)
        await lab.touch.process_retention()
        before = snapshot(lab.store)
    app = create_app(options=replace(options_, clock=LabTrialEndClock()))
    async with app.router.lifespan_context(app):
        lab = app.state.chat_lab
        assert lab.options.clock.now().day == 28
        assert await lab.store.trial_grant(LAB_PARENT) == grant
        assert snapshot(lab.store) == before
        assert not await lab.touch.process_retention()


async def test_real_runtime_selects_v26_and_retains_it_when_the_feature_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted: list[str] = []

    def deny(request: httpx.Request) -> httpx.Response:
        attempted.append(request.url.host or "")
        raise AssertionError("No model/source call belongs to idle runtime wiring")

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(deny))
    settings = config(
        tmp_path,
        make_credential_file(tmp_path),
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
        mana_conversion_trial_periods_enabled=True,
        mana_retention_trial_end_enabled=True,
        mana_child_safety_limits=ChildSafetyLimits(
            server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=2000, lease_seconds=360
        ),
    )
    for enabled in [True, False]:
        current = settings.model_copy(update={"mana_retention_trial_end_enabled": enabled})
        async with runtime_module.parent_chat_runtime(current) as touch:
            assert isinstance(touch, ParentTouchService)
            with sqlite3.connect(settings.mana_parent_chat_database_path) as db:
                assert db.execute("PRAGMA user_version").fetchone()[0] == 26
                assert db.execute("SELECT count(*) FROM trial_end_admissions").fetchone()[0] == 0
            assert not await touch.process_retention()
    assert not attempted
    with pytest.raises(ValidationError, match="Trial-end notices require"):
        Settings(_env_file=None, openai_api_key="test-only", mana_retention_trial_end_enabled=True)


async def test_before_end_timer_and_stale_post_end_fact_cannot_replace_a_fresh_observation(
    tmp_path: Path,
) -> None:
    lab, clock, store = await start(tmp_path / "time")
    try:
        assert await store.publish_expiry(clock.now()) is not None
        with store._connect() as db:
            assert db.execute("SELECT count(*) FROM trial_end_notices").fetchone()[0] == 0
        await ended(lab, clock)
        clock.value += timedelta(seconds=181)
        assert not await lab.touch.process_retention()
        await lab._profiles.read(LAB_PARENT)
        assert await lab.touch.process_retention()
        with store._connect() as db:
            assert db.execute("SELECT count(*) FROM trial_end_notices").fetchone()[0] == 1
    finally:
        await lab.close()


async def test_even_a_fresh_pre_end_observation_cannot_become_confirmation_by_timer(
    tmp_path: Path,
) -> None:
    lab, clock, store = await start(tmp_path / "boundary")
    try:
        grant = await store.trial_grant(LAB_PARENT)
        assert grant.result
        clock.value = grant.result.valid_until - timedelta(seconds=1)
        await fresh_contact(lab, clock)
        await lab._profiles.read(LAB_PARENT)
        clock.value += timedelta(seconds=2)
        assert not await lab.touch.process_retention()
        await lab._profiles.read(LAB_PARENT)
        assert await lab.touch.process_retention()
    finally:
        await lab.close()


@pytest.mark.parametrize("revoke", ["paid", "stale", "feature", "proof"])
async def test_unsubmitted_push_rechecks_end_proof_without_deleting_the_saved_message(
    tmp_path: Path, revoke: str
) -> None:
    lab, clock, store = await start(tmp_path / revoke)
    try:
        store._push_enabled = True
        await ended(lab, clock)
        await fresh_contact(lab, clock, retention_push_consent=True)
        assert await lab.touch.process_retention()
        messages = (await lab.state()).history.messages
        with store._connect() as db:
            assert db.execute("SELECT count(*) FROM parent_push_outbox").fetchone()[0] == 1
        if revoke == "paid":
            grant = await store.trial_grant(LAB_PARENT)
            assert grant.result
            clock.value += timedelta(seconds=1)
            await store.observe_inventory_tariffs(
                (
                    RetentionTariffFact(
                        parent_id=LAB_PARENT,
                        collected_at=clock.now(),
                        is_paid=True,
                        valid_until=grant.result.valid_until,
                    ),
                ),
                clock.now(),
            )
        elif revoke == "stale":
            clock.value += timedelta(seconds=181)
        elif revoke == "feature":
            store._trial_end_enabled = False
        else:
            with store._transaction() as db:
                db.execute("DELETE FROM trial_end_notices")
        assert await store.claim_push(clock.now()) is None
        assert (await lab.state()).history.messages == messages
        assert (await lab.state()).history.quota.used_tokens == 0
    finally:
        await lab.close()


async def test_a_disabled_grant_never_acquires_end_notice_eligibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    settings = replace(
        options(tmp_path / "disabled-capture", clock),
        trial_periods=True,
        trial_end=True,
        action_cards=False,
    )

    def disabled(path: Path, **family: Any) -> SqliteTrialEndStore:
        return SqliteTrialEndStore(path, **(family | {"trial_end_enabled": False}))

    with monkeypatch.context() as patcher:
        patcher.setattr(runtime, "SqliteTrialEndStore", disabled)
        lab = ChatLab(settings)
        await lab.start()
        original = await lab.store.trial_grant(LAB_PARENT)
        await lab.close()
    lab = ChatLab(settings)
    await lab.start()
    try:
        with lab.store._connect() as db:
            assert db.execute("SELECT enabled FROM trial_end_admissions").fetchone()[0] == 0
        await ended(lab, clock)
        assert not await lab.touch.process_retention()
        assert await lab.store.trial_grant(LAB_PARENT) == original
    finally:
        await lab.close()


@pytest.mark.parametrize(
    ("language", "word"),
    [("ru", "завершился"), ("uz-Latn", "tugagan"), ("uz-Cyrl", "тугаган"), ("en", "ended")],
)
async def test_first_end_notice_uses_current_verified_contact_language(
    tmp_path: Path, language: str, word: str
) -> None:
    lab, clock, store = await start(tmp_path / language)
    try:
        await ended(lab, clock)
        await fresh_contact(lab, clock, language=language)
        assert await lab.touch.process_retention()
        assert word in (await lab.state()).history.messages[-1].content
        assert (await lab.state()).history.quota.used_tokens == 0
        assert await store.claim_push(clock.now()) is None
    finally:
        await lab.close()
