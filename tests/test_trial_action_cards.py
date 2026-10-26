"""New trial offers use explicit buttons and the existing owning grant lifecycle."""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.parent_touch_offers import render_parent_offer
from app.mana_ai.domain.chat_actions import (
    ChatActionCard,
    ChatActionClaim,
    ChatActionClick,
    TrialChatActionResult,
)
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.client_retention import ClientRetentionPolicy
from app.mana_ai.domain.client_upsell import ClientUpsellPolicy
from app.mana_ai.domain.conversion import ConversionPolicy, ConversionSnapshot
from app.mana_ai.domain.conversion_accounts import ConversionAccountReadLimits
from app.mana_ai.domain.conversion_grants import TrialGrantResult
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.parent_reminders import ReminderPolicy
from app.mana_ai.domain.proactive_parent import ParentContactContext
from app.mana_ai.domain.retention_expiry import RetentionExpiryPolicy
from app.services.lab_chat_action_store import SqliteLabChatActionStore
from app.services.lab_trial_action_store import (
    SqliteClosedLabTrialActionStore,
    SqliteLabTrialActionStore,
)
from app.services.location_safety_store import SqliteClosedLocationSafetyStore
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from scripts.mana_chat_lab import create_app
from tests.test_lab_chat_actions import BASE, PATH, Clock, click, options, session


def snapshot(store: SqliteLabChatActionStore) -> dict[str, list[tuple[object, ...]]]:
    with store._connect() as db:
        return {
            table[0]: sorted(
                [tuple(row) for row in db.execute('SELECT * FROM "' + table[0] + '"')], key=repr
            )
            for table in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


async def start(path: Path) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(replace(options(path, clock), trial_action_cards=True))
    await lab.start()
    return lab, clock


async def publish(lab: ChatLab, *, language: str = "ru") -> ChatActionCard:
    scenario = next(item for item in lab.bootstrap().scenarios if item.key == "conversion")
    assert lab.touch.conversion
    result = await lab.touch.conversion.observe(
        ConversionSnapshot.model_validate(scenario.body | {"language": language})
    )
    assert result.proposal
    assert await lab.store.publish_conversion(lab.options.clock.now(), render_parent_offer)
    assert lab.action_cards
    page = await lab.action_cards.list(LAB_PARENT, after=0, limit=20)
    assert len(page.cards) == 1
    return page.cards[0]


async def test_button_claims_the_existing_grant_without_a_fabricated_user_turn(
    tmp_path: Path,
) -> None:
    directory, clock = tmp_path / "lab", Clock()
    configuration = replace(options(directory, clock), trial_action_cards=True)
    app = create_app(options=configuration)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        lab = app.state.chat_lab
        assert not (await lab.state()).history.messages
        card = await publish(lab)
        assert card.action_type == "free_trial_days" and card.trial is not None
        assert card.trial.grant_days == 1
        state = (await client.get("/lab/state")).json()
        assert len(state["history"]["messages"]) == 1
        assert state["history"]["messages"][0]["turn_id"] == card.turn_id
        assert "напишите" not in state["history"]["messages"][0]["content"]
        payload = click(card.model_dump(mode="json"))
        url = PATH + f"/{card.card_id}/click"
        results = await asyncio.gather(
            *(client.post(url, headers=headers, json=payload) for _ in range(6))
        )
        assert all(item.status_code == 200 for item in results), [item.text for item in results]
        result = (await client.get(PATH + f"/{card.card_id}?parent_id={LAB_PARENT}")).json()
        assert result["status"] == "completed"
        assert result["result"]["outcome"] == "trial_granted"
        assert result["result"]["grant"]["days"] == 1 and lab.trial_gateway.calls == 1
        assert await lab.store.publish_trial_result(clock.now())
        assert not await lab.store.publish_trial_result(clock.now())
        state = (await client.get("/lab/state")).json()
        assert len(state["history"]["messages"]) == 2
        assert all(message["role"] == "assistant" for message in state["history"]["messages"])
        assert state["history"]["quota"]["used_tokens"] == 0
        assert state["safety_budget"]["server_used_tokens"] == 0
        assert (await client.post(url, headers=headers, json=payload)).json() == result
        with lab.store._connect() as db:
            assert db.execute("SELECT count(*) FROM trial_period_facts").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM conversion_trial_grants").fetchone()[0] == 1
            assert (
                db.execute("SELECT count(*) FROM parent_chat_turns WHERE message!=''").fetchone()[0]
                == 0
            )
            acceptance = json.loads(
                db.execute("SELECT acceptance FROM conversion_trial_grants").fetchone()[0]
            )
            assert acceptance["confirmation_card_id"] == str(card.card_id)
            assert "reply_turn_id" not in acceptance
        history = state["history"]["messages"]
    app = create_app(options=configuration)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        assert (await client.post(url, headers=headers, json=payload)).json() == result
        assert app.state.chat_lab.trial_gateway.calls == 0
        assert (await client.get("/lab/state")).json()["history"]["messages"] == history


async def test_cancel_does_not_claim_or_grant_and_custom_payload_cannot_create_trial(
    tmp_path: Path,
) -> None:
    lab, _ = await start(tmp_path / "lab")
    try:
        card = await publish(lab)
        assert lab.action_cards and lab.trial_gateway
        result = await lab.action_cards.click(
            card.card_id,
            ChatActionClick.model_validate(click(card.model_dump(mode="json"), "cancel")),
        )
        assert result.status == "cancelled" and lab.trial_gateway.calls == 0
        assert isinstance(lab.store, SqliteLabTrialActionStore)
        with lab.store._connect() as db:
            assert db.execute("SELECT count(*) FROM conversion_trial_grants").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM trial_button_dispatches").fetchone()[0] == 0
        with pytest.raises(ParentChatError, match="action_card_already_decided"):
            await lab.action_cards.click(
                card.card_id, ChatActionClick.model_validate(click(card.model_dump(mode="json")))
            )
    finally:
        await lab.close()


async def test_explicit_offer_opt_out_cancels_only_an_unclaimed_card(tmp_path: Path) -> None:
    lab, _ = await start(tmp_path / "opt-out")
    try:
        card = await publish(lab)
        assert lab.action_cards and lab.trial_gateway
        state = await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT, request_id=uuid4(), message="не присылайте предложения"
            )
        )
        assert state.phase in {"awaiting_review", "responding"}
        assert (await lab.action_cards.read(LAB_PARENT, card.card_id)).status == "cancelled"
        assert lab.trial_gateway.calls == 0
        with lab.store._connect() as db:
            assert db.execute("SELECT count(*) FROM conversion_opt_outs").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM trial_button_dispatches").fetchone()[0] == 0
    finally:
        await lab.close()


