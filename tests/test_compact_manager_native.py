"""Actual SDK native envelope and owning SQL lifecycle; all providers fictional."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI

from app.mana_ai.application.chat_ports import ChatPrompt
from app.mana_ai.application.compact_manager_decision import compact_manager_decision_instructions
from app.mana_ai.domain.compact_manager_decision import COMPACT_MANAGER_DECISION_TOOL
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.parent_touch_manager import ParentTouchManagerScope
from app.services.compact_manager_decision_store import SqliteCompactManagerDecisionStore
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.parent_chat_model import OpenAIParentChatModel
from tests.test_mana_chat_lab import Clock
from tests.test_parent_chat_adapters import settings as model_settings
from tests.test_saved_observations import snapshot


def scope(protocol: Literal[1, 2] = 1) -> ParentTouchManagerScope:
    return ParentTouchManagerScope(
        language="ru",
        upsell_enabled=True,
        reminders_enabled=True,
        clarifications_enabled=True,
        tariff_handoff_enabled=True,
        compact_decision_protocol=protocol,
    )


@pytest.mark.parametrize("kind", ["reply", "question", "child_safety", "reminder", "upsell"])
@pytest.mark.parametrize("protocol", [1, 2])
async def test_actual_sdk_one_native_schema_no_second_reply_format_and_raw_usage(
    kind: str, protocol: Literal[1, 2]
) -> None:
    args: dict[str, object] = {
        "kind": "reply" if kind == "question" else kind,
        "body": "Здравствуйте." if kind == "reply" else "" if kind == "question" else None,
        "question": "У вас Android?" if kind == "question" else None,
        "enquiry": None,
    }
    calls = []
    if protocol == 2:
        args = {
            "decision": {
                key: value
                for key, value in args.items()
                if key == "kind"
                or (key in {"body", "question"} and args["kind"] == "reply")
                or (key == "enquiry" and args["kind"] == "upsell")
            }
        }

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "fake-model",
                "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                "output": [
                    {
                        "type": "function_call",
                        "name": COMPACT_MANAGER_DECISION_TOOL,
                        "call_id": "call_native",
                        "status": "completed",
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Ignored accompanying prose"}],
                    },
                ],
            },
        )

    sdk = AsyncOpenAI(
        api_key="fake-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    model = OpenAIParentChatModel(model_settings(), client=sdk)
    prompt = ChatPrompt(
        instructions=compact_manager_decision_instructions(scope(protocol)) or "",
        messages=(("user", "Полный исходный вопрос"),),
        manager_scope=scope(protocol),
        structured_reply=True,
        response_language="ru",
        input_presentation=1,
    )
    try:
        assert await model.count_input(prompt) == 100
        receipt = await model.respond(prompt, max_output_tokens=256)
        assert (
            receipt.completed and receipt.usage.total == 150 and receipt.native_manager_invocation
        )
        assert len(calls) == 2 and calls[0]["input"] == calls[1]["input"]
        assert calls[0]["tools"] == calls[1]["tools"] and len(calls[1]["tools"]) == 1
        assert "format" not in calls[0]["text"] and "format" not in calls[1]["text"]
        assert calls[1]["tool_choice"] == {
            "type": "function",
            "name": COMPACT_MANAGER_DECISION_TOOL,
        }
        if kind in {"reply", "question"}:
            assert receipt.manager_handoff is None and receipt.answer
            assert "Ignored" not in receipt.answer
        else:
            assert (
                receipt.manager_handoff
                and receipt.manager_handoff.target == kind
                and receipt.answer is None
            )
    finally:
        await sdk.close()


@pytest.mark.parametrize(
    "change",
    [
        "missing_call",
        "wrong_name",
        "missing_field",
        "double_call",
        "wrong_language",
        "bad_id",
        "deep_json",
        "surrogate",
        "bad_model_utf8",
        "question_language",
        "incomplete",
        "output_cap",
    ],
)
@pytest.mark.parametrize("protocol", [1, 2])
async def test_invalid_native_output_keeps_verified_usage_without_text_fallback(
    change: str, protocol: Literal[1, 2]
) -> None:
    args: dict[str, object] = {
        "kind": "reply",
        "body": "Hello. I can help you.",
        "question": None,
        "enquiry": None,
    }
    if change != "wrong_language":
        args["body"] = "Здравствуйте."
    if change == "missing_field":
        args.pop("enquiry" if protocol == 1 else "body")
    if change == "surrogate":
        args["body"] = "\ud800"
    if change == "question_language":
        args["body"], args["question"] = "", "How can I help your child?"
    if protocol == 2:
        args = {"decision": {key: value for key, value in args.items() if key != "enquiry"}}
    call = {
        "type": "function_call",
        "name": "other" if change == "wrong_name" else COMPACT_MANAGER_DECISION_TOOL,
        "call_id": "bad id" if change == "bad_id" else "call_native",
        "arguments": "[" * 16000 + "]" * 16000 if change == "deep_json" else json.dumps(args),
    }
    prose = {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "Здравствуйте."}],
    }
    output = (
        [prose] if change == "missing_call" else [call, call] if change == "double_call" else [call]
    )

    def handle(request: httpx.Request) -> httpx.Response:
        output_tokens = 300 if change == "output_cap" else 50
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "status": "incomplete" if change == "incomplete" else "completed",
                    "model": "\ud800" if change == "bad_model_utf8" else "fake-model",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": output_tokens,
                        "total_tokens": 100 + output_tokens,
                    },
                    "output": output,
                }
            ),
            headers={"content-type": "application/json"},
        )

    sdk = AsyncOpenAI(
        api_key="fake-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    try:
        receipt = await OpenAIParentChatModel(model_settings(), client=sdk).respond(
            ChatPrompt(
                "Native decision",
                (("user", "Привет"),),
                manager_scope=scope(protocol),
                structured_reply=True,
                response_language="ru",
            ),
            max_output_tokens=256,
        )
        assert not receipt.completed
        assert receipt.usage.total == (400 if change == "output_cap" else 150)
        assert receipt.answer is None
        assert receipt.manager_handoff is None
        assert receipt.native_manager_invocation is None
    finally:
        await sdk.close()


async def setup(path: Path) -> ChatLab:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        replace(
            workspace_options(path, clock=clock, worker_enabled=False),
            tariff_handoff=True,
            compact_inputs=True,
            compact_publication=True,
            compact_manager=True,
            saved_observations=True,
            compact_source_tools=True,
            direct_reminders=True,
            compact_decisions=True,
        )
    )
    await lab.start()
    assert isinstance(lab.store, SqliteCompactManagerDecisionStore)
    return lab


@pytest.mark.parametrize(
    "message,owner",
    [
        ("Привет", "reply"),
        ("Как помочь ребёнку учиться?", "child_safety"),
        ("Тариф на 90 дней до 200000 UZS", "upsell"),
    ],
)
async def test_one_same_chat_native_audit_and_owning_lifecycle(
    tmp_path: Path, message: str, owner: str
) -> None:
    lab = await setup(tmp_path / owner)
    try:
        req = ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=message)
        await lab.touch.admit_message(req)
        assert await lab.touch.process_reviewed_message()
        if owner == "child_safety":
            job = await lab.safety.process_one()
            assert job and job.status == "completed"
            assert await lab.touch.process_reviewed_message()
        if owner == "upsell":
            assert await lab.touch.process_upsell()
        done = await lab.touch.message_state(LAB_PARENT, req.request_id)
        assert done.phase == "completed" and done.response
        with lab.store._connect() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 44
            assert db.execute("SELECT COUNT(*) FROM compact_manager_decisions").fetchone()[0] == 1
            assert (
                db.execute("SELECT manager_binding FROM parent_publication_captures")
                .fetchone()[0]
                .startswith("native-manager-v2:")
            )
        before = snapshot(lab.store._path)
        assert await lab.touch.admit_message(req) == done
        assert snapshot(lab.store._path) == before
        options = lab.options
        await lab.close()
        lab = ChatLab(options)
        await lab.start()
        assert snapshot(lab.store._path) == before
        assert await lab.touch.admit_message(req) == done
        assert snapshot(lab.store._path) == before
    finally:
        await lab.close()


async def test_missing_paired_capture_never_falls_back_to_legacy_generation(tmp_path: Path) -> None:
    lab = await setup(tmp_path / "missing")
    try:
        req = ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message="Привет")
        await lab.touch.admit_message(req)
        with lab.store._transaction() as db:
            db.execute("DELETE FROM compact_manager_admissions")
        assert not await lab.touch.process_reviewed_message()
        done = await lab.touch.message_state(LAB_PARENT, req.request_id)
        assert done.phase == "failed" and done.error_code == "compact_manager_capture_invalid"
        assert (await lab.state()).history.quota.used_tokens == 0
    finally:
        await lab.close()
