"""New captured commercial turns; fictional accounts and fake providers only."""

import asyncio
import json
import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from pytest import MonkeyPatch

from app import product_ai_main
from app.core.config import Settings, get_settings
from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.application.conversion import ConversionService
from app.mana_ai.application.conversion_grants import TrialGrantRejected, TrialGrantService
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.application.parent_touch_offers import render_parent_offer, render_trial_result
from app.mana_ai.domain.chat import ResponseLanguage
from app.mana_ai.domain.conversion import ConversionOffer, ConversionOutcome, ConversionPolicy
from app.mana_ai.domain.conversion_grants import TrialAcceptance, TrialGrantResult
from app.services import parent_chat_runtime as runtime_module
from app.services.child_safety_prompts import ChildSafetyPromptBuilder
from app.services.commercial_conversation_store import (
    SqliteClosedCommercialConversationStore,
    SqliteCommercialConversationStore,
)
from app.services.proactive_parent_store import SqliteProactiveParentStore
from tests.test_child_safety_store import limits
from tests.test_conversion_agent import paid_offer, snapshot, trial_offer
from tests.test_parent_chat import NOW, Children, Model, message
from tests.test_parent_chat_api import BACKEND_TOKEN, HEADERS
from tests.test_parent_proactive_api import contact
from tests.test_parent_touch_api import TouchModel
from tests.test_reviewed_messages import Clock, ReviewModel
from tests.test_reviewed_messages import request as reviewed_request


async def repository(
    path: Path,
    *,
    offers: tuple[ConversionOffer, ...] | None = None,
    conversation_enabled: bool = True,
) -> SqliteCommercialConversationStore:
    store = SqliteCommercialConversationStore(
        path,
        conversion_policy=ConversionPolicy(),
        conversion_offers=offers or (trial_offer(),),
        limits=limits(),
        daily_limit=2000,
        timezone="Asia/Samarkand",
        conversation_enabled=conversation_enabled,
    )
    await store.initialize()
    return store


class Gateway:
    def __init__(self, status: str = "granted") -> None:
        self.calls = 0
        self.status = status

    async def grant(self, parent_id: str, days: int) -> TrialGrantResult:
        self.calls += 1
        if self.status == "rejected":
            raise TrialGrantRejected("synthetic_refusal")
        if self.status == "unknown":
            raise TimeoutError("private upstream outcome")
        return TrialGrantResult(
            purchase_id=73668,
            parent_id=parent_id,
            tariff="Maxsus",
            valid_until=NOW + timedelta(days=days),
        )


async def prepare(
    path: Path,
    language: ResponseLanguage = "en",
) -> tuple[SqliteCommercialConversationStore, TrialAcceptance]:
    store = await repository(path)
    event = snapshot(language=language)
    admission = await store.ingest_conversion(event, NOW)
    assert admission.proposal
    assert await store.publish_conversion(NOW, render_parent_offer)
    request = message(
        text={
            "en": "activate free days",
            "ru": "активировать бесплатные дни",
            "uz-Latn": "bepul kunlarni faollashtiring",
            "uz-Cyrl": "бепул кунларни фаоллаштиринг",
        }[language]
    )
    turn = await store.admit(request, NOW)
    # Admission alone is sufficient for explicit backend acceptance. Release the
    # synthetic unsubmitted chat before exercising the independent receipt lane.
    await store.fail(turn, code="synthetic_no_inference")
    return store, TrialAcceptance(
        parent_id="123",
        event_id=uuid4(),
        proposal_id=admission.proposal.proposal_id,
        reply_turn_id=turn.turn_id,
        confirmed_by_parent=True,
    )


