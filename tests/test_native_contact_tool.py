"""Actual pinned SDK over fake HTTP; no paid model, source read or executor write."""

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI
from pytest import MonkeyPatch
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput
from app.mana_operation_ai.application.inference_errors import InferenceProviderError
from app.mana_operation_ai.domain.chat import MessageCreate
from app.mana_operation_ai.domain.contact_preparation import (
    CONTACT_TOOL,
    CONTACT_TOOL_CONTRACT,
    ContactToolSelection,
)
from app.mana_operation_ai.infrastructure.chat_model import (
    OpenAIConversationModel,
    conversation_input_bound,
)
from app.mana_operation_ai.infrastructure.contact_tool_schema import contact_function_tools
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import SqlAlchemyCostLedger
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import ChatTurnRow, CostReservationRow
from tests.test_inference_failures import wire
from tests.test_operation_api import headers
from tests.test_operation_chat_costs import policy
from tests.test_operation_cost_ledger import Clock
from tests.test_workspace_retention_contacts import setup


def context() -> str:
    return json.dumps(
        {
            "topic": {"product": "mana", "agent_id": "retention-agent"},
            "contact_tool_contract": CONTACT_TOOL_CONTRACT,
            "allowed_next_actions": ["none", "retention_contacts"],
            "message": "Test fictional Uzbek onboarding message",
            "response_language": "ru",
        }
    )


def tool() -> dict[str, object]:
    return {
        "id": "fc_synthetic",
        "type": "function_call",
        "name": CONTACT_TOOL,
        "call_id": "call_synthetic_1",
        "status": "completed",
        "arguments": json.dumps({"recipient": "sample_uz", "template": "onboarding_help"}),
    }


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "extra",
        "duplicate",
        "multiple",
        "unknown_tool",
        "spoofed_receipt",
        "missing_usage",
        "pending",
    ],
)
async def test_native_function_precedes_bad_text_after_verified_usage(
    tmp_path: Path, failure: str | None
) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'native-model.db'}")
    await db.create_schema()
    ledger = SqlAlchemyCostLedger(db, clock=Clock(), limits=policy())
    settings = Settings(
        _env_file=None,
        openai_api_key="test-key",
        operation_workspace_contact_tool_proposals_enabled=True,
    )
    gateway = OpenAIConversationModel(settings, ledger=ledger)
    payload = wire(settings.effective_operation_chat_model, "chat")
    payload["output"][0]["content"][0]["text"] = "PRIVATE-invalid-text-with-a-provider-secret"
    call = tool()
    if failure == "extra":
        call["arguments"] = (
            '{"recipient":"sample_uz","template":"onboarding_help","source_grant":"secret"}'
        )
    elif failure == "duplicate":
        call["arguments"] = (
            '{"recipient":"sample_ru","recipient":"sample_uz","template":"onboarding_help"}'
        )
    elif failure == "unknown_tool":
        call["name"] = "send_real_push"
    payload["output"].append(call)
    if failure == "multiple":
        payload["output"].append(tool())
    elif failure == "spoofed_receipt":
        payload["output"].append(
            {
                "type": "function_call_output",
                "call_id": "call_synthetic_1",
                "output": "Already sent",
            }
        )
    elif failure == "missing_usage":
        payload.pop("usage")
    elif failure == "pending":
        payload["status"] = "in_progress"
    requests: list[dict[str, object]] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=payload)

    await gateway.close()
    gateway._client = AsyncOpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    try:
        if failure:
            with pytest.raises(InferenceProviderError) as denied:
                await gateway.reply(
                    instructions="Synthetic native test", context=context(), owner="alice"
                )
            assert "PRIVATE" not in str(denied.value) and "source_grant" not in str(denied.value)
        else:
            result = await gateway.reply(
                instructions="Synthetic native test", context=context(), owner="alice"
            )
            assert result.contact_selection == ContactToolSelection(
                recipient="sample_uz", template="onboarding_help"
            )
            assert result.next_action == "retention_contacts" and "PRIVATE" not in result.answer
        assert len(requests) == 1 and requests[0]["parallel_tool_calls"] is False
        assert requests[0]["tools"] == contact_function_tools()
        assert conversation_input_bound(
            instructions="Synthetic native test", context=context(), tools=contact_function_tools()
        ) > conversation_input_bound(instructions="Synthetic native test", context=context())
        async with db.session_factory() as session:
            rows = (await session.scalars(select(CostReservationRow))).all()
            assert len(rows) == 1
            assert (rows[0].actual is None) == (failure in {"missing_usage", "pending"})
            if rows[0].actual is not None:
                assert (
                    rows[0].actual["input_tokens"] == 100 and rows[0].actual["output_tokens"] == 50
                )
    finally:
        await gateway.close()
        await db.dispose()


class NativeSelectionModel:
    def __init__(self, *, valid: bool = True) -> None:
        self.calls = 0
        self.valid = valid

    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        self.calls += 1
        assert CONTACT_TOOL in instructions
        payload = json.loads(context)
        eligible = payload.get("contact_tool_contract") == CONTACT_TOOL_CONTRACT
        return ChatTurnOutput(
            "Только тестовая подготовка.",
            "fake-native",
            10,
            10,
            next_action="retention_contacts" if eligible else "none",
            contact_selection=ContactToolSelection(
                recipient="sample_uz", template="onboarding_help"
            )
            if self.valid
            else None,
            contact_call_sha256="a" * 64 if self.valid else None,
        )


