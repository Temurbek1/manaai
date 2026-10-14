"""Actual HTTP → private SQL → owning-domain fake; no paid model or live source."""

import json
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import Settings, get_settings
from app.main import create_app
from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.chat_ports import ChatError, ChatTurnOutput
from app.mana_operation_ai.domain.chat import ChatTopic, ChatTurn, MessageCreate, TopicCreate
from app.mana_operation_ai.domain.enums import UserRole
from app.mana_operation_ai.domain.retention_contact import (
    RetentionContactAction,
    contact_proposal_fingerprint,
)
from app.mana_operation_ai.domain.workspace_retention_contacts import WorkspaceContactPrepare
from app.mana_operation_ai.infrastructure.persistence.models import (
    ChatTurnRow,
    RetentionContactRow,
)
from tests.test_operation_agent_workspace import configure_workspace
from tests.test_operation_api import headers
from tests.test_retention_contact import Clock

BASE = "/api/v1/admin/operation/workspace"


class ContactConversation:
    def __init__(self) -> None:
        self.contexts: list[dict[str, object]] = []

    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        payload = json.loads(context)
        self.contexts.append(payload)
        assert "fictional Retention contact" in instructions
        return ChatTurnOutput(
            "Открою тестовый сценарий. Реальных сообщений не будет.",
            "fake-router",
            10,
            10,
            next_action="retention_contacts",
        )


def setup(
    monkeypatch: MonkeyPatch, path: Path, *, enabled: bool = True, self_approval: bool = True
) -> FastAPI:
    configure_workspace(monkeypatch, path)
    monkeypatch.setenv("OPERATION_WORKSPACE_RETENTION_CONTACTS_ENABLED", str(enabled).lower())
    monkeypatch.setenv("OPERATION_ALLOW_SELF_APPROVAL", str(self_approval).lower())
    monkeypatch.setattr("app.main.SystemClock", Clock)
    get_settings.cache_clear()
    return create_app()


async def send(
    app: FastAPI, *, owner: str = "alice", agent: str = "retention-agent", product: str = "mana"
) -> tuple[ChatTopic, ChatTurn, ContactConversation]:
    model = ContactConversation()
    chats = app.state.operation_chat_service
    chats._model = model
    topic = await chats.create(
        owner,
        TopicCreate.model_validate(
            {"agent_id": agent, "product": product, "title": "Synthetic contact"}
        ),
    )
    result = await app.state.operation_workspace_service.send(
        owner,
        topic.topic_id,
        MessageCreate(
            request_id=uuid4(),
            message="Покажи вымышленный контактный sandbox для тестирования.",
            execution_mode="agent",
        ),
    )
    assert result.goal is None
    return topic, result.turn, model


async def test_http_prepare_review_send_replay_reload_and_minimized_page(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    app = setup(monkeypatch, tmp_path / "contact-chat.db")
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        topic, turn, model = await send(app)
        assert turn.next_action == "retention_contacts"
        assert "retention_contacts" in cast(list[str], model.contexts[0]["allowed_next_actions"])
        url = f"{BASE}/topics/{topic.topic_id}/messages/{turn.turn_id}/retention-contacts"
        h = headers("alice", "admin")
        page = await client.get(url, headers=h)
        assert page.status_code == 200 and page.json()["items"] == []
        request = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "recipient": "sample_uz",
            "template": "onboarding_help",
        }
        proposal = await client.post(url + "/prepare", headers=h, json=request)
        assert proposal.status_code == 200, proposal.text
        body = proposal.json()
        assert body["status"] == "proposed" and body["message"]["language"] == "uz"
        assert not {"account_ref", "owner", "target_sha256", "consent_evidence_ref"} & body.keys()
        assert (await client.post(url + "/prepare", headers=h, json=request)).json() == body
        assert (await client.get(url, headers=h)).json()["items"] == [body]
        bridge = app.state.operation_workspace_retention_contacts
        executor = bridge._contacts._executor
        assert sum(item.dispatch_count for item in executor.executors.values()) == 0
        command = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "approve": True,
            "reason": "Review exact fictional Uzbek text",
            "fingerprint": body["fingerprint"],
        }
        decision_url = f"{url}/{body['action_id']}/decision"
        accepted = await client.post(decision_url, headers=h, json=command)
        assert accepted.status_code == 200, accepted.text
        assert (
            accepted.json()["status"] == "verified"
            and accepted.json()["business_outcome"] == "not_measured"
        )
        reads = sum(item.target_reads for item in executor.executors.values())
        assert (await client.post(decision_url, headers=h, json=command)).json() == accepted.json()
        assert sum(item.dispatch_count for item in executor.executors.values()) == 1
        assert sum(item.target_reads for item in executor.executors.values()) == reads
        async with bridge._store._sessions() as session:
            row = await session.get(RetentionContactRow, body["action_id"])
            assert row and row.payload["version"] == 2 and row.payload["turn_id"] == turn.turn_id
            saved_turn = await session.get(ChatTurnRow, turn.turn_id)
            assert saved_turn and saved_turn.payload["next_action"] == "none"
            assert saved_turn.context_metadata["next_action"] == "none"
            assert saved_turn.workspace_metadata["next_action"] == "retention_contacts"
        # Read-only reload cannot create another target read or write.
        assert (await client.get(url, headers=h)).json()["items"][0]["status"] == "verified"
        assert sum(item.target_reads for item in executor.executors.values()) == reads
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "agent,product",
    [("growth-agent", "mana"), ("technical-agent", "mana"), ("retention-agent", "360rec")],
)
async def test_other_room_or_product_cannot_offer_or_use_contacts(
    monkeypatch: MonkeyPatch, tmp_path: Path, agent: str, product: str
) -> None:
    app = setup(monkeypatch, tmp_path / "scope.db")
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        topic, turn, model = await send(app, agent=agent, product=product)
        assert "retention_contacts" not in cast(
            list[str], model.contexts[0]["allowed_next_actions"]
        )
        assert turn.next_action == "none"
        url = f"{BASE}/topics/{topic.topic_id}/messages/{turn.turn_id}/retention-contacts"
        assert (await client.get(url, headers=headers("alice", "admin"))).status_code == 403
    get_settings.cache_clear()


