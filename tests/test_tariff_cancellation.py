"""A UI cancellation belongs to one parent/request and never replays inference."""

import asyncio
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.conversion_catalog import ConversionCatalogObservation
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.tariff_handoff_store import (
    SqliteClosedTariffHandoffStore,
    SqliteTariffHandoffStore,
)
from scripts.mana_chat_lab import create_app
from tests.test_lab_chat_actions import BASE, session
from tests.test_tariff_handoff import setup
from tests.test_trial_action_cards import snapshot

PATH = "/api/v1/mana-ai/parent-touch/messages"


async def waiting(lab: ChatLab) -> ParentTouchMessageRequest:
    request = ParentTouchMessageRequest(
        parent_id=LAB_PARENT, request_id=uuid4(), message="Тариф на 90 дней UZS"
    )
    admitted = await lab.touch.admit_message(request)
    assert not admitted.can_cancel_tariff
    assert await lab.touch.process_reviewed_message()
    state = await lab.touch.message_state(LAB_PARENT, request.request_id)
    assert state.can_cancel_tariff and state.phase == "responding"
    return request


def cancel(target: UUID, **changes: object) -> ParentTouchMessageRequest:
    return ParentTouchMessageRequest.model_validate(
        {
            "parent_id": LAB_PARENT,
            "request_id": str(uuid4()),
            "message": "отмени подбор",
            "cancel_tariff_request_id": str(target),
        }
        | changes
    )


@pytest.mark.parametrize("binding", ["self", "question", "confirmation", "ordinary_text"])
def test_cancel_schema_rejects_ambiguous_controls(binding: str) -> None:
    request = cancel(uuid4())
    updates: dict[str, dict[str, object]] = {
        "self": {"cancel_tariff_request_id": request.request_id},
        "question": {"reply_to_question_id": uuid4()},
        "confirmation": {"reply_to_confirmation_id": uuid4()},
        "ordinary_text": {"message": "Как дела?"},
    }
    with pytest.raises(ValidationError):
        ParentTouchMessageRequest.model_validate(request.model_dump() | updates[binding])


async def test_bound_control_has_atomic_audit_zero_extra_cost_and_exact_http_replay(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "http")
    options = lab.options
    await lab.close()
    app = create_app(options=options)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        lab = app.state.chat_lab
        target = await waiting(lab)
        read = await client.get(f"{PATH}/{target.request_id}?parent_id={LAB_PARENT}")
        assert read.status_code == 200 and read.json()["can_cancel_tariff"] is True
        request = cancel(target.request_id)
        body = request.model_dump(mode="json")
        result = await client.post(PATH, headers=headers, json=body)
        assert result.status_code == 202 and result.json()["phase"] == "completed"
        assert result.json()["response"]["usage"] == {"input_tokens": 0, "output_tokens": 0}
        assert "can_cancel_tariff" not in result.json()
        assert (await client.post(PATH, headers=headers, json=body)).json() == result.json()
        assert (
            await client.get(f"{PATH}/{request.request_id}?parent_id={LAB_PARENT}")
        ).json() == result.json()
        state = await lab.state()
        assert state.history.quota.used_tokens == 150 and state.history.quota.reserved_tokens == 0
        assert len(state.history.messages) == 3
        assert state.history.messages[-2].content == "отмени подбор"
        assert not await lab.touch.process_upsell() and lab.catalog.calls == 0
        with lab.store._connect() as db:
            row = db.execute("SELECT * FROM tariff_reply_cancellations").fetchone()
            assert row["target_request_id"] == str(target.request_id)
            assert row["turn_id"] == result.json()["turn_id"]
            assert db.execute("SELECT COUNT(*) FROM tariff_reply_cancellations").fetchone()[0] == 1


@pytest.mark.parametrize("wrong", ["parent", "target"])
async def test_foreign_or_wrong_target_cannot_cancel_a_waiting_enquiry(
    tmp_path: Path, wrong: str
) -> None:
    lab, _ = await setup(tmp_path / wrong)
    try:
        target = await waiting(lab)
        request = cancel(
            target.request_id if wrong == "parent" else uuid4(),
            **({"parent_id": "900002"} if wrong == "parent" else {}),
        )
        before = snapshot(lab.store)
        with pytest.raises(ParentChatError, match="upsell_reply_not_waiting"):
            await lab.touch.admit_message(request)
        assert snapshot(lab.store) == before
        assert (await lab.touch.message_state(LAB_PARENT, target.request_id)).can_cancel_tariff
        assert lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_late_old_target_cannot_cancel_a_new_tariff_request(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "race")
    try:
        old = await waiting(lab)
        assert await lab.touch.process_upsell()
        new = await waiting(lab)
        before = snapshot(lab.store)
        with pytest.raises(ParentChatError, match="upsell_reply_not_waiting"):
            await lab.touch.admit_message(cancel(old.request_id))
        assert snapshot(lab.store) == before
        assert (await lab.touch.message_state(LAB_PARENT, new.request_id)).can_cancel_tariff
        assert lab.catalog.calls == 1
    finally:
        await lab.close()


