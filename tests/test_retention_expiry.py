"""Source-driven first contact, real SQL broker and fake providers only."""

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pytest import MonkeyPatch

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.retention_expiry import RetentionExpiryPolicy
from app.services.mana_chat_lab import LAB_PARENT, ChatLab, LabOptions
from app.services.retention_expiry_store import SqliteRetentionExpiryStore
from tests.test_mana_chat_lab import Clock


async def setup(path: Path) -> tuple[ChatLab, Clock]:
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
        )
    )
    await lab.start()
    return lab, clock


async def test_profile_event_starts_chat_once_without_any_model_or_write(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "first")
    try:
        assert not (await lab.state()).history.messages
        assert not await lab.touch.process_retention()
        await lab.prepare_expiry_scenario()
        assert await lab.touch.process_retention()
        state = await lab.state()
        assert len(state.history.messages) == 1 and state.history.messages[0].role == "assistant"
        assert "тарифа" in state.history.messages[0].content
        assert state.history.quota.used_tokens == state.safety_budget.server_used_tokens == 0
        assert state.history.messages[0].created_at == clock.now()
        await lab.prepare_expiry_scenario()
        assert not await lab.touch.process_retention()
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM retention_expiry_notices").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM retention_tariff_changes").fetchone()[0] == 1
            assert not db.execute("SELECT 1 FROM conversion_trial_grants").fetchone()
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
            assert not db.execute("SELECT 1 FROM child_safety_jobs").fetchone()
        assert lab.battery.calls == lab.app_usage.calls == lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_concurrent_publishers_and_restart_never_duplicate_notice(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "concurrent")
    try:
        await lab.prepare_expiry_scenario()
        result = await asyncio.gather(*(lab.touch.process_retention() for _ in range(8)))
        assert result.count(True) == 1
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        await lab.prepare_expiry_scenario()
        assert not await lab.touch.process_retention()
        assert len((await lab.state()).history.messages) == 1
    finally:
        await lab.close()


async def test_independent_stop_suspends_expiry_without_erasing_its_history(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "stopped")
    try:
        await lab.prepare_expiry_scenario()
        assert isinstance(lab.store, SqliteRetentionExpiryStore)
        with lab.store._connect() as db:
            original = tuple(db.execute("SELECT * FROM retention_tariff_heads").fetchone())
        monkeypatch.setattr(lab.store, "_expiry_enabled", False)
        assert not await lab.touch.process_retention()
        clock.value += timedelta(seconds=1)
        await lab.prepare_expiry_scenario()
        with lab.store._connect() as db:
            assert tuple(db.execute("SELECT * FROM retention_tariff_heads").fetchone()) == original
            assert db.execute("SELECT COUNT(*) FROM retention_tariff_changes").fetchone()[0] == 1
        monkeypatch.setattr(lab.store, "_expiry_enabled", True)
        assert await lab.touch.process_retention()
        history = (await lab.state()).history.messages
        monkeypatch.setattr(lab.store, "_expiry_enabled", False)
        with lab.store._connect() as db:
            notice = db.execute(
                "SELECT turn_id,parent_id,'retention' AS purpose FROM retention_expiry_notices"
            ).fetchone()
            assert not lab.store._push_delivery_ready(db, notice, clock.now())
        monkeypatch.setattr(lab.store, "_expiry_enabled", True)
        assert not await lab.touch.process_retention()
        assert (await lab.state()).history.messages == history
        assert (await lab.state()).history.quota.used_tokens == 0
    finally:
        await lab.close()


