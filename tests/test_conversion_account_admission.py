"""Durable account-source admission with fictional parents and no live providers."""

import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from pytest import MonkeyPatch

from app import product_ai_main
from app.core.config import Settings, get_settings
from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.conversion import ConversionService
from app.mana_ai.application.conversion_accounts import ConversionAccountVerifier
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.conversion import ConversionPolicy
from app.mana_ai.domain.conversion_accounts import (
    ConversionAccountFacts,
    ConversionAccountReadLimits,
)
from app.mana_ai.domain.conversion_grants import TrialAcceptance
from app.services import parent_chat_runtime as runtime_module
from app.services.commercial_conversation_store import SqliteClosedCommercialConversationStore
from app.services.conversion_account_store import (
    SqliteClosedConversionAccountStore,
    SqliteConversionAccountStore,
)
from app.services.manakids_conversion_accounts import ManakidsConversionAccountSource
from tests.test_child_safety_store import limits
from tests.test_commercial_conversation import repository as v9_repository
from tests.test_conversion_agent import paid_offer, snapshot, trial_offer
from tests.test_parent_chat import NOW, Children, Model, message
from tests.test_parent_chat_api import BACKEND_TOKEN, HEADERS
from tests.test_parent_proactive_api import contact


async def repository(path: Path, **changes: Any) -> SqliteConversionAccountStore:
    options: dict[str, Any] = {
        "conversion_policy": ConversionPolicy(),
        "conversion_offers": (paid_offer(),),
        "limits": limits(),
        "daily_limit": 2000,
        "timezone": "Asia/Samarkand",
        "account_source_enabled": True,
        "account_read_limits": ConversionAccountReadLimits(),
    }
    store = SqliteConversionAccountStore(path, **(options | changes))
    await store.initialize()
    return store


def facts(**changes: Any) -> ConversionAccountFacts:
    return ConversionAccountFacts.model_validate(
        {
            "parent_id": "123",
            "collected_at": NOW,
            "is_paid": False,
            "agent_trial_used": False,
            # Intentionally NOT the backend's actual seven-day free start.
            "created_at": NOW - timedelta(days=365),
            "payment_date": NOW - timedelta(days=7),
            "valid_until": NOW + timedelta(days=1),
        }
        | changes
    )


class Source:
    def __init__(self, result: ConversionAccountFacts | None = None) -> None:
        self.result = result or facts()
        self.calls = 0

    async def read(self, parent_id: str) -> ConversionAccountFacts:
        self.calls += 1
        return self.result


def service(
    store: SqliteConversionAccountStore, source: Source, *, now: datetime = NOW
) -> ConversionService:
    return ConversionService(
        store,
        clock=lambda: now,
        accounts=ConversionAccountVerifier(store, source, clock=lambda: now),
    )


async def test_verified_account_admits_once_and_replay_restart_never_rereads(
    tmp_path: Path,
) -> None:
    path = tmp_path / "family.db"
    store = await repository(path)
    source = Source()
    event = snapshot()
    original = await service(store, source).observe(event)
    assert original.proposal and original.decision == "seven_day_free_use"
    assert await service(store, source).observe(event) == original
    restarted = await repository(path)
    assert await service(restarted, source, now=NOW + timedelta(days=2)).observe(event) == original
    assert source.calls == 1
    read = await restarted.account_read("123", event.event_id)
    assert read.status == "verified" and read.facts == source.result
    with pytest.raises(ParentChatError, match="not_found"):
        await restarted.account_read("456", event.event_id)
    conflict = event.model_copy(update={"sessions_7d": 99})
    with pytest.raises(ParentChatError, match="event_conflict"):
        await service(restarted, source).observe(conflict)
    assert source.calls == 1


