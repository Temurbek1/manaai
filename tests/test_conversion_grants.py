"""Real adapter/SQLite protocol against MockTransport, never actual tariff writes."""

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.conversion_grants import TrialGrantService
from app.mana_ai.application.parent_touch_offers import render_parent_offer
from app.mana_ai.domain.conversion_grants import TrialAcceptance, TrialGrantResult
from app.services.manakids_trial_grants import ManakidsTrialGrantGateway
from tests.test_conversion_agent import repository, snapshot
from tests.test_parent_chat import NOW, message


async def prepare(tmp_path: Path, *, parent_id: str = "123") -> tuple[Any, TrialAcceptance]:
    store = await repository(tmp_path / "grant.db", trial=True)
    admitted = await store.ingest_conversion(snapshot(parent_id=parent_id), NOW)
    assert admitted.proposal
    assert await store.publish_conversion(NOW, render_parent_offer)
    reply = await store.admit(message(parent_id=parent_id, text="активировать бесплатные дни"), NOW)
    acceptance = TrialAcceptance(
        parent_id=parent_id,
        event_id=uuid4(),
        proposal_id=admitted.proposal.proposal_id,
        reply_turn_id=reply.turn_id,
        confirmed_by_parent=True,
    )
    return store, acceptance


def payload(**changes: Any) -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "purchase_id": 73668,
            "parent_id": 123,
            "tariff": "Maxsus",
            "valid_until": (NOW + timedelta(days=3)).isoformat(),
        }
        | changes,
        "error": None,
    }


def enriched_payload(**changes: Any) -> dict[str, Any]:
    return payload(
        **{
            "is_paid": False,
            "created_at": NOW.isoformat(),
            "agent_trial_used": True,
        }
        | changes
    )


