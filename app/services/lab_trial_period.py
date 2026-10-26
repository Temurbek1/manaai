"""Declared fictional one-day grant history; never mounted in production factories."""

import json
import os
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.mana_ai.application.chat_ports import (
    ChatModelReceipt,
    ParentChatError,
    ParentChildrenSource,
)
from app.mana_ai.application.conversion_grants import TrialGrantService
from app.mana_ai.application.parent_touch_offers import render_parent_offer
from app.mana_ai.application.ports import Clock
from app.mana_ai.domain.chat import ChatTokens, ParentChildContext, ParentTariffContext
from app.mana_ai.domain.conversion import ConversionSnapshot
from app.mana_ai.domain.conversion_grants import TrialAcceptance, TrialGrantResult
from app.mana_ai.domain.family_agents import ParentTouchRequest
from app.mana_ai.domain.trial_periods import TrialPeriodMetadata
from app.services.trial_period_store import SqliteTrialPeriodStore


class LabTrialGrantGateway:
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self.calls = 0

    async def grant(self, parent_id: str, days: int) -> TrialGrantResult:
        if parent_id != "900001" or days != 1:
            raise ValueError("Only the fictional one-day lab grant is supported")
        self.calls += 1
        now = self._clock()
        return TrialGrantResult(
            purchase_id=900001,
            parent_id=parent_id,
            tariff="Maxsus",
            valid_until=now + timedelta(days=days),
        ).with_period_metadata(
            TrialPeriodMetadata(created_at=now, is_paid=False, agent_trial_used=True)
        )


class LabTrialProfiles:
    def __init__(self, base: ParentChildrenSource, store: SqliteTrialPeriodStore) -> None:
        self._base, self._store = base, store

    async def read(self, parent_id: str) -> ParentChildContext:
        context = await self._base.read(parent_id)
        try:
            grant = await self._store.trial_grant(parent_id)
        except ParentChatError as error:
            if error.code != "trial_grant_not_found":
                raise
            grant = None
        result = grant.result if grant and grant.status == "granted" else None
        return context.model_copy(
            update={
                "tariff": ParentTariffContext(
                    collected_at=context.collected_at,
                    tariff_name=result.tariff if result else None,
                    is_paid=False if result else None,
                    valid_until=result.valid_until if result else None,
                    payment_date=None,
                    agent_trial_used=True if result else None,
                )
            }
        )


async def seed_trial_history(store: SqliteTrialPeriodStore, clock: Clock, directory: Path) -> None:
    marker = directory / "fictional-trial-history.json"
    if marker.exists():
        if json.loads(marker.read_text()) != {"version": 1, "status": "completed"}:
            raise ParentChatError("lab_trial_fixture_unresolved", 409)
        grant = await store.trial_grant("900001")
        if grant.status != "granted" or grant.result is None:
            raise ParentChatError("lab_trial_fixture_missing_receipt", 409)
        return
    with store._connect() as db:
        if db.execute("SELECT 1 FROM parent_chat_turns").fetchone():
            raise ParentChatError("lab_trial_fixture_requires_empty_history", 409)
    with os.fdopen(os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump({"version": 1, "status": "admitted"}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    now = clock.now()
    past = now - timedelta(minutes=11)
    contact = await store.contact_context("900001", now)
    if contact is None:
        raise ParentChatError("lab_trial_fixture_contact_missing", 409)
    event = ConversionSnapshot(
        parent_id="900001",
        event_id=uuid4(),
        revision=1,
        observed_at=past,
        subscription="free",
        free_started_at=past - timedelta(days=7),
        agent_trial_given=False,
        marketing_consent=True,
        consent_observed_at=past,
        language=contact.language,
        timezone=contact.timezone,
        last_active_at=past - timedelta(minutes=15),
        active_days_7d=3,
        sessions_7d=5,
        paywall_views_7d=1,
    )
    admitted = await store.ingest_conversion(event, past)
    if admitted.proposal is None or not await store.publish_conversion(past, render_parent_offer):
        raise ParentChatError("lab_trial_fixture_proposal_refused", 409)
    reply = await store.admit(
        ParentTouchRequest(
            parent_id="900001",
            request_id=uuid4(),
            message={
                "ru": "активировать бесплатные дни",
                "en": "activate free days",
                "uz-Latn": "bepul kunlarni faollashtiring",
                "uz-Cyrl": "бепул кунларни фаоллаштиринг",
            }[contact.language],
        ),
        past,
    )
    await store.submit(reply, reserved_tokens=32, now=past)
    await store.settle(
        reply,
        receipt=ChatModelReceipt(
            usage=ChatTokens(input_tokens=0, output_tokens=0),
            model="lab-simulated-not-billed",
            answer={
                "ru": "Подтверждение получено.",
                "en": "Confirmation received.",
                "uz-Latn": "Tasdiq olindi.",
                "uz-Cyrl": "Тасдиқ олинди.",
            }[contact.language],
            completed=True,
        ),
        now=past,
        history_turns=0,
        context_at=past,
    )
    state = await TrialGrantService(store, LabTrialGrantGateway(clock.now), clock=clock.now).accept(
        TrialAcceptance(
            parent_id="900001",
            event_id=uuid4(),
            proposal_id=admitted.proposal.proposal_id,
            reply_turn_id=reply.turn_id,
            confirmed_by_parent=True,
        )
    )
    if state.status != "granted" or not await store.publish_trial_result(now):
        raise ParentChatError("lab_trial_fixture_grant_unresolved", 409)
    with marker.open("w") as stream:
        json.dump({"version": 1, "status": "completed"}, stream)
        stream.flush()
        os.fsync(stream.fileno())
