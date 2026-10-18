"""Real SDK/HTTP/SQL with fictional adults only; no live provider or paid inference."""

import asyncio
import json
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from openai import AsyncOpenAI
from pytest import MonkeyPatch
from sqlalchemy import select

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.domain.chat import ChatTurn, TopicCreate
from app.mana_operation_ai.domain.enums import AgentStatus
from app.mana_operation_ai.infrastructure.persistence.models import (
    ChatTurnRow,
    ContactPreparationRow,
    CostReservationRow,
)
from tests.test_contact_tool_continuation import configure
from tests.test_inference_failures import wire
from tests.test_native_contact_tool import tool
from tests.test_operation_api import headers

BASE = "/api/v1/admin/operation/workspace"
ADMIN = headers("alice", "admin")


def configure_loop(monkeypatch: MonkeyPatch, path: Path, *, enabled: bool = True) -> FastAPI:
    configure(monkeypatch, path)
    monkeypatch.setenv("OPERATION_WORKSPACE_CONTACT_TOOL_LOOPS_ENABLED", str(enabled).lower())
    get_settings.cache_clear()
    return create_app()


@pytest.mark.parametrize(
    "failure",
    [
        "missing_usage",
        "pending",
        "timeout",
        "same_recipient",
        "same_call_id",
        "provider_receipt",
        "raw_reasoning",
        "summary",
        "lost_prefix",
        "stop",
        "cancel",
    ],
)
async def test_invalid_or_unknown_next_decision_never_prepares_or_replays(
    monkeypatch: MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    path = tmp_path / "failed-loop.db"
    app = configure_loop(monkeypatch, path)
    calls = 0
    topic_id = ""
    first_id = ""

    async def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        if calls == 1:
            return httpx.Response(200, json=selected_wire(body["model"], "sample_ru", 1))
        payload = selected_wire(body["model"], "sample_uz", 2)
        if failure == "missing_usage":
            payload.pop("usage")
        elif failure == "pending":
            payload["status"] = "in_progress"
        elif failure == "timeout":
            raise httpx.ReadTimeout("PRIVATE unknown model receipt", request=request)
        elif failure == "same_recipient":
            payload = selected_wire(body["model"], "sample_ru", 2)
        elif failure == "same_call_id":
            payload["output"][-1]["call_id"] = "call_loop_1"
        elif failure == "provider_receipt":
            payload["output"].append(
                {
                    "type": "function_call_output",
                    "call_id": "call_loop_2",
                    "output": "PRIVATE delivered",
                }
            )
        elif failure == "raw_reasoning":
            payload["output"][-2]["content"] = [{"type": "reasoning_text", "text": "PRIVATE raw"}]
        elif failure == "summary":
            payload["output"][-2]["summary"] = [{"type": "summary_text", "text": "PRIVATE summary"}]
        elif failure == "stop":
            await app.state.operation_repository.set_agent_status(
                "retention-agent", AgentStatus.PAUSED
            )
        elif failure == "cancel":
            repo = app.state.operation_chat_service.repository
            origin = await repo.turn("alice", topic_id, first_id)
            await repo.cancel("alice", topic_id, origin.contact_reply_turn_id)
        return httpx.Response(200, json=payload)

    if failure == "lost_prefix":
        from app.mana_operation_ai.domain.contact_continuation import window_digest
        from app.mana_operation_ai.infrastructure.contact_loop_model import capture_loop_append

        def changed_capture(window: Any, **kwargs: Any) -> Any:
            result = capture_loop_append(window, **kwargs)
            items = json.loads(result.items)
            items.pop(0)
            encoded = json.dumps(items, ensure_ascii=False)
            return result.model_copy(
                update={
                    "items": encoded,
                    "digest": window_digest(
                        result.model, result.effort, result.instructions, result.context, encoded
                    ),
                }
            )

        monkeypatch.setattr(
            "app.mana_operation_ai.infrastructure.chat_model.capture_loop_append", changed_capture
        )

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        await inject(app, transport)
        topic = await app.state.operation_chat_service.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="No retry"),
        )
        topic_id = topic.topic_id
        first_reply = await client.post(
            f"{BASE}/topics/{topic_id}/messages",
            headers=ADMIN,
            json={
                "request_id": str(uuid4()),
                "message": "Проверь два вымышленных контакта по очереди.",
                "execution_mode": "agent",
            },
        )
        first = first_reply.json()["turn"]
        first_id = first["turn_id"]
        action = await prepare(client, topic_id, first)
        url = action_url(topic_id, first_id)
        action = await decide(client, url, action)
        response = await client.post(url + "/continue", headers=ADMIN, json=continuation(action))
        assert response.status_code == 200, response.text
        child = response.json()
        assert child["status"] == ("cancelled" if failure == "cancel" else "failed")
        assert child["contact_preparation"] is None and child["next_action"] == "none"
        assert "PRIVATE" not in json.dumps(child) and calls == 2
        for _ in range(2):
            repeat = await client.post(url + "/continue", headers=ADMIN, json=continuation(action))
            assert repeat.json() == child and calls == 2
        child_url = action_url(topic_id, child["turn_id"])
        assert (await client.get(child_url, headers=ADMIN)).status_code == 403
        async with app.state.operation_database.session_factory() as session:
            assert len((await session.scalars(select(ContactPreparationRow))).all()) == 1
            costs = (await session.scalars(select(CostReservationRow))).all()
            assert len(costs) == 2
            assert sum(row.actual is None for row in costs) == int(
                failure in {"missing_usage", "pending", "timeout"}
            )
        catalog = app.state.operation_workspace_retention_contacts._contacts._executor
        assert sum(item.target_reads for item in catalog.executors.values()) == 2
        assert sum(item.dispatch_count for item in catalog.executors.values()) == 1
    restarted = configure_loop(monkeypatch, path, enabled=False)
    async with (
        restarted.router.lifespan_context(restarted),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://test"
        ) as client,
    ):
        observed = await client.post(url + "/continue", headers=ADMIN, json=continuation(action))
        assert observed.json() == child and calls == 2
    get_settings.cache_clear()