async def test_confirmed_expiry_selects_only_paid_offer_and_caps_elapsed_days(
    tmp_path: Path,
) -> None:
    store = await repository(
        tmp_path / "family.db",
        offers=(trial_offer(priority=100), paid_offer(priority=0)),
    )
    end = NOW - timedelta(hours=2)
    event = snapshot(
        subscription="expired",
        free_started_at=end - timedelta(days=7),
        free_access_ends_at=end,
        agent_trial_given=True,
        language="en",
    )
    admitted = await store.ingest_conversion(event, NOW)
    assert admitted.proposal and admitted.proposal.reason == "free_access_expired"
    assert admitted.proposal.offer.kind == "paid_subscription"
    await store.ingest_contact_context(contact(marketing_push_consent=True), NOW)
    assert await store.publish_conversion(NOW, render_parent_offer)
    history = await store.history("123", before=None, limit=20, now=NOW)
    text = history.messages[0].content
    assert "7-day free access ended on 2026-10-16 (UTC)" in text
    assert "15%" in text and "85.00 UZS" in text and "No automatic renewal" in text
    assert not await store.publish_conversion(NOW, render_parent_offer)
    push = await store.claim_push(NOW)
    assert push and push.notification.purpose == "marketing"
    paid = ConversionOutcome(
        parent_id="123",
        event_id=uuid4(),
        proposal_id=admitted.proposal.proposal_id,
        observed_at=NOW,
        kind="payment_confirmed",
        payment_id="synthetic-paid-receipt",
        amount_minor=8500,
        currency="UZS",
        billing_offer_id="billing-15",
    )
    assert (await store.conversion_outcome(paid, NOW)).status == "converted"


async def test_expiry_with_only_trial_catalog_never_proposes_free_days(tmp_path: Path) -> None:
    store = await repository(tmp_path / "family.db")
    admitted = await store.ingest_conversion(
        snapshot(
            subscription="expired",
            free_access_ends_at=NOW - timedelta(hours=1),
        ),
        NOW,
    )
    assert admitted.decision == "no_approved_offer" and admitted.proposal is None
    assert not await store.publish_conversion(NOW, render_parent_offer)


async def test_context_is_frozen_at_admission_and_not_recaptured_on_replay(tmp_path: Path) -> None:
    store = await repository(tmp_path / "family.db")
    admission = await store.ingest_conversion(snapshot(), NOW)
    assert admission.proposal
    assert await store.publish_conversion(NOW, render_parent_offer)
    request = message(text="What are the terms?")
    turn = await store.admit(request, NOW)
    original = await store.commercial_context("123", turn.turn_id)
    assert original and original.offer_available_at_capture
    await store.ingest_conversion(
        snapshot(
            revision=2,
            subscription="paid",
            marketing_consent=False,
        ),
        NOW,
    )
    with pytest.raises(ParentChatError, match="request_in_progress"):
        await store.admit(request, NOW)
    assert await store.commercial_context("123", turn.turn_id) == original
    assert await store.commercial_context("456", turn.turn_id) is None
    prompt = original.presentation()
    assert not any(
        key in json.dumps(prompt)
        for key in (
            "billing_offer_id",
            "approval_reference",
            "purchase_id",
            "proposal_id",
            "parent_id",
        )
    )


async def test_parent_touch_receives_terms_but_no_write_authority_or_success_claim(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "family.db")
    await store.ingest_conversion(snapshot(language="en"), NOW)
    assert await store.publish_conversion(NOW, render_parent_offer)
    model, children = Model(), Children()
    service = ParentTouchService(
        store=store,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
        conversion=ConversionService(store, clock=lambda: NOW),
    )
    request = message(text="activate free days")
    response = await service.send(request)
    prompt = model.prompts[-1]
    context = json.loads(prompt.messages[0][1])["commercial_context"]
    assert context["terms"]["grant_days"] == 3
    assert context["free_days_action"] is None
    assert "not proof of success" in prompt.instructions
    assert "never a paid" in prompt.instructions
    assert "separate or future subscription" in prompt.instructions
    assert "this free grant itself might charge" in prompt.instructions
    assert await service.send(request) == response
    assert model.calls == children.calls == 1
    with pytest.raises(ParentChatError, match="trial_grant_not_found"):
        await store.trial_grant("123")


@pytest.mark.parametrize("status", ["granted", "rejected", "unknown"])
@pytest.mark.parametrize("language", ["ru", "uz-Latn", "uz-Cyrl", "en"])
async def test_terminal_result_reaches_same_chat_once_without_model_or_push(
    tmp_path: Path,
    status: str,
    language: ResponseLanguage,
) -> None:
    path = tmp_path / "family.db"
    store, acceptance = await prepare(path, language)
    gateway = Gateway(status)
    service = TrialGrantService(store, gateway, clock=lambda: NOW)
    result = await service.accept(acceptance)
    assert result.status == status and gateway.calls == 1
    history_before = await store.history("123", before=None, limit=20, now=NOW)
    assert await store.publish_trial_result(NOW)
    assert not await store.publish_trial_result(NOW)
    history = await store.history("123", before=None, limit=20, now=NOW)
    assert len(history.messages) == len(history_before.messages) + 1
    receipt = history.messages[-1]
    assert receipt.role == "assistant"
    assert receipt.content == render_trial_result(result, NOW, language)
    assert "73668" not in receipt.content and "private upstream" not in receipt.content
    assert (await store.pushes("123")).pushes == []
    restarted = await repository(path)
    assert (
        await TrialGrantService(restarted, gateway, clock=lambda: NOW).accept(acceptance) == result
    )
    assert not await restarted.publish_trial_result(NOW) and gateway.calls == 1
    proposal = await restarted.conversion_proposal("123", acceptance.proposal_id)
    assert proposal.status != "converted"
    followup = await restarted.admit(message(text="Was it activated?"), NOW)
    captured = await restarted.commercial_context("123", followup.turn_id)
    assert captured and captured.grant == result and captured.grant_recorded_at == NOW


