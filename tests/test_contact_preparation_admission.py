"""Durable bounded fictional admission; no provider, model or production calls."""

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.retention.preparation_errors import ContactPreparationError
from app.mana_operation_ai.domain.chat import TopicCreate
from app.mana_operation_ai.domain.contact_admission import ContactPreparationLimits
from app.mana_operation_ai.domain.enums import AgentStatus, UserRole
from app.mana_operation_ai.infrastructure.persistence.models import (
    ContactPreparationGateRow,
    ContactPreparationRow,
    RetentionContactRow,
)
from app.mana_operation_ai.infrastructure.persistence.repository import (
    SqlAlchemyOperationRepository,
)
from tests.test_operation_api import headers
from tests.test_retention_contact import ADMIN, request
from tests.test_workspace_retention_contacts import BASE, send, setup

pytest_plugins = ["tests.test_retention_contact"]


@pytest.mark.parametrize("kind", ["per_turn", "per_owner_hour", "per_day"])
async def test_caps_and_exact_replay_before_any_new_target_read(system: Any, kind: str) -> None:
    _, chats, topic, _, executor, _, service = system
    service._preparation_limits = ContactPreparationLimits.model_validate({kind: 1})
    original = request()
    saved = await service.prepare(ADMIN, topic.topic_id, original)
    owner = "bob" if kind == "per_day" else "alice"
    next_topic = (
        topic
        if kind == "per_turn"
        else await chats.create(
            owner,
            TopicCreate(
                agent_id="retention-agent", product="mana", title="Another fictional topic"
            ),
        )
    )
    actor = ActorContext(actor_id=owner, role=UserRole.ADMIN)
    with pytest.raises(ContactPreparationError) as failure:
        await service.prepare(actor, next_topic.topic_id, request())
    assert failure.value.code == "contact_preparation_limit"
    assert executor.target_reads == 1
    assert await service.prepare(ADMIN, topic.topic_id, original) == saved
    assert executor.target_reads == 1


async def test_pending_reservation_blocks_same_new_nonce_and_other_owner_after_restart(
    system: Any,
) -> None:
    db, chats, topic, clock, executor, store, service = system
    executor.target = AsyncMock(side_effect=TimeoutError("Synthetic lost target response"))
    original = request()
    with pytest.raises(ContactPreparationError) as failure:
        await service.prepare(ADMIN, topic.topic_id, original)
    assert failure.value.code == "contact_preparation_pending"
    # A reservation has no expiry. A later clock and a fresh store/service instance
    # do not turn an unknown target read into permission for another attempt.
    clock.current += timedelta(days=2)
    from app.mana_operation_ai.infrastructure.persistence.retention_contact import (
        SqlAlchemyRetentionContacts,
    )

    service._store = SqlAlchemyRetentionContacts(db)
    other = await chats.create(
        "bob", TopicCreate(agent_id="retention-agent", product="mana", title="Other owner")
    )
    for actor, destination, req in [
        (ADMIN, topic, original),
        (ADMIN, topic, request()),
        (ActorContext(actor_id="bob", role=UserRole.ADMIN), other, request()),
    ]:
        with pytest.raises(ContactPreparationError, match="Подготовка"):
            await service.prepare(actor, destination.topic_id, req)
    assert executor.target.await_count == 1
    assert await store.preparation_request_pending("alice", str(original.request_id))
    async with db.session_factory() as session:
        assert len((await session.scalars(select(ContactPreparationRow))).all()) == 1
        assert (await session.scalars(select(RetentionContactRow))).all() == []


@pytest.mark.parametrize(
    "stop",
    [
        "global_kill_switch",
        "agent_kill_switch:retention-agent",
        "capability_kill_switch:retention-agent:retention.contact.sandbox",
        "paused",
        "disabled",
    ],
)
async def test_existing_unknown_preparation_never_becomes_a_closed_refusal_on_stop(
    system: Any, stop: str
) -> None:
    db, _, topic, clock, executor, store, service = system
    executor.target = AsyncMock(side_effect=TimeoutError("Synthetic lost target response"))
    original = request()
    with pytest.raises(ContactPreparationError) as first:
        await service.prepare(ADMIN, topic.topic_id, original)
    assert first.value.code == "contact_preparation_pending"
    repository = SqlAlchemyOperationRepository(db)
    if stop in {"paused", "disabled"}:
        await repository.set_agent_status("retention-agent", AgentStatus(stop))
    else:
        await repository.set_control(
            key=stop, enabled=True, updated_at=clock.now(), updated_by="admin"
        )
    # A stop prevents new work; it cannot prove that this exact prior target
    # lookup never started or permit the browser to label its receipt refused.
    with pytest.raises(ContactPreparationError) as stopped:
        await service.prepare(ADMIN, topic.topic_id, original)
    assert stopped.value.code == "contact_preparation_pending"
    assert await store.preparation_request_pending("alice", str(original.request_id))
    assert executor.target.await_count == 1