@pytest.mark.parametrize("state", ["uncertain", "rejected", "refused"])
async def test_nonverified_action_terminates_loop_without_another_tool(
    monkeypatch: MonkeyPatch, tmp_path: Path, state: str
) -> None:
    app = configure_loop(monkeypatch, tmp_path / "closed-loop.db")
    calls = 0

    async def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        if calls == 1:
            return httpx.Response(200, json=selected_wire(body["model"], "sample_ru", 1))
        assert body["tool_choice"] == "none"
        output = next(item for item in body["input"] if item["type"] == "function_call_output")
        assert json.loads(output["output"])["status"] == state
        return httpx.Response(200, json=wire(body["model"], "chat"))

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        await inject(app, transport)
        topic = await app.state.operation_chat_service.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Closed action")
        )
        reply = await client.post(
            f"{BASE}/topics/{topic.topic_id}/messages",
            headers=ADMIN,
            json={
                "request_id": str(uuid4()),
                "message": "Проверь два вымышленных контакта по очереди.",
                "execution_mode": "agent",
            },
        )
        first = reply.json()["turn"]
        catalog = app.state.operation_workspace_retention_contacts._contacts._executor
        if state == "refused":
            for executor in catalog.executors.values():
                executor.replace_target(executor._target.model_copy(update={"consent": False}))
        action = await prepare(client, topic.topic_id, first)
        url = action_url(topic.topic_id, first["turn_id"])
        if state == "uncertain":
            for executor in catalog.executors.values():
                executor.lose_ack = True
                executor.receipt_unavailable = True
            action = await decide(client, url, action)
        elif state == "rejected":
            action = await decide(client, url, action, approve=False)
        assert action["status"] == state
        child = await client.post(url + "/continue", headers=ADMIN, json=continuation(action))
        assert child.status_code == 200, child.text
        assert child.json()["status"] == "completed" and child.json()["next_action"] == "none"
        assert child.json()["contact_preparation"] is None and calls == 2
    get_settings.cache_clear()


