"""Reuse fictional profile observations, never contact or mutate a real account."""

import asyncio
import hashlib
import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.mana_ai.application.parent_touch_offers import render_parent_offer
from app.mana_ai.application.retention_expiry import RetentionProfileSource
from app.mana_ai.domain.chat import ParentChildContext, ParentTariffContext
from app.mana_ai.domain.conversion import ConversionSnapshot
from app.mana_ai.domain.proactive_parent import ParentContactContext
from app.mana_ai.domain.retention_expiry import RetentionTariffFact
from app.services.lab_collection import LabCollectionClock
from app.services.mana_chat_lab import LAB_PARENT, ChatLab, LabOptions
from app.services.shared_conversion_profile_store import SqliteSharedConversionProfileStore
from tests.test_conversion_agent import snapshot
from tests.test_mana_chat_lab import Clock


async def test_private_lab_profile_endpoint_vetoes_original_offer_without_a_new_backend_event(
    tmp_path: Path,
) -> None:
    from scripts.mana_chat_lab import create_app
    from tests.test_mana_chat_lab import BASE, PREFIX, session

    clock = Clock()
    clock.value = Clock.value
    app = create_app(
        options=LabOptions(
            tmp_path / "http",
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
            shared_conversion_profile=True,
        )
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=BASE,
        ) as client,
    ):
        body = {"parent_id": LAB_PARENT, "is_paid": False}
        assert (await client.post("/lab/conversion-profile", json=body)).status_code == 401
        headers = await session(client)
        assert (await client.post("/lab/conversion-profile", json=body)).status_code == 403
        foreign = await client.post(
            "/lab/conversion-profile", headers=headers, json={"parent_id": "4", "is_paid": False}
        )
        assert foreign.status_code == 403
        invalid = await client.post(
            "/lab/conversion-profile", headers=headers, json={"parent_id": LAB_PARENT, "is_paid": 0}
        )
        assert invalid.status_code == 422
        assert (
            await client.post("/lab/conversion-profile", headers=headers, json=body)
        ).status_code == 200
        metadata = (await client.get("/lab/bootstrap")).json()
        event = next(s["body"] for s in metadata["scenarios"] if s["key"] == "conversion")
        admitted = await client.post(
            PREFIX + "/conversion-agent/events", headers=headers, json=event
        )
        assert admitted.status_code == 202
        proposal = admitted.json()["proposal"]
        assert proposal["status"] == "queued"
        clock.value += timedelta(seconds=1)
        assert (
            await client.post(
                "/lab/conversion-profile",
                headers=headers,
                json={"parent_id": LAB_PARENT, "is_paid": True},
            )
        ).status_code == 200
        current = await client.get(
            PREFIX + "/conversion-agent/proposals/" + proposal["proposal_id"],
            params={"parent_id": LAB_PARENT},
        )
        assert current.status_code == 200
        assert current.json()["closed_reason"] == "shared_profile_paid"
        history = await client.get(PREFIX + "/parent-touch/chat", params={"parent_id": LAB_PARENT})
        assert history.status_code == 200 and history.json()["messages"] == []


async def setup(path: Path) -> tuple[ChatLab, Clock, SqliteSharedConversionProfileStore]:
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
            shared_conversion_profile=True,
        )
    )
    await lab.start()
    assert isinstance(lab.store, SqliteSharedConversionProfileStore)
    return lab, clock, lab.store


async def test_fixed_clock_lab_restores_observed_afternoon_after_actual_reconstruction(
    tmp_path: Path,
) -> None:
    def options() -> LabOptions:
        clock = LabCollectionClock()
        clock.advance(9)
        return LabOptions(
            tmp_path / "fixed-restart",
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
            shared_conversion_profile=True,
        )

    lab = ChatLab(options())
    await lab.start()
    try:
        await lab.prepare_conversion_profile(False)
        await lab.prepare_conversion_profile(True)
        recorded_time = lab.options.clock.now()
        with sqlite3.connect(lab.options.directory / "family.sqlite3") as db:
            before = db.execute("SELECT * FROM conversion_profile_heads").fetchall()
        await lab.close()
        lab = ChatLab(options())
        await lab.start()
        assert lab.options.clock.now() == recorded_time
        assert not (await lab.state()).history.messages
        with sqlite3.connect(lab.options.directory / "family.sqlite3") as db:
            assert db.execute("SELECT * FROM conversion_profile_heads").fetchall() == before
        assert lab.battery.calls == lab.app_usage.calls == lab.catalog.calls == 0
    finally:
        await lab.close()