async def test_concurrent_different_nonces_and_cancel_never_reissue_target(system: Any) -> None:
    _, _, topic, _, executor, store, service = system
    entered = asyncio.Event()
    original_target = executor.target

    async def slow_target(account: str) -> Any:
        entered.set()
        await asyncio.Event().wait()
        return await original_target(account)

    executor.target = AsyncMock(side_effect=slow_target)
    req = request()
    task = asyncio.create_task(service.prepare(ADMIN, topic.topic_id, req))
    await asyncio.wait_for(entered.wait(), timeout=5)
    with pytest.raises(ContactPreparationError) as failure:
        await service.prepare(ADMIN, topic.topic_id, request())
    assert failure.value.code == "contact_preparation_pending"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ContactPreparationError):
        await service.prepare(ADMIN, topic.topic_id, req)
    assert executor.target.await_count == 1
    assert await store.preparation_request_pending("alice", str(req.request_id))


@pytest.mark.parametrize("status", [AgentStatus.PAUSED, AgentStatus.DISABLED])
async def test_owning_status_blocks_new_preparation_but_not_sql_replay(
    system: Any, status: AgentStatus
) -> None:
    db, _, topic, _, executor, _, service = system
    req = request()
    action = await service.prepare(ADMIN, topic.topic_id, req)
    await SqlAlchemyOperationRepository(db).set_agent_status("retention-agent", status)
    with pytest.raises(ContactPreparationError) as failure:
        await service.prepare(ADMIN, topic.topic_id, request())
    assert failure.value.code == "contact_preparation_stopped"
    assert await service.prepare(ADMIN, topic.topic_id, req) == action
    assert executor.target_reads == 1