@pytest.mark.parametrize("boundary", ["loop_disabled", "paused", "default_self_approval"])
async def test_new_loop_boundary_cannot_grant_another_action(
    monkeypatch: MonkeyPatch, tmp_path: Path, boundary: str
) -> None:
    app = configure_loop(monkeypatch, tmp_path / "denied-loop.db")
    calls = 0

    async def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, json=selected_wire(json.loads(request.content)["model"], "sample_ru", 1)
        )

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        await inject(app, transport)
        topic = await app.state.operation_chat_service.create(
            "alice",
            TopicCreate(agent_id="retention-agent", product="mana", title="No inherited authority"),
        )
        reply = await client.post(
            f"{BASE}/topics/{topic.topic_id}/messages",
            headers=ADMIN,
            json={
                "request_id": str(uuid4()),
                "message": "Проверь два вымышленных контакта по очереди.",
                "execution_mode": "agent",
            },
        )
        first = reply.json()["turn"]
        url = action_url(topic.topic_id, first["turn_id"])
        action = await prepare(client, topic.topic_id, first)
        bridge = app.state.operation_workspace_retention_contacts
        if boundary == "default_self_approval":
            bridge._contacts._allow_self_approval = False
            denied = await client.post(
                url + f"/{action['action_id']}/decision",
                headers=ADMIN,
                json={
                    "request_id": str(uuid4()),
                    "confirmed": True,
                    "approve": True,
                    "fingerprint": action["fingerprint"],
                    "reason": "Cannot approve own intent",
                },
            )
            assert denied.status_code == 403
        else:
            action = await decide(client, url, action)
        if boundary == "loop_disabled":
            app.state.operation_contact_result_continuation._loop_enabled = False
            bridge._loops_enabled = False
        elif boundary == "paused":
            await app.state.operation_repository.set_agent_status(
                "retention-agent", AgentStatus.PAUSED
            )
        assert not (await client.get(url, headers=ADMIN)).json()["continuation_available"]
        denied = await client.post(url + "/continue", headers=ADMIN, json=continuation(action))
        assert (
            denied.status_code
            == {"loop_disabled": 503, "paused": 423, "default_self_approval": 409}[boundary]
        )
        assert calls == 1
        catalog = bridge._contacts._executor
        assert sum(item.target_reads for item in catalog.executors.values()) == (
            1 if boundary == "default_self_approval" else 2
        )
        assert sum(item.dispatch_count for item in catalog.executors.values()) == (
            0 if boundary == "default_self_approval" else 1
        )
    get_settings.cache_clear()


