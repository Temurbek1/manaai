"""Verified new grant -> fresh profile -> one permitted notice, without provider writes."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pytest import MonkeyPatch

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.conversion_grants import TrialGrantResult, TrialGrantState
from app.mana_ai.domain.family_agents import AgentQuestionRequest, ParentTouchMessageRequest
from app.mana_ai.domain.retention_expiry import RetentionTariffFact
from app.mana_ai.domain.trial_periods import TrialPeriodMetadata
from app.services.lab_trial_period import LabTrialGrantGateway, seed_trial_history
from app.services.mana_chat_lab import LAB_PARENT, ChatLab, LabOptions
from app.services.trial_period_store import SqliteClosedTrialPeriodStore, SqliteTrialPeriodStore
from tests.test_mana_chat_lab import Clock


async def test_dedicated_lab_factory_starts_and_preserves_its_seed_on_restart(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from app.services import mana_chat_lab as runtime
    from scripts import mana_chat_lab as script

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("The trial-period lab must not initialize live providers")

    monkeypatch.setattr(runtime, "get_settings", forbidden)
    create_app = script.create_app

    def isolated_app(*, options: LabOptions | None = None) -> FastAPI:
        assert options is not None
        return create_app(options=replace(options, directory=tmp_path / "lab"))

    monkeypatch.setattr(script, "create_app", isolated_app)
    saved: list[str] | None = None
    for _ in range(2):
        app = script.create_trial_period_app()
        async with app.router.lifespan_context(app):
            lab = app.state.chat_lab
            assert lab.options.clock.now().hour == 10
            assert lab.bootstrap().seeded_history == "fictional_trial_grant"
            for _ in range(100):
                history = (await lab.state()).history
                if len(history.messages) == 5:
                    break
                await asyncio.sleep(0.02)
            assert len(history.messages) == 5
            assert history.quota.used_tokens == 0
            actual = [message.model_dump_json() for message in history.messages]
            if saved is None:
                saved = actual
            assert actual == saved
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8092"
            ) as client:
                page = await client.get("/")
                assert page.status_code == 200


async def setup(path: Path) -> tuple[ChatLab, Clock, SqliteTrialPeriodStore]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        LabOptions(
            path,
            clock=clock,
            worker_enabled=False,
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
            retention=True,
            upsell=True,
            tariff_context=True,
            expiry=True,
            manager=True,
            trial_periods=True,
        )
    )
    await lab.start()
    assert isinstance(lab.store, SqliteTrialPeriodStore)
    return lab, clock, lab.store


async def test_verified_period_notice_then_tariff_enquiry_uses_the_same_chat(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "flow")
    try:
        original = await store.trial_grant(LAB_PARENT)
        assert original.status == "granted" and original.result
        assert original.result.period_metadata is None
        assert "period_metadata" not in original.model_dump_json()
        assert (
            "period_metadata"
            not in TrialGrantResult.model_json_schema(mode="serialization")["properties"]
        )
        assert await lab.touch.process_retention()
        assert not await lab.touch.process_retention()
        state = await lab.state()
        assert len(state.history.messages) == 5
        assert "бесплатный доступ на 1 дн." in state.history.messages[-1].content
        assert "900001" not in state.history.messages[-1].content
        assert state.history.quota.used_tokens == 0 and state.safety_budget.server_used_tokens == 0
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Покажи самый дешёвый тариф на 90 дней в UZS",
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_upsell()
        final = await lab.state()
        assert len(final.history.messages) == 8 and final.history.quota.used_tokens == 300
        assert final.safety_budget.server_used_tokens == 0
        assert "90 дней" in final.history.messages[-1].content
        assert (await store.trial_grant(LAB_PARENT)) == original
    finally:
        await lab.close()


@pytest.mark.parametrize("language", ["ru", "uz-Latn", "uz-Cyrl", "en"])
async def test_verified_recipient_language_and_no_model_budget_charge(
    tmp_path: Path, language: str
) -> None:
    lab, clock, store = await setup(tmp_path / language)
    try:
        contact = await store.contact_context(LAB_PARENT, clock.now())
        assert contact
        await store.ingest_contact_context(
            contact.model_copy(
                update={
                    "event_id": uuid4(),
                    "revision": contact.revision + 1,
                    "language": language,
                }
            ),
            clock.now(),
        )
        with store._transaction() as db:
            db.execute("UPDATE parent_chat_quota SET used=2000 WHERE parent_id=?", (LAB_PARENT,))
        assert await lab.touch.process_retention()
        text = (await lab.state()).history.messages[-1].content
        assert {"ru": "бесплатный", "uz-Latn": "bepul", "uz-Cyrl": "бепул", "en": "free access"}[
            language
        ] in text
        assert (await lab.state()).history.quota.used_tokens == 2000
    finally:
        await lab.close()


@pytest.mark.parametrize(
    "change", ["missing_consent", "unknown", "changed_end", "stale", "disabled", "safety"]
)
async def test_unverified_or_disallowed_period_never_sends_a_notice(
    tmp_path: Path, change: str
) -> None:
    lab, clock, store = await setup(tmp_path / change)
    try:
        if change == "missing_consent":
            contact = await store.contact_context(LAB_PARENT, clock.now())
            assert contact
            await store.ingest_contact_context(
                contact.model_copy(
                    update={
                        "event_id": uuid4(),
                        "revision": contact.revision + 1,
                        "retention_chat_consent": False,
                    }
                ),
                clock.now(),
            )
        elif change in {"unknown", "changed_end"}:
            grant = await store.trial_grant(LAB_PARENT)
            assert grant.result
            clock.value += timedelta(seconds=1)
            await store.observe_inventory_tariffs(
                (
                    RetentionTariffFact(
                        parent_id=LAB_PARENT,
                        collected_at=clock.now(),
                        is_paid=None if change == "unknown" else False,
                        valid_until=grant.result.valid_until
                        + (timedelta(days=1) if change == "changed_end" else timedelta()),
                    ),
                ),
                clock.now(),
            )
        elif change == "stale":
            clock.value += timedelta(seconds=181)
        elif change == "disabled":
            store._trial_periods_enabled = False
        else:
            event = AgentQuestionRequest.model_validate(
                next(s.body for s in lab.bootstrap().scenarios if s.key == "question")
            )
            await store.enqueue(event, clock.now())
        assert not await lab.touch.process_retention()
        assert len((await lab.state()).history.messages) == 4
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM trial_period_notices").fetchone()
    finally:
        await lab.close()


@pytest.mark.parametrize("metadata", ["absent", "capture_disabled"])
async def test_old_or_uncaptured_grant_never_infers_a_start_date(
    tmp_path: Path, monkeypatch: MonkeyPatch, metadata: str
) -> None:
    original = LabTrialGrantGateway.grant

    async def legacy(self: LabTrialGrantGateway, parent_id: str, days: int) -> TrialGrantResult:
        return (await original(self, parent_id, days)).with_period_metadata(None)

    if metadata == "absent":
        monkeypatch.setattr(LabTrialGrantGateway, "grant", legacy)
    else:
        capture = SqliteTrialPeriodStore._on_trial_grant_claimed

        def disabled(
            self: SqliteTrialPeriodStore,
            db: sqlite3.Connection,
            state: TrialGrantState,
            now: datetime,
        ) -> None:
            self._trial_periods_enabled = False
            try:
                capture(self, db, state, now)
            finally:
                self._trial_periods_enabled = True

        monkeypatch.setattr(SqliteTrialPeriodStore, "_on_trial_grant_claimed", disabled)
    lab, clock, store = await setup(tmp_path / metadata)
    try:
        assert (await store.trial_grant(LAB_PARENT)).status == "granted"
        assert not await lab.touch.process_retention()
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM trial_period_facts").fetchone()
        await lab.close()
        await lab.start()
        assert not await lab.touch.process_retention()
    finally:
        await lab.close()


async def test_corrupted_period_closes_only_its_consumer_not_paid_expiry(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "corruption")
    try:
        with store._transaction() as db:
            db.execute("UPDATE trial_period_facts SET payload='{}'")
        assert not await lab.touch.process_retention()
        with store._connect() as db:
            assert db.execute("SELECT closed FROM trial_period_state").fetchone()[0] == 1
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
        assert await lab.touch.process_retention()
        assert "бесплатн" not in (await lab.state()).history.messages[-1].content
    finally:
        await lab.close()


@pytest.mark.parametrize("revoke", ["feature", "proof"])
async def test_pending_push_requires_its_period_proof_and_current_flag(
    tmp_path: Path, revoke: str
) -> None:
    lab, clock, store = await setup(tmp_path / revoke)
    try:
        store._push_enabled = True
        contact = await store.contact_context(LAB_PARENT, clock.now())
        assert contact
        await store.ingest_contact_context(
            contact.model_copy(
                update={
                    "event_id": uuid4(),
                    "revision": contact.revision + 1,
                    "retention_push_consent": True,
                }
            ),
            clock.now(),
        )
        assert await lab.touch.process_retention()
        with store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM parent_push_outbox").fetchone()[0] == 1
        if revoke == "feature":
            store._trial_periods_enabled = False
        else:
            with store._transaction() as db:
                db.execute("DELETE FROM trial_period_notices")
        assert await store.claim_push(clock.now()) is None
        assert len((await lab.state()).history.messages) == 5
    finally:
        await lab.close()


async def test_restart_and_closed_reader_preserve_new_period_and_exact_old_receipt(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "restart")
    try:
        original = await store.trial_grant(LAB_PARENT)
        assert await lab.touch.process_retention()
        before = (await lab.state()).history.messages
        await lab.close()
        await lab.start()
        assert not await lab.touch.process_retention()
        assert await lab.store.trial_grant(LAB_PARENT) == original
        assert (await lab.state()).history.messages == before
        await lab.close()
        closed = SqliteClosedTrialPeriodStore(
            tmp_path / "restart/family.sqlite3",
            history_only=True,
            daily_limit=2000,
            timezone="Asia/Samarkand",
        )
        await closed.initialize()
        assert (
            await closed.touch_history(LAB_PARENT, before=None, limit=100, now=clock.now())
        ).messages == before
    finally:
        await lab.close()


async def test_nested_unverified_metadata_stops_after_one_fake_grant_and_never_replays(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    async def skip_seed(*args: object) -> None:
        pass

    monkeypatch.setattr("app.services.mana_chat_lab.seed_trial_history", skip_seed)
    original = LabTrialGrantGateway.grant
    calls = 0

    async def invalid(self: LabTrialGrantGateway, parent_id: str, days: int) -> TrialGrantResult:
        nonlocal calls
        calls += 1
        result = await original(self, parent_id, days)
        return result.with_period_metadata(
            TrialPeriodMetadata.model_construct(
                created_at=result.valid_until - timedelta(days=days),
                is_paid=True,
                agent_trial_used=True,
            )
        )

    monkeypatch.setattr(LabTrialGrantGateway, "grant", invalid)
    lab, clock, store = await setup(tmp_path / "invalid-typed-port")
    try:
        with pytest.raises(ParentChatError, match="lab_trial_fixture_grant_unresolved"):
            await seed_trial_history(store, clock, tmp_path / "invalid-typed-port")
        assert (await store.trial_grant(LAB_PARENT)).status == "unknown"
        with pytest.raises(ParentChatError, match="lab_trial_fixture_unresolved"):
            await seed_trial_history(store, clock, tmp_path / "invalid-typed-port")
        assert calls == 1
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM trial_period_facts").fetchone()
    finally:
        await lab.close()


async def test_concurrent_workers_publish_once_and_rearming_does_not_recapture(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "workers")
    try:
        store._trial_periods_enabled = False
        assert not await lab.touch.process_retention()
        store._trial_periods_enabled = True
        await lab._profiles.read(LAB_PARENT)
        results = await asyncio.gather(lab.touch.process_retention(), lab.touch.process_retention())
        assert sorted(results) == [False, True]
        with store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM trial_period_admissions").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM trial_period_facts").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM trial_period_notices").fetchone()[0] == 1
        assert (await lab.state()).history.quota.used_tokens == 0
    finally:
        await lab.close()