async def test_newer_offer_blocks_accepting_an_old_generic_activation_reply(tmp_path: Path) -> None:
    store = await repository(tmp_path / "family.db", offers=(trial_offer(),))
    first = await store.ingest_conversion(snapshot(), NOW)
    assert first.proposal and await store.publish_conversion(NOW, render_parent_offer)
    later = NOW + timedelta(days=8)
    second = await store.ingest_conversion(
        snapshot(
            event_id=uuid4(),
            revision=2,
            observed_at=later,
            last_active_at=later,
            free_access_ends_at=later + timedelta(days=1),
        ),
        later,
    )
    assert second.proposal and await store.publish_conversion(later, render_parent_offer)
    reply = await store.admit(message(text="activate free days"), later)
    old = TrialAcceptance(
        parent_id="123",
        event_id=uuid4(),
        proposal_id=first.proposal.proposal_id,
        reply_turn_id=reply.turn_id,
        confirmed_by_parent=True,
    )
    with pytest.raises(ParentChatError, match="trial_parent_reply_offer_mismatch"):
        await store.claim_trial_grant(old, later)
    current = old.model_copy(
        update={"event_id": uuid4(), "proposal_id": second.proposal.proposal_id}
    )
    assert (await store.claim_trial_grant(current, later))[1]


async def test_v8_history_is_not_upgraded_into_a_frozen_offer_binding(tmp_path: Path) -> None:
    path = tmp_path / "family.db"
    old = SqliteProactiveParentStore(
        path,
        conversion_policy=ConversionPolicy(),
        conversion_offers=(trial_offer(),),
        limits=limits(),
        daily_limit=2000,
        timezone="Asia/Samarkand",
    )
    await old.initialize()
    admitted = await old.ingest_conversion(snapshot(), NOW)
    assert admitted.proposal and await old.publish_conversion(NOW, render_parent_offer)
    request = message(text="activate free days")
    turn = await old.admit(request, NOW)
    await old.fail(turn, code="synthetic_no_inference")
    store = await repository(path)
    assert await store.commercial_context("123", turn.turn_id) is None
    with pytest.raises(ParentChatError, match="synthetic_no_inference"):
        await store.admit(request, NOW)
    with pytest.raises(ParentChatError, match="trial_reply_has_no_frozen_offer"):
        await store.claim_trial_grant(
            TrialAcceptance(
                parent_id="123",
                event_id=uuid4(),
                proposal_id=admitted.proposal.proposal_id,
                reply_turn_id=turn.turn_id,
                confirmed_by_parent=True,
            ),
            NOW,
        )
    closed = SqliteClosedCommercialConversationStore(
        path, daily_limit=2000, timezone="Asia/Samarkand"
    )
    await closed.initialize()
    assert await closed.commercial_context("123", turn.turn_id) is None
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 9
    with pytest.raises(RuntimeError, match="dedicated database"):
        await old.initialize()


async def test_concurrent_result_publication_is_atomic_and_closed_mode_retains_context(
    tmp_path: Path,
) -> None:
    path = tmp_path / "family.db"
    store, acceptance = await prepare(path)
    gateway = Gateway()
    await TrialGrantService(store, gateway, clock=lambda: NOW).accept(acceptance)
    assert sum(await asyncio.gather(*(store.publish_trial_result(NOW) for _ in range(4)))) == 1
    before = await store.history("123", before=None, limit=20, now=NOW)
    context = await store.commercial_context("123", acceptance.reply_turn_id)
    closed = SqliteClosedCommercialConversationStore(
        path, daily_limit=2000, timezone="Asia/Samarkand"
    )
    await closed.initialize()
    assert (await closed.history("123", before=None, limit=20, now=NOW)).messages == before.messages
    assert await closed.commercial_context("123", acceptance.reply_turn_id) == context
    disabled = await repository(path, conversation_enabled=False)
    assert not await disabled.publish_trial_result(NOW)
    assert await disabled.commercial_context("123", acceptance.reply_turn_id) == context


