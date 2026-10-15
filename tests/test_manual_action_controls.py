"""HTTP/SQL controls govern the owning fictional executor, not an analysis schedule."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import select

from app.core.config import get_settings
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput
from app.mana_operation_ai.application.registry import AgentRegistry, UnknownAgentError
from app.mana_operation_ai.domain.chat import MessageCreate, TopicCreate
from app.mana_operation_ai.domain.manual_action_controls import ManualActionControlDefinition
from app.mana_operation_ai.infrastructure.persistence.models import RetentionContactRow
from tests.test_operation_api import headers
from tests.test_workspace_retention_contacts import BASE, send, setup

CONTROL = "retention.contact.sandbox"
URL = BASE + "/manual-action-controls"
CHANGE = URL + f"/retention-agent/{CONTROL}"
STANDARD = f"/api/v1/admin/operation/kill-switch/agents/retention-agent/capabilities/{CONTROL}"


async def test_registered_manual_control_is_separate_from_runner_schedules_and_legacy_json(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    app = setup(monkeypatch, tmp_path / "catalog.db", self_approval=False)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        catalog = await client.get(URL, headers=headers("viewer", "viewer"))
        assert catalog.status_code == 200
        [item] = catalog.json()["items"]
        assert item["definition"] == ManualActionControlDefinition().model_dump(mode="json")
        with pytest.raises(UnknownAgentError):
            AgentRegistry().register_manual_action_control(ManualActionControlDefinition())
        with pytest.raises(ValueError, match="collides"):
            app.state.operation_admin_service._agents.register_manual_action_control(
                ManualActionControlDefinition()
            )
        assert item["capability_kill_switch"] is False
        agent = (
            await client.get(
                "/api/v1/admin/operation/agents/retention-agent",
                headers=headers("viewer", "viewer"),
            )
        ).json()
        assert CONTROL not in {capability["key"] for capability in agent["agent"]["capabilities"]}
        assert CONTROL not in agent["agent"]["configuration_schema"]
        assert not any(row["capability_key"] == CONTROL for row in agent["schedules"])
        for suffix, payload, expected in [
            ("run", {"capability_key": CONTROL, "job_type": "analysis"}, 409),
            (f"configurations?capability_key={CONTROL}", {"values": {}}, 404),
        ]:
            result = await client.post(
                f"/api/v1/admin/operation/agents/retention-agent/{suffix}",
                headers=headers("admin", "admin"),
                json=payload,
            )
            assert result.status_code == expected, result.text
        assert (
            await client.get(URL + "?agent_id=growth-agent", headers=headers("viewer", "viewer"))
        ).json() == {"items": []}
    get_settings.cache_clear()


async def test_disabled_lane_has_no_registered_manual_control_or_private_reads(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    app = setup(monkeypatch, tmp_path / "disabled.db", enabled=False)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):

        async def forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("Disabled control discovery must not read contact data")

        bridge = app.state.operation_workspace_retention_contacts
        monkeypatch.setattr(bridge._store, "list_for_turn", forbidden)
        monkeypatch.setattr(bridge._store, "history", forbidden)
        assert (await client.get(URL, headers=headers("v", "viewer"))).json() == {"items": []}
        for path, body in [
            (CHANGE, {"confirmed": True, "enabled": True}),
            (STANDARD, {"enabled": True}),
        ]:
            assert (
                await client.put(path, headers=headers("a", "admin"), json=body)
            ).status_code == 404
    get_settings.cache_clear()


async def test_admin_controls_stop_before_target_reads_and_preserve_existing_request_replay(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "controls.db"
    app = setup(monkeypatch, path, self_approval=False)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        topic, turn, _ = await send(app)
        prepare = (
            f"{BASE}/topics/{topic.topic_id}/messages/{turn.turn_id}/retention-contacts/prepare"
        )
        actor = headers("alice", "admin")
        request = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "recipient": "sample_uz",
            "template": "onboarding_help",
        }
        saved = await client.post(prepare, headers=actor, json=request)
        assert saved.status_code == 200
        assert saved.json()["self_approval_forbidden"] is True
        executor = app.state.operation_workspace_retention_contacts._contacts._executor
        reads = sum(item.target_reads for item in executor.executors.values())
        stopped = await client.put(CHANGE, headers=actor, json={"confirmed": True, "enabled": True})
        assert stopped.status_code == 200 and stopped.json()["capability_kill_switch"] is True
        assert (await client.post(prepare, headers=actor, json=request)).json() == saved.json()
        denied = await client.post(
            prepare, headers=actor, json={**request, "request_id": str(uuid4())}
        )
        assert denied.status_code == 423
        assert sum(item.target_reads for item in executor.executors.values()) == reads
        assert sum(item.dispatch_count for item in executor.executors.values()) == 0
        # The standard API recognizes the same registered control, not a new handler.
        resumed = await client.put(STANDARD, headers=actor, json={"enabled": False})
        assert resumed.status_code == 200
        assert (await client.get(URL, headers=actor)).json()["items"][0][
            "capability_kill_switch"
        ] is False
        assert (
            await client.post(prepare, headers=actor, json={**request, "request_id": str(uuid4())})
        ).status_code == 200
        await client.put(CHANGE, headers=actor, json={"confirmed": True, "enabled": True})
        async with app.state.operation_workspace_retention_contacts._store._sessions() as session:
            before = [
                (row.action_id, row.payload)
                for row in (await session.scalars(select(RetentionContactRow))).all()
            ]
    restarted = setup(monkeypatch, path, self_approval=False)
    async with (
        restarted.router.lifespan_context(restarted),
        AsyncClient(transport=ASGITransport(app=restarted), base_url="http://test") as client,
    ):
        assert (await client.get(URL, headers=headers("v", "viewer"))).json()["items"][0][
            "capability_kill_switch"
        ] is True
        async with (
            restarted.state.operation_workspace_retention_contacts._store._sessions() as session
        ):
            after = [
                (row.action_id, row.payload)
                for row in (await session.scalars(select(RetentionContactRow))).all()
            ]
        assert sorted(before) == sorted(after)
    get_settings.cache_clear()


async def test_control_roles_strict_confirmation_and_sibling_scope(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    app = setup(monkeypatch, tmp_path / "rbac.db")
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        body = {"confirmed": True, "enabled": True}
        for role in ["viewer", "operator", "approver"]:
            assert (
                await client.put(CHANGE, headers=headers(role, role), json=body)
            ).status_code == 403
        for invalid in [
            {"enabled": True},
            {**body, "confirmed": 1},
            {**body, "enabled": "true"},
            {**body, "send": True},
        ]:
            assert (
                await client.put(CHANGE, headers=headers("a", "admin"), json=invalid)
            ).status_code == 422
        for path in [
            URL + "/growth-agent/" + CONTROL,
            URL + "/retention-agent/retention.engagement.analyze",
            URL + "/retention-agent/unknown",
        ]:
            assert (
                await client.put(path, headers=headers("a", "admin"), json=body)
            ).status_code == 404
        assert (
            await client.put(CHANGE, headers=headers("a", "admin"), json=body)
        ).status_code == 200
        agent = (
            await client.get(
                "/api/v1/admin/operation/agents/retention-agent", headers=headers("v", "viewer")
            )
        ).json()
        assert not any(agent["capability_kill_switches"].values())
        events = (
            await client.get(
                "/api/v1/admin/operation/audit-events?limit=100", headers=headers("v", "viewer")
            )
        ).json()["items"]
        assert any(
            row["event_type"] == "kill_switch_changed"
            and row["capability_key"] == CONTROL
            and row["actor_id"] == "a"
            for row in events
        )
    get_settings.cache_clear()


async def test_global_default_is_observed_without_overriding_owning_control(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    app = setup(monkeypatch, tmp_path / "global.db")
    monkeypatch.setenv("OPERATION_GLOBAL_KILL_SWITCH", "true")
    get_settings.cache_clear()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        observed = (await client.get(URL, headers=headers("v", "viewer"))).json()["items"][0]
        assert observed["global_kill_switch"] is True
        assert observed["capability_kill_switch"] is False
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "key",
    [
        "global_kill_switch",
        "agent_kill_switch:retention-agent",
        f"capability_kill_switch:retention-agent:{CONTROL}",
    ],
)
async def test_new_stopped_turn_has_no_native_contact_tool_but_retains_observable_context(
    monkeypatch: MonkeyPatch, tmp_path: Path, key: str
) -> None:
    app = setup(monkeypatch, tmp_path / "admission.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_CONTACT_TOOL_PROPOSALS_ENABLED", "true")
    monkeypatch.setenv("OPERATION_WORKSPACE_CONTACT_TOOL_CONTINUATIONS_ENABLED", "true")
    get_settings.cache_clear()

    class ObservedModel:
        calls = 0

        async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
            payload = json.loads(context)
            assert "retention_contacts" not in payload["allowed_next_actions"]
            assert payload["manual_contact_control_at_admission"]["registered"] is True
            assert any(
                payload["manual_contact_control_at_admission"][scope]
                for scope in ["global_kill_switch", "agent_kill_switch", "capability_kill_switch"]
            )
            self.calls += 1
            return ChatTurnOutput(
                "Контактный sandbox остановлен; сообщений не отправляю.", "fake", 10, 10
            )

    async with app.router.lifespan_context(app):
        chats = app.state.operation_chat_service
        model = ObservedModel()
        chats._model = model
        topic = await chats.create(
            "alice",
            TopicCreate(agent_id="retention-agent", product="mana", title="Stopped sandbox"),
        )
        await app.state.operation_admin_service.repository.set_control(
            key=key, enabled=True, updated_by="admin", updated_at=chats._clock.now()
        )
        request = MessageCreate(
            request_id=uuid4(),
            execution_mode="agent",
            message="Проверь вымышленный контактный sandbox MANA.",
        )
        result = await app.state.operation_workspace_service.send("alice", topic.topic_id, request)
        assert result.turn.next_action == "none" and result.turn.contact_tool_contract is None
        assert (
            await app.state.operation_workspace_service.send("alice", topic.topic_id, request)
        ).turn == result.turn
        assert model.calls == 1
    get_settings.cache_clear()


async def test_personal_control_change_requires_csrf_even_for_an_admin(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    from tests.test_contact_peer_reviews import scenario

    async with scenario(monkeypatch, tmp_path / "csrf.db") as (app, client, ids, _, _):
        body = {"confirmed": True, "enabled": True}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as bare:
            request = client.build_request(
                "PUT", CHANGE, headers=headers(ids[0], "admin"), json=body
            )
            await client.event_hooks["request"][0](request)
            request.headers.pop("X-CSRF-Token")
            assert (await bare.send(request)).status_code == 403
        changed = await client.put(CHANGE, headers=headers(ids[0], "admin"), json=body)
        assert changed.status_code == 200 and changed.json()["capability_kill_switch"] is True