@pytest.mark.parametrize(
    ("response_status", "body", "expected"),
    [
        (201, payload(), "granted"),
        (201, enriched_payload(), "granted"),
        (201, enriched_payload(created_at=(NOW - timedelta(seconds=300)).isoformat()), "granted"),
        (201, enriched_payload(created_at=(NOW + timedelta(seconds=300)).isoformat()), "granted"),
        (201, enriched_payload(created_at=(NOW - timedelta(seconds=301)).isoformat()), "unknown"),
        (201, enriched_payload(created_at=(NOW + timedelta(seconds=301)).isoformat()), "unknown"),
        (201, enriched_payload(is_paid=True), "unknown"),
        (201, enriched_payload(is_paid=None), "unknown"),
        (201, enriched_payload(is_paid=0), "unknown"),
        (201, enriched_payload(is_paid="false"), "unknown"),
        (201, enriched_payload(agent_trial_used=False), "unknown"),
        (201, enriched_payload(agent_trial_used=None), "unknown"),
        (201, enriched_payload(agent_trial_used=1), "unknown"),
        (201, enriched_payload(agent_trial_used="true"), "unknown"),
        (201, enriched_payload(created_at=None), "unknown"),
        (201, enriched_payload(created_at=123), "unknown"),
        (201, enriched_payload(created_at="invalid-date"), "unknown"),
        (201, enriched_payload(created_at=NOW.replace(tzinfo=None).isoformat()), "unknown"),
        (201, enriched_payload(created_at=(NOW - timedelta(days=30)).isoformat()), "unknown"),
        (201, enriched_payload(created_at=(NOW + timedelta(days=1)).isoformat()), "unknown"),
        (201, payload(is_paid=False), "unknown"),
        (201, payload(agent_trial_used=True, created_at=NOW.isoformat()), "unknown"),
        (
            409,
            {
                "success": False,
                "data": None,
                "code": "trial_already_given",
                "error": "raw provider text",
            },
            "rejected",
        ),
        (409, {"success": False, "data": None, "code": "has_active_paid_tariff"}, "rejected"),
        (409, {"success": False, "data": None, "code": "agent_tariff_not_configured"}, "rejected"),
        (409, {"success": False, "data": None, "code": "agent_tariff_limit_missing"}, "rejected"),
        (403, {"error": "private upstream details"}, "rejected"),
        (500, {"error": "private upstream details"}, "unknown"),
        (201, payload(parent_id=456), "unknown"),
        (201, payload(tariff="Different plan"), "unknown"),
        (201, payload(tariff="maxsus"), "unknown"),
        (201, payload(tariff="Maxsus "), "unknown"),
        (201, payload(valid_until=(NOW + timedelta(days=30)).isoformat()), "unknown"),
        (201, {"success": True}, "unknown"),
        (302, {}, "unknown"),
    ],
)
async def test_documented_non_paid_grant_receipt_and_exact_replay_never_retries(
    tmp_path: Path, response_status: int, body: dict[str, Any], expected: str
) -> None:
    store, acceptance = await prepare(tmp_path)
    calls: list[httpx.Request] = []

    def dispatch(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-jwt"})
        assert request.url.path == "/api/v1/admin-panel-payment/agent-grant-tariff/"
        assert json.loads(request.content) == {"parent_id": 123, "days": 3}
        assert request.headers["Authorization"] == "Bearer fake-jwt"
        return httpx.Response(response_status, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        gateway = ManakidsTrialGrantGateway(
            client=client,
            base_url="https://synthetic.invalid",
            username="fake-user",
            password="fake-password",
        )
        service = TrialGrantService(store, gateway, clock=lambda: NOW)
        result = await service.accept(acceptance)
        assert result.status == expected
        assert await service.accept(acceptance) == result
        assert len(calls) == 2
        assert "private upstream" not in result.model_dump_json()
        assert "raw provider" not in result.model_dump_json()
        if result.result is not None:
            assert set(result.result.model_dump()) == {
                "purchase_id",
                "parent_id",
                "tariff",
                "valid_until",
            }
        assert (
            await store.conversion_proposal("123", acceptance.proposal_id)
        ).status == "published"
        with pytest.raises(ParentChatError, match="already_admitted"):
            await service.accept(acceptance.model_copy(update={"event_id": uuid4()}))
        assert len(calls) == 2
        restarted = await repository(tmp_path / "grant.db", trial=True)
        assert (
            await TrialGrantService(restarted, gateway, clock=lambda: NOW).accept(acceptance)
            == result
        )
        assert len(calls) == 2


@pytest.mark.parametrize("phase", ["auth", "grant"])
async def test_duplicate_receipt_keys_never_verify_or_redispatch(
    tmp_path: Path, phase: str
) -> None:
    store, acceptance = await prepare(tmp_path)
    calls = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path.endswith("/login/"):
            if phase == "auth":
                return httpx.Response(
                    200, content='{"access":"fake-jwt","access":"fake-other-jwt"}'
                )
            return httpx.Response(200, json={"access": "fake-jwt"})
        body = json.dumps(enriched_payload()).replace(
            '"is_paid": false', '"is_paid": false, "is_paid": true'
        )
        return httpx.Response(201, content=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        gateway = ManakidsTrialGrantGateway(
            client=client,
            base_url="https://synthetic.invalid",
            username="fake-user",
            password="fake-password",
        )
        result = await TrialGrantService(store, gateway, clock=lambda: NOW).accept(acceptance)
        assert result.status == ("rejected" if phase == "auth" else "unknown")
        assert result.result is None
        expected_calls = 1 if phase == "auth" else 2
        assert calls == expected_calls
        restarted = await repository(tmp_path / "grant.db", trial=True)
        replayed = await TrialGrantService(restarted, gateway, clock=lambda: NOW).accept(acceptance)
        assert replayed == result and calls == expected_calls


@pytest.mark.parametrize("first_status", [201, 401, 403])
async def test_distinct_parent_actions_each_login_once_before_their_only_write(
    tmp_path: Path, first_status: int
) -> None:
    store, first = await prepare(tmp_path)
    _, second = await prepare(tmp_path, parent_id="456")
    calls: list[tuple[str, str | None]] = []
    logins = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal logins
        calls.append((request.url.path, request.headers.get("Authorization")))
        assert request.headers["User-Agent"] == "MANA-Conversion/1.0"
        if request.url.path.endswith("/login/"):
            logins += 1
            assert json.loads(request.content) == {
                "username": "fake-user",
                "password": "fake-password",
            }
            return httpx.Response(200, json={"access": f"fake-fresh-jwt-{logins}"})
        assert request.url.path == "/api/v1/admin-panel-payment/agent-grant-tariff/"
        body = json.loads(request.content)
        expected_login = 1 if body["parent_id"] == 123 else 2
        assert logins == expected_login
        assert request.headers["Authorization"] == f"Bearer fake-fresh-jwt-{expected_login}"
        assert body["days"] == 3
        status = first_status if body["parent_id"] == 123 else 201
        return httpx.Response(
            status,
            json=payload(parent_id=body["parent_id"], purchase_id=73668 + body["parent_id"]),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        gateway = ManakidsTrialGrantGateway(
            client=client,
            base_url="https://synthetic.invalid",
            username="fake-user",
            password="fake-password",
        )
        service = TrialGrantService(store, gateway, clock=lambda: NOW)
        first_result = await service.accept(first)
        assert first_result.status == ("granted" if first_status == 201 else "rejected")
        assert await service.accept(first) == first_result
        assert len(calls) == 2
        second_result = await service.accept(second)
        assert second_result.status == "granted"
        assert await service.accept(second) == second_result
        assert await service.accept(first) == first_result
        assert [path for path, _ in calls] == [
            "/api/v1/admin-panel-auth/login/",
            "/api/v1/admin-panel-payment/agent-grant-tariff/",
            "/api/v1/admin-panel-auth/login/",
            "/api/v1/admin-panel-payment/agent-grant-tariff/",
        ]
        restarted = await repository(tmp_path / "grant.db", trial=True)
        restarted_service = TrialGrantService(restarted, gateway, clock=lambda: NOW)
        assert await restarted_service.accept(first) == first_result
        assert await restarted_service.accept(second) == second_result
        assert len(calls) == 4


async def test_timeout_and_concurrent_acceptance_leave_single_unknown_action(
    tmp_path: Path,
) -> None:
    store, acceptance = await prepare(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()
    writes = 0

    async def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal writes
        if request.url.path.endswith("/login/"):
            return httpx.Response(200, json={"access": "fake-jwt"})
        writes += 1
        started.set()
        await release.wait()
        raise httpx.ReadTimeout("private timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        gateway = ManakidsTrialGrantGateway(
            client=client,
            base_url="https://synthetic.invalid",
            username="fake-user",
            password="fake-password",
        )
        service = TrialGrantService(store, gateway, clock=lambda: NOW)
        pending = asyncio.create_task(service.accept(acceptance))
        await asyncio.wait_for(started.wait(), timeout=2)
        assert (await service.accept(acceptance)).status == "submitting"
        release.set()
        assert (await pending).status == "unknown"
        assert (await service.accept(acceptance)).status == "unknown" and writes == 1


async def test_forged_or_other_family_acceptance_never_reaches_provider(tmp_path: Path) -> None:
    store, acceptance = await prepare(tmp_path)
    calls = 0

    def dispatch(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("No request was approved")

    async with httpx.AsyncClient(transport=httpx.MockTransport(dispatch)) as client:
        gateway = ManakidsTrialGrantGateway(
            client=client,
            base_url="https://synthetic.invalid",
            username="fake-user",
            password="fake-password",
        )
        service = TrialGrantService(store, gateway, clock=lambda: NOW)
        for changes in ({"parent_id": "456"}, {"reply_turn_id": 999}, {"reply_turn_id": 1}):
            with pytest.raises(ParentChatError):
                await service.accept(acceptance.model_copy(update=changes))
        assert calls == 0
    with pytest.raises(ValidationError):
        TrialAcceptance.model_validate(acceptance.model_dump() | {"days": 30})
    with pytest.raises(ValidationError):
        TrialAcceptance.model_validate(acceptance.model_dump() | {"confirmed_by_parent": 1})


@pytest.mark.parametrize("malformed", ["invalid_purchase_id", "missing_receipt", "extra_field"])
async def test_typed_port_bypass_never_becomes_a_verified_grant_or_automatic_retry(
    tmp_path: Path, malformed: str
) -> None:
    store, acceptance = await prepare(tmp_path)

    class MalformedGateway:
        def __init__(self) -> None:
            self.calls = 0

        async def grant(self, parent_id: str, days: int) -> TrialGrantResult:
            self.calls += 1
            if malformed == "missing_receipt":
                # An incorrectly implemented adapter may violate its annotation.
                return None  # type: ignore[return-value]
            original = TrialGrantResult(
                purchase_id=1,
                parent_id=parent_id,
                tariff="Maxsus",
                valid_until=NOW + timedelta(days=days),
            )
            if malformed == "invalid_purchase_id":
                return original.model_copy(update={"purchase_id": -1})
            return original.model_copy(update={"unexpected_provider_payload": "not trusted"})

    gateway = MalformedGateway()
    service = TrialGrantService(store, gateway, clock=lambda: NOW)
    result = await service.accept(acceptance)
    assert result.status == "unknown" and result.result is None
    assert result.error_code == "trial_grant_outcome_unknown"
    assert await service.accept(acceptance) == result
    restarted = await repository(tmp_path / "grant.db", trial=True)
    assert (
        await TrialGrantService(restarted, gateway, clock=lambda: NOW).accept(acceptance) == result
    )
    assert gateway.calls == 1