def account(clock: Clock, **changes: object) -> ConversionSnapshot:
    now = clock.now()
    return snapshot(
        parent_id=LAB_PARENT,
        observed_at=now,
        last_active_at=now,
        consent_observed_at=now - timedelta(days=7),
        free_started_at=now - timedelta(days=7),
        free_access_ends_at=now + timedelta(days=1),
        **changes,
    )


def fact(
    clock: Clock, *, paid: bool | None = False, parent: str = LAB_PARENT
) -> RetentionTariffFact:
    return RetentionTariffFact(
        parent_id=parent,
        collected_at=clock.now(),
        is_paid=paid,
        valid_until=clock.now().replace(hour=9, minute=0, second=0, microsecond=0)
        + timedelta(days=1),
    )


async def test_one_existing_profile_read_feeds_both_consumers_and_payment_vetoes_offer(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "profile")

    class Profiles:
        calls = 0
        paid = False

        async def read(self, parent_id: str) -> ParentChildContext:
            self.calls += 1
            return ParentChildContext(
                parent_id=parent_id,
                children=[],
                limitations=[],
                collected_at=clock.now(),
                tariff=ParentTariffContext(
                    collected_at=clock.now(),
                    tariff_name="Fictional",
                    is_paid=self.paid,
                    valid_until=fact(clock).valid_until,
                    payment_date=None,
                    agent_trial_used=False,
                ),
            )

    profiles = Profiles()
    source = RetentionProfileSource(profiles, store, clock=clock.now)
    try:
        await source.read(LAB_PARENT)
        with store._connect() as db:
            assert not db.execute("SELECT 1 FROM conversion_proposals").fetchone()
        original = account(clock)
        admitted = await store.ingest_conversion(original, clock.now())
        assert admitted.proposal is not None and admitted.proposal.status == "queued"
        clock.value += timedelta(seconds=1)
        profiles.paid = True
        await source.read(LAB_PARENT)
        current = await store.conversion_proposal(LAB_PARENT, admitted.proposal.proposal_id)
        assert current.status == "cancelled" and current.closed_reason == "shared_profile_paid"
        assert not await store.publish_conversion(clock.now(), render_parent_offer)
        assert profiles.calls == 2
        assert not (await lab.state()).history.messages
        assert (await lab.state()).safety_budget.server_used_tokens == 0
        assert lab.battery.calls == lab.app_usage.calls == lab.catalog.calls == 0
        with store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM conversion_profile_heads").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM retention_tariff_heads").fetchone()[0] == 1
            assert not db.execute("SELECT 1 FROM conversion_trial_grants").fetchone()
    finally:
        await lab.close()


@pytest.mark.parametrize(
    "condition,reason",
    [
        ("missing", "shared_profile_not_current"),
        ("unknown", "shared_profile_unverified"),
        ("paid", "shared_profile_paid"),
        ("stale", "shared_profile_not_current"),
        ("mismatch", "shared_profile_term_mismatch"),
        ("closed", "shared_profile_source_closed"),
    ],
)
async def test_shared_observation_can_only_veto_eligibility(
    tmp_path: Path, condition: str, reason: str
) -> None:
    lab, clock, store = await setup(tmp_path / condition)
    try:
        original = account(clock)
        if condition != "missing":
            row = fact(
                clock,
                paid=True if condition == "paid" else None if condition == "unknown" else False,
            )
            if condition == "mismatch":
                row = row.model_copy(update={"valid_until": clock.now() + timedelta(days=2)})
            await store.observe_inventory_tariffs((row,), clock.now())
        if condition == "stale":
            clock.value += timedelta(seconds=181)
            original = account(clock)
        if condition == "closed":
            await store.close_expiry_source()
        admitted = await store.ingest_conversion(original, clock.now())
        assert admitted.decision == reason and admitted.proposal is None
        assert not await store.publish_conversion(clock.now(), render_parent_offer)
        assert not (await lab.state()).history.messages
        assert lab.battery.calls == lab.app_usage.calls == lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_nonpaid_profile_does_not_manufacture_activity_consent_or_approved_offer(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "no-permission")
    try:
        await store.observe_inventory_tariffs((fact(clock),), clock.now())
        denied = await store.ingest_conversion(account(clock, marketing_consent=False), clock.now())
        assert denied.decision == "no_marketing_consent" and denied.proposal is None
        next_snapshot = account(
            clock, revision=2, active_days_7d=0, sessions_7d=0, paywall_views_7d=0
        )
        denied = await store.ingest_conversion(next_snapshot, clock.now())
        assert denied.decision == "inactive_account" and denied.proposal is None
        assert not await store.publish_conversion(clock.now(), render_parent_offer)
    finally:
        await lab.close()


