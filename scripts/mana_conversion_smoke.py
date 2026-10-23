"""Hermetic packaged conversion lifecycle; no live families, reads or writes.

Mount this harness read-only, not the application source, into the candidate
image and run with Docker --network=none. The HTTP gateways and pinned SDK still
execute their actual adapters, using MockTransport only.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from pydantic import SecretStr

from app import product_ai_main
from app.core.config import Settings, get_settings
from app.mana_ai.application.chat_ports import ChatModelReceipt
from app.mana_ai.domain.chat import ChatTokens, ParentChatRequest
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.conversion import (
    ConversionPolicy,
    ConversionSnapshot,
    PaidConversionOffer,
    TrialConversionOffer,
)
from app.mana_ai.domain.proactive_parent import ParentContactContext
from app.services import parent_chat_runtime as runtime_module
from app.services.family_compatibility_store import family_storage_version
from app.services.manakids_conversion_accounts import ManakidsConversionAccountSource
from app.services.manakids_parent_push import ManakidsParentPushGateway
from app.services.manakids_trial_grants import ManakidsTrialGrantGateway
from app.services.parent_chat_store import SqliteParentChatStore
from app.services.reviewed_message_store import SqliteReviewedMessageStore
from scripts.mana_family_agents_smoke import HEADERS, PREFIX, SYNTHETIC_BACKEND, Profiles, Provider


class CommercialProvider(Provider):
    """Actual SDK parsing/metering, with deterministic synthetic decisions."""

    commercial_inputs = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "tools" not in payload and "previous_response_id" not in payload
        if request.url.path.endswith("/input_tokens"):
            self.counts += 1
            return httpx.Response(200, json={"input_tokens": 100})
        assert payload["store"] is False
        self.generations += 1
        answer: dict[str, object]
        if payload["text"]["format"]["name"] == "child_safety_decision":
            answer = {
                "analysis": None,
                "followup_summary": (
                    "Ota-ona bepul kunlarni so'radi; xavf haqidagi yangi fakt yo'q."
                ),
                "question": None,
            }
        else:
            context = json.loads(payload["input"][0]["content"])["commercial_context"]
            assert context["terms"]["grant_days"] == 3
            assert context["free_days_action"] is None
            assert "not proof of success" in payload["instructions"]
            assert not any(
                key in json.dumps(context)
                for key in (
                    "purchase_id",
                    "billing_offer_id",
                    "approval_reference",
                    "parent_id",
                )
            )
            self.commercial_inputs += 1
            answer = {
                "body": "Bepul kunlar so'rovingiz qabul qilindi; faollashuv hali tasdiqlanmadi.",
                "question": None,
                "notice_communicated": False,
            }
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "synthetic-model",
                "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": json.dumps(answer)},
                        ],
                    }
                ],
            },
        )


class Upstream:
    """Actual documented login/grant/push payloads; no billing endpoints."""

    def __init__(self) -> None:
        self.logins = 0
        self.pushes: list[str] = []
        self.grants: list[str] = []
        self.accounts: dict[str, dict[str, Any]] = {}
        self.account_reads: list[str] = []
        self.reject_next_login = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "synthetic.invalid"
        if request.method == "GET":
            assert request.url.path == "/api/v1/admin-panel-parent/parent-list/"
            parent = request.url.params["parent_id"]
            assert dict(request.url.params) == {"parent_id": parent, "limit": "1", "offset": "0"}
            assert request.headers["authorization"].startswith("Bearer fake-jwt-")
            self.account_reads.append(parent)
            if parent == "423":
                raise httpx.ReadTimeout("synthetic unknown account read, never repeat")
            event = self.accounts[parent]
            return httpx.Response(
                200,
                json={
                    "count": 1,
                    "next": None,
                    "results": [
                        {
                            "id": int(parent),
                            "is_paid": False,
                            "agent_trial_used": event["agent_trial_given"],
                            "created_at": (datetime.now(UTC) - timedelta(days=365)).isoformat(),
                            "payment_date": event["free_started_at"],
                            "valid_until": event["free_access_ends_at"],
                            "phone": "synthetic-not-for-model-context",
                            "children": [{"id": int(parent) + 1}],
                        }
                    ],
                },
            )
        body = json.loads(request.content)
        if request.url.path == "/api/v1/admin-panel-auth/login/":
            self.logins += 1
            if self.reject_next_login:
                self.reject_next_login = False
                return httpx.Response(403, json={"detail": "synthetic login refusal"})
            return httpx.Response(200, json={"access": f"fake-jwt-{self.logins}"})
        assert request.headers["authorization"].startswith("Bearer fake-jwt-")
        if request.url.path == "/api/v1/admin-panel-payment/agent-grant-tariff/":
            assert set(body) == {"parent_id", "days"} and body["days"] == 3
            parent = str(body["parent_id"])
            self.grants.append(parent)
            if parent == "223":
                raise httpx.ReadTimeout("synthetic unknown write, never repeat")
            assert parent == "123"
            created_at = datetime.now(UTC)
            return httpx.Response(
                201,
                json={
                    "success": True,
                    "error": None,
                    "data": {
                        "purchase_id": 73668,
                        "parent_id": 123,
                        "tariff": "Maxsus",
                        "valid_until": (created_at + timedelta(days=3)).isoformat(),
                        "is_paid": False,
                        "created_at": created_at.isoformat(),
                        "agent_trial_used": True,
                    },
                },
            )
        prefix = "/api/v1/parent/notify-parent/"
        assert request.url.path.startswith(prefix) and request.url.path.endswith("/")
        parent = request.url.path[len(prefix) : -1]
        assert set(body) == {"title", "description"}
        assert body["title"] == "MANA"
        assert body["description"] == "MANA chatida yangi xabar bor. Ilovani oching."
        self.pushes.append(parent)
        return httpx.Response(
            201,
            json={
                "message": "Notification queued for 1 devices",
                "results": {
                    "parent_id": int(parent),
                    "phone": "synthetic-not-a-customer",
                    "title": body["title"],
                    "description": body["description"],
                    "type": "ai_agent",
                },
            },
        )


def fingerprint(database: Path) -> str:
    with sqlite3.connect(database) as connection:
        rows = {
            table: connection.execute(
                f"SELECT * FROM {table} WHERE parent_id IN ('901','902') ORDER BY parent_id"
            ).fetchall()
            for table in ("parent_chat_turns", "parent_chat_quota")
        }
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


async def seed_legacy(database: Path, limits: ChildSafetyLimits) -> str:
    """Actual v1 -> v6 storage, including a completed chat and an unknown hold."""
    now = datetime.now(UTC)
    store = SqliteParentChatStore(database, daily_limit=2000, timezone="Asia/Samarkand")
    await store.initialize()
    for parent, completed in (("901", True), ("902", False)):
        turn = await store.admit(
            ParentChatRequest(
                parent_id=parent,
                request_id=uuid4(),
                message="Legacy synthetic text",
            ),
            now,
        )
        await store.submit(turn, reserved_tokens=2000, now=now)
        if completed:
            await store.settle(
                turn,
                receipt=ChatModelReceipt(
                    usage=ChatTokens(input_tokens=100, output_tokens=50),
                    model="synthetic-seed",
                    answer="Legacy synthetic answer",
                    completed=True,
                ),
                now=now,
                history_turns=0,
                context_at=now,
            )
        else:
            await store.fail(turn, code="synthetic_lost_receipt", unknown=True)
    before = fingerprint(database)
    v6 = SqliteReviewedMessageStore(
        database,
        limits=limits,
        daily_limit=2000,
        timezone="Asia/Samarkand",
    )
    await v6.initialize()
    assert await family_storage_version(database) == 6 and fingerprint(database) == before
    return before


def source_fingerprint(database: Path) -> str:
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT * FROM conversion_account_reads ORDER BY parent_id,event_id"
        ).fetchall()
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


async def poll(
    read: Callable[[], Awaitable[httpx.Response]],
    ready: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    async with asyncio.timeout(5):
        while True:
            value = await read()
            assert value.status_code == 200, value.text
            body: dict[str, Any] = value.json()
            if ready(body):
                return body
            await asyncio.sleep(0.01)


def account(parent: str, *, expired: bool = False) -> ConversionSnapshot:
    now = datetime.now(UTC)
    return ConversionSnapshot(
        parent_id=parent,
        event_id=uuid4(),
        revision=1,
        observed_at=now,
        subscription="expired" if expired else "free",
        free_started_at=now - timedelta(days=8 if expired else 7),
        free_access_ends_at=now - timedelta(days=1) if expired else now + timedelta(days=1),
        agent_trial_given=expired,
        marketing_consent=True,
        consent_observed_at=now,
        language="uz-Latn",
        timezone="Asia/Samarkand",
        last_active_at=now,
        active_days_7d=3,
        sessions_7d=5,
        paywall_views_7d=1,
    )


async def main(*, verify_accounts: bool = False) -> dict[str, object]:
    if os.environ.get("MANA_EXPECT_PACKAGED_APP") == "1":
        assert Path(product_ai_main.__file__).resolve() == Path("/app/app/product_ai_main.py")
    provider, profiles, upstream = CommercialProvider(), Profiles(), Upstream()
    now = datetime.now(UTC)
    with TemporaryDirectory(prefix="mana-conversion-smoke-") as directory:
        database = Path(directory) / "family.db"
        limits = ChildSafetyLimits(
            server_daily_tokens=20_000,
            parent_daily_tokens=6000,
            job_tokens=2000,
        )  # Synthetic capacity only; production's 2000 global limit is unchanged.
        legacy = await seed_legacy(database, limits)
        hour = now.astimezone(ZoneInfo("Asia/Samarkand")).hour
        policy = ConversionPolicy(quiet_start_hour=(hour + 2) % 24, quiet_end_hour=(hour + 3) % 24)
        free = TrialConversionOffer(
            offer_id="synthetic-free-3",
            approval_reference="synthetic-only",
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=30),
            grant_days=3,
            priority=100,
        )
        paid = PaidConversionOffer(
            offer_id="synthetic-paid-15",
            billing_offer_id="synthetic-billing-15",
            approval_reference="synthetic-only",
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=30),
            currency="USD",
            list_price_minor=1000,
            price_minor=850,
            discount_percent=15,
            duration_days=30,
            auto_renew=False,
            checkout_path="/subscriptions/synthetic-paid-15",
        )
        config = Settings(
            _env_file=None,
            app_env="production",
            mana_telegram_auth_enabled=False,
            api_rate_limit_requests=1000,
            openai_api_key=SecretStr("fake-synthetic-only"),
            app_api_key=SecretStr(SYNTHETIC_BACKEND),
            mana_parent_chat_enabled=True,
            mana_parent_touch_enabled=True,
            mana_parent_touch_review_first_enabled=True,
            mana_child_safety_enabled=True,
            mana_child_safety_limits=limits,
            mana_child_safety_poll_seconds=0.05,
            mana_parent_chat_database_path=database,
            mana_conversion_enabled=True,
            mana_conversion_conversation_enabled=True,
            mana_conversion_trial_grants_enabled=True,
            mana_conversion_account_source_enabled=verify_accounts,
            mana_conversion_policy=policy,
            mana_conversion_offers=(free, paid),
            mana_parent_touch_proactive_enabled=True,
            mana_parent_push_enabled=True,
            manakids_api_base_url="https://synthetic.invalid",
            manakids_api_username="fake-user",
            manakids_api_password=SecretStr("fake-password"),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream.handle)) as mocked:
            with (
                patch.object(runtime_module, "ManakidsChatChildrenSource", lambda **_: profiles),
                patch.object(runtime_module, "OpenAIParentChatModel", provider.model),
                patch.object(
                    runtime_module,
                    "ManakidsConversionAccountSource",
                    lambda **kw: ManakidsConversionAccountSource(**(kw | {"client": mocked})),
                ),
                patch.object(
                    runtime_module,
                    "OpenAIChildSafetyModel",
                    lambda s: provider.model(s, safety=True),
                ),
                patch.object(
                    runtime_module,
                    "ManakidsParentPushGateway",
                    lambda **kw: ManakidsParentPushGateway(**(kw | {"client": mocked})),
                ),
                patch.object(
                    runtime_module,
                    "ManakidsTrialGrantGateway",
                    lambda **kw: ManakidsTrialGrantGateway(**(kw | {"client": mocked})),
                ),
                patch.object(product_ai_main, "get_settings", lambda: config),
            ):
                app = product_ai_main.create_app()
                app.dependency_overrides[get_settings] = lambda: config
                replays: list[tuple[str, dict[str, object], dict[str, Any]]] = []
                snapshots: list[dict[str, Any]] = []
                admissions: list[dict[str, Any]] = []
                async with (
                    app.router.lifespan_context(app),
                    httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=app),
                        base_url="http://unit",
                    ) as client,
                ):
                    assert (await client.get("/api/v1/health/live")).status_code == 200
                    assert (
                        await client.get(PREFIX + "/conversion-agent/proposals?parent_id=123")
                    ).status_code == 401
                    for parent in ("123", "223", "323"):
                        before_offer = profiles.reads, provider.generations
                        contact_now = datetime.now(UTC)
                        context = ParentContactContext(
                            parent_id=parent,
                            event_id=uuid4(),
                            revision=1,
                            observed_at=contact_now,
                            valid_until=contact_now + timedelta(hours=1),
                            language="uz-Latn",
                            timezone="Asia/Samarkand",
                            safety_chat_consent=False,
                            safety_push_consent=False,
                            marketing_push_consent=True,
                        )
                        registered = await client.post(
                            PREFIX + "/parent-touch/contact-context",
                            json=context.model_dump(mode="json"),
                            headers=HEADERS,
                        )
                        assert registered.status_code == 200
                        event = account(
                            parent, expired=parent == "323" and not verify_accounts
                        ).model_dump(mode="json")
                        if parent == "323" and verify_accounts:
                            # A current non-paid record, with the lifetime trial
                            # already used. Do not fake expired Parent List coverage.
                            event["agent_trial_given"] = True
                        upstream.accounts[parent] = event
                        snapshots.append(event)
                        result = await client.post(
                            PREFIX + "/conversion-agent/events", json=event, headers=HEADERS
                        )
                        assert result.status_code == 202 and result.json()["proposal"]
                        admissions.append(result.json())
                        history = await poll(
                            partial(
                                client.get,
                                PREFIX + f"/parent-touch/chat?parent_id={parent}",
                                headers=HEADERS,
                            ),
                            lambda body: bool(body["messages"]),
                        )
                        assert [m["role"] for m in history["messages"]] == ["assistant"]
                        assert "365" not in history["messages"][0]["content"]
                        notification = await poll(
                            partial(
                                client.get,
                                PREFIX + f"/parent-touch/notifications?parent_id={parent}",
                                headers=HEADERS,
                            ),
                            lambda body: bool(body["pushes"])
                            and body["pushes"][0]["status"] == "queued_by_provider",
                        )
                        assert notification["pushes"][0]["queued_devices"] == 1
                        assert (profiles.reads, provider.generations) == before_offer
                        if parent == "323":
                            assert result.json()["decision"] == (
                                "seven_day_free_use" if verify_accounts else "free_access_expired"
                            )
                            assert result.json()["proposal"]["offer"]["kind"] == "paid_subscription"
                            assert "15%" in history["messages"][0]["content"]
                            continue
                        parent_message: dict[str, object] = {
                            "parent_id": parent,
                            "request_id": str(uuid4()),
                            "message": "Bepul kunlarni faollashtiring",
                        }
                        admitted = await client.post(
                            PREFIX + "/parent-touch/messages", json=parent_message, headers=HEADERS
                        )
                        assert admitted.status_code == 202
                        status_path = (
                            PREFIX
                            + f"/parent-touch/messages/{parent_message['request_id']}"
                            + f"?parent_id={parent}"
                        )
                        response = await poll(
                            partial(client.get, status_path, headers=HEADERS),
                            lambda body: body["phase"] in {"completed", "failed", "unknown"},
                        )
                        assert response["phase"] == "completed", response
                        replays.append((status_path, parent_message, response))
                        acceptance = {
                            "parent_id": parent,
                            "event_id": str(uuid4()),
                            "proposal_id": result.json()["proposal"]["proposal_id"],
                            "reply_turn_id": admitted.json()["turn_id"],
                            "confirmed_by_parent": True,
                        }
                        route = PREFIX + "/conversion-agent/trial-acceptances"
                        grant = await client.post(route, json=acceptance, headers=HEADERS)
                        assert grant.status_code == 200
                        expected_status = "granted" if parent == "123" else "unknown"
                        assert grant.json()["status"] == expected_status
                        assert (
                            await client.post(route, json=acceptance, headers=HEADERS)
                        ).json() == grant.json()
                        receipt_history = await poll(
                            partial(
                                client.get,
                                PREFIX + f"/parent-touch/chat?parent_id={parent}",
                                headers=HEADERS,
                            ),
                            lambda body: len(body["messages"]) == 4,
                        )
                        receipt = receipt_history["messages"][-1]
                        assert receipt["role"] == "assistant" and "73668" not in receipt["content"]
                        assert (
                            "tasdiqlandi" in receipt["content"]
                            if parent == "123"
                            else "noma'lum" in receipt["content"]
                        )
                    schema_version = 10 if verify_accounts else 9
                    source_events: list[dict[str, Any]] = []
                    if verify_accounts:
                        for parent in ("423", "523"):
                            event = account(parent).model_dump(mode="json")
                            upstream.accounts[parent] = event
                            upstream.reject_next_login = parent == "523"
                            result = await client.post(
                                PREFIX + "/conversion-agent/events", json=event, headers=HEADERS
                            )
                            source_expected = "unknown" if parent == "423" else "refused"
                            assert result.status_code == 202
                            assert result.json()["decision"] == "account_read_" + source_expected
                            assert result.json()["proposal"] is None
                            observation = await client.get(
                                PREFIX
                                + f"/conversion-agent/source-observations/{event['event_id']}"
                                + f"?parent_id={parent}",
                                headers=HEADERS,
                            )
                            assert observation.json()["status"] == source_expected
                            assert observation.headers["cache-control"] == "no-store"
                            source_events.append(event)
                            changed = event | {"event_id": str(uuid4()), "revision": 2}
                            denied = await client.post(
                                PREFIX + "/conversion-agent/events", json=changed, headers=HEADERS
                            )
                            assert denied.status_code == (409 if parent == "423" else 429)
                        for event, original in zip(snapshots, admissions, strict=True):
                            replay = await client.post(
                                PREFIX + "/conversion-agent/events", json=event, headers=HEADERS
                            )
                            assert replay.json() == original
                        assert upstream.account_reads == ["123", "223", "323", "423"]
                    assert await family_storage_version(database) == schema_version
                    counts = provider.generations, provider.counts, profiles.reads, upstream.logins
                    for path, body, expected in replays:
                        assert (await client.get(path, headers=HEADERS)).json() == expected
                        assert (
                            await client.post(
                                PREFIX + "/parent-touch/messages", json=body, headers=HEADERS
                            )
                        ).json() == expected
                    assert (
                        provider.generations,
                        provider.counts,
                        profiles.reads,
                        upstream.logins,
                    ) == counts
                    assert upstream.grants == ["123", "223"] and sorted(upstream.pushes) == [
                        "123",
                        "223",
                        "323",
                    ]
                    assert upstream.logins == (10 if verify_accounts else 5)
                    assert provider.commercial_inputs == 2
                    assert provider.generations == 4
                    assert fingerprint(database) == legacy
                    source_before = source_fingerprint(database) if verify_accounts else None
                active_config = config
                config = config.model_copy(
                    update={
                        "mana_conversion_enabled": False,
                        "mana_conversion_conversation_enabled": False,
                        "mana_conversion_trial_grants_enabled": False,
                        "mana_conversion_account_source_enabled": False,
                        "mana_parent_touch_proactive_enabled": False,
                        "mana_parent_push_enabled": False,
                        "mana_child_safety_enabled": False,
                        "mana_parent_touch_review_first_enabled": False,
                    }
                )
                closed = product_ai_main.create_app()
                closed.dependency_overrides[get_settings] = lambda: config
                async with (
                    closed.router.lifespan_context(closed),
                    httpx.AsyncClient(
                        transport=httpx.ASGITransport(app=closed),
                        base_url="http://unit",
                    ) as client,
                ):
                    for path, body, expected in replays:
                        assert (await client.get(path, headers=HEADERS)).json() == expected
                        assert (
                            await client.post(
                                PREFIX + "/parent-touch/messages", json=body, headers=HEADERS
                            )
                        ).json() == expected
                    assert (
                        await client.post(
                            PREFIX + "/conversion-agent/events", json=snapshots[0], headers=HEADERS
                        )
                    ).status_code == 503
                    unknown = (
                        await client.get(PREFIX + "/chat?parent_id=902", headers=HEADERS)
                    ).json()
                    assert unknown["quota"]["reserved_tokens"] == 2000
                    assert unknown["latest_request_status"] == "unknown"
                    assert (
                        provider.generations,
                        provider.counts,
                        profiles.reads,
                        upstream.logins,
                    ) == counts
                    assert (
                        await family_storage_version(database) == schema_version
                        and fingerprint(database) == legacy
                    )
                    if verify_accounts:
                        assert source_fingerprint(database) == source_before
                if verify_accounts:
                    config = active_config
                    reconstructed = product_ai_main.create_app()
                    reconstructed.dependency_overrides[get_settings] = lambda: config
                    async with (
                        reconstructed.router.lifespan_context(reconstructed),
                        httpx.AsyncClient(
                            transport=httpx.ASGITransport(app=reconstructed), base_url="http://unit"
                        ) as client,
                    ):
                        for event in source_events:
                            source_expected = (
                                "unknown" if event["parent_id"] == "423" else "refused"
                            )
                            replay = await client.post(
                                PREFIX + "/conversion-agent/events", json=event, headers=HEADERS
                            )
                            assert replay.json()["decision"] == "account_read_" + source_expected
                            denied = await client.post(
                                PREFIX + "/conversion-agent/events",
                                json=event | {"event_id": str(uuid4()), "revision": 2},
                                headers=HEADERS,
                            )
                            assert denied.status_code == (
                                409 if event["parent_id"] == "423" else 429
                            )
                        assert source_fingerprint(database) == source_before
                        assert fingerprint(database) == legacy
                        assert (
                            provider.generations,
                            provider.counts,
                            profiles.reads,
                            upstream.logins,
                        ) == counts
                        assert upstream.account_reads == ["123", "223", "323", "423"]
        summary: dict[str, object] = {
            "result": "passed",
            "schema": schema_version,
            "mocked_account_reads": len(upstream.account_reads),
            "source_unknown_preserved": verify_accounts,
            "source_auth_refusal_preserved": verify_accounts,
            "legacy_fingerprint_preserved": True,
            "legacy_unknown_hold": 2000,
            "synthetic_generations": provider.generations,
            "mocked_input_counts": provider.counts,
            "synthetic_profile_reads": profiles.reads,
            "mocked_grant_writes": len(upstream.grants),
            "mocked_push_writes": len(upstream.pushes),
            "real_provider_calls": 0,
            "real_source_calls": 0,
            "real_contacts": 0,
            "production_mutations": 0,
        }
        print(json.dumps(summary, sort_keys=True))
        return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-accounts", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(main(verify_accounts=arguments.verify_accounts))