@pytest.mark.parametrize("kind", ["unknown", "refused", "cancelled"])
async def test_pending_and_unknown_claims_survive_concurrency_restart_and_new_nonce(
    tmp_path: Path, kind: str
) -> None:
    path = tmp_path / "family.db"
    store = await repository(path)
    started, release = asyncio.Event(), asyncio.Event()

    class SlowSource(Source):
        async def read(self, parent_id: str) -> ConversionAccountFacts:
            self.calls += 1
            started.set()
            await release.wait()
            if kind == "refused":
                raise ParentChatError("conversion_account_invalid", 503)
            raise TimeoutError("fake-private-source-message")

    source = SlowSource()
    event = snapshot()
    original = asyncio.create_task(service(store, source).observe(event))
    await asyncio.wait_for(started.wait(), 2)
    restarted = await repository(path)
    assert (await service(restarted, source).observe(event)).decision == "account_read_pending"
    with pytest.raises(ParentChatError, match="unresolved"):
        await service(restarted, source).observe(snapshot(revision=2))
    if kind == "cancelled":
        original.cancel()
        with pytest.raises(asyncio.CancelledError):
            await original
    else:
        release.set()
        result = await original
        expected = "account_read_refused" if kind == "refused" else "account_read_unknown"
        assert result.decision == expected and result.proposal is None
    saved = await restarted.account_read("123", event.event_id)
    assert saved.status == ("refused" if kind == "refused" else "unknown")
    assert "fake-private" not in saved.model_dump_json()
    replay = await service(restarted, source).observe(event)
    assert replay.proposal is None
    assert source.calls == 1
    if kind != "refused":
        later = NOW + timedelta(days=2)
        with pytest.raises(ParentChatError, match="unresolved"):
            await service(restarted, source, now=later).observe(
                snapshot(revision=2, observed_at=later, last_active_at=later)
            )


@pytest.mark.parametrize(
    ("changes", "decision"),
    [
        ({"is_paid": True}, "account_source_paid_or_unknown"),
        ({"is_paid": None}, "account_source_paid_or_unknown"),
        ({"agent_trial_used": True}, "account_source_trial_history_mismatch"),
        ({"agent_trial_used": None}, "account_source_trial_history_mismatch"),
        ({"valid_until": NOW + timedelta(days=10)}, "account_source_period_mismatch"),
        ({"valid_until": None}, "account_source_period_mismatch"),
        ({"collected_at": NOW - timedelta(hours=1)}, "account_read_refused"),
        ({"parent_id": "456"}, "account_read_refused"),
    ],
)
async def test_source_veto_never_creates_an_offer_or_uses_created_at_as_free_start(
    tmp_path: Path, changes: dict[str, Any], decision: str
) -> None:
    store = await repository(tmp_path / "family.db")
    source = Source(facts(**changes))
    event = snapshot()
    result = await service(store, source).observe(event)
    assert result.decision == decision and result.proposal is None
    assert source.calls == 1
    assert (await store.history("123", before=None, limit=20, now=NOW)).messages == []


@pytest.mark.parametrize(
    "changes",
    [
        {"subscription": "paid"},
        {"marketing_consent": False},
        {"active_days_7d": 0, "sessions_7d": 0, "paywall_views_7d": 0},
        {"free_started_at": NOW - timedelta(hours=1)},
    ],
)
async def test_non_candidates_do_not_spend_source_attempts(
    tmp_path: Path, changes: dict[str, Any]
) -> None:
    store = await repository(tmp_path / "family.db")
    source = Source()
    result = await service(store, source).observe(snapshot(**changes))
    assert result.proposal is None and source.calls == 0


async def test_opted_out_and_no_available_offer_do_not_dispatch_source(tmp_path: Path) -> None:
    source = Source()
    store = await repository(tmp_path / "family.db")
    await store.suppress_conversion("123", NOW)
    assert (await service(store, source).observe(snapshot())).proposal is None
    empty = await repository(tmp_path / "no-offer.db", conversion_offers=())
    assert (await service(empty, source).observe(snapshot())).proposal is None
    assert source.calls == 0