async def test_same_time_conflicting_facts_close_only_conversion_consumer(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "conflict")
    try:
        await store.observe_inventory_tariffs((fact(clock),), clock.now())
        admitted = await store.ingest_conversion(account(clock), clock.now())
        assert admitted.proposal is not None
        await asyncio.gather(
            store.observe_inventory_tariffs((fact(clock, paid=True),), clock.now()),
            store.observe_inventory_tariffs((fact(clock),), clock.now()),
        )
        current = await store.conversion_proposal(LAB_PARENT, admitted.proposal.proposal_id)
        assert current.status == "cancelled"
        assert not await store.publish_conversion(clock.now(), render_parent_offer)
        with store._connect() as db:
            assert (
                db.execute("SELECT circuit_open FROM conversion_profile_policy").fetchone()[0] == 1
            )
            assert db.execute("SELECT circuit_open FROM retention_expiry_policy").fetchone()[0] == 0
    finally:
        await lab.close()


async def test_legacy_paid_observation_cannot_be_replaced_by_same_time_free_selection(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "legacy-conflict")
    try:
        store._shared_profile_enabled = False
        await store.observe_inventory_tariffs((fact(clock, paid=True),), clock.now())
        store._shared_profile_enabled = True
        await store.observe_inventory_tariffs((fact(clock),), clock.now())
        result = await store.ingest_conversion(account(clock), clock.now())
        assert result.decision == "shared_profile_source_closed" and result.proposal is None
        assert not (await lab.state()).history.messages
    finally:
        await lab.close()


async def test_older_profile_cannot_replace_known_payment_or_rearm_original_event(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "older")
    try:
        old = fact(clock)
        original = account(clock)
        await store.observe_inventory_tariffs((old,), clock.now())
        admitted = await store.ingest_conversion(original, clock.now())
        clock.value += timedelta(seconds=1)
        await store.observe_inventory_tariffs((fact(clock, paid=True),), clock.now())
        await store.observe_inventory_tariffs((old,), clock.now())
        assert await store.ingest_conversion(original, clock.now()) == admitted
        assert admitted.proposal is not None
        current = await store.conversion_proposal(LAB_PARENT, admitted.proposal.proposal_id)
        assert current.closed_reason == "shared_profile_paid"
        assert not await store.publish_conversion(clock.now(), render_parent_offer)
        with store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM conversion_profile_captures").fetchone()[0] == 1
    finally:
        await lab.close()


async def test_saved_message_survives_payment_but_unsubmitted_push_is_suppressed(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "push")
    try:
        store._push_enabled = True  # Fictional SQL outbox only; no gateway is installed.
        prior = await store.contact_context(LAB_PARENT, clock.now())
        assert prior is not None
        await store.ingest_contact_context(
            ParentContactContext(
                parent_id=LAB_PARENT,
                event_id=uuid4(),
                revision=prior.revision + 1,
                observed_at=clock.now(),
                valid_until=clock.now() + timedelta(days=1),
                language="ru",
                timezone="Asia/Samarkand",
                safety_chat_consent=True,
                safety_push_consent=False,
                marketing_push_consent=True,
            ),
            clock.now(),
        )
        await store.observe_inventory_tariffs((fact(clock),), clock.now())
        admitted = await store.ingest_conversion(account(clock), clock.now())
        assert admitted.proposal is not None
        assert await store.publish_conversion(clock.now(), render_parent_offer)
        history = (await lab.state()).history
        assert len(history.messages) == 1 and history.messages[0].role == "assistant"
        with store._connect() as db:
            assert db.execute("SELECT status FROM parent_push_outbox").fetchone()[0] == "queued"
        clock.value += timedelta(seconds=1)
        await store.observe_inventory_tariffs((fact(clock, paid=True),), clock.now())
        assert await store.claim_push(clock.now()) is None
        assert (await lab.state()).history.messages == history.messages
        assert (await lab.state()).history.quota.used_tokens == 0
    finally:
        await lab.close()