async def test_disabled_role_owner_wrong_turn_and_changed_request_fail_before_dispatch(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    assert (
        Settings(
            _env_file=None, openai_api_key="test-key"
        ).operation_workspace_retention_contacts_enabled
        is False
    )
    app = setup(monkeypatch, tmp_path / "denials.db", self_approval=False)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        topic, turn, _ = await send(app)
        url = f"{BASE}/topics/{topic.topic_id}/messages/{turn.turn_id}/retention-contacts"
        req = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "recipient": "sample_ru",
            "template": "onboarding_help",
        }
        assert (
            await client.post(url + "/prepare", headers=headers("alice", "viewer"), json=req)
        ).status_code == 403
        assert (await client.get(url, headers=headers("bob", "admin"))).status_code == 404
        proposed = (
            await client.post(url + "/prepare", headers=headers("alice", "operator"), json=req)
        ).json()
        changed = {**req, "recipient": "sample_uz"}
        assert (
            await client.post(url + "/prepare", headers=headers("alice", "operator"), json=changed)
        ).status_code == 409
        command = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "approve": True,
            "reason": "Test",
            "fingerprint": proposed["fingerprint"],
        }
        path = f"{url}/{proposed['action_id']}/decision"
        assert (
            await client.post(path, headers=headers("alice", "operator"), json=command)
        ).status_code == 403
        assert (
            await client.post(path, headers=headers("alice", "admin"), json=command)
        ).status_code == 403
        other_topic, other_turn, _ = await send(app)
        foreign_path = (
            f"{BASE}/topics/{other_topic.topic_id}/messages/{other_turn.turn_id}"
            f"/retention-contacts/{proposed['action_id']}/decision"
        )
        assert (
            await client.post(foreign_path, headers=headers("alice", "admin"), json=command)
        ).status_code == 404
        command["approve"] = False
        assert (await client.post(path, headers=headers("alice", "admin"), json=command)).json()[
            "status"
        ] == "rejected"
    get_settings.cache_clear()