async def test_atomic_global_ceiling_and_six_hour_cooldown_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "family.db"
    store = await repository(path, account_read_limits=ConversionAccountReadLimits(daily_limit=1))
    first, second = snapshot(), snapshot(parent_id="223")
    results = await asyncio.gather(
        store.claim_account_read(first, NOW),
        store.claim_account_read(second, NOW),
        return_exceptions=True,
    )
    assert sum(isinstance(value, tuple) and value[1] for value in results) == 1
    denied = [value for value in results if isinstance(value, ParentChatError)]
    assert len(denied) == 1 and denied[0].code == "conversion_account_read_daily_limit"
    chosen = first if isinstance(results[0], tuple) else second
    await store.finish_account_read(chosen, NOW, status="refused", facts=None)
    await store.ingest_conversion(chosen, NOW)
    restarted = await repository(
        path, account_read_limits=ConversionAccountReadLimits(daily_limit=1)
    )
    newer = snapshot(parent_id=chosen.parent_id, revision=2)
    with pytest.raises(ParentChatError, match="cooldown"):
        await restarted.claim_account_read(newer, NOW + timedelta(minutes=5))
    later = NOW + timedelta(hours=6)
    with pytest.raises(ParentChatError, match="daily_limit"):
        await restarted.claim_account_read(
            snapshot(
                parent_id=chosen.parent_id, revision=2, observed_at=later, last_active_at=later
            ),
            later,
        )


async def test_crash_after_verified_read_only_resumes_sql_finalization(tmp_path: Path) -> None:
    path = tmp_path / "family.db"
    store = await repository(path)
    event = snapshot()
    assert await store.claim_account_read(event, NOW) == (None, True)
    await store.finish_account_read(event, NOW, status="verified", facts=facts())
    source = Source()
    restarted = await repository(path)
    result = await service(restarted, source).observe(event)
    assert result.proposal and source.calls == 0
    assert await service(restarted, source).observe(event) == result


async def test_restart_with_orphaned_pending_claim_only_observes_it(tmp_path: Path) -> None:
    path = tmp_path / "family.db"
    store = await repository(path)
    event = snapshot()
    assert await store.claim_account_read(event, NOW) == (None, True)
    # Simulate loss after the commit with no owner left to complete the request.
    restarted = await repository(path)
    source = Source()
    assert (await service(restarted, source).observe(event)).decision == "account_read_pending"
    with pytest.raises(ParentChatError, match="unresolved"):
        await service(restarted, source).observe(snapshot(revision=2))
    assert source.calls == 0


async def test_newer_paid_event_fences_late_source_result_without_a_second_read(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "family.db")
    event = snapshot()
    assert await store.claim_account_read(event, NOW) == (None, True)
    paid = snapshot(revision=2, subscription="paid")
    assert (await service(store, Source()).observe(paid)).proposal is None
    await store.finish_account_read(event, NOW, status="verified", facts=facts())
    source = Source()
    with pytest.raises(ParentChatError, match="out_of_order"):
        await service(store, source).observe(event)
    assert source.calls == 0


async def test_v9_history_does_not_acquire_source_grants_and_v10_cannot_downgrade(
    tmp_path: Path,
) -> None:
    path = tmp_path / "family.db"
    old = await v9_repository(path, offers=(paid_offer(),))
    event = snapshot()
    original = await old.ingest_conversion(event, NOW)
    assert original.proposal
    store = await repository(path)
    source = Source()
    assert await service(store, source).observe(event) == original and source.calls == 0
    touch = ParentTouchService(
        store=store,
        children=Children(),
        model=Model(),
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
        conversion=service(store, source),
    )
    assert not await touch.process_conversion()
    assert (
        await store.conversion_proposal("123", original.proposal.proposal_id)
    ).closed_reason == ("account_source_not_verified")
    pending = snapshot(revision=2)
    assert (await store.claim_account_read(pending, NOW))[1]
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT * FROM conversion_account_reads").fetchall()
    closed = SqliteClosedConversionAccountStore(path, daily_limit=2000, timezone="Asia/Samarkand")
    await closed.initialize()
    assert not (await closed.history("123", before=None, limit=20, now=NOW)).messages
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM conversion_account_reads").fetchall() == before
        assert db.execute("PRAGMA user_version").fetchone()[0] == 10
    with pytest.raises(RuntimeError, match="dedicated database"):
        await SqliteClosedCommercialConversationStore(
            path, daily_limit=2000, timezone="Asia/Samarkand"
        ).initialize()
    disabled = await repository(path, account_source_enabled=False)
    assert (await service(disabled, source).observe(pending)).decision == "account_read_pending"
    assert source.calls == 0