async def test_frozen_native_selection_only_prepares_after_exact_human_confirmation(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    app = setup(monkeypatch, tmp_path / "native-action.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_CONTACT_TOOL_PROPOSALS_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        # Create the topic directly; the first native-mode router must return an actual selection.
        from app.mana_operation_ai.domain.chat import TopicCreate

        topic = await app.state.operation_chat_service.create(
            "alice",
            TopicCreate(
                agent_id="retention-agent", product="mana", title="Native fictional selection"
            ),
        )
        model = NativeSelectionModel()
        app.state.operation_chat_service._model = model
        req = MessageCreate(
            request_id=uuid4(), message="Test fictional Uzbek contact.", execution_mode="agent"
        )
        result = await app.state.operation_workspace_service.send("alice", topic.topic_id, req)
        turn = result.turn
        assert (
            turn.status == "completed"
            and turn.contact_preparation is not None
            and result.goal is None
        )
        replay = await app.state.operation_workspace_service.send("alice", topic.topic_id, req)
        assert replay == result and model.calls == 1
        bridge = app.state.operation_workspace_retention_contacts
        assert sum(item.target_reads for item in bridge._contacts._executor.executors.values()) == 0
        url = (
            f"/api/v1/admin/operation/workspace/topics/{topic.topic_id}"
            f"/messages/{turn.turn_id}/retention-contacts"
        )
        page = (await client.get(url, headers=headers("alice", "admin"))).json()
        assert page["preparation_request"]["recipient"] == "sample_uz"
        prepare = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "recipient": "sample_uz",
            "template": "onboarding_help",
            "selection_fingerprint": turn.contact_preparation.selection_fingerprint,
        }
        for mismatch in (
            {"recipient": "sample_ru"},
            {"template": "renewal_reminder"},
            {"selection_fingerprint": None},
        ):
            assert (
                await client.post(
                    url + "/prepare",
                    headers=headers("alice", "admin"),
                    json={**prepare, **mismatch},
                )
            ).status_code == 409
        assert sum(item.target_reads for item in bridge._contacts._executor.executors.values()) == 0
        response = await client.post(
            url + "/prepare", headers=headers("alice", "admin"), json=prepare
        )
        assert response.status_code == 200 and response.json()["message"]["language"] == "uz"
        assert (
            await client.post(url + "/prepare", headers=headers("alice", "admin"), json=prepare)
        ).json() == response.json()
        assert (
            sum(item.dispatch_count for item in bridge._contacts._executor.executors.values()) == 0
        )
        assert sum(item.target_reads for item in bridge._contacts._executor.executors.values()) == 1
        async with app.state.operation_database.session_factory() as session:
            row = await session.get(ChatTurnRow, turn.turn_id)
            assert (
                row
                and "contact_preparation" not in row.payload
                and "contact_tool_contract" not in row.context_metadata
            )
            assert (
                row.workspace_metadata["contact_preparation"]["selection_fingerprint"]
                == turn.contact_preparation.selection_fingerprint
            )
    restarted = setup(monkeypatch, tmp_path / "native-action.db")
    async with restarted.router.lifespan_context(restarted):
        assert (
            await restarted.state.operation_chat_service.repository.turn(
                "alice", topic.topic_id, turn.turn_id
            )
        ).contact_preparation == turn.contact_preparation
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "agent,product",
    [("growth-agent", "mana"), ("technical-agent", "mana"), ("retention-agent", "360rec")],
)
async def test_selection_cannot_escape_room_scope(
    monkeypatch: MonkeyPatch, tmp_path: Path, agent: str, product: str
) -> None:
    app = setup(monkeypatch, tmp_path / "native-scope.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_CONTACT_TOOL_PROPOSALS_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        from app.mana_operation_ai.domain.chat import TopicCreate

        topic = await app.state.operation_chat_service.create(
            "alice",
            TopicCreate.model_validate(
                {"agent_id": agent, "product": product, "title": "Wrong scope"}
            ),
        )
        app.state.operation_chat_service._model = NativeSelectionModel()
        result = await app.state.operation_workspace_service.send(
            "alice",
            topic.topic_id,
            MessageCreate(
                request_id=uuid4(), message="Fictional contact test.", execution_mode="agent"
            ),
        )
        assert result.turn.status == "failed" and result.turn.contact_preparation is None
    get_settings.cache_clear()


async def test_native_text_card_fails_without_starting_a_second_stream(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    setup(monkeypatch, tmp_path / "native-text-card.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_CONTACT_TOOL_PROPOSALS_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        from app.mana_operation_ai.domain.chat import TopicCreate

        topic = await app.state.operation_chat_service.create(
            "alice",
            TopicCreate(agent_id="retention-agent", product="mana", title="Native contract"),
        )
        model = NativeSelectionModel(valid=False)
        app.state.operation_chat_service._model = model

        class NoStream:
            called = False

            async def stream_reply(self, **kwargs):  # type: ignore[no-untyped-def]
                self.called = True
                yield "This stream must not be used"

        stream = NoStream()
        app.state.operation_chat_service._streaming_model = stream
        result = await app.state.operation_workspace_service.send(
            "alice",
            topic.topic_id,
            MessageCreate(
                request_id=uuid4(), message="Explicit fictional test.", execution_mode="agent"
            ),
        )
        assert result.turn.status == "failed" and result.turn.contact_preparation is None
        assert model.calls == 1 and not stream.called
    get_settings.cache_clear()
