"""Actual HTTP/SQL/owning-domain execution, using synthetic scoped sources only."""

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import select

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError, ChatTurnOutput
from app.mana_operation_ai.domain.chat import MessageCreate, TopicCreate
from app.mana_operation_ai.domain.goals import GoalCreate
from app.mana_operation_ai.infrastructure.persistence.models import (
    ActionProposalRow,
    DataSnapshotRow,
    GoalRow,
)
from tests.test_operation_agent_workspace import BASE, configure_workspace
from tests.test_operation_api import headers

ADMIN = "/api/v1/admin/operation"


class ActionConversation:
    def __init__(self) -> None:
        self.contexts: list[dict[str, object]] = []

    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        self.contexts.append(json.loads(context))
        return ChatTurnOutput(
            "Покажу предложения для согласования.", "fake", 10, 10, next_action="approvals"
        )


async def proposals(client: AsyncClient) -> None:
    h = headers("author", "admin")
    config = (
        await client.get(
            f"{ADMIN}/agents/growth-agent/configurations?capability_key=growth.funnel.analyze",
            headers=h,
        )
    ).json()["items"][0]["values"]
    config["experiment_mode"] = "sandbox"
    assert (
        await client.post(
            f"{ADMIN}/agents/growth-agent/configurations?capability_key=growth.funnel.analyze",
            headers=h,
            json={"values": config},
        )
    ).status_code == 201
    assert (
        await client.post(
            f"{ADMIN}/agents/growth-agent/run",
            headers=h,
            json={
                "capability_key": "growth.funnel.analyze",
                "job_type": "analysis",
                "correlation_id": "workspace-action",
                "idempotency_key": "workspace-action",
            },
        )
    ).status_code == 202


async def action_topic(app: object, product: str = "mana", owner: str = "alice") -> tuple[str, str]:
    from fastapi import FastAPI

    assert isinstance(app, FastAPI)
    chat = app.state.operation_chat_service
    chat._model = ActionConversation()
    topic = await chat.create(
        owner,
        TopicCreate(agent_id="operations-orchestrator", product=product, title="Experiment review"),
    )
    turn = await chat.send(
        owner,
        topic.topic_id,
        MessageCreate(
            request_id=uuid4(),
            message="Покажи предложения экспериментов для согласования",
            execution_mode="agent",
        ),
        workspace=True,
    )
    return topic.topic_id, turn.turn_id


def decision(item: dict[str, object], approve: bool = True) -> dict[str, object]:
    return {
        "request_id": str(uuid4()),
        "confirmed": True,
        "approve": approve,
        "reason": "Checked sandbox parameters",
        "fingerprint": item["fingerprint"],
    }