@pytest.mark.parametrize("change", ["expired", "language", "corrupt_hash"])
async def test_changed_confirmation_fails_without_any_grant(change: str, tmp_path: Path) -> None:
    lab, clock = await start(tmp_path / change)
    try:
        card = await publish(lab)
        assert lab.action_cards and lab.trial_gateway
        if change == "expired":
            clock.value += timedelta(seconds=901)
        elif change == "language":
            contact = await lab.store.contact_context(LAB_PARENT, clock.now())
            assert contact and lab.touch.proactive
            await lab.touch.proactive.register(
                contact.model_copy(
                    update={
                        "event_id": uuid4(),
                        "revision": contact.revision + 1,
                        "language": "uz-Latn",
                    }
                )
            )
        else:
            with lab.store._transaction() as db:
                db.execute(
                    "UPDATE lab_action_cards SET definition_hash=? WHERE card_id=?",
                    ("0" * 64, str(card.card_id)),
                )
        with pytest.raises(ParentChatError):
            await lab.action_cards.click(
                card.card_id, ChatActionClick.model_validate(click(card.model_dump(mode="json")))
            )
        assert lab.trial_gateway.calls == 0
        with lab.store._connect() as db:
            assert db.execute("SELECT count(*) FROM conversion_trial_grants").fetchone()[0] == 0
    finally:
        await lab.close()