async def test_v9_unknown_chat_hold_survives_v10_migration_and_closed_observation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "family.db"
    old = await v9_repository(path, offers=(paid_offer(),))
    turn = await old.admit(message(), NOW)
    await old.submit(turn, reserved_tokens=2000, now=NOW)
    await old.fail(turn, code="provider_outcome_unknown", unknown=True)
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT * FROM parent_chat_turns").fetchall()
    store = await repository(path)
    quota = await store.quota("123", NOW)
    assert quota.blocked_by_unresolved_request and quota.reserved_tokens == 2000
    closed = SqliteClosedConversionAccountStore(path, daily_limit=2000, timezone="Asia/Samarkand")
    await closed.initialize()
    await closed.history("123", before=None, limit=20, now=NOW + timedelta(days=1))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM parent_chat_turns").fetchall() == rows
        assert db.execute("PRAGMA user_version").fetchone()[0] == 10


async def test_out_of_range_parent_fails_before_claim_or_read(tmp_path: Path) -> None:
    store = await repository(tmp_path / "family.db")
    source = Source()
    with pytest.raises(ParentChatError, match="parent_profile_id_required"):
        await service(store, source).observe(snapshot(parent_id=str(2**63)))
    assert source.calls == 0
    with pytest.raises(ParentChatError, match="not_found"):
        await store.account_read(str(2**63), uuid4())


async def test_stale_source_fences_commercial_context_trial_and_unclaimed_marketing_push(
    tmp_path: Path,
) -> None:
    store = await repository(tmp_path / "family.db", conversion_offers=(trial_offer(),))
    source = Source(facts(collected_at=NOW - timedelta(seconds=119)))
    event = snapshot(language="en")
    offered = await service(store, source).observe(event)
    assert offered.proposal
    await store.ingest_contact_context(contact(marketing_push_consent=True), NOW)
    touch = ParentTouchService(
        store=store,
        children=Children(),
        model=Model(),
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
        conversion=service(store, source),
    )
    assert await touch.process_conversion()
    parent = await store.admit(message(text="activate free days"), NOW)
    frozen = await store.commercial_context("123", parent.turn_id)
    assert frozen and frozen.offer_available_at_capture
    # The backend snapshot remains fresh (800s), but its captured source proof
    # is now 919s old. These checks must fail specifically on source freshness.
    later = NOW + timedelta(seconds=800)
    with pytest.raises(ParentChatError, match="trial_account_source_not_verified"):
        await store.claim_trial_grant(
            TrialAcceptance(
                parent_id="123",
                event_id=uuid4(),
                proposal_id=offered.proposal.proposal_id,
                reply_turn_id=parent.turn_id,
                confirmed_by_parent=True,
            ),
            later,
        )
    assert await store.claim_push(later) is None
    pushes = (await store.pushes("123")).pushes
    assert len(pushes) == 1 and pushes[0].status == "suppressed"
    assert pushes[0].error_code == "parent_push_marketing_source_not_verified"
    await store.fail(parent, code="synthetic_no_inference")
    followup = await store.admit(message(text="Is the offer still available?"), later)
    stale = await store.commercial_context("123", followup.turn_id)
    assert stale and not stale.offer_available_at_capture
    assert source.calls == 1