async def test_real_domain_execution_replay_memory_and_legacy_projection(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_workspace(monkeypatch, tmp_path / "actions.db")
    monkeypatch.setenv("OPERATION_DRY_RUN", "false")
    get_settings.cache_clear()
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        await proposals(client)
        topic, turn = await action_topic(app)
        path = f"{BASE}/topics/{topic}/messages/{turn}/actions"
        h = headers("alice", "admin")
        preview = await client.get(path, headers=h)
        assert preview.status_code == 200, preview.text
        item = preview.json()["items"][0]
        assert item["synthetic"] and item["product"] == "mana"
        platform = app.state.operation_experiment_platform
        assert platform.dispatch_count == 0
        payload = decision(item)
        url = f"{path}/{item['proposal_id']}/decision"
        result = await client.post(url, headers=h, json=payload)
        assert result.status_code == 200, result.text
        assert result.json()["execution_status"] == "succeeded"
        assert result.json()["verification_status"] == "verified"
        assert result.json()["business_outcome"] == "not_measured"
        assert platform.dispatch_count == 1
        for _ in range(2):
            replay = await client.post(url, headers=h, json=payload)
            assert replay.json() == result.json()
        assert platform.dispatch_count == 1
        assert (await client.post(url, headers=h, json=decision(item))).status_code == 409
        assert (await client.get(path, headers=headers("bob", "admin"))).status_code == 404
        after = await client.get(path, headers=h)
        assert after.json()["items"][0]["receipt"]["state"] == "resolved"
        # Snapshot retention must not erase a settled human decision or trigger a source read.
        await app.state.operation_repository.cleanup_before(
            app.state.operation_workspace_actions._clock.now() + timedelta(seconds=1)
        )
        assert (await client.get(path, headers=h)).json()["items"][0]["receipt"][
            "parameters"
        ] == item["parameters"]
        assert (await client.post(url, headers=h, json=payload)).json() == result.json()
        chats = app.state.operation_chat_service
        follow = await chats.send(
            "alice",
            topic,
            MessageCreate(
                request_id=uuid4(),
                message="Что произошло после моего решения?",
                execution_mode="agent",
            ),
            workspace=True,
        )
        assert follow.session_memory is not None and len(follow.session_memory.actions) == 1
        assert follow.session_memory.actions[0].verification_status == "verified"
        assert "Checked sandbox parameters" not in str(chats._model.contexts[-1])
        goals = app.state.operation_goal_service
        goal = await goals.create(
            "alice",
            topic,
            GoalCreate(
                request_id=uuid4(),
                objective="Assess historical experiment outcome safely.",
                execution_mode="agent",
            ),
            session_memory=follow.session_memory,
            capture_session_context=False,
        )
        database = app.state.operation_database
        async with database.session_factory() as session:
            row = await session.scalar(select(GoalRow).where(GoalRow.goal_id == goal.goal_id))
            assert row is not None and row.workspace_payload is not None
            assert row.workspace_payload["version"] == 3
            assert "session_memory" not in row.payload and "tools" not in row.payload
        assert (
            await goals.repository.get("alice", goal.goal_id)
        ).session_memory == follow.session_memory
        with pytest.raises(ChatError, match="не найдена"):
            await app.state.operation_workspace_actions.history(
                "bob", topic, before=goals._clock.now() + timedelta(seconds=1)
            )
    get_settings.cache_clear()


@pytest.mark.parametrize("guard", ["stale", "kill", "unverified", "disabled", "wrong_target"])
async def test_source_and_runtime_guards_never_dispatch(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    guard: str,
) -> None:
    configure_workspace(monkeypatch, tmp_path / "source-guards.db")
    monkeypatch.setenv("OPERATION_DRY_RUN", "false")
    get_settings.cache_clear()
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        await proposals(client)
        topic, turn = await action_topic(app)
        path = f"{BASE}/topics/{topic}/messages/{turn}/actions"
        h = headers("alice", "admin")
        item = (await client.get(path, headers=h)).json()["items"][0]
        service = app.state.operation_workspace_actions
        if guard == "stale":
            now = service._clock.now() + timedelta(hours=7)
            monkeypatch.setattr(
                service, "_clock", type("FutureClock", (), {"now": lambda _: now})()
            )
        elif guard == "disabled":
            monkeypatch.setattr(service, "_enabled", False)
        elif guard == "kill":
            from app.mana_operation_ai.application.admin_service import ActorContext
            from app.mana_operation_ai.domain.enums import UserRole

            await app.state.operation_admin_service.set_kill_switch(
                agent_id=None,
                enabled=True,
                actor=ActorContext("test-admin", UserRole.ADMIN),
            )
        elif guard == "wrong_target":
            async with app.state.operation_database.session_factory() as session, session.begin():
                row = await session.scalar(
                    select(ActionProposalRow).where(
                        ActionProposalRow.proposal_id == item["proposal_id"]
                    )
                )
                assert row is not None
                row.payload = {**row.payload, "provider_object_id": "wrong-object"}
        else:
            async with app.state.operation_database.session_factory() as session, session.begin():
                row = await session.scalar(select(DataSnapshotRow))
                assert row is not None
                row.payload = {**row.payload, "provider": "unverified"}
        result = await client.post(
            f"{path}/{item['proposal_id']}/decision", headers=h, json=decision(item)
        )
        if guard == "kill":
            assert result.status_code == 200 and result.json()["receipt"]["state"] == "refused"
        else:
            assert (
                result.status_code
                == {"stale": 409, "disabled": 503, "unverified": 403, "wrong_target": 403}[guard]
            )
        assert app.state.operation_experiment_platform.dispatch_count == 0
    get_settings.cache_clear()


async def test_committed_intent_survives_lost_receipt_ack_without_dispatch_retry(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_workspace(monkeypatch, tmp_path / "receipt-ack.db")
    monkeypatch.setenv("OPERATION_DRY_RUN", "false")
    get_settings.cache_clear()
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client,
    ):
        await proposals(client)
        topic, turn = await action_topic(app)
        path = f"{BASE}/topics/{topic}/messages/{turn}/actions"
        h = headers("alice", "admin")
        item = (await client.get(path, headers=h)).json()["items"][0]
        service = app.state.operation_workspace_actions
        failed_finish = AsyncMock(side_effect=RuntimeError("Synthetic lost SQL acknowledgement"))
        monkeypatch.setattr(service._store, "finish", failed_finish)
        payload = decision(item)
        url = f"{path}/{item['proposal_id']}/decision"
        assert (await client.post(url, headers=h, json=payload)).status_code == 500
        observed = (await client.get(path, headers=h)).json()["items"][0]
        assert observed["receipt"]["state"] == "dispatching"
        assert (
            observed["execution_status"] == "succeeded"
            and observed["verification_status"] == "verified"
        )
        replay = await client.post(url, headers=h, json=payload)
        assert replay.status_code == 200 and replay.json() == observed
        failed_finish.assert_awaited_once()
        assert app.state.operation_experiment_platform.dispatch_count == 1
    get_settings.cache_clear()


@pytest.mark.parametrize("approve", [False, True])
async def test_decision_roles_immutable_fingerprint_self_approval_and_product(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    approve: bool,
) -> None:
    configure_workspace(monkeypatch, tmp_path / "guards.db")
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        await proposals(client)
        topic, turn = await action_topic(app)
        path = f"{BASE}/topics/{topic}/messages/{turn}/actions"
        item = (await client.get(path, headers=headers("alice", "admin"))).json()["items"][0]
        payload = decision(item, approve)
        url = f"{path}/{item['proposal_id']}/decision"
        for role in ("viewer", "operator"):
            assert (
                await client.post(url, headers=headers("alice", role), json=payload)
            ).status_code == 403
        assert (
            await client.post(
                url,
                headers=headers("alice", "admin"),
                json={
                    **payload,
                    "fingerprint": "0" * 64,
                },
            )
        ).status_code == 409
        rec_topic, rec_turn = await action_topic(app, product="360rec")
        rec_path = f"{BASE}/topics/{rec_topic}/messages/{rec_turn}/actions"
        assert (await client.get(rec_path, headers=headers("alice", "admin"))).status_code == 403
        author_topic, author_turn = await action_topic(app, owner="author")
        author_path = f"{BASE}/topics/{author_topic}/messages/{author_turn}/actions"
        own_item = (await client.get(author_path, headers=headers("author", "admin"))).json()[
            "items"
        ][0]
        assert own_item["self_approval_forbidden"]
        assert (
            await client.post(
                f"{author_path}/{own_item['proposal_id']}/decision",
                headers=headers("author", "admin"),
                json=decision(own_item),
            )
        ).status_code == 403
        assert app.state.operation_experiment_platform.dispatch_count == 0
        result = await client.post(url, headers=headers("alice", "admin"), json=payload)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == ("dry_run" if approve else "rejected")
        assert app.state.operation_experiment_platform.dispatch_count == 0
    get_settings.cache_clear()


async def test_lost_reply_is_never_redispatched_and_sql_race_has_one_winner(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_workspace(monkeypatch, tmp_path / "lost.db")
    monkeypatch.setenv("OPERATION_DRY_RUN", "false")
    get_settings.cache_clear()
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        await proposals(client)
        topic, turn = await action_topic(app)
        path = f"{BASE}/topics/{topic}/messages/{turn}/actions"
        h = headers("alice", "admin")
        item = (await client.get(path, headers=h)).json()["items"][0]
        service = app.state.operation_workspace_actions
        original = service._admin.decide_approval

        async def lost(**kwargs: object) -> None:
            await original(**kwargs)
            raise RuntimeError("SECRET lost after applied domain write")

        monkeypatch.setattr(service._admin, "decide_approval", lost)
        payload = decision(item)
        url = f"{path}/{item['proposal_id']}/decision"
        results = await asyncio.gather(
            *[client.post(url, headers=h, json=payload) for _ in range(2)]
        )
        assert all(result.status_code == 200 for result in results)
        assert app.state.operation_experiment_platform.dispatch_count == 1
        observed = await client.get(path, headers=h)
        assert observed.json()["items"][0]["receipt"]["state"] == "unknown"
        assert observed.json()["items"][0]["verification_status"] == "verified"
        assert "SECRET" not in observed.text
        await client.post(url, headers=h, json=payload)
        assert app.state.operation_experiment_platform.dispatch_count == 1
        assert service._admin.decide_approval is lost
        forbidden = AsyncMock(side_effect=AssertionError("Observation may not dispatch"))
        monkeypatch.setattr(service._admin, "decide_approval", forbidden)
        await client.get(path, headers=h)
        await client.post(url, headers=h, json=payload)
        forbidden.assert_not_called()
    get_settings.cache_clear()