@pytest.mark.parametrize(
    "case", ["consent", "quiet", "stale", "expired", "far", "unpaid", "unknown", "missing"]
)
async def test_no_contact_for_ineligible_or_stale_evidence(tmp_path: Path, case: str) -> None:
    lab, clock = await setup(tmp_path / case)
    try:
        if case in {"consent", "quiet"}:
            old = await lab.store.contact_context(LAB_PARENT, clock.now())
            assert old
            assert lab.touch.proactive
            await lab.touch.proactive.register(
                old.model_copy(
                    update={
                        "event_id": uuid4(),
                        "revision": old.revision + 1,
                        **(
                            {"retention_chat_consent": False}
                            if case == "consent"
                            else {"timezone": "Pacific/Honolulu"}
                        ),
                    }
                )
            )
        await lab.prepare_expiry_scenario()
        assert isinstance(lab.store, SqliteRetentionExpiryStore)
        if case == "stale":
            clock.value += timedelta(seconds=181)
        elif case not in {"consent", "quiet"}:
            context = await lab._profiles.read(LAB_PARENT)
            assert context.tariff
            values: dict[str, dict[str, Any]] = {
                "expired": {"valid_until": clock.now() - timedelta(seconds=1)},
                "far": {"valid_until": clock.now() + timedelta(days=8)},
                "unpaid": {"is_paid": False},
                "unknown": {"is_paid": None},
            }
            clock.value += timedelta(seconds=1)
            tariff = context.tariff.model_copy(
                update={"collected_at": clock.now(), **values.get(case, {})}
            )
            await lab.store.observe_expiry_profile(
                LAB_PARENT,
                context.model_copy(
                    update={
                        "collected_at": clock.now(),
                        "tariff": None if case == "missing" else tariff,
                    }
                ),
                clock.now(),
            )
        assert not await lab.touch.process_retention()
        assert not (await lab.state()).history.messages
    finally:
        await lab.close()


async def test_safety_priority_and_opt_out_prevent_expiry_contact(tmp_path: Path) -> None:
    from tests.test_family_agent_queue import intent

    lab, clock = await setup(tmp_path / "priority")
    try:
        await lab.prepare_expiry_scenario()
        # A queued child question must retain the sole conversation slot.
        ctx = await lab._profiles.read(LAB_PARENT)
        await lab.store.enqueue(
            intent().model_copy(
                update={
                    "parent_id": LAB_PARENT,
                    "child_id": ctx.children[0].child_id,
                    "observed_at": clock.now(),
                    "expires_at": clock.now() + timedelta(hours=1),
                }
            ),
            clock.now(),
        )
        assert not await lab.touch.process_retention()
        stopped = await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT, request_id=uuid4(), message="не пиши первым"
            )
        )
        assert stopped.phase == "completed"
        assert not await lab.touch.process_retention()
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM retention_expiry_notices").fetchone()
    finally:
        await lab.close()


