"""Frozen contact SQL history, not a new source read, approval or paid model call."""

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.chat_ports import ChatError, SessionContextTooLarge
from app.mana_operation_ai.application.model_continuation import continuation_scope_digest
from app.mana_operation_ai.domain.chat import ChatTopic, ChatTurn, MessageCreate, TopicCreate
from app.mana_operation_ai.domain.enums import UserRole
from app.mana_operation_ai.domain.goals import GoalCreate, OperationGoal
from app.mana_operation_ai.domain.session import SessionMemory
from app.mana_operation_ai.domain.workspace_retention_contacts import (
    WorkspaceContactPrepare,
    WorkspaceContactView,
)
from app.mana_operation_ai.infrastructure.persistence.models import GoalRow
from tests.test_operation_agent_workspace import ToolModel
from tests.test_operation_goals import seed
from tests.test_retention_contact import decision
from tests.test_workspace_retention_contacts import ContactConversation, send, setup

ACTOR = ActorContext(actor_id="alice", role=UserRole.ADMIN)


def test_session_memory_schema_keeps_typed_bounded_contact_history() -> None:
    schema = SessionMemory.model_json_schema(mode="serialization")
    assert schema["properties"]["retention_contacts"]["maxItems"] == 3
    assert schema["properties"]["retention_contacts"]["items"]["$ref"].endswith(
        "/WorkspaceContactHistory"
    )
    assert schema["additionalProperties"] is False


async def prepare(app: FastAPI) -> tuple[ChatTopic, ChatTurn, WorkspaceContactView]:
    topic, turn, _ = await send(app)
    bridge = app.state.operation_workspace_retention_contacts
    view = await bridge.prepare(
        ACTOR,
        topic.topic_id,
        turn.turn_id,
        WorkspaceContactPrepare(
            request_id=uuid4(), confirmed=True, recipient="sample_uz", template="onboarding_help"
        ),
    )
    return topic, turn, view


@pytest.mark.parametrize("unknown", [False, True])
async def test_event_cutoff_retains_original_status_without_provider_observation(
    monkeypatch: MonkeyPatch, tmp_path: Path, unknown: bool
) -> None:
    app = setup(monkeypatch, tmp_path / "event-cutoff.db")
    async with app.router.lifespan_context(app):
        topic, _, proposal = await prepare(app)
        bridge = app.state.operation_workspace_retention_contacts
        clock = bridge._contacts._clock
        executors = bridge._contacts._executor.executors.values()
        for executor in executors:
            executor.lose_ack = unknown
            executor.receipt_unavailable = unknown
        cutoff = clock.now() + timedelta(microseconds=1)
        clock.current += timedelta(seconds=1)
        result = await bridge._contacts.decide(
            ACTOR, proposal.action_id, decision(proposal.fingerprint)
        )
        assert result.status == ("uncertain" if unknown else "verified")
        reads = [(item.target_reads, item.receipt_reads, item.dispatch_count) for item in executors]
        old = await bridge.history("alice", topic.topic_id, before=cutoff)
        assert len(old) == 1 and old[0].status == "proposed" and old[0].revision == 0
        current = await bridge.history(
            "alice", topic.topic_id, before=clock.now() + timedelta(seconds=1)
        )
        assert current[0].status == result.status and current[0].language == "uz"
        assert current[0].business_outcome == "not_measured"
        assert [
            (item.target_reads, item.receipt_reads, item.dispatch_count) for item in executors
        ] == reads
        assert await bridge._store.history("bob", topic.topic_id, before=cutoff) == []
        rec = await app.state.operation_chat_service.create(
            "alice", TopicCreate(agent_id="retention-agent", product="360rec", title="Separate")
        )
        assert await bridge.history("alice", rec.topic_id, before=cutoff) == []
        encoded = json.dumps([item.model_dump(mode="json") for item in current])
        for forbidden in ("account_ref", "fingerprint", "consent", "reason", "MANA: sozlashda"):
            assert forbidden not in encoded
    get_settings.cache_clear()