async def test_failed_result_transaction_keeps_pending_claim(
    system: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, _, topic, _, executor, store, service = system

    async def broken_link(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Synthetic SQL result failure")

    monkeypatch.setattr(store._preparations, "complete", broken_link)
    req = request()
    with pytest.raises(RuntimeError, match="Synthetic"):
        await service.prepare(ADMIN, topic.topic_id, req)
    assert await store.by_request("alice", str(req.request_id)) is None
    assert await store.preparation_request_pending("alice", str(req.request_id))
    with pytest.raises(ContactPreparationError):
        await service.prepare(ADMIN, topic.topic_id, req)
    assert executor.target_reads == 1
    async with db.session_factory() as session:
        assert (await session.scalars(select(RetentionContactRow))).all() == []


async def test_legacy_preparations_count_without_rewriting_old_json(system: Any) -> None:
    db, _, topic, _, executor, _, service = system
    saved = await service.prepare(ADMIN, topic.topic_id, request())
    async with db.session_factory() as session, session.begin():
        await session.execute(delete(ContactPreparationRow))
        row = await session.get(RetentionContactRow, saved.action_id)
        assert row is not None
        historical = dict(row.payload)
    service._preparation_limits = ContactPreparationLimits(per_turn=1)
    with pytest.raises(ContactPreparationError) as failure:
        await service.prepare(ADMIN, topic.topic_id, request())
    assert failure.value.code == "contact_preparation_limit"
    assert executor.target_reads == 1
    async with db.session_factory() as session:
        row = await session.get(RetentionContactRow, saved.action_id)
        assert row is not None and row.payload == historical
        gate = await session.get(ContactPreparationGateRow, "retention.contact.sandbox")
        assert gate is not None and gate.limits["per_turn"] == 1
    # Refusal committed the tightened ceiling; a stale process cannot loosen it.
    service._preparation_limits = ContactPreparationLimits()
    with pytest.raises(ContactPreparationError):
        await service.prepare(ADMIN, topic.topic_id, request())
    assert executor.target_reads == 1


@pytest.mark.parametrize("at", [None, "2026-09-29T12:00:00", "2099-01-01T00:00:00Z"])
async def test_invalid_legacy_dates_fail_closed_before_target(system: Any, at: str | None) -> None:
    db, _, topic, _, executor, _, service = system
    saved = await service.prepare(ADMIN, topic.topic_id, request())
    async with db.session_factory() as session, session.begin():
        await session.execute(delete(ContactPreparationRow))
        row = await session.get(RetentionContactRow, saved.action_id)
        assert row is not None
        row.payload = {**row.payload, "prepared_at": at}
    with pytest.raises(ContactPreparationError) as failure:
        await service.prepare(ADMIN, topic.topic_id, request())
    assert failure.value.code == "contact_preparation_history_unavailable"
    assert executor.target_reads == 1


async def test_stop_observed_after_claim_prevents_target_without_freeing_claim(
    system: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, _, topic, _, executor, store, service = system
    original = store.admit_preparation

    async def pause_after_admission(*args: Any, **kwargs: Any) -> Any:
        claim = await original(*args, **kwargs)
        await SqlAlchemyOperationRepository(db).set_agent_status(
            "retention-agent", AgentStatus.PAUSED
        )
        return claim

    monkeypatch.setattr(store, "admit_preparation", pause_after_admission)
    req = request()
    with pytest.raises(ContactPreparationError) as failure:
        await service.prepare(ADMIN, topic.topic_id, req)
    assert failure.value.code == "contact_preparation_pending"
    assert executor.target_reads == 0
    assert await store.preparation_request_pending("alice", str(req.request_id))


async def test_http_closed_refusal_same_request_readmission_and_owner_only_observation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = setup(monkeypatch, tmp_path / "admission-http.db")
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        topic, turn, _ = await send(app)
        url = f"{BASE}/topics/{topic.topic_id}/messages/{turn.turn_id}/retention-contacts"
        h = headers("alice", "admin")
        bridge = app.state.operation_workspace_retention_contacts
        controls = bridge._contacts._controls
        nonce = str(uuid4())
        req = {
            "request_id": nonce,
            "confirmed": True,
            "recipient": "sample_uz",
            "template": "onboarding_help",
        }
        await controls.set_agent_status("retention-agent", AgentStatus.PAUSED)
        response = await client.post(url + "/prepare", headers=h, json=req)
        assert response.status_code == 423
        assert response.json()["detail"]["code"] == "contact_preparation_stopped"
        assert (await client.get(url, headers=h)).json()["preparation_availability"][
            "state"
        ] == "stopped"
        observation = f"{url}/preparation?request_id={nonce}"
        assert (await client.get(observation, headers=h)).json()["state"] == "absent"
        assert sum(e.target_reads for e in bridge._contacts._executor.executors.values()) == 0
        await controls.set_agent_status("retention-agent", AgentStatus.ENABLED)
        saved = await client.post(url + "/prepare", headers=h, json=req)
        assert saved.status_code == 200, saved.text
        seen = (await client.get(observation, headers=h)).json()
        assert seen["request_id"] == nonce and seen["state"] == "recorded"
        assert seen["action"] == saved.json()
        assert (await client.post(url + "/prepare", headers=h, json=req)).json() == saved.json()
        assert (await client.get(observation, headers=headers("bob", "admin"))).status_code == 404
        assert sum(e.target_reads for e in bridge._contacts._executor.executors.values()) == 1


async def test_history_overflow_and_changed_pending_request_do_not_read(system: Any) -> None:
    db, _, topic, _, executor, _, service = system
    for _ in range(2):
        await service.prepare(ADMIN, topic.topic_id, request())
    async with db.session_factory() as session, session.begin():
        await session.execute(delete(ContactPreparationRow))
    service._preparation_limits = ContactPreparationLimits(legacy_scan_limit=1)
    with pytest.raises(ContactPreparationError) as failure:
        await service.prepare(ADMIN, topic.topic_id, request())
    assert failure.value.code == "contact_preparation_history_unavailable"
    assert executor.target_reads == 2