async def test_review_first_binds_commercial_terms_before_specialist_and_preserves_replay(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "family.db")
    children, specialist, speaker, clock = Children(), ReviewModel(), TouchModel(), Clock()
    specialist.ask = False
    safety = ChildSafetyService(
        store=store,
        children=children,
        model=specialist,
        prompts=ChildSafetyPromptBuilder(),
        clock=clock,
        limits=limits(),
        max_output_tokens=256,
    )
    touch = ParentTouchService(
        store=store,
        children=children,
        model=speaker,
        clock=clock.now,
        max_output_tokens=512,
        history_turn_limit=2,
        safety=safety,
        reviewed=store,
        conversion=ConversionService(store, clock=clock.now),
    )
    await store.ingest_conversion(snapshot(language="uz-Latn"), NOW)
    assert await touch.process_conversion()
    parent = reviewed_request("Bepul kunlarni faollashtiring")
    admitted = await touch.admit_message(parent)
    frozen = await store.commercial_context("123", admitted.turn_id)
    assert frozen and frozen.proposal and frozen.language == "uz-Latn"
    assert frozen.offer_available_at_capture
    review = await safety.process_one()
    assert review and review.status == "completed"
    assert await touch.process_reviewed_message()
    assert (await touch.message_state("123", parent.request_id)).phase == "completed"
    prompt = json.loads(speaker.prompts[-1].messages[0][1])
    assert "specialist_guidance" in prompt and "commercial_context" in prompt
    assert "commercial_context" not in json.loads(specialist.prompts[-1].messages[0][1])
    acceptance = TrialAcceptance(
        parent_id="123",
        event_id=uuid4(),
        proposal_id=frozen.proposal.proposal_id,
        reply_turn_id=admitted.turn_id,
        confirmed_by_parent=True,
    )
    gateway = Gateway()
    grant = await TrialGrantService(store, gateway, clock=clock.now).accept(acceptance)
    assert grant.status == "granted"
    assert await touch.process_conversion()
    before = (await touch.read_touch_history("123", before=None, limit=20)).messages
    assert before[-1].content == render_trial_result(grant, NOW, "uz-Latn")
    assert (await touch.admit_message(parent)).phase == "completed"
    assert not await touch.process_conversion()
    assert speaker.calls == specialist.calls == gateway.calls == 1
    assert (await touch.read_touch_history("123", before=None, limit=20)).messages == before