async def test_chat_and_goal_freeze_contact_history_on_replay_and_restart(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "frozen-contact-context.db"
    app = setup(monkeypatch, path)
    async with app.router.lifespan_context(app):
        topic, _, proposal = await prepare(app)
        bridge = app.state.operation_workspace_retention_contacts
        clock = bridge._contacts._clock
        clock.current += timedelta(seconds=1)
        await bridge._contacts.decide(ACTOR, proposal.action_id, decision(proposal.fingerprint))
        clock.current += timedelta(seconds=1)
        model = ContactConversation()
        chats, goals = app.state.operation_chat_service, app.state.operation_goal_service
        chats._model = model
        request = MessageCreate(
            request_id=uuid4(),
            message="Explain the previous fictional action.",
            execution_mode="agent",
        )
        turn = await chats.send("alice", topic.topic_id, request, workspace=True)
        assert turn.session_memory is not None
        assert turn.session_memory.retention_contacts[0].status == "verified"
        assert (
            SessionMemory.model_validate(model.contexts[0]["session_memory"])
            .retention_contacts[0]
            .language
            == "uz"
        )
        goal_request = GoalCreate(
            request_id=uuid4(),
            objective="Analyze retention without contacting customers.",
            constraints="No source reads or sends are approved.",
            execution_mode="agent",
        )
        goal = await goals.create("alice", topic.topic_id, goal_request)
        assert goal.session_memory is not None and goal.session_memory.retention_contacts
        assert goal.approved_capability is None and not goal.read_attempted
        assert goal.tools == [] and goal.accounted_microusd == 0
        async with app.state.operation_database.session_factory() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row and row.workspace_payload
            assert row.workspace_payload["version"] == 15
            assert row.workspace_payload["contact_profile_version"] == 2
            assert "session_memory" not in row.payload and row.payload["status"] == "cancelled"
        frozen_turn, frozen_goal = turn.model_dump_json(), goal.model_dump_json()
        changed = goal.model_copy(deep=True)
        assert changed.session_memory is not None
        changed.session_memory.retention_contacts[0].language = "ru"
        assert continuation_scope_digest("alice", goal) != continuation_scope_digest(
            "alice", changed
        )
        with pytest.raises(ChatError, match="контактный контекст"):
            await goals.repository.save("alice", goal, changed)
        old = await goals.repository.create(
            "alice",
            await chats.create(
                "alice",
                TopicCreate(agent_id="retention-agent", product="mana", title="No contacts"),
            ),
            GoalCreate(request_id=uuid4(), objective="Original task with no contact capture."),
        )
        with pytest.raises(ChatError, match="контактный контекст"):
            await goals.repository.save(
                "alice", old, old.model_copy(update={"session_memory": goal.session_memory})
            )
        with pytest.raises(ChatError, match="контактный контекст"):
            await goals.repository.save(
                "alice", goal, goal.model_copy(update={"session_memory": None})
            )
        assert await goals.repository.save(
            "alice", old, old.model_copy(update={"status": "cancelled"})
        )
        monkeypatch.setattr(
            goals._session_context,
            "read",
            AsyncMock(side_effect=AssertionError("Replay recaptured history")),
        )
        assert (
            await chats.send("alice", topic.topic_id, request, workspace=True)
        ).model_dump_json() == frozen_turn
        assert (
            await goals.create("alice", topic.topic_id, goal_request)
        ).model_dump_json() == frozen_goal
        assert len(model.contexts) == 1
    restarted = setup(monkeypatch, path)
    async with restarted.router.lifespan_context(restarted):
        chats, goals = (
            restarted.state.operation_chat_service,
            restarted.state.operation_goal_service,
        )
        assert (
            await chats.repository.turn("alice", topic.topic_id, turn.turn_id)
        ).model_dump_json() == frozen_turn
        assert (await goals.repository.get("alice", goal.goal_id)).model_dump_json() == frozen_goal
        goal_model = ToolModel()
        goals._model = goal_model
        await seed(goals)
        for _ in range(6):
            if not await goals.tick():
                break
        completed = await goals.repository.get("alice", goal.goal_id)
        assert completed.status == "completed", completed.waiting_reason
        assert completed.session_memory == goal.session_memory
        assert all(
            OperationGoal.model_validate(item["goal"]).session_memory == goal.session_memory
            for item in goal_model.contexts
        )
        assert (
            goal_model.contexts
            and not completed.read_attempted
            and completed.approved_capability is None
        )
        restarted_catalog = (
            restarted.state.operation_workspace_retention_contacts._contacts._executor
        )
        assert sum(item.dispatch_count for item in restarted_catalog.executors.values()) == 0
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "corruption",
    ["old_version", "missing_profile", "wrong_profile", "empty_history", "future_history"],
)
async def test_contact_checkpoint_protocol_corruption_fails_closed(
    monkeypatch: MonkeyPatch, tmp_path: Path, corruption: str
) -> None:
    app = setup(monkeypatch, tmp_path / "contact-protocol.db")
    async with app.router.lifespan_context(app):
        topic, _, _ = await prepare(app)
        bridge = app.state.operation_workspace_retention_contacts
        bridge._contacts._clock.current += timedelta(seconds=1)
        goals = app.state.operation_goal_service
        goal = await goals.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(), objective="Keep exact contact context.", execution_mode="agent"
            ),
        )
        async with app.state.operation_database.session_factory.begin() as session:
            row = await session.get(GoalRow, goal.goal_id)
            assert row and row.workspace_payload
            payload = json.loads(json.dumps(row.workspace_payload))
            if corruption == "old_version":
                payload["version"] = 2
                payload.pop("contact_profile_version")
            elif corruption == "missing_profile":
                payload.pop("contact_profile_version")
            elif corruption == "wrong_profile":
                payload["contact_profile_version"] = 14
            elif corruption == "empty_history":
                payload["goal"]["session_memory"]["retention_contacts"] = []
            else:
                memory = payload["goal"]["session_memory"]
                memory["retention_contacts"][0]["at"] = memory["captured_at"]
            row.workspace_payload = payload
        with pytest.raises(ChatError) as failed:
            await goals.repository.get("alice", goal.goal_id)
        assert failed.value.status == 503
    get_settings.cache_clear()