async def test_v24_upgrade_retains_demo_claims_without_capturing_historical_offers(
    tmp_path: Path,
) -> None:
    clock, directory = Clock(), tmp_path / "upgrade"
    lab = ChatLab(options(directory, clock))
    await lab.start()
    try:
        assert isinstance(lab.store, SqliteLabChatActionStore) and lab.action_cards
        from app.mana_ai.domain.chat_actions import ChatActionCreate
        from tests.test_lab_chat_actions import definition

        card = await lab.action_cards.create(ChatActionCreate.model_validate(definition()))
        claim = await lab.store.claim_card(
            card.card_id,
            ChatActionClick.model_validate(click(card.model_dump(mode="json"))),
            clock.now(),
        )
        assert isinstance(claim, ChatActionClaim)
        before = snapshot(lab.store)
        offers = tuple(lab.store._conversion_offers.values())
    finally:
        await lab.close()
    new = SqliteLabTrialActionStore(
        directory / "family.sqlite3",
        trial_cards_enabled=True,
        native_model="lab-simulated-not-billed",
        manager_binding="fictional-manager-v1",
        manager_model="lab-simulated-not-billed",
        manager_enabled=True,
        expiry_policy=RetentionExpiryPolicy(),
        profile_binding="fictional-mana-profile-v1",
        upsell_policy=ClientUpsellPolicy(),
        catalog_binding="fictional-mana-catalog-v1",
        retention_policy=ClientRetentionPolicy(),
        reminder_policy=ReminderPolicy(),
        limits=ChildSafetyLimits(
            server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=2000
        ),
        daily_limit=2000,
        timezone="Asia/Samarkand",
        conversion_policy=ConversionPolicy(),
        conversion_offers=offers,
        account_read_limits=ConversionAccountReadLimits(),
    )
    await new.initialize()
    after = snapshot(new)
    assert {table: after[table] for table in before} == before
    assert after["trial_card_bindings"] == after["trial_button_dispatches"] == []
    assert (await new.action_card(LAB_PARENT, card.card_id, clock.now())).status == "executing"
    closed = SqliteClosedLabTrialActionStore(
        directory / "family.sqlite3", daily_limit=2000, timezone="Asia/Samarkand"
    )
    await closed.initialize()
    history = await closed.history(LAB_PARENT, before=None, limit=20, now=clock.now())
    assert len(history.messages) == 1
    assert snapshot(new) == after
    with pytest.raises(RuntimeError, match="dedicated database"):
        await SqliteClosedLocationSafetyStore(
            directory / "family.sqlite3", daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
    assert snapshot(new) == after


async def test_dedicated_factory_is_fictional_and_starts_without_a_seeded_grant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import mana_chat_lab as runtime
    from scripts import mana_chat_lab as script

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("The trial-button lab must not initialize live providers")

    monkeypatch.setattr(runtime, "get_settings", forbidden)
    original = script.create_app

    def isolated(*, options: runtime.LabOptions | None = None) -> FastAPI:
        assert options and options.trial_action_cards and options.action_cards
        assert not options.real_model and not options.trial_periods
        return original(options=replace(options, directory=tmp_path / "factory"))

    monkeypatch.setattr(script, "create_app", isolated)
    app = script.create_trial_action_cards_app()
    async with app.router.lifespan_context(app):
        lab = app.state.chat_lab
        assert lab.bootstrap().trial_action_cards_enabled
        assert lab.bootstrap().seeded_history is None
        assert not (await lab.state()).history.messages
        assert lab.trial_gateway.calls == 0
        assert isinstance(lab.store, SqliteLabTrialActionStore)
        with lab.store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 25
            assert db.execute("SELECT count(*) FROM conversion_trial_grants").fetchone()[0] == 0


async def test_disabled_or_historical_proposal_never_acquires_a_card_on_replay(
    tmp_path: Path,
) -> None:
    lab, clock = await start(tmp_path / "capture")
    try:
        assert isinstance(lab.store, SqliteLabTrialActionStore)
        assert lab.touch.conversion and lab.action_cards
        lab.store._trial_cards_enabled = False
        event = next(item for item in lab.bootstrap().scenarios if item.key == "conversion")
        payload = ConversionSnapshot.model_validate(event.body)
        admission = await lab.touch.conversion.observe(payload)
        assert admission.proposal
        lab.store._trial_cards_enabled = True
        assert await lab.touch.conversion.observe(payload) == admission
        assert await lab.store.publish_conversion(clock.now(), render_parent_offer)
        assert not (await lab.action_cards.list(LAB_PARENT, after=0, limit=20)).cards
        with lab.store._connect() as db:
            assert db.execute("SELECT enabled FROM trial_card_admissions").fetchone()[0] == 0
        # An older reader never had an admission row. Absence stays absence.
        with lab.store._transaction() as db:
            db.execute("DELETE FROM trial_card_admissions")
        assert await lab.touch.conversion.observe(payload) == admission
        with lab.store._connect() as db:
            assert db.execute("SELECT count(*) FROM trial_card_admissions").fetchone()[0] == 0
        assert not (await lab.action_cards.list(LAB_PARENT, after=0, limit=20)).cards
    finally:
        await lab.close()


async def test_ready_claim_survives_restart_and_midnight_without_redispatch(tmp_path: Path) -> None:
    directory = tmp_path / "ready"
    lab, clock = await start(directory)
    try:
        card = await publish(lab)
        assert isinstance(lab.store, SqliteLabTrialActionStore) and lab.action_cards
        request = ChatActionClick.model_validate(click(card.model_dump(mode="json")))
        claim = await lab.store.claim_card(card.card_id, request, clock.now())
        assert isinstance(claim, ChatActionClaim)
        assert (await lab.store.trial_grant(LAB_PARENT)).status == "submitting"
    finally:
        await lab.close()
    clock.value += timedelta(days=1)
    restarted = ChatLab(replace(options(directory, clock), trial_action_cards=True))
    await restarted.start()
    try:
        assert restarted.action_cards and restarted.trial_gateway
        assert (await restarted.action_cards.read(LAB_PARENT, card.card_id)).status == "executing"
        assert (
            await restarted.action_cards.click(
                card.card_id, request.model_copy(update={"request_id": uuid4()})
            )
        ).status == "executing"
        assert restarted.trial_gateway.calls == 0
        with restarted.store._connect() as db:
            assert db.execute("SELECT phase FROM trial_button_dispatches").fetchone()[0] == "ready"
            assert db.execute("SELECT count(*) FROM conversion_trial_grants").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM trial_period_facts").fetchone()[0] == 0
    finally:
        await restarted.close()


@pytest.mark.parametrize(
    "language,label",
    [
        ("ru", "Активировать бесплатно"),
        ("uz-Latn", "Bepul faollashtirish"),
        ("uz-Cyrl", "Бепул фаоллаштириш"),
        ("en", "Activate free days"),
    ],
)
async def test_card_language_and_terms_are_host_owned(
    language: str,
    label: str,
    tmp_path: Path,
) -> None:
    lab, clock = await start(tmp_path / language)
    try:
        assert lab.touch.proactive and lab.action_cards
        contact = await lab.store.contact_context(LAB_PARENT, clock.now())
        assert contact
        await lab.touch.proactive.register(
            ParentContactContext.model_validate(
                contact.model_dump()
                | {"event_id": uuid4(), "revision": contact.revision + 1, "language": language}
            )
        )
        card = await publish(lab, language=language)
        assert card.buttons[0].label == label
        assert card.trial and card.trial.grant_days == 1
        result = await lab.action_cards.click(
            card.card_id, ChatActionClick.model_validate(click(card.model_dump(mode="json")))
        )
        assert result.status == "completed"
        with lab.store._connect() as db:
            assert (
                db.execute("SELECT language FROM conversion_trial_result_messages").fetchone()[0]
                == language
            )
        with pytest.raises(ParentChatError, match="action_card_not_found"):
            await lab.action_cards.read("4", card.card_id)
    finally:
        await lab.close()


@pytest.mark.parametrize("change", ["paid", "opted_out", "revoked", "disabled"])
async def test_changed_facts_refuse_before_claim_and_provider(change: str, tmp_path: Path) -> None:
    lab, clock = await start(tmp_path / change)
    try:
        card = await publish(lab)
        assert isinstance(lab.store, SqliteLabTrialActionStore)
        assert lab.action_cards and lab.trial_gateway
        if change == "paid":
            scenario = next(item for item in lab.bootstrap().scenarios if item.key == "paid")
            assert lab.touch.conversion
            await lab.touch.conversion.observe(ConversionSnapshot.model_validate(scenario.body))
        elif change == "opted_out":
            await lab.store.suppress_conversion(LAB_PARENT, clock.now())
        elif change == "revoked":
            lab.store._conversion_offers.clear()
        else:
            lab.store._trial_cards_enabled = False
        with pytest.raises(ParentChatError):
            await lab.action_cards.click(
                card.card_id, ChatActionClick.model_validate(click(card.model_dump(mode="json")))
            )
        assert lab.trial_gateway.calls == 0
        projected = await lab.action_cards.read(LAB_PARENT, card.card_id)
        assert projected.selected_button is None
        assert projected.status == ("cancelled" if change == "opted_out" else "pending")
        with lab.store._connect() as db:
            assert db.execute("SELECT count(*) FROM conversion_trial_grants").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM trial_button_dispatches").fetchone()[0] == 0
    finally:
        await lab.close()


async def test_pre_dispatch_change_has_a_known_refusal_without_provider_or_retry(
    tmp_path: Path,
) -> None:
    lab, clock = await start(tmp_path / "changed")
    try:
        card = await publish(lab)
        assert isinstance(lab.store, SqliteLabTrialActionStore)
        assert lab.action_cards and lab.trial_gateway and lab.trial_grants
        request = ChatActionClick.model_validate(click(card.model_dump(mode="json")))
        claim = await lab.store.claim_card(card.card_id, request, clock.now())
        assert isinstance(claim, ChatActionClaim)
        acceptance = await lab.store.button_acceptance(claim)
        lab.store._trial_cards_enabled = False
        state = await lab.trial_grants.accept_button(acceptance)
        assert state.status == "rejected" and state.error_code == "trial_cards_disabled"
        assert lab.trial_gateway.calls == 0
        projected = await lab.action_cards.read(LAB_PARENT, card.card_id)
        assert projected.status == "completed" and isinstance(
            projected.result, TrialChatActionResult
        )
        assert projected.result.outcome == "trial_rejected"
        assert await lab.trial_grants.accept_button(acceptance) == state
        assert lab.trial_gateway.calls == 0
    finally:
        await lab.close()


async def test_lost_owner_receipt_is_unknown_and_lost_card_ack_recovers_from_known_sql(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab, clock = await start(tmp_path / "unknown")
    try:
        card = await publish(lab)
        assert lab.action_cards and lab.trial_gateway
        gateway = lab.trial_gateway

        async def lost(parent_id: str, days: int) -> TrialGrantResult:
            gateway.calls += 1
            raise TimeoutError("Synthetic unknown grant acknowledgement")

        monkeypatch.setattr(gateway, "grant", lost)
        request = ChatActionClick.model_validate(click(card.model_dump(mode="json")))
        result = await lab.action_cards.click(card.card_id, request)
        assert result.status == "unknown" and isinstance(result.result, TrialChatActionResult)
        assert result.result.grant.status == "unknown"
        assert await lab.action_cards.click(card.card_id, request) == result
        assert lab.trial_gateway.calls == 1
    finally:
        await lab.close()
    lab, clock = await start(tmp_path / "known")
    try:
        card = await publish(lab)
        assert isinstance(lab.store, SqliteLabTrialActionStore)
        assert lab.action_cards and lab.trial_grants and lab.trial_gateway
        request = ChatActionClick.model_validate(click(card.model_dump(mode="json")))
        claim = await lab.store.claim_card(card.card_id, request, clock.now())
        assert isinstance(claim, ChatActionClaim)
        acceptance = await lab.store.button_acceptance(claim)
        known = await lab.trial_grants.accept_button(acceptance)
        assert known.status == "granted"
        # No finish_card acknowledgement was written; GET only observes the owning receipt.
        result = await lab.action_cards.read(LAB_PARENT, card.card_id)
        assert result.status == "completed" and isinstance(result.result, TrialChatActionResult)
        assert result.result.grant == known
        assert (await lab.action_cards.click(card.card_id, request)) == result
        assert lab.trial_gateway.calls == 1
    finally:
        await lab.close()