async def test_disabled_lane_never_reads_the_new_private_tables(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    app = setup(monkeypatch, tmp_path / "disabled.db", enabled=False)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        topic, turn, model = await send(app)
        assert "retention_contacts" not in cast(
            list[str], model.contexts[0]["allowed_next_actions"]
        )
        assert turn.next_action == "none"
        service = app.state.operation_workspace_retention_contacts

        async def forbidden(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("Disabled bridge read a private table")

        monkeypatch.setattr(service._store, "list_for_turn", forbidden)
        url = f"{BASE}/topics/{topic.topic_id}/messages/{turn.turn_id}/retention-contacts"
        assert (await client.get(url, headers=headers("alice", "admin"))).status_code == 503
    get_settings.cache_clear()


async def test_sql_request_collision_cannot_rebind_contact_to_another_valid_turn(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    app = setup(monkeypatch, tmp_path / "turn-binding.db")
    async with app.router.lifespan_context(app):
        topic, turn, _ = await send(app)
        service = app.state.operation_workspace_retention_contacts
        actor = ActorContext(actor_id="alice", role=UserRole.ADMIN)
        view = await service.prepare(
            actor,
            topic.topic_id,
            turn.turn_id,
            WorkspaceContactPrepare(
                request_id=uuid4(),
                confirmed=True,
                recipient="sample_ru",
                template="onboarding_help",
            ),
        )
        original = await service._contacts.get(actor, view.action_id)
        other = await app.state.operation_workspace_service.send(
            "alice",
            topic.topic_id,
            MessageCreate(
                request_id=uuid4(),
                message="Ещё один вымышленный контактный sandbox.",
                execution_mode="agent",
            ),
        )
        payload = original.model_dump()
        payload.update(action_id=str(uuid4()), turn_id=other.turn.turn_id)
        payload["fingerprint"] = contact_proposal_fingerprint(
            action_id=payload["action_id"],
            owner=original.owner,
            topic_id=original.topic_id,
            request=original.request,
            message=original.message,
            target_sha256=original.target_sha256,
            policy=original.policy,
            prepared_at=original.prepared_at,
            expires_at=original.expires_at,
            turn_id=other.turn.turn_id,
        )
        with pytest.raises(ChatError, match="другим контактным действием"):
            await service._store.create(RetentionContactAction.model_validate(payload))
        assert await service._contacts.get(actor, view.action_id) == original
    get_settings.cache_clear()


async def test_unknown_chat_receipt_is_observed_without_a_second_send(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    app = setup(monkeypatch, tmp_path / "unknown-chat.db")
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        topic, turn, _ = await send(app)
        bridge = app.state.operation_workspace_retention_contacts
        catalog = bridge._contacts._executor
        url = f"{BASE}/topics/{topic.topic_id}/messages/{turn.turn_id}/retention-contacts"
        h = headers("alice", "admin")
        prepared = await client.post(
            url + "/prepare",
            headers=h,
            json={
                "request_id": str(uuid4()),
                "confirmed": True,
                "recipient": "sample_uz",
                "template": "onboarding_help",
            },
        )
        proposal = prepared.json()
        for executor in catalog.executors.values():
            executor.lose_ack = True
            executor.receipt_unavailable = True
        decision = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "approve": True,
            "reason": "Exact fictional template reviewed",
            "fingerprint": proposal["fingerprint"],
        }
        endpoint = f"{url}/{proposal['action_id']}"
        result = await client.post(endpoint + "/decision", headers=h, json=decision)
        assert result.status_code == 200 and result.json()["status"] == "uncertain"
        assert sum(item.dispatch_count for item in catalog.executors.values()) == 1
        reads = sum(item.receipt_reads for item in catalog.executors.values())
        assert (
            await client.post(endpoint + "/decision", headers=h, json=decision)
        ).json() == result.json()
        assert (await client.get(url, headers=h)).json()["items"][0]["status"] == "uncertain"
        assert sum(item.receipt_reads for item in catalog.executors.values()) == reads
        for executor in catalog.executors.values():
            executor.receipt_unavailable = False
        reconciled = await client.post(
            endpoint + "/reconcile",
            headers=h,
            json={"confirmed": True, "fingerprint": proposal["fingerprint"]},
        )
        assert reconciled.json()["status"] == "verified"
        assert sum(item.dispatch_count for item in catalog.executors.values()) == 1
        assert reconciled.json()["business_outcome"] == "not_measured"
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "changes",
    [
        {"recipient": "real_parent"},
        {"confirmed": 1},
        {"language": "uz"},
        {"account_ref": "acct_" + "a" * 64},
        {"message": "Arbitrary outreach"},
        {"mode": "live"},
    ],
)
async def test_http_cannot_inject_live_recipient_language_or_message(
    monkeypatch: MonkeyPatch, tmp_path: Path, changes: dict[str, object]
) -> None:
    app = setup(monkeypatch, tmp_path / "closed-contract.db")
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        topic, turn, _ = await send(app)
        url = f"{BASE}/topics/{topic.topic_id}/messages/{turn.turn_id}/retention-contacts"
        payload = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "recipient": "sample_ru",
            "template": "onboarding_help",
            **changes,
        }
        result = await client.post(
            url + "/prepare", headers=headers("alice", "admin"), json=payload
        )
        assert result.status_code == 422
        assert (await client.get(url, headers=headers("alice", "admin"))).json()["items"] == []
    get_settings.cache_clear()
