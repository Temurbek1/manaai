"""Complete fictional peer-reviewed v3 history; mock HTTP only, never paid inference.

Invoked by the networkless workspace compatibility audit. The manifest contains
fixture IDs/hashes, never cookies, OTPs, raw provider output or usable permissions.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch
from uuid import uuid4

if TYPE_CHECKING:
    from fastapi import FastAPI
    from httpx import AsyncClient, Request, Response

BASE = "/api/v1/admin/operation/workspace"
ORIGIN = "http://testserver"
MESSAGE = "Проверь два вымышленных контакта по очереди. Не отправляй ничего без согласования."
TABLES = (
    "operation_retention_contacts",
    "operation_retention_contact_guards",
    "operation_retention_contact_events",
    "operation_contact_preparation_gate",
    "operation_contact_preparations",
    "operation_contact_review_grants",
    "operation_contact_review_events",
    "operation_cost_periods",
    "operation_cost_reservations",
)


def _manifest(path: Path) -> Path:
    return path.with_suffix(".peer-loop.json")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(_manifest(path).read_text())
    assert value["fixture"] == "two-person-contact-loop-v1"
    assert value["owner"] != value["reviewer"] and len(value["steps"]) == 2
    return dict(value)


def fingerprint(path: Path, expected: dict[str, Any]) -> str:
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        rows: dict[str, Any] = {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in TABLES
        }
        rows["chat"] = connection.execute(
            "SELECT * FROM operation_chat_turns WHERE topic_id=? ORDER BY turn_id",
            (expected["topic_id"],),
        ).fetchall()
        rows["topic"] = connection.execute(
            "SELECT * FROM operation_chat_topics WHERE topic_id=?", (expected["topic_id"],)
        ).fetchall()
        # Login/last-seen timestamps are not historical action authority.
        rows["identities"] = connection.execute(
            "SELECT user_id,role,status FROM operation_admin_users "
            "WHERE user_id IN (?,?) ORDER BY user_id",
            (expected["owner"], expected["reviewer"]),
        ).fetchall()
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def check_fingerprint(path: Path) -> None:
    expected = _load(path)
    assert fingerprint(path, expected) == expected["fingerprint"]
    _assert_lifecycle(path, expected)


def _reservation_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        if not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='operation_cost_reservations'"
        ).fetchone():
            return set()
        return {
            row[0]
            for row in connection.execute("SELECT reservation_id FROM operation_cost_reservations")
        }


def _assert_lifecycle(path: Path, expected: dict[str, Any]) -> None:
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
        for step in expected["steps"]:
            action = json.loads(
                connection.execute(
                    "SELECT payload FROM operation_retention_contacts WHERE action_id=?",
                    (step["action_id"],),
                ).fetchone()[0]
            )
            grant = json.loads(
                connection.execute(
                    "SELECT payload FROM operation_contact_review_grants WHERE review_id=?",
                    (step["review_id"],),
                ).fetchone()[0]
            )
            assert action["status"] == "verified" and action["decided_by"] == expected["reviewer"]
            assert (
                action["owner"] == expected["owner"]
                and action["business_outcome"] == "not_measured"
            )
            assert action["request"]["parameters"]["mode"] == "sandbox"
            assert action["decision"]["request_id"] == step["decision"]["request_id"]
            assert grant["owner"] == expected["owner"] and grant["revoked_at"] is None
            assert grant["request"]["reviewer_id"] == expected["reviewer"]
            assert grant["request"]["fingerprint"] == action["fingerprint"]
            assert (
                connection.execute(
                    "SELECT count(*) FROM operation_contact_review_events WHERE review_id=?",
                    (step["review_id"],),
                ).fetchone()[0]
                >= 1
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM operation_contact_preparations "
                    "WHERE action_id=? AND status='recorded'",
                    (step["action_id"],),
                ).fetchone()[0]
                == 1
            )
        receipts = [
            connection.execute(
                "SELECT usage,actual FROM operation_cost_reservations WHERE reservation_id=?",
                (key,),
            ).fetchone()
            for key in expected["reservation_ids"]
        ]
        assert len(receipts) == 4 and all(row is not None for row in receipts)
        actual = [json.loads(row[1]) if row[1] is not None else None for row in receipts]
        assert sum(item is None for item in actual) == 1
        priced = [item for item in actual if item is not None]
        assert len(priced) == 3 and all(
            item["llm_calls"] == 1 and item["input_tokens"] == 100 and item["output_tokens"] == 50
            for item in priced
        )
        assert all(json.loads(row[0])["llm_microusd"] > 0 for row in receipts)


@dataclass(frozen=True)
class FixtureClock:
    at: datetime

    def now(self) -> datetime:
        return self.at


class CapturingSender:
    code: str | None = None

    async def send_login_code(self, *, telegram_id: int, code: str, ttl_seconds: int) -> None:
        del telegram_id, ttl_seconds
        self.code = code


class FixtureWire:
    def __init__(self, *, allow: bool) -> None:
        self.allow = allow
        self.calls = 0

    async def respond(self, request: Request) -> Response:
        import httpx

        from app.mana_operation_ai.domain.chat import ChatReply

        assert self.allow and self.calls < 4, "Observation attempted another model request"
        assert (
            request.method == "POST" and str(request.url) == "https://api.openai.com/v1/responses"
        )
        assert request.headers["Authorization"] == "Bearer test-peer-loop-compatibility"
        self.calls += 1
        if self.calls == 4:
            raise httpx.ReadTimeout("Synthetic lost terminal receipt", request=request)
        body = json.loads(request.content)
        assert body["store"] is False and body["parallel_tool_calls"] is False
        if isinstance(body["input"], str):
            assert self.calls == 1 and json.loads(body["input"])["message"] == MESSAGE
            outputs = []
        else:
            outputs = [item for item in body["input"] if item.get("type") == "function_call_output"]
        assert len(outputs) == self.calls - 1
        assert all(json.loads(item["output"])["status"] == "verified" for item in outputs)
        output: list[dict[str, Any]]
        if self.calls < 3:
            recipient = "sample_uz" if self.calls == 1 else "sample_ru"
            output = [
                {
                    "id": f"rs_peer_{self.calls}",
                    "type": "reasoning",
                    "summary": [],
                    "encrypted_content": f"test-opaque-peer-{self.calls}",
                },
                {
                    "id": f"fc_peer_{self.calls}",
                    "type": "function_call",
                    "status": "completed",
                    "name": "request_retention_contact_preparation",
                    "call_id": f"call_peer_{self.calls}",
                    "arguments": json.dumps(
                        {"recipient": recipient, "template": "onboarding_help"}
                    ),
                },
            ]
        else:
            assert body["tool_choice"] == "none"
            output = [
                {
                    "id": "msg_peer_final",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "annotations": [],
                            "text": ChatReply(
                                answer=(
                                    "Два вымышленных результата сохранены. "
                                    "Реальная доставка не измерена."
                                ),
                                plan=[],
                                next_action="none",
                            ).model_dump_json(),
                        }
                    ],
                }
            ]
        return httpx.Response(
            200,
            json={
                "id": f"resp_peer_{self.calls}",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": body["model"],
                "service_tier": "default",
                "parallel_tool_calls": False,
                "tool_choice": "none",
                "tools": [],
                "output": output,
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                    "input_tokens_details": {"cached_tokens": 10, "cache_write_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )


@asynccontextmanager
async def runtime(
    path: Path, clock: FixtureClock, *, allow_model: bool
) -> AsyncIterator[tuple[FastAPI, FixtureWire]]:
    import httpx
    from openai import AsyncOpenAI

    from app.core.config import Settings, get_settings
    from app.mana_operation_ai.infrastructure.retention.contact_catalog import (
        FakeRetentionContactCatalog,
    )

    settings = Settings(
        _env_file=None,
        app_env="local",
        openai_api_key="test-peer-loop-compatibility",
        app_api_key=None,
        meta_access_token=None,
        mana_telegram_bot_token=None,
        mana_telegram_auth_enabled=True,
        mana_auth_test_mode=False,
        mana_auth_test_otp_sink_path=None,
        mana_otp_hmac_secret="test-peer-loop-hmac-with-enough-entropy-123456789",
        mana_bootstrap_admin_telegram_ids="10001,10002",
        mana_trusted_origins=[ORIGIN],
        marketing_database_path=path.with_suffix(".peer-marketing.db"),
        operation_database_url=f"sqlite+aiosqlite:///{path}",
        operation_scheduler_enabled=False,
        operation_goals_worker_enabled=False,
        operation_allow_insecure_dev_headers=False,
        operation_allow_self_approval=False,
        operation_ads_provider="fake_meta",
        operation_product_activity_provider="fake",
        operation_parent_analytics_enabled=False,
        operation_child_telemetry_enabled=False,
        manakids_parent_source_enabled=False,
        audio_moderation_enabled=False,
        operation_dry_run=False,
        operation_agent_workspace_enabled=True,
        operation_workspace_retention_contacts_enabled=True,
        operation_workspace_retention_peer_reviews_enabled=True,
        operation_workspace_contact_tool_proposals_enabled=True,
        operation_workspace_contact_tool_continuations_enabled=True,
        operation_workspace_contact_tool_loops_enabled=True,
        operation_chat_max_output_tokens=2048,
        operation_model_selection_enabled=True,
        operation_chat_model="gpt-6.1-sol",
        operation_chat_rate_model="gpt-6.1-sol",
        operation_chat_input_usd_per_million="2.00",
        operation_chat_cached_input_usd_per_million="0.10",
        operation_chat_cache_write_usd_per_million="2.50",
        operation_chat_output_usd_per_million="10.00",
        api_rate_limit_requests=1000,
    )
    # Prime the existing configuration boundary with one explicit, validated object.
    # No .env is read; every imported get_settings reference sees this same cache.
    get_settings.cache_clear()
    with patch("app.core.config.Settings", return_value=settings):
        assert get_settings() is settings
    from app.main import create_app

    app = create_app()
    wire = FixtureWire(allow=allow_model)
    try:
        async with app.router.lifespan_context(app):
            app.state.admin_auth_service._sender = CapturingSender()
            bridge = app.state.operation_workspace_retention_contacts
            bridge._contacts._clock = clock
            bridge._contacts._executor = FakeRetentionContactCatalog(clock)
            app.state.operation_workspace_contact_reviews._clock = clock
            gateway = app.state.operation_chat_service._model
            await gateway.close()
            gateway._client = AsyncOpenAI(
                api_key="test-peer-loop-compatibility",
                base_url="https://api.openai.com/v1",
                max_retries=0,
                http_client=httpx.AsyncClient(transport=httpx.MockTransport(wire.respond)),
            )
            yield app, wire
    finally:
        get_settings.cache_clear()


async def _post(
    client: AsyncClient, url: str, payload: dict[str, Any], *, status: int = 200
) -> dict[str, Any]:
    response = await client.post(
        url,
        json=payload,
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": str(client.cookies.get("mana_csrf")),
        },
    )
    assert response.status_code == status, (url, response.status_code)
    return dict(response.json())


async def _login(app: FastAPI, client: AsyncClient, telegram_id: int) -> str:
    response = await client.post(
        "/api/v1/auth/telegram/request-code",
        headers={"Origin": ORIGIN},
        json={"telegram_id": telegram_id},
    )
    assert response.status_code == 202
    response = await client.post(
        "/api/v1/auth/telegram/verify-code",
        headers={"Origin": ORIGIN},
        json={
            "telegram_id": telegram_id,
            "code": app.state.admin_auth_service._sender.code,
        },
    )
    assert response.status_code == 200
    return str(response.json()["user"]["user_id"])


def _url(topic: str, turn: str) -> str:
    return f"{BASE}/topics/{topic}/messages/{turn}/retention-contacts"


async def setup(path: Path) -> None:
    import httpx

    if path.exists() or path.is_symlink() or _manifest(path).exists():
        raise RuntimeError("Peer fixture setup requires a new isolated database; never resume it")
    at = (datetime.now(UTC) - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    expected: dict[str, Any] = {
        "fixture": "two-person-contact-loop-v1",
        "clock": at.isoformat(),
        "steps": [],
    }
    existing_receipts = _reservation_ids(path)
    async with (
        runtime(path, FixtureClock(at), allow_model=True) as (app, wire),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as owner,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as reviewer,
    ):
        expected["owner"] = await _login(app, owner, 10001)
        expected["reviewer"] = await _login(app, reviewer, 10002)
        topic = await _post(
            owner,
            "/api/v1/admin/operation/chat/topics",
            {
                "agent_id": "retention-agent",
                "product": "mana",
                "title": "Peer loop rollback fixture",
            },
            status=201,
        )
        topic_id = expected["topic_id"] = topic["topic_id"]
        current = (
            await _post(
                owner,
                f"{BASE}/topics/{topic_id}/messages",
                {
                    "request_id": str(uuid4()),
                    "message": MESSAGE,
                    "execution_mode": "agent",
                    "response_language": "ru",
                },
            )
        )["turn"]
        expected["root_turn_id"] = current["turn_id"]
        for recipient in ("sample_uz", "sample_ru"):
            assert (
                current["status"] == "completed"
                and current["contact_preparation"]["recipient"] == recipient
            ), (current["status"], wire.calls)
            url = _url(topic_id, current["turn_id"])
            preparation = {
                "request_id": str(uuid4()),
                "confirmed": True,
                "recipient": recipient,
                "template": "onboarding_help",
                "selection_fingerprint": current["contact_preparation"]["selection_fingerprint"],
            }
            action = await _post(owner, url + "/prepare", preparation)
            assert action["status"] == "proposed" and action["self_approval_forbidden"]
            decision = {
                "request_id": str(uuid4()),
                "confirmed": True,
                "approve": True,
                "reason": "Separate fictional staff review",
                "fingerprint": action["fingerprint"],
            }
            await _post(owner, url + f"/{action['action_id']}/decision", decision, status=403)
            grant = await _post(
                owner,
                url + f"/{action['action_id']}/review",
                {
                    "request_id": str(uuid4()),
                    "confirmed": True,
                    "reviewer_id": expected["reviewer"],
                    "fingerprint": action["fingerprint"],
                },
            )
            review_url = f"{BASE}/retention-contact-reviews/{grant['review_id']}"
            assert (await reviewer.get(f"{BASE}/topics/{topic_id}/messages")).status_code == 404
            assert (
                await reviewer.get(f"/api/v1/admin/operation/goals/topics/{topic_id}")
            ).status_code == 404
            assert (await reviewer.get(url)).status_code == 404
            view = await reviewer.get(review_url)
            assert view.status_code == 200 and view.json()["action"]["message"] == action["message"]
            verified = await _post(
                reviewer, review_url + f"/{action['action_id']}/decision", decision
            )
            assert (
                verified["status"] == "verified" and verified["business_outcome"] == "not_measured"
            )
            assert (
                await _post(reviewer, review_url + f"/{action['action_id']}/decision", decision)
                == verified
            )
            continuation = {
                "request_id": str(uuid4()),
                "confirmed": True,
                "action_id": action["action_id"],
                "action_fingerprint": verified["fingerprint"],
                "revision": verified["revision"],
            }
            child = await _post(owner, url + "/continue", continuation)
            assert (
                await _post(owner, url + "/continue", {**continuation, "request_id": str(uuid4())})
                == child
            )
            expected["steps"].append(
                {
                    "turn_id": current["turn_id"],
                    "child_id": child["turn_id"],
                    "review_id": grant["review_id"],
                    "action_id": action["action_id"],
                    "preparation": preparation,
                    "decision": decision,
                    "continuation": continuation,
                }
            )
            current = child
        assert current["status"] == "completed" and current["next_action"] == "none"
        assert current["contact_preparation"] is None and wire.calls == 3
        unknown_request = {
            "request_id": str(uuid4()),
            "message": "Тест потерянной квитанции. Ничего не отправляй.",
            "execution_mode": "agent",
            "response_language": "ru",
        }
        unknown = (await _post(owner, f"{BASE}/topics/{topic_id}/messages", unknown_request))[
            "turn"
        ]
        assert unknown["status"] == "failed" and unknown["next_action"] == "none"
        assert wire.calls == 4
        assert (await _post(owner, f"{BASE}/topics/{topic_id}/messages", unknown_request))[
            "turn"
        ] == unknown
        assert wire.calls == 4
        expected["unknown"] = {"request": unknown_request, "turn_id": unknown["turn_id"]}
        executors = (
            app.state.operation_workspace_retention_contacts._contacts._executor.executors.values()
        )
        assert sum(item.target_reads for item in executors) == 4
        assert sum(item.dispatch_count for item in executors) == 2
    expected["reservation_ids"] = sorted(_reservation_ids(path) - existing_receipts)
    _assert_lifecycle(path, expected)
    expected["fingerprint"] = fingerprint(path, expected)
    _manifest(path).write_text(json.dumps(expected))
    check_fingerprint(path)


async def check_peer_loop(path: Path, *, stage: str) -> None:
    if stage == "setup":
        await setup(path)
        return
    check_fingerprint(path)
    expected = _load(path)
    if stage == "legacy":
        from app.mana_operation_ai.infrastructure.persistence.chat_repository import (
            SqlAlchemyChatRepository,
        )
        from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase

        database = OperationDatabase(f"sqlite+aiosqlite:///{path}")
        try:
            turns = await SqlAlchemyChatRepository(
                database, hourly_limit=20, daily_limit=200
            ).turns(expected["owner"], expected["topic_id"])
            assert len(turns) == 4 and all(turn.next_action == "none" for turn in turns)
            assert sum(turn.status == "completed" for turn in turns) == 3
            assert sum(turn.status == "failed" for turn in turns) == 1
        finally:
            await database.dispose()
    else:
        from app.mana_operation_ai.application.admin_service import ActorContext
        from app.mana_operation_ai.domain.chat import MessageCreate
        from app.mana_operation_ai.domain.contact_continuation import ContactContinueRequest
        from app.mana_operation_ai.domain.enums import UserRole
        from app.mana_operation_ai.domain.retention_contact import RetentionContactDecision
        from app.mana_operation_ai.domain.workspace_retention_contacts import (
            WorkspaceContactPrepare,
        )

        async with runtime(
            path, FixtureClock(datetime.fromisoformat(expected["clock"])), allow_model=False
        ) as (app, wire):
            owner = ActorContext(actor_id=expected["owner"], role=UserRole.ADMIN)
            peer = ActorContext(actor_id=expected["reviewer"], role=UserRole.ADMIN)
            bridge = app.state.operation_workspace_retention_contacts
            for step in expected["steps"]:
                action = await bridge.prepare(
                    owner,
                    expected["topic_id"],
                    step["turn_id"],
                    WorkspaceContactPrepare.model_validate(step["preparation"]),
                )
                assert action.action_id == step["action_id"] and action.status == "verified"
                result = await app.state.operation_workspace_contact_reviews.decide(
                    peer,
                    step["review_id"],
                    step["action_id"],
                    RetentionContactDecision.model_validate(step["decision"]),
                )
                assert result.status == "verified"
                child = await app.state.operation_contact_result_continuation.continue_with_result(
                    owner,
                    expected["topic_id"],
                    step["turn_id"],
                    ContactContinueRequest.model_validate(
                        {**step["continuation"], "request_id": str(uuid4())}
                    ),
                )
                assert child.turn_id == step["child_id"] and child.status == "completed"
            unknown = await app.state.operation_workspace_service.send(
                expected["owner"],
                expected["topic_id"],
                MessageCreate.model_validate(expected["unknown"]["request"]),
            )
            assert unknown.turn.turn_id == expected["unknown"]["turn_id"]
            assert unknown.turn.status == "failed"
            executors = bridge._contacts._executor.executors.values()
            assert sum(item.target_reads for item in executors) == 0
            assert sum(item.dispatch_count for item in executors) == 0
            assert wire.calls == 0
    check_fingerprint(path)
    print(f"Complete peer contact loop retained: {stage}; no source/model/contact redispatch")