async def test_same_control_nonce_cannot_change_target_or_become_ordinary_text(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "nonce")
    try:
        target = await waiting(lab)
        request = cancel(target.request_id)
        assert (await lab.touch.admit_message(request)).phase == "completed"
        before = snapshot(lab.store)
        for changed in (
            request.model_copy(update={"cancel_tariff_request_id": uuid4()}),
            request.model_copy(update={"cancel_tariff_request_id": None}),
        ):
            with pytest.raises(ParentChatError, match="request_id_conflict"):
                await lab.touch.admit_message(changed)
        assert snapshot(lab.store) == before
    finally:
        await lab.close()


@pytest.mark.parametrize("lost", [False, True])
async def test_targeted_inflight_cancel_retains_known_or_unknown_catalogue_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lost: bool
) -> None:
    lab, _ = await setup(tmp_path / str(lost))
    entered, release = asyncio.Event(), asyncio.Event()
    original = lab.catalog.read

    async def blocked() -> ConversionCatalogObservation:
        entered.set()
        await release.wait()
        if lost:
            raise TimeoutError("Synthetic submitted catalogue receipt lost")
        return await original()

    monkeypatch.setattr(lab.catalog, "read", blocked)
    try:
        target = await waiting(lab)
        task = asyncio.create_task(lab.touch.process_upsell())
        await asyncio.wait_for(entered.wait(), 3)
        result = await lab.touch.admit_message(cancel(target.request_id))
        assert result.phase == "completed"
        release.set()
        assert await task and not await lab.touch.process_upsell()
        history = (await lab.state()).history
        assert len(history.messages) == 3 and history.quota.used_tokens == 150
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM upsell_catalog_reads").fetchone()[0] == (
                "unknown" if lost else "recorded"
            )
    finally:
        release.set()
        await lab.close()


async def test_atomic_publication_failure_leaves_original_work_and_ledger_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "atomic")
    try:
        target = await waiting(lab)
        before = snapshot(lab.store)

        def lost(*args: object, **kwargs: object) -> None:
            raise sqlite3.OperationalError("Synthetic failed control publication")

        monkeypatch.setattr(lab.store, "_host_reply", lost)
        with pytest.raises(sqlite3.OperationalError):
            await lab.touch.admit_message(cancel(target.request_id))
        assert snapshot(lab.store) == before and lab.catalog.calls == 0
    finally:
        await lab.close()


async def test_concurrent_control_replay_survives_disable_closed_reader_and_restart(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "restart")
    try:
        target = await waiting(lab)
        request = cancel(target.request_id)
        results = await asyncio.gather(*(lab.touch.admit_message(request) for _ in range(4)))
        assert all(result == results[0] for result in results)
        assert isinstance(lab.store, SqliteTariffHandoffStore)
        lab.store._tariff_handoff_enabled = False
        lab.store._inline_enabled = False
        assert await lab.touch.admit_message(request) == results[0]
        before = snapshot(lab.store)
        closed = SqliteClosedTariffHandoffStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        observed = await closed.reviewed_message(LAB_PARENT, request.request_id, clock.now())
        assert observed.phase == "completed" and observed.turn.result is not None
        assert results[0].response and observed.turn.result.answer == results[0].response.answer
        assert snapshot(lab.store) == before
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        assert snapshot(lab.store) == before
        assert await lab.touch.admit_message(request) == results[0]
        assert not await lab.touch.process_reviewed_message()
        assert not await lab.touch.process_upsell() and lab.catalog.calls == 0
        assert (await lab.store.quota(LAB_PARENT, clock.now())).used_tokens == 150
        assert snapshot(lab.store) == before
    finally:
        await lab.close()


async def test_missing_owning_runtime_never_routes_a_control_into_model_or_reminders(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "unavailable")
    try:
        lab.touch.upsell = None
        before = snapshot(lab.store)
        with pytest.raises(ParentChatError, match="targeted_tariff_cancellation_unavailable"):
            await lab.touch.admit_message(cancel(uuid4()))
        assert snapshot(lab.store) == before
        assert (await lab.state()).history.quota.used_tokens == 0
    finally:
        await lab.close()


async def test_explicit_current_closed_reader_keeps_pre_cancel_v33_without_migration(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "prior-closed")
    try:
        # Exact prior shape projection; actual prior-image acceptance is separate.
        with lab.store._transaction() as db:
            db.execute("DROP TABLE tariff_reply_cancellations")
            db.execute("PRAGMA user_version=33")
        before = snapshot(lab.store)
        await SqliteClosedTariffHandoffStore(
            lab.store._path,
            storage_version=33,
            history_only=True,
            daily_limit=2000,
            timezone="Asia/Samarkand",
        ).initialize()
        assert snapshot(lab.store) == before
        with lab.store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 33
    finally:
        await lab.close()