async def test_context_event_limit_refuses_prefix_and_disabled_lane_avoids_sql(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    app = setup(monkeypatch, tmp_path / "contact-event-bound.db")
    async with app.router.lifespan_context(app):
        topic, _, proposal = await prepare(app)
        bridge = app.state.operation_workspace_retention_contacts
        clock = bridge._contacts._clock
        clock.current += timedelta(seconds=1)
        await bridge._contacts.decide(ACTOR, proposal.action_id, decision(proposal.fingerprint))
        original = await bridge._contacts.get(ACTOR, proposal.action_id)
        assert original.turn_id is not None
        second = await bridge.prepare(
            ACTOR,
            topic.topic_id,
            original.turn_id,
            WorkspaceContactPrepare(
                request_id=uuid4(),
                confirmed=True,
                recipient="sample_ru",
                template="onboarding_help",
            ),
        )
        await bridge._contacts.decide(ACTOR, second.action_id, decision(second.fingerprint))
        # Use an explicit smaller test ceiling, never treat its prefix as all history.
        bridge._store._history_event_limit = 4
        with pytest.raises(SessionContextTooLarge):
            await bridge.history("alice", topic.topic_id, before=clock.now() + timedelta(seconds=1))
        bridge._enabled = False
        forbidden = AsyncMock(side_effect=AssertionError("Disabled history read SQL"))
        monkeypatch.setattr(bridge._store, "history", forbidden)
        assert await bridge.history("alice", topic.topic_id, before=clock.now()) == []
        forbidden.assert_not_called()
        empty = SessionMemory(topic_id=topic.topic_id, product="mana", captured_at=clock.now())
        assert "retention_contacts" not in empty.model_dump()
    get_settings.cache_clear()