async def test_stopping_captured_checks_never_falls_back_or_redispatches_on_restart(
    tmp_path: Path,
) -> None:
    lab, clock, store = await setup(tmp_path / "stop")
    try:
        await store.observe_inventory_tariffs((fact(clock),), clock.now())
        admitted = await store.ingest_conversion(account(clock), clock.now())
        assert admitted.proposal is not None
        store._shared_profile_enabled = False
        assert not await store.publish_conversion(clock.now(), render_parent_offer)
        current = await store.conversion_proposal(LAB_PARENT, admitted.proposal.proposal_id)
        assert current.closed_reason == "shared_profile_disabled"
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        assert not await lab.store.publish_conversion(clock.now(), render_parent_offer)
        assert not (await lab.state()).history.messages
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM conversion_profile_captures").fetchone()[0] == 1
    finally:
        await lab.close()


async def test_old_reader_refuses_v20_and_preserves_database_bytes(tmp_path: Path) -> None:
    from app.services.dated_review_safety_store import SqliteClosedDatedReviewSafetyStore

    lab, _, store = await setup(tmp_path / "reader")
    try:
        before = hashlib.sha256(store._path.read_bytes()).hexdigest()
        old = SqliteClosedDatedReviewSafetyStore(
            store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        with pytest.raises(RuntimeError, match="dedicated database"):
            await old.initialize()
        assert hashlib.sha256(store._path.read_bytes()).hexdigest() == before
    finally:
        await lab.close()


async def test_enabling_never_recaptures_old_profiles_or_snapshot_events(tmp_path: Path) -> None:
    lab, clock, store = await setup(tmp_path / "capture")
    try:
        store._shared_profile_enabled = False
        await store.observe_inventory_tariffs((fact(clock),), clock.now())
        original = account(clock)
        admitted = await store.ingest_conversion(original, clock.now())
        assert admitted.proposal is not None
        store._shared_profile_enabled = True
        assert await store.ingest_conversion(original, clock.now()) == admitted
        await store.observe_inventory_tariffs((fact(clock),), clock.now())
        with store._connect() as db:
            assert db.execute("SELECT enabled FROM conversion_profile_captures").fetchone()[0] == 0
            assert not db.execute("SELECT 1 FROM conversion_profile_heads").fetchone()
        next_result = await store.ingest_conversion(account(clock, revision=2), clock.now())
        assert next_result.decision == "shared_profile_not_current"
        clock.value += timedelta(seconds=1)
        fresh = fact(clock)
        await store.observe_inventory_tariffs((fresh,), clock.now())
        confirmed = account(clock, revision=3).model_copy(
            update={"free_access_ends_at": fresh.valid_until}
        )
        assert (await store.ingest_conversion(confirmed, clock.now())).proposal is not None
    finally:
        await lab.close()


async def test_current_closed_reader_retains_new_scopes_and_historical_results(
    tmp_path: Path,
) -> None:
    from app.services.shared_conversion_profile_store import (
        SqliteClosedSharedConversionProfileStore,
    )

    lab, clock, store = await setup(tmp_path / "closed")
    try:
        await store.observe_inventory_tariffs((fact(clock),), clock.now())
        original = account(clock)
        admitted = await store.ingest_conversion(original, clock.now())
        assert admitted.proposal is not None
        assert await store.publish_conversion(clock.now(), render_parent_offer)
        before = hashlib.sha256(store._path.read_bytes()).hexdigest()
        closed = SqliteClosedSharedConversionProfileStore(
            store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        history = await closed.history(LAB_PARENT, before=None, limit=100, now=clock.now())
        assert len(history.messages) == 1
        assert hashlib.sha256(store._path.read_bytes()).hexdigest() == before
    finally:
        await lab.close()
