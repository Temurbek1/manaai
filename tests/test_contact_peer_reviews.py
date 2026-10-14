"""Two personal fake browser sessions; no real model/source or production calls."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Request
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.mana_operation_ai.domain.enums import AdminUserStatus, UserRole
from app.mana_operation_ai.infrastructure.persistence.models import RetentionContactRow
from tests.test_operation_api import headers
from tests.test_workspace_retention_contacts import send, setup

BASE = "/api/v1/admin/operation/workspace"


@asynccontextmanager
async def scenario(
    monkeypatch: MonkeyPatch, path: Path, *, enabled: bool = True
) -> AsyncIterator[tuple[FastAPI, AsyncClient, list[str], str, dict[str, object]]]:
    app = setup(monkeypatch, path, self_approval=False)
    monkeypatch.setenv("OPERATION_WORKSPACE_RETENTION_PEER_REVIEWS_ENABLED", str(enabled).lower())
    monkeypatch.setenv("MANA_TELEGRAM_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "MANA_OTP_HMAC_SECRET", "test-synthetic-peer-session-hmac-with-enough-entropy-123456"
    )
    monkeypatch.setenv("MANA_TRUSTED_ORIGINS", '["http://testserver"]')
    monkeypatch.setenv("OPERATION_ADMIN_API_KEY", "test-synthetic-peer-technical-key")
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        users = await app.state.admin_auth_service.bootstrap_admins((10001, 10002, 10003))
        ids = [user.user_id for user in users]
        from tests.test_telegram_auth_api import CapturingSender

        sender = CapturingSender()
        app.state.admin_auth_service._sender = sender
        sessions: dict[str, tuple[str, str]] = {}
        for user in users:
            await client.post(
                "/api/v1/auth/telegram/request-code",
                headers={"Origin": "http://testserver"},
                json={"telegram_id": user.telegram_id},
            )
            logged = await client.post(
                "/api/v1/auth/telegram/verify-code",
                headers={"Origin": "http://testserver"},
                json={"telegram_id": user.telegram_id, "code": sender.code},
            )
            assert logged.status_code == 200, logged.text
            sessions[user.user_id] = (
                str(client.cookies.get("mana_admin_session")),
                str(client.cookies.get("mana_csrf")),
            )
            client.cookies.clear()

        async def choose_fake_session(request: Request) -> None:
            # Test-only driver switches actual separately issued cookie sessions;
            # the application receives no development actor/role headers.
            selected = request.headers.pop("X-MANA-Actor-ID", None)
            request.headers.pop("X-MANA-Role", None)
            if selected in sessions:
                token, csrf = sessions[selected]
                request.headers["Cookie"] = f"mana_admin_session={token}; mana_csrf={csrf}"
                request.headers["X-CSRF-Token"] = csrf
                request.headers["Origin"] = "http://testserver"

        client.event_hooks["request"].append(choose_fake_session)
        topic, turn, _ = await send(app, owner=ids[0])
        url = f"{BASE}/topics/{topic.topic_id}/messages/{turn.turn_id}/retention-contacts"
        proposal = await client.post(
            url + "/prepare",
            headers=headers(ids[0], "admin"),
            json={
                "request_id": str(uuid4()),
                "confirmed": True,
                "recipient": "sample_uz",
                "template": "onboarding_help",
            },
        )
        assert proposal.status_code == 200, proposal.text
        yield app, client, ids, url, proposal.json()
    get_settings.cache_clear()


def command(fingerprint: object, *, approve: bool = True) -> dict[str, object]:
    return {
        "request_id": str(uuid4()),
        "confirmed": True,
        "approve": approve,
        "reason": "Exact fictional text reviewed by another human",
        "fingerprint": fingerprint,
    }


async def share(
    client: AsyncClient, ids: list[str], url: str, action: dict[str, object]
) -> dict[str, object]:
    payload = {
        "request_id": str(uuid4()),
        "reviewer_id": ids[1],
        "confirmed": True,
        "fingerprint": action["fingerprint"],
    }
    result = await client.post(
        f"{url}/{action['action_id']}/review", headers=headers(ids[0], "admin"), json=payload
    )
    assert result.status_code == 200, result.text
    assert (
        await client.post(
            f"{url}/{action['action_id']}/review", headers=headers(ids[0], "admin"), json=payload
        )
    ).json() == result.json()
    return cast(dict[str, object], result.json())


async def test_two_humans_exact_approval_replay_and_no_topic_or_goal_disclosure(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    async with scenario(monkeypatch, tmp_path / "two-humans.db") as (app, client, ids, url, action):
        h_owner, h_peer, h_other = [headers(user, "admin") for user in ids]
        owner_decision = await client.post(
            f"{url}/{action['action_id']}/decision",
            headers=h_owner,
            json=command(action["fingerprint"]),
        )
        assert owner_decision.status_code == 403
        options = (await client.get(f"{url}/{action['action_id']}/review", headers=h_owner)).json()
        assert ids[0] not in [item["user_id"] for item in options["reviewers"]]
        assert "telegram_id" not in str(options)
        grant = await share(client, ids, url, action)
        peer_url = f"{BASE}/retention-contact-reviews/{grant['review_id']}"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as bare:
            technical = await bare.get(
                peer_url,
                headers={
                    "X-API-Key": "test-synthetic-peer-technical-key",
                    "X-MANA-Actor-ID": ids[1],
                    "X-MANA-Role": "admin",
                },
            )
            assert technical.status_code == 401
            observed = client.build_request("GET", peer_url, headers=h_peer)
            await client.event_hooks["request"][0](observed)
            observed.headers.pop("X-CSRF-Token")
            assert (await bare.send(observed)).status_code == 200
            denied = client.build_request(
                "POST",
                f"{peer_url}/{action['action_id']}/decision",
                headers=h_peer,
                json=command(action["fingerprint"]),
            )
            await client.event_hooks["request"][0](denied)
            denied.headers.pop("X-CSRF-Token")
            assert (await bare.send(denied)).status_code == 403
        assert (await client.get(peer_url, headers=h_other)).status_code == 404
        topic_path = url.split("/messages/")[0]
        assert (await client.get(topic_path + "/messages", headers=h_peer)).status_code == 404
        item = (await client.get(peer_url, headers=h_peer)).json()
        assert (
            item["action"]["message"] == action["message"]
            and item["action"]["self_approval_forbidden"] is False
        )
        assert (await client.get(url, headers=h_peer)).status_code == 404
        decision_path = f"{peer_url}/{action['action_id']}/decision"
        decision = command(action["fingerprint"])
        result = await client.post(decision_path, headers=h_peer, json=decision)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "verified"
        assert (
            await client.post(decision_path, headers=h_peer, json=decision)
        ).json() == result.json()
        assert (await client.get(peer_url, headers=h_peer)).json()["action"]["status"] == "verified"
        assert (
            len(
                (await client.get(f"{BASE}/retention-contact-reviews", headers=h_peer)).json()[
                    "items"
                ]
            )
            == 1
        )
        assert (
            await client.post(
                f"{url}/{action['action_id']}/review/revoke",
                headers=h_owner,
                json={"confirmed": True, "fingerprint": action["fingerprint"]},
            )
        ).status_code == 409
        bridge = app.state.operation_workspace_retention_contacts
        assert (
            sum(item.dispatch_count for item in bridge._contacts._executor.executors.values()) == 1
        )
        async with app.state.operation_database.session_factory() as session:
            row = await session.get(RetentionContactRow, action["action_id"])
            assert row and row.payload["decided_by"] == ids[1]


@pytest.mark.parametrize("denial", ["revoke", "expiry", "reviewer_role", "owner_disabled"])
async def test_revocation_expiry_and_current_identity_deny_before_fake_dispatch(
    monkeypatch: MonkeyPatch, tmp_path: Path, denial: str
) -> None:
    async with scenario(monkeypatch, tmp_path / "denied-peer.db") as (
        app,
        client,
        ids,
        url,
        action,
    ):
        grant = await share(client, ids, url, action)
        peer_url = f"{BASE}/retention-contact-reviews/{grant['review_id']}"
        bridge = app.state.operation_workspace_retention_contacts
        if denial == "revoke":
            payload = {"confirmed": True, "fingerprint": action["fingerprint"]}
            result = await client.post(
                f"{url}/{action['action_id']}/review/revoke",
                headers=headers(ids[0], "admin"),
                json=payload,
            )
            assert result.status_code == 200 and result.json()["revoked"]
            assert (
                await client.post(
                    f"{url}/{action['action_id']}/review/revoke",
                    headers=headers(ids[0], "admin"),
                    json=payload,
                )
            ).json() == result.json()
        elif denial == "expiry":
            from datetime import timedelta

            bridge._contacts._clock.current += timedelta(hours=1)
        else:
            await app.state.admin_auth_repository.update_user_access(
                user_id=ids[1] if denial == "reviewer_role" else ids[0],
                role=UserRole.VIEWER if denial == "reviewer_role" else None,
                status=AdminUserStatus.DISABLED if denial == "owner_disabled" else None,
                disabled_reason="Synthetic test revocation" if denial == "owner_disabled" else None,
                display_name=None,
                username=None,
                update_display_name=False,
                update_username=False,
                updated_at=bridge._contacts._clock.now(),
                events=[],
            )
        result = await client.post(
            f"{peer_url}/{action['action_id']}/decision",
            headers=headers(ids[1], "admin"),
            json=command(action["fingerprint"]),
        )
        assert result.status_code in {403, 404}, result.text
        assert (
            sum(item.dispatch_count for item in bridge._contacts._executor.executors.values()) == 0
        )


async def test_sql_rechecks_reviewer_role_after_application_access(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    async with scenario(monkeypatch, tmp_path / "role-race.db") as (app, client, ids, url, action):
        grant = await share(client, ids, url, action)
        bridge = app.state.operation_workspace_retention_contacts
        original = bridge._store.transition

        async def changed(previous, updated, event):  # type: ignore[no-untyped-def]
            await app.state.admin_auth_repository.update_user_access(
                user_id=ids[1],
                role=UserRole.VIEWER,
                status=None,
                disabled_reason=None,
                display_name=None,
                username=None,
                update_display_name=False,
                update_username=False,
                updated_at=event.at,
                events=[],
            )
            return await original(previous, updated, event)

        monkeypatch.setattr(bridge._store, "transition", changed)
        result = await client.post(
            f"{BASE}/retention-contact-reviews/{grant['review_id']}/{action['action_id']}/decision",
            headers=headers(ids[1], "admin"),
            json=command(action["fingerprint"]),
        )
        assert result.status_code == 403, result.text
        assert (
            sum(item.dispatch_count for item in bridge._contacts._executor.executors.values()) == 0
        )


async def test_disabled_review_lane_has_no_private_table_read(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    async with scenario(monkeypatch, tmp_path / "disabled-reviews.db", enabled=False) as (
        app,
        client,
        ids,
        url,
        action,
    ):

        async def forbidden(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("Disabled reviews touched private SQL")

        monkeypatch.setattr(
            app.state.operation_workspace_contact_reviews._access.store, "by_action", forbidden
        )
        result = await client.get(
            f"{url}/{action['action_id']}/review", headers=headers(ids[0], "admin")
        )
        assert result.status_code == 503


async def test_share_request_cannot_broaden_scope_or_replace_selected_reviewer(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    async with scenario(monkeypatch, tmp_path / "share-contract.db") as (
        _,
        client,
        ids,
        url,
        action,
    ):
        path = f"{url}/{action['action_id']}/review"
        request = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "reviewer_id": ids[0],
            "fingerprint": action["fingerprint"],
        }
        assert (
            await client.post(path, headers=headers(ids[0], "admin"), json=request)
        ).status_code == 403
        request["reviewer_id"] = ids[1]
        for extra in (
            {"confirmed": 1},
            {"topic_access": True},
            {"source_grant": "firebase"},
            {"fingerprint": "a" * 64},
        ):
            result = await client.post(
                path, headers=headers(ids[0], "admin"), json={**request, **extra}
            )
            assert result.status_code in {409, 422}
        assert (
            await client.post(path, headers=headers(ids[0], "admin"), json=request)
        ).status_code == 200
        request["reviewer_id"] = ids[2]
        assert (
            await client.post(path, headers=headers(ids[0], "admin"), json=request)
        ).status_code == 409


async def test_unknown_ack_is_observed_once_without_a_second_send(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    async with scenario(monkeypatch, tmp_path / "peer-unknown.db") as (
        app,
        client,
        ids,
        url,
        action,
    ):
        grant = await share(client, ids, url, action)
        bridge = app.state.operation_workspace_retention_contacts
        for executor in bridge._contacts._executor.executors.values():
            executor.lose_ack = True
            executor.receipt_unavailable = True
        peer_url = f"{BASE}/retention-contact-reviews/{grant['review_id']}"
        command_url = f"{peer_url}/{action['action_id']}/decision"
        decision = command(action["fingerprint"])
        response = await client.post(command_url, headers=headers(ids[1], "admin"), json=decision)
        assert response.status_code == 200 and response.json()["status"] == "uncertain"
        reads = sum(item.receipt_reads for item in bridge._contacts._executor.executors.values())
        assert (
            await client.post(command_url, headers=headers(ids[1], "admin"), json=decision)
        ).json() == response.json()
        assert (await client.get(peer_url, headers=headers(ids[1], "admin"))).json()["action"][
            "status"
        ] == "uncertain"
        assert (
            sum(item.receipt_reads for item in bridge._contacts._executor.executors.values())
            == reads
        )
        for executor in bridge._contacts._executor.executors.values():
            executor.receipt_unavailable = False
        receipt = await client.post(
            f"{peer_url}/{action['action_id']}/reconcile",
            headers=headers(ids[1], "admin"),
            json={"confirmed": True, "fingerprint": action["fingerprint"]},
        )
        assert receipt.status_code == 200 and receipt.json()["status"] == "verified"
        assert (
            sum(item.dispatch_count for item in bridge._contacts._executor.executors.values()) == 1
        )