async def inject(
    app: FastAPI, transport: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]
) -> None:
    gateway = app.state.operation_chat_service._model
    await gateway.close()
    gateway._client = AsyncOpenAI(
        api_key="test-contact-loop-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )


async def test_inflight_result_is_observable_and_stoppable_before_model_receipt(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    app = configure_loop(monkeypatch, tmp_path / "observed-loop.db")
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        model = json.loads(request.content)["model"]
        if calls == 1:
            return httpx.Response(200, json=selected_wire(model, "sample_ru", 1))
        entered.set()
        await release.wait()
        return httpx.Response(200, json=selected_wire(model, "sample_uz", 2))

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        await inject(app, transport)
        topic = await app.state.operation_chat_service.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Observe only")
        )
        topic_id = topic.topic_id
        initial = await client.post(
            f"{BASE}/topics/{topic_id}/messages",
            headers=ADMIN,
            json={
                "request_id": str(uuid4()),
                "message": "Проверь два вымышленных контакта.",
                "execution_mode": "agent",
            },
        )
        first = initial.json()["turn"]
        action = await prepare(client, topic_id, first)
        url = action_url(topic_id, first["turn_id"])
        action = await decide(client, url, action)
        pending = asyncio.create_task(
            client.post(url + "/continue", headers=ADMIN, json=continuation(action))
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            history = f"{BASE}/topics/{topic_id}/messages?limit=20"
            for _ in range(2):
                observed = await client.get(history, headers=ADMIN)
                assert observed.status_code == 200, observed.text
                turns = observed.json()["turns"]
                assert len(turns) == 2 and turns[-1]["status"] == "thinking"
                assert "PRIVATE" not in observed.text
                assert (
                    "contact_loop" not in observed.text and "encrypted_content" not in observed.text
                )
            child_id = turns[-1]["turn_id"]
            # This local fixture enables development actors; the default actor
            # still cannot observe Alice's private topic.
            assert (await client.get(history)).status_code == 404
            assert (await client.get(history, headers=headers("bob", "admin"))).status_code == 404
            replay = await client.post(url + "/continue", headers=ADMIN, json=continuation(action))
            assert replay.json()["turn_id"] == child_id and not pending.done() and calls == 2
            stop_url = f"/api/v1/admin/operation/chat/topics/{topic_id}/messages/{child_id}/stop"
            for _ in range(2):
                stopped = await client.post(stop_url, headers=ADMIN)
                assert stopped.status_code == 200 and stopped.json()["status"] == "cancelled"
            assert not pending.done() and calls == 2
        finally:
            release.set()
            finished = await asyncio.wait_for(pending, timeout=10)
        assert finished.json()["status"] == "cancelled"
        assert finished.json()["contact_preparation"] is None
        assert finished.json()["next_action"] == "none"
        assert (await client.get(url, headers=ADMIN)).json()["items"][0]["status"] == "verified"
        async with app.state.operation_database.session_factory() as session:
            costs = (await session.scalars(select(CostReservationRow))).all()
            assert len(costs) == 2 and all(row.actual is not None for row in costs)
            assert len((await session.scalars(select(ContactPreparationRow))).all()) == 1
        replay = await client.post(url + "/continue", headers=ADMIN, json=continuation(action))
        assert replay.json() == finished.json() and calls == 2
        catalog = app.state.operation_workspace_retention_contacts._contacts._executor
        assert sum(item.dispatch_count for item in catalog.executors.values()) == 1
    get_settings.cache_clear()


def selected_wire(model: str, recipient: str, position: int) -> dict[str, Any]:
    payload = wire(model, "chat")
    payload["output"][0]["content"][0]["text"] = "PRIVATE invalid accompanying prose"
    call = tool()
    call.update(
        id=f"fc_loop_{position}",
        call_id=f"call_loop_{position}",
        arguments=json.dumps({"recipient": recipient, "template": "onboarding_help"}),
    )
    payload["output"] += [
        {
            "id": f"rs_loop_{position}",
            "type": "reasoning",
            "summary": [],
            "encrypted_content": f"test-opaque-loop-{position}",
        },
        call,
    ]
    return payload


def action_url(topic_id: str, turn_id: str) -> str:
    return f"{BASE}/topics/{topic_id}/messages/{turn_id}/retention-contacts"


def continuation(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": str(uuid4()),
        "confirmed": True,
        "action_id": action["action_id"],
        "action_fingerprint": action["fingerprint"],
        "revision": action["revision"],
    }


async def prepare(client: httpx.AsyncClient, topic_id: str, turn: dict[str, Any]) -> dict[str, Any]:
    choice = turn["contact_preparation"]
    body = {
        "request_id": str(uuid4()),
        "confirmed": True,
        "recipient": choice["recipient"],
        "template": choice["template"],
        "selection_fingerprint": choice["selection_fingerprint"],
    }
    url = action_url(topic_id, turn["turn_id"])
    response = await client.post(url + "/prepare", headers=ADMIN, json=body)
    assert response.status_code == 200, response.text
    repeated = await client.post(
        url + "/prepare", headers=ADMIN, json={**body, "request_id": str(uuid4())}
    )
    assert repeated.json() == response.json()
    return cast(dict[str, Any], response.json())


async def decide(
    client: httpx.AsyncClient, url: str, action: dict[str, Any], *, approve: bool = True
) -> dict[str, Any]:
    response = await client.post(
        url + f"/{action['action_id']}/decision",
        headers=ADMIN,
        json={
            "request_id": str(uuid4()),
            "confirmed": True,
            "approve": approve,
            "fingerprint": action["fingerprint"],
            "reason": "Explicit fictional fixture review",
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


@pytest.mark.parametrize("language,third_call", [("ru", False), ("uz", False), ("ru", True)])
async def test_two_requests_preserve_pairing_conditions_restart_and_one_consumer(
    monkeypatch: MonkeyPatch, tmp_path: Path, language: str, third_call: bool
) -> None:
    path = tmp_path / "loop.db"
    app = configure_loop(monkeypatch, path)
    requests: list[dict[str, Any]] = []
    root_context = ""
    continuation_entered = asyncio.Event()
    allow_continuation = asyncio.Event()

    async def transport(request: httpx.Request) -> httpx.Response:
        nonlocal root_context
        body = json.loads(request.content)
        requests.append(body)
        if isinstance(body["input"], str):
            context = json.loads(body["input"])
            assert context["contact_tool_contract"] == "native_contact_preparation_v3"
            if "Дополнительное условие" in context["message"]:
                return httpx.Response(200, json=wire(body["model"], "chat"))
            root_context = body["input"]
            return httpx.Response(200, json=selected_wire(body["model"], "sample_ru", 1))
        assert body["input"][0]["content"] == root_context
        assert (
            "Дополнительное условие: никаких скидок; только два вымышленных взрослых."
            in json.dumps(body["input"], ensure_ascii=False)
        )
        assert json.loads(root_context)["response_language"] == language
        outputs = [item for item in body["input"] if item["type"] == "function_call_output"]
        calls = [item for item in body["input"] if item["type"] == "function_call"]
        assert [item["call_id"] for item in outputs] == [item["call_id"] for item in calls]
        assert all(json.loads(item["output"])["status"] == "verified" for item in outputs)
        assert "PRIVATE" not in json.dumps(body["input"])
        if len(outputs) == 1:
            assert body["tool_choice"] == "auto" and not body["parallel_tool_calls"]
            assert body["tools"][0]["parameters"]["properties"]["recipient"]["enum"] == [
                "sample_uz"
            ]
            continuation_entered.set()
            await asyncio.wait_for(allow_continuation.wait(), timeout=10)
            return httpx.Response(200, json=selected_wire(body["model"], "sample_uz", 2))
        assert len(outputs) == 2 and body["tool_choice"] == "none"
        assert "test-opaque-loop-1" in json.dumps(body["input"])
        assert "test-opaque-loop-2" in json.dumps(body["input"])
        if third_call:
            return httpx.Response(200, json=selected_wire(body["model"], "sample_ru", 3))
        return httpx.Response(200, json=wire(body["model"], "chat"))

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        await inject(app, transport)
        topic = await app.state.operation_chat_service.create(
            "alice",
            TopicCreate(agent_id="retention-agent", product="mana", title="Two fictional actions"),
        )
        body = {
            "request_id": str(uuid4()),
            "message": "Проверь два вымышленных контакта по очереди, без скидок.",
            "execution_mode": "agent",
            "response_language": language,
        }
        response = await client.post(
            f"{BASE}/topics/{topic.topic_id}/messages", headers=ADMIN, json=body
        )
        assert response.status_code == 200, response.text
        first = response.json()["turn"]
        ChatTurn.model_validate(first)  # Public response needs no private continuation fields.
        assert first["contact_preparation"]["contract"] == "native_contact_preparation_v3"
        assert "contact_loop" not in first and len(requests) == 1
        added = await client.post(
            f"{BASE}/topics/{topic.topic_id}/messages",
            headers=ADMIN,
            json={
                **body,
                "request_id": str(uuid4()),
                "message": (
                    "Дополнительное условие: никаких скидок; только два вымышленных взрослых."
                ),
            },
        )
        assert added.status_code == 200 and len(requests) == 2
        url = action_url(topic.topic_id, first["turn_id"])
        action = await prepare(client, topic.topic_id, first)
        assert not (await client.get(url, headers=ADMIN)).json()["continuation_available"]
        early = await client.post(url + "/continue", headers=ADMIN, json=continuation(action))
        assert early.status_code == 409 and len(requests) == 2
        action = await decide(client, url, action)
        assert action["status"] == "verified"

        async def observe_pending() -> httpx.Response:
            try:
                await asyncio.wait_for(continuation_entered.wait(), timeout=10)
                observed = await client.post(
                    url + "/continue", headers=ADMIN, json=continuation(action)
                )
                assert observed.status_code == 200, observed.text
                assert observed.json()["status"] == "thinking"
                assert observed.json()["contact_preparation"] is None
                return observed
            finally:
                allow_continuation.set()

        # The first gathered response deliberately observes the in-flight child;
        # only the owning inference request waits for the terminal result.
        replies = await asyncio.gather(
            observe_pending(),
            client.post(url + "/continue", headers=ADMIN, json=continuation(action)),
        )
        assert all(reply.status_code == 200 for reply in replies), [reply.text for reply in replies]
        observed = replies[0].json()
        second = replies[1].json()
        assert second["status"] == "completed"
        assert observed["turn_id"] == second["turn_id"] and len(requests) == 3
        assert second["contact_preparation"]["recipient"] == "sample_uz"
        assert second["next_action"] == "retention_contacts"
        ChatTurn.model_validate(second)
        assert "PRIVATE" not in json.dumps(second) and "contact_loop" not in second
        catalog = app.state.operation_workspace_retention_contacts._contacts._executor
        assert sum(item.target_reads for item in catalog.executors.values()) == 2
        assert sum(item.dispatch_count for item in catalog.executors.values()) == 1
        async with app.state.operation_database.session_factory() as session:
            saved = await session.get(ChatTurnRow, second["turn_id"])
            assert saved and len(saved.workspace_metadata["contact_loop"]["receipts"]) == 1
            assert (
                "contact_loop" not in saved.payload and "contact_loop" not in saved.context_metadata
            )

    restarted = configure_loop(monkeypatch, path)
    async with (
        restarted.router.lifespan_context(restarted),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://test"
        ) as client,
    ):
        await inject(restarted, transport)
        observed = await client.post(url + "/continue", headers=ADMIN, json=continuation(action))
        assert observed.json() == second and len(requests) == 3
        second_url = action_url(topic.topic_id, second["turn_id"])
        second_action = await prepare(client, topic.topic_id, second)
        second_action = await decide(client, second_url, second_action)
        assert second_action["status"] == "verified"
        final = await client.post(
            second_url + "/continue", headers=ADMIN, json=continuation(second_action)
        )
        assert final.status_code == 200, final.text
        assert final.json()["status"] == ("failed" if third_call else "completed")
        assert final.json()["next_action"] == "none"
        assert final.json()["contact_preparation"] is None and len(requests) == 4
        replay = await client.post(
            second_url + "/continue", headers=ADMIN, json=continuation(second_action)
        )
        assert replay.json() == final.json() and len(requests) == 4
        recent = await restarted.state.operation_chat_service.repository.recent_conversation(
            "alice", topic.topic_id, before=ChatTurn.model_validate(final.json()).created_at
        )
        assert recent.turns[-1].contact_preparation.recipient == "sample_uz"
        async with restarted.state.operation_database.session_factory() as session:
            assert len((await session.scalars(select(ContactPreparationRow))).all()) == 2
            costs = (await session.scalars(select(CostReservationRow))).all()
            assert len(costs) == 4 and all(row.actual is not None for row in costs)
        catalog = restarted.state.operation_workspace_retention_contacts._contacts._executor
        assert sum(item.target_reads for item in catalog.executors.values()) == 2
        assert sum(item.dispatch_count for item in catalog.executors.values()) == 1
    get_settings.cache_clear()