async def test_real_http_adapter_and_authenticated_api_use_one_filtered_read(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    store = await repository(tmp_path / "family.db")
    paths: list[str] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-jwt"})
        assert dict(request.url.params) == {"parent_id": "123", "limit": "1", "offset": "0"}
        return httpx.Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "id": 123,
                        "is_paid": False,
                        "agent_trial_used": False,
                        "created_at": (NOW - timedelta(days=365)).isoformat(),
                        "payment_date": (NOW - timedelta(days=7)).isoformat(),
                        "valid_until": (NOW + timedelta(days=1)).isoformat(),
                    }
                ],
                "next": None,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as provider:
        source = ManakidsConversionAccountSource(
            client=provider,
            base_url="https://synthetic.invalid",
            username="fake-user",
            password="fake-password",
            clock=lambda: NOW,
        )
        conversion = ConversionService(
            store,
            clock=lambda: NOW,
            accounts=ConversionAccountVerifier(
                store,
                source,
                clock=lambda: NOW,
            ),
        )
        touch = ParentTouchService(
            store=store,
            children=Children(),
            model=Model(),
            clock=lambda: NOW,
            max_output_tokens=512,
            history_turn_limit=2,
            conversion=conversion,
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
        event = snapshot()
        body = event.model_dump(mode="json")
        prefix = "/api/v1/mana-ai/conversion-agent"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.post(prefix + "/events", json=body)).status_code == 401
            assert paths == []
            first = await client.post(prefix + "/events", json=body, headers=HEADERS)
            assert first.status_code == 202 and first.json()["proposal"]
            assert await touch.process_conversion()
            history = await touch.read_touch_history("123", before=None, limit=20)
            assert len(history.messages) == 1 and history.messages[0].role == "assistant"
            assert "15%" in history.messages[0].content
            assert "365" not in history.messages[0].content
            assert (await client.post(prefix + "/events", json=body, headers=HEADERS)).json() == (
                first.json()
            )
            observation_url = prefix + f"/source-observations/{event.event_id}?parent_id=123"
            observed = await client.get(observation_url, headers=HEADERS)
            assert observed.status_code == 200 and observed.json()["status"] == "verified"
            assert observed.headers["cache-control"] == "no-store"
            assert (await client.get(observation_url)).status_code == 401
            assert (
                await client.get(observation_url.replace("123", "456"), headers=HEADERS)
            ).status_code == 404
        assert paths == [
            "/api/v1/admin-panel-auth/login/",
            "/api/v1/admin-panel-parent/parent-list/",
        ]


async def test_runtime_selects_v10_and_same_code_closed_reader_without_dispatch(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    class UnusedModel(Model):
        async def close(self) -> None:
            pass

    model, children, source = UnusedModel(), Children(), Source()
    monkeypatch.setattr(runtime_module, "OpenAIParentChatModel", lambda config: model)
    monkeypatch.setattr(runtime_module, "OpenAIChildSafetyModel", lambda config: model)
    monkeypatch.setattr(runtime_module, "ManakidsChatChildrenSource", lambda **kwargs: children)
    monkeypatch.setattr(runtime_module, "ManakidsConversionAccountSource", lambda **kwargs: source)
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
        mana_conversion_account_source_enabled=True,
        mana_conversion_offers=(paid_offer(),),
        manakids_api_username="fake-user",
        manakids_api_password=SecretStr("fake-password"),
    )
    async with runtime_module.parent_chat_runtime(config) as touch:
        assert isinstance(touch, ParentTouchService) and touch.conversion
        assert touch.conversion.accounts is not None
        assert not await touch.process_conversion()
    closed = config.model_copy(
        update={
            "mana_conversion_enabled": False,
            "mana_conversion_conversation_enabled": False,
            "mana_conversion_account_source_enabled": False,
            "mana_child_safety_enabled": False,
            "mana_parent_touch_review_first_enabled": False,
        }
    )
    async with runtime_module.parent_chat_runtime(closed) as touch:
        assert isinstance(touch, ParentTouchService) and touch.conversion is None
        assert not (await touch.read_touch_history("123", before=None, limit=20)).messages
    with sqlite3.connect(config.mana_parent_chat_database_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 10
    assert source.calls == model.calls == children.calls == 0
    with pytest.raises(ValidationError, match="Account source requires"):
        Settings(_env_file=None, mana_conversion_account_source_enabled=True)
