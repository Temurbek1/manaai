"""Real SDK, HTTP, SQL and owning fake lifecycle; no paid calls or live sources."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from openai import AsyncOpenAI
from pytest import MonkeyPatch
from sqlalchemy import select

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.domain.chat import MessageCreate, TopicCreate
from app.mana_operation_ai.domain.contact_continuation import contact_result_meaning
from app.mana_operation_ai.domain.retention_contact import ContactStatus
from app.mana_operation_ai.infrastructure.persistence.models import ChatTurnRow, CostReservationRow
from tests.test_inference_failures import wire
from tests.test_native_contact_tool import tool
from tests.test_operation_api import headers
from tests.test_workspace_retention_contacts import setup


@pytest.mark.parametrize(
    "status,step",
    [
        ("proposed", "separate_human_approval"),
        ("dispatching", "observe_without_redispatch"),
        ("uncertain", "observe_without_redispatch"),
        ("refused", "none"),
        ("rejected", "none"),
        ("verified", "none"),
    ],
)
def test_preparation_result_is_not_a_pending_preparation_request(
    status: ContactStatus, step: str
) -> None:
    meaning = contact_result_meaning(status)
    assert meaning.preparation_recorded is True and meaning.preparation_is_approval is False
    assert meaning.next_human_step == step
    if status == "proposed":
        assert "Do not ask for preparation again" in meaning.status_explanation


def configure(monkeypatch: MonkeyPatch, path: Path) -> FastAPI:
    setup(monkeypatch, path)
    monkeypatch.setenv("OPERATION_WORKSPACE_CONTACT_TOOL_PROPOSALS_ENABLED", "true")
    monkeypatch.setenv("OPERATION_WORKSPACE_CONTACT_TOOL_CONTINUATIONS_ENABLED", "true")
    get_settings.cache_clear()
    return create_app()


@pytest.mark.parametrize("defect", ["raw", "summary", "missing_opaque", "provider_receipt"])
async def test_invalid_private_window_keeps_verified_cost_without_a_request(
    monkeypatch: MonkeyPatch, tmp_path: Path, defect: str
) -> None:
    app = configure(monkeypatch, tmp_path / "invalid-window.db")
    calls = 0

    async def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = wire(json.loads(request.content)["model"], "chat")
        reasoning: dict[str, object] = {
            "id": "rs_test",
            "type": "reasoning",
            "summary": [],
            "encrypted_content": "opaque-test",
            "content": [],
        }
        if defect == "raw":
            reasoning["content"] = [{"type": "reasoning_text", "text": "PRIVATE raw reasoning"}]
        elif defect == "summary":
            reasoning["summary"] = [{"type": "summary_text", "text": "PRIVATE summary"}]
        elif defect == "missing_opaque":
            reasoning.pop("encrypted_content")
        payload["output"] += [reasoning, tool()]
        if defect == "provider_receipt":
            payload["output"].append(
                {
                    "type": "function_call_output",
                    "call_id": "call_synthetic_1",
                    "output": "Already sent",
                }
            )
        return httpx.Response(200, json=payload)

    async with app.router.lifespan_context(app):
        gateway = app.state.operation_chat_service._model
        await gateway.close()
        gateway._client = AsyncOpenAI(
            api_key="test-key",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )
        topic = await app.state.operation_chat_service.create(
            "alice",
            TopicCreate(agent_id="retention-agent", product="mana", title="Rejected private state"),
        )
        request = MessageCreate(
            request_id=uuid4(), message="Test only fictional contact.", execution_mode="agent"
        )
        result = await app.state.operation_workspace_service.send("alice", topic.topic_id, request)
        assert result.turn.status == "failed" and result.turn.contact_model_window is None
        assert result.turn.contact_preparation is None and "PRIVATE" not in result.turn.answer
        replay = await app.state.operation_workspace_service.send("alice", topic.topic_id, request)
        assert replay == result and calls == 1
        async with app.state.operation_database.session_factory() as session:
            costs = (await session.scalars(select(CostReservationRow))).all()
            assert len(costs) == 1 and costs[0].actual is not None
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "failure,state",
    [
        (None, "proposed"),
        ("missing_usage", "proposed"),
        ("pending", "proposed"),
        ("bad_text", "proposed"),
        ("new_call", "proposed"),
        ("timeout", "proposed"),
        ("cancel", "proposed"),
        (None, "verified"),
        (None, "uncertain"),
    ],
)
async def test_exact_native_result_loop_and_unknown_no_replay(
    monkeypatch: MonkeyPatch, tmp_path: Path, failure: str | None, state: str
) -> None:
    path = tmp_path / "contact-loop.db"
    app = configure(monkeypatch, path)
    requests: list[dict[str, object]] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        payload = wire(body["model"], "chat")
        if len(requests) == 1:
            assert body["include"] == ["reasoning.encrypted_content"]
            payload["output"][0]["content"][0]["text"] = "PRIVATE invalid prose"
            payload["output"] += [
                {
                    "id": "rs_test",
                    "type": "reasoning",
                    "summary": [],
                    "content": [],
                    "encrypted_content": "opaque-synthetic-only",
                },
                tool(),
            ]
        elif isinstance(body["input"], list):
            assert body["store"] is False and body["tool_choice"] == "none"
            assert body["parallel_tool_calls"] is False
            items = body["input"]
            assert items[0]["content"] == original_context
            assert "Не готовить другие сообщения" in items[-1]["content"]
            assert "opaque-synthetic-only" in json.dumps(items)
            calls = [item for item in items if item["type"] == "function_call"]
            outputs = [item for item in items if item["type"] == "function_call_output"]
            assert len(calls) == len(outputs) == 1
            assert calls[0]["call_id"] == outputs[0]["call_id"] == "call_synthetic_1"
            result = json.loads(outputs[0]["output"])
            assert (
                result["action_id"] == action["action_id"]
                and result["revision"] == action["revision"]
            )
            assert result["delivered"] is False and result["business_outcome"] == "not_measured"
            assert result["message"]["language"] == "uz" and result["status"] == state
            assert result["lifecycle"]["preparation_recorded"] is True
            assert result["lifecycle"]["next_human_step"] == (
                "separate_human_approval"
                if state == "proposed"
                else "observe_without_redispatch"
                if state == "uncertain"
                else "none"
            )
            assert "account_ref" not in outputs[0]["output"] and "PRIVATE" not in json.dumps(items)
            if failure == "missing_usage":
                payload.pop("usage")
            elif failure == "pending":
                payload["status"] = "in_progress"
            elif failure == "bad_text":
                payload["output"][0]["content"][0]["text"] = "PRIVATE invalid result"
            elif failure == "new_call":
                payload["output"].append(tool())
            elif failure == "timeout":
                raise httpx.ReadTimeout("PRIVATE lost receipt", request=request)
            elif failure == "cancel":
                source = await app.state.operation_chat_service.repository.turn(
                    "alice", topic.topic_id, turn.turn_id
                )
                assert source.contact_reply_turn_id is not None
                await app.state.operation_chat_service.repository.cancel(
                    "alice", topic.topic_id, source.contact_reply_turn_id
                )
        return httpx.Response(200, json=payload)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        gateway = app.state.operation_chat_service._model
        await gateway.close()
        gateway._client = AsyncOpenAI(
            api_key="test-key",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )
        topic = await app.state.operation_chat_service.create(
            "alice", TopicCreate(agent_id="retention-agent", product="mana", title="Tool result")
        )
        parent = await app.state.operation_workspace_service.send(
            "alice",
            topic.topic_id,
            MessageCreate(
                request_id=uuid4(),
                message="Проверь вымышленное сообщение на узбекском.",
                execution_mode="agent",
                response_language="ru",
            ),
        )
        turn = parent.turn
        assert turn.status == "completed" and turn.contact_model_window is not None
        original_context = turn.contact_model_window.window.context
        assert "contact_model_window" not in turn.model_dump(mode="json")
        assert turn.contact_preparation is not None and turn.contact_preparation.contract.endswith(
            "v2"
        )
        history = await app.state.operation_chat_service.repository.recent_conversation(
            "alice", topic.topic_id, before=turn.created_at.replace(year=turn.created_at.year + 1)
        )
        assert history.turns[0].contact_preparation == turn.contact_preparation
        # New actual user conditions must survive the deferred human step.
        await app.state.operation_workspace_service.send(
            "alice",
            topic.topic_id,
            MessageCreate(
                request_id=uuid4(),
                message="Не готовить другие сообщения, только этот тест.",
                execution_mode="agent",
                response_language="ru",
            ),
        )
        url = (
            f"/api/v1/admin/operation/workspace/topics/{topic.topic_id}"
            f"/messages/{turn.turn_id}/retention-contacts"
        )
        preparation = {
            "confirmed": True,
            "recipient": "sample_uz",
            "template": "onboarding_help",
            "selection_fingerprint": turn.contact_preparation.selection_fingerprint,
        }
        action = (
            await client.post(
                url + "/prepare",
                headers=headers("alice", "admin"),
                json={**preparation, "request_id": str(uuid4())},
            )
        ).json()
        duplicate = (
            await client.post(
                url + "/prepare",
                headers=headers("alice", "admin"),
                json={**preparation, "request_id": str(uuid4())},
            )
        ).json()
        assert action == duplicate  # One preparation per original invocation, not per UI nonce.
        if state != "proposed":
            catalog = app.state.operation_workspace_retention_contacts._contacts._executor
            if state == "uncertain":
                for executor in catalog.executors.values():
                    executor.lose_ack = True
                    executor.receipt_unavailable = True
            decision = await client.post(
                url + f"/{action['action_id']}/decision",
                headers=headers("alice", "admin"),
                json={
                    "request_id": str(uuid4()),
                    "confirmed": True,
                    "approve": True,
                    "fingerprint": action["fingerprint"],
                    "reason": "Explicit fictional test",
                },
            )
            assert decision.status_code == 200 and decision.json()["status"] == state
            action = decision.json()
        expected_reads = 2 if state != "proposed" else 1
        expected_sends = 1 if state != "proposed" else 0
        params = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "action_id": action["action_id"],
            "action_fingerprint": action["fingerprint"],
            "revision": action["revision"],
        }
        denial_cases: list[tuple[dict[str, object], str, str, int]] = [
            ({"revision": action["revision"] + 10}, "alice", "admin", 409),
            ({"action_fingerprint": "0" * 64}, "alice", "admin", 409),
            ({}, "bob", "admin", 404),
            ({}, "alice", "viewer", 403),
            ({"confirmed": 1}, "alice", "admin", 422),
        ]
        for overrides, owner, role, expected in denial_cases:
            denied = await client.post(
                url + "/continue", headers=headers(owner, role), json={**params, **overrides}
            )
            assert denied.status_code == expected
        responses = await asyncio.gather(
            *[
                client.post(
                    url + "/continue",
                    headers=headers("alice", "admin"),
                    json={**params, "request_id": str(uuid4())},
                )
                for _ in range(2)
            ]
        )
        assert all(response.status_code == 200 for response in responses)
        assert responses[0].json()["turn_id"] == responses[1].json()["turn_id"]
        page = (await client.get(url, headers=headers("alice", "admin"))).json()
        child_id = page["continuation"]["turn_id"]
        expected_status = (
            "cancelled" if failure == "cancel" else "failed" if failure else "completed"
        )
        assert page["continuation"]["status"] == expected_status
        assert page["continuation_available"] is False
        assert "PRIVATE" not in json.dumps(page) and "contact_model_window" not in json.dumps(page)
        assert len(requests) == 3  # Parent, follow-up, one continuation, never another request.
        async with app.state.operation_database.session_factory() as session:
            stored = await session.get(ChatTurnRow, child_id)
            assert (
                stored
                and stored.workspace_metadata["contact_result"]["action_id"] == action["action_id"]
            )
            assert (
                "contact_result" not in stored.payload
                and "contact_model_window" not in stored.payload
            )
            costs = (await session.scalars(select(CostReservationRow))).all()
            assert len(costs) == 3
            assert sum(item.actual is None for item in costs) == (
                1 if failure in {"missing_usage", "pending", "timeout"} else 0
            )
        bridge = app.state.operation_workspace_retention_contacts
        assert (
            sum(item.target_reads for item in bridge._contacts._executor.executors.values())
            == expected_reads
        )
        assert (
            sum(item.dispatch_count for item in bridge._contacts._executor.executors.values())
            == expected_sends
        )
    restarted = configure(monkeypatch, path)
    async with (
        restarted.router.lifespan_context(restarted),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://test"
        ) as client,
    ):
        # New client remains uninjected: any inference/source redispatch would fail this test.
        replay = await client.post(
            url + "/continue",
            headers=headers("alice", "admin"),
            json={**params, "request_id": str(uuid4())},
        )
        assert replay.status_code == 200 and replay.json()["turn_id"] == child_id
        assert replay.json()["status"] == expected_status
    get_settings.cache_clear()