async def test_runtime_selects_v9_and_closed_reader_without_source_or_model_calls(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    class UnusedModel(Model):
        async def close(self) -> None:
            pass

    speaker, safety, children = UnusedModel(), UnusedModel(), Children()
    monkeypatch.setattr(runtime_module, "OpenAIParentChatModel", lambda config: speaker)
    monkeypatch.setattr(runtime_module, "OpenAIChildSafetyModel", lambda config: safety)
    monkeypatch.setattr(runtime_module, "ManakidsChatChildrenSource", lambda **kwargs: children)
    config = Settings(
        _env_file=None,
        openai_api_key=SecretStr("fake-only"),
        app_api_key=SecretStr(BACKEND_TOKEN),
        mana_parent_chat_enabled=True,
        mana_parent_touch_enabled=True,
        mana_parent_chat_database_path=tmp_path / "runtime.db",
        mana_parent_touch_review_first_enabled=True,
        mana_child_safety_enabled=True,
        mana_child_safety_limits=limits(),
        mana_child_safety_max_output_tokens=256,
        mana_conversion_enabled=True,
        mana_conversion_conversation_enabled=True,
        mana_conversion_offers=(paid_offer(),),
        manakids_api_username="fake-user",
        manakids_api_password=SecretStr("fake-password"),
    )
    async with runtime_module.parent_chat_runtime(config) as touch:
        assert isinstance(touch, ParentTouchService) and touch.conversion
        with sqlite3.connect(config.mana_parent_chat_database_path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 9
        assert not await touch.process_conversion()
    closed = config.model_copy(
        update={
            "mana_conversion_conversation_enabled": False,
            "mana_conversion_enabled": False,
            "mana_child_safety_enabled": False,
            "mana_parent_touch_review_first_enabled": False,
        }
    )
    async with runtime_module.parent_chat_runtime(closed) as touch:
        assert isinstance(touch, ParentTouchService) and touch.conversion is None
        assert not await touch.process_conversion()
        assert not (await touch.read_touch_history("123", before=None, limit=20)).messages
    assert speaker.calls == safety.calls == children.calls == 0
    with pytest.raises(ValidationError, match="Commercial conversation requires"):
        Settings(_env_file=None, mana_conversion_conversation_enabled=True)


async def test_http_grant_and_same_chat_receipt_without_repeat_or_payment(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "family.db")
    gateway, model, children = Gateway(), Model(), Children()
    grants = TrialGrantService(store, gateway, clock=lambda: NOW)
    touch = ParentTouchService(
        store=store,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
        conversion=ConversionService(store, clock=lambda: NOW, grants=grants),
    )
    config = Settings(
        _env_file=None,
        openai_api_key=SecretStr("fake-only"),
        app_api_key=SecretStr(BACKEND_TOKEN),
    )
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: config)
    app = product_ai_main.create_app()
    app.dependency_overrides[get_settings] = lambda: config
    app.state.parent_chat_service = touch
    base = "/api/v1/mana-ai"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        event = snapshot(language="en").model_dump(mode="json")
        assert (await client.post(base + "/conversion-agent/events", json=event)).status_code == 401
        admitted = await client.post(base + "/conversion-agent/events", json=event, headers=HEADERS)
        assert admitted.status_code == 202 and gateway.calls == 0
        assert await touch.process_conversion()
        parent = message(text="activate free days")
        sent = await client.post(
            base + "/parent-touch/chat", headers=HEADERS, json=parent.model_dump(mode="json")
        )
        assert sent.status_code == 200
        history = (
            await client.get(base + "/parent-touch/chat?parent_id=123", headers=HEADERS)
        ).json()
        reply = next(item for item in history["messages"] if item["role"] == "user")
        body = TrialAcceptance(
            parent_id="123",
            event_id=uuid4(),
            proposal_id=admitted.json()["proposal"]["proposal_id"],
            reply_turn_id=reply["turn_id"],
            confirmed_by_parent=True,
        ).model_dump(mode="json")
        endpoint = base + "/conversion-agent/trial-acceptances"
        assert (await client.post(endpoint, json=body)).status_code == 401
        result = await client.post(endpoint, json=body, headers=HEADERS)
        assert result.status_code == 200 and result.json()["status"] == "granted"
        assert result.headers["cache-control"] == "no-store"
        assert (await client.post(endpoint, json=body, headers=HEADERS)).json() == result.json()
        assert await touch.process_conversion()
        read = await client.get(
            base + "/conversion-agent/trial-grants?parent_id=123", headers=HEADERS
        )
        assert read.json() == result.json()
        history = (
            await client.get(base + "/parent-touch/chat?parent_id=123", headers=HEADERS)
        ).json()
        assert history["messages"][-1]["content"].startswith(
            "Your 3 free Maxsus days were confirmed"
        )
        assert (
            await client.get(base + "/conversion-agent/trial-grants?parent_id=456", headers=HEADERS)
        ).status_code == 404
        assert gateway.calls == model.calls == children.calls == 1


async def test_payment_before_acceptance_fences_frozen_old_terms(tmp_path: Path) -> None:
    store, acceptance = await prepare(tmp_path / "family.db")
    await store.ingest_conversion(snapshot(revision=2, subscription="paid"), NOW)
    gateway = Gateway()
    with pytest.raises(ParentChatError, match="trial_account_no_longer_eligible"):
        await TrialGrantService(store, gateway, clock=lambda: NOW).accept(acceptance)
    assert gateway.calls == 0


async def test_clock_alone_does_not_turn_queued_offer_into_an_expiry_promise(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "family.db", offers=(paid_offer(),))
    admitted = await store.ingest_conversion(
        snapshot(free_access_ends_at=NOW + timedelta(seconds=1)), NOW
    )
    assert admitted.proposal
    assert not await store.publish_conversion(NOW + timedelta(seconds=2), render_parent_offer)
    saved = await store.conversion_proposal("123", admitted.proposal.proposal_id)
    assert saved.status == "cancelled"
    assert not (await store.history("123", before=None, limit=20, now=NOW)).messages