async def test_profile_auth_failure_closes_expiry_without_retry_or_reactivating_on_restart(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from app.mana_ai.application.retention_expiry import RetentionProfileSource

    lab, clock = await setup(tmp_path / "denied")
    try:
        await lab.prepare_expiry_scenario()
        assert isinstance(lab._profiles, RetentionProfileSource)
        calls = 0

        async def denied(parent: str) -> ParentChildContext:
            nonlocal calls
            calls += 1
            raise ParentChatError("child_source_auth_denied", 503)

        monkeypatch.setattr(lab._profiles._source, "read", denied)
        with pytest.raises(ParentChatError, match="child_source_auth_denied"):
            await lab.prepare_expiry_scenario()
        assert calls == 1 and not await lab.touch.process_retention()
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        await lab.prepare_expiry_scenario()
        assert not await lab.touch.process_retention()
        assert not (await lab.state()).history.messages
    finally:
        await lab.close()


@pytest.mark.parametrize("failure", ["timeout", "stale", "foreign"])
async def test_missing_profile_invalidates_older_eligible_fact(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    failure: str,
) -> None:
    lab, clock = await setup(tmp_path / "lost")
    try:
        await lab.prepare_expiry_scenario()
        clock.value += timedelta(seconds=1)

        from app.mana_ai.application.retention_expiry import RetentionProfileSource

        assert isinstance(lab._profiles, RetentionProfileSource)
        source = lab._profiles._source.read

        async def lost(parent: str) -> ParentChildContext:
            if failure == "timeout":
                raise TimeoutError("fictional unknown profile read")
            context = await source(parent)
            return context.model_copy(
                update={"parent_id": "123"}
                if failure == "foreign"
                else {"collected_at": clock.now() - timedelta(seconds=181)}
            )

        monkeypatch.setattr(lab._profiles._source, "read", lost)
        with pytest.raises(TimeoutError if failure == "timeout" else ParentChatError):
            await lab.prepare_expiry_scenario()
        assert not await lab.touch.process_retention()
    finally:
        await lab.close()


async def test_renewal_observation_suppresses_outdated_push_without_removing_chat(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "renewed")
    try:
        await lab.prepare_expiry_scenario()
        assert await lab.touch.process_retention()
        original = (await lab.state()).history.messages
        clock.value += timedelta(seconds=1)
        ctx = await lab._profiles.read(LAB_PARENT)
        assert ctx.tariff
        future = ctx.model_copy(
            update={
                "tariff": ctx.tariff.model_copy(
                    update={"valid_until": clock.now() + timedelta(days=30)}
                )
            }
        )
        assert isinstance(lab.store, SqliteRetentionExpiryStore)
        await lab.store.observe_expiry_profile(LAB_PARENT, future, clock.now())
        with lab.store._connect() as db:
            row = db.execute(
                "SELECT turn_id,parent_id,'retention' AS purpose FROM retention_expiry_notices"
            ).fetchone()
            assert not lab.store._push_delivery_ready(db, row, clock.now())
        assert (await lab.state()).history.messages == original
        assert not await lab.touch.process_retention()
    finally:
        await lab.close()


@pytest.mark.parametrize("daily_limit", [1, 20])
async def test_expiry_and_chat_gap_share_outreach_limit_and_parent_cooldown(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    daily_limit: int,
) -> None:
    from app.mana_ai.domain.client_retention import ClientRetentionPolicy

    monkeypatch.setattr(
        "app.services.mana_chat_lab.ClientRetentionPolicy",
        lambda: ClientRetentionPolicy(daily_outreach_limit=daily_limit),
    )
    lab, clock = await setup(tmp_path / f"daily-{daily_limit}")
    try:
        await lab.prepare_retention_scenario()
        await lab.prepare_expiry_scenario()
        assert await lab.touch.process_retention()
        assert isinstance(lab.store, SqliteRetentionExpiryStore)
        assert await lab.store.claim_retention(clock.now()) is None
        with lab.store._connect() as db:
            assert lab.store._retention_daily_count(db, clock.now()) == 1
            assert not db.execute("SELECT 1 FROM retention_intents").fetchone()
    finally:
        await lab.close()


async def test_capacity_closes_expiry_and_survives_restart_without_source_retry(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.mana_chat_lab.RetentionExpiryPolicy",
        lambda: RetentionExpiryPolicy(maximum_profiles=1),
    )
    lab, clock = await setup(tmp_path / "capacity")
    try:
        await lab.prepare_expiry_scenario()
        ctx = await lab._profiles.read(LAB_PARENT)
        assert isinstance(lab.store, SqliteRetentionExpiryStore)
        await lab.store.observe_expiry_profile(
            "123", ctx.model_copy(update={"parent_id": "123"}), clock.now()
        )
        assert not await lab.touch.process_retention()
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        assert not await lab.touch.process_retention()
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM retention_tariff_heads").fetchone()[0] == 1
            assert db.execute("SELECT circuit_open FROM retention_expiry_policy").fetchone()[0] == 1
    finally:
        await lab.close()


async def test_tampered_index_cannot_substitute_another_expiry(tmp_path: Path) -> None:
    lab, clock = await setup(tmp_path / "tampered")
    try:
        await lab.prepare_expiry_scenario()
        with lab.store._transaction() as db:
            db.execute(
                "UPDATE retention_tariff_heads SET valid_until=?",
                ((clock.now() + timedelta(days=1)).isoformat(),),
            )
        assert not await lab.touch.process_retention()
        with lab.store._connect() as db:
            assert db.execute("SELECT circuit_open FROM retention_expiry_policy").fetchone()[0] == 1
            assert not db.execute("SELECT 1 FROM retention_expiry_notices").fetchone()
    finally:
        await lab.close()


async def test_recent_communicated_urgent_notice_defers_account_reminder(tmp_path: Path) -> None:
    from app.mana_ai.application.parent_touch import ParentTouchService
    from app.mana_ai.domain.chat import ParentTariffContext
    from app.mana_ai.domain.proactive_parent import ParentContactContext
    from tests.test_parent_chat import NOW, Children
    from tests.test_parent_touch_evidence import TouchModel, completed_report

    lab, clock = await setup(tmp_path / "urgent")
    clock.value = NOW
    assert isinstance(lab.store, SqliteRetentionExpiryStore)
    assert lab.touch.proactive
    try:
        await lab.touch.proactive.register(
            ParentContactContext(
                parent_id="123",
                event_id=uuid4(),
                revision=1,
                observed_at=NOW,
                valid_until=NOW + timedelta(days=3),
                language="ru",
                timezone="Asia/Samarkand",
                safety_chat_consent=True,
                safety_push_consent=False,
                marketing_push_consent=False,
                retention_chat_consent=True,
            )
        )
        context = await Children().read("123")
        tariff = ParentTariffContext(
            collected_at=NOW,
            tariff_name=None,
            is_paid=True,
            valid_until=NOW + timedelta(days=2),
            payment_date=None,
            agent_trial_used=None,
        )
        await lab.store.observe_expiry_profile(
            "123", context.model_copy(update={"tariff": tariff}), NOW
        )
        await completed_report(lab.store)
        candidate = await lab.store.next_delivery(NOW)
        assert candidate
        touch = ParentTouchService(
            store=lab.store,
            children=Children(),
            model=TouchModel(),
            clock=clock.now,
            max_output_tokens=512,
            history_turn_limit=2,
        )
        delivered = await touch.deliver(candidate)
        assert delivered.delivered_notice and delivered.delivered_notice.kind == "urgent"
        assert not await lab.store.publish_expiry(clock.now())
        clock.value += timedelta(hours=24, seconds=1)
        current = context.model_copy(
            update={
                "collected_at": clock.now(),
                "tariff": tariff.model_copy(update={"collected_at": clock.now()}),
            }
        )
        await lab.store.observe_expiry_profile("123", current, clock.now())
        assert await lab.store.publish_expiry(clock.now())
    finally:
        await lab.close()


async def test_lost_local_publish_ack_observes_one_saved_message_without_redispatch(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from datetime import datetime

    lab, clock = await setup(tmp_path / "ack")
    assert isinstance(lab.store, SqliteRetentionExpiryStore)
    original = lab.store._publish_expiry

    def lose(now: datetime) -> bool:
        done = original(now)
        if done:
            raise OSError("fictional acknowledgement lost after atomic commit")
        return done

    try:
        await lab.prepare_expiry_scenario()
        monkeypatch.setattr(lab.store, "_publish_expiry", lose)
        with pytest.raises(OSError):
            await lab.touch.process_retention()
        assert not await lab.touch.process_retention()
        history = (await lab.state()).history
        assert len(history.messages) == 1 and history.quota.used_tokens == 0
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM retention_expiry_notices").fetchone()[0] == 1
    finally:
        await lab.close()


async def test_parent_reply_uses_actual_fixture_deadline_and_does_not_repeat_reminder(
    tmp_path: Path,
) -> None:
    from zoneinfo import ZoneInfo

    lab, clock = await setup(tmp_path / "reply")
    try:
        await lab.prepare_expiry_scenario()
        assert await lab.touch.process_retention()
        context = await lab._profiles.read(LAB_PARENT)
        assert context.tariff and context.tariff.valid_until
        expected = context.tariff.valid_until.astimezone(ZoneInfo("Asia/Samarkand")).strftime(
            "%Y-%m-%d %H:%M"
        )
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Какой у меня тариф?"
        )
        await lab.touch.admit_message(request)
        reviewed = await lab.safety.process_one()
        assert reviewed and reviewed.status == "completed"
        assert await lab.touch.process_reviewed_message()
        state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert state.phase == "completed" and state.response and expected in state.response.answer
        assert not await lab.touch.process_retention()
        assert (await lab.touch.admit_message(request)).phase == "completed"
        assert len((await lab.state()).history.messages) == 3
    finally:
        await lab.close()
