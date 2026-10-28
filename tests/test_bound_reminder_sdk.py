"""Pinned OpenAI transport with fictional raw responses, never live inference."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from openai import AsyncOpenAI

from app.mana_ai.application.bound_reminder_review import (
    BOUND_REMINDER_PREPARE_ACK,
    bound_reminder_review_instructions,
    bound_reminder_review_schema,
)
from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt
from app.mana_ai.application.direct_reminders import direct_reminder_request
from app.mana_ai.application.parent_languages import parent_language
from app.mana_ai.domain.bound_reminder_review import BoundReminderDecision
from app.mana_ai.domain.client_retention import RetentionIntent
from app.mana_ai.domain.client_upsell import UpsellScope
from app.mana_ai.domain.family_agents import FamilyQuestion
from app.mana_ai.domain.parent_reminders import ReminderScope
from app.services.parent_chat_model import OpenAIParentChatModel
from tests.test_bound_reminder_review_contract import NOW, request, review_scope
from tests.test_parent_chat_adapters import settings


def prompt() -> ChatPrompt:
    manager = review_scope(reminders_enabled=True)
    reminder = ReminderScope(
        now=NOW,
        default_timezone="UTC",
        timezone_basis="application_default_requires_confirmation",
        active=(),
        pending=None,
    )
    full = {
        "profiles": [
            {"child_id": 17, "name": "Тестовая дочь", "age": 8, "connected": True},
            {"child_id": 18, "name": "Тестовый сын", "age": 5, "connected": False},
        ],
        "limitations": ["Exact fictional full context, no current telemetry."],
        "assistant_reminders": reminder.model_dump(mode="json"),
        "parent_context": {"language": "ru", "qualification": "Untouched profile context."},
    }
    latest = "Напомни завтра в 10:00 купить тетради для дочери."
    frozen = direct_reminder_request(
        latest, now=NOW, timezone="UTC", timezone_basis="application_default_requires_confirmation"
    )
    assert frozen is not None
    return ChatPrompt(
        instructions=bound_reminder_review_instructions(manager),
        messages=(
            ("user", json.dumps(full, ensure_ascii=False, separators=(",", ":"))),
            ("user", "Сохраните все слова предыдущего условия."),
            ("assistant", "Ранее обсуждали точные условия."),
            ("user", latest),
        ),
        structured_reply=True,
        slot_reply=True,
        response_language="ru",
        reminder_scope=reminder,
        manager_scope=manager,
        minimum_output_tokens=128,
        input_presentation=1,
        bound_reminder_request=frozen,
    )


def payload(decision: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": "completed",
        "model": "fake-model",
        "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        "output": [
            {"type": "reasoning", "summary": [{"text": "Private provider material."}]},
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {"decision": decision if decision is not None else {"kind": "prepare"}}
                        ),
                    }
                ],
            },
        ],
    }


def text_payload(text: str) -> dict[str, Any]:
    result = payload()
    result["output"][1]["content"][0]["text"] = text
    return result


@asynccontextmanager
async def fake_model(
    result: dict[str, Any],
) -> AsyncIterator[tuple[OpenAIParentChatModel, list[dict[str, Any]]]]:
    calls: list[dict[str, Any]] = []

    def handle(http_request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(http_request.content))
        response = (
            {"input_tokens": 100} if http_request.url.path.endswith("/input_tokens") else result
        )
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            content=json.dumps(response, ensure_ascii=True).encode("ascii"),
        )

    sdk = AsyncOpenAI(
        api_key="non-issued-test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    try:
        yield OpenAIParentChatModel(settings(), client=sdk), calls
    finally:
        await sdk.close()


def assert_no_other_actions(receipt: ChatModelReceipt) -> None:
    assert receipt.manager_handoff is None and receipt.native_manager_invocation is None
    assert receipt.upsell_choice is None and receipt.upsell_enquiry is None
    assert receipt.upsell_question_text is None and receipt.reminder_question_text is None
    assert receipt.notice_id is None and receipt.question_id is None


async def test_count_and_generation_retain_identical_complete_input_and_bound_schema() -> None:
    original = prompt()
    original_messages = original.messages
    async with fake_model(payload()) as (model, calls):
        assert await model.count_input(original) == 100
        receipt = await model.respond(original, max_output_tokens=256)
    assert len(calls) == 2
    assert calls[0]["model"] == calls[1]["model"] == "fake-model"
    assert calls[0]["instructions"] == calls[1]["instructions"] == original.instructions
    assert (
        calls[0]["input"]
        == calls[1]["input"]
        == [{"role": role, "content": content} for role, content in original_messages]
    )
    assert "Тестовая дочь" in calls[1]["input"][0]["content"]
    assert "Тестовый сын" in calls[1]["input"][0]["content"]
    assert calls[0]["text"] == calls[1]["text"]
    assert original.manager_scope is not None
    assert calls[1]["text"]["format"] == {
        "type": "json_schema",
        "name": "parent_touch_bound_reminder_review",
        "strict": True,
        "schema": bound_reminder_review_schema(original.manager_scope),
    }
    assert original.messages == original_messages and original.minimum_output_tokens == 128
    assert calls[1]["max_output_tokens"] == 256 and calls[1]["store"] is False
    assert calls[1]["service_tier"] == "default"
    assert calls[0]["truncation"] == calls[1]["truncation"] == "disabled"
    for sent in calls:
        assert "tools" not in sent and "tool_choice" not in sent
    assert receipt.usage.total == 150 and receipt.completed


async def test_prepare_uses_the_exact_frozen_candidate_and_internal_ack_only() -> None:
    original = prompt()
    assert original.bound_reminder_request is not None
    async with fake_model(payload()) as (model, calls):
        receipt = await model.respond(original, max_output_tokens=256)
    assert len(calls) == 1 and receipt.usage.total == 150 and receipt.completed
    assert receipt.bound_reminder_decision == BoundReminderDecision(
        kind="prepare", body=None, question=None
    )
    assert receipt.reminder_candidate is original.bound_reminder_request.candidate
    assert receipt.reminder_candidate.content == "купить тетради для дочери."
    assert receipt.answer == BOUND_REMINDER_PREPARE_ACK and receipt.clarification_question is None
    assert_no_other_actions(receipt)


@pytest.mark.parametrize(
    ("body", "question"),
    [
        ("Я не могу помочь с таким напоминанием.", None),
        ("Нужно уточнить задачу.", "Что именно вы имеете в виду?"),
        ("", "Что именно вы имеете в виду?"),
    ],
)
async def test_reply_and_essential_question_normalize_without_a_candidate(
    body: str, question: str | None
) -> None:
    async with fake_model(payload({"kind": "reply", "body": body, "question": question})) as (
        model,
        calls,
    ):
        receipt = await model.respond(prompt(), max_output_tokens=256)
    assert len(calls) == 1 and receipt.completed and receipt.usage.total == 150
    assert receipt.bound_reminder_decision == BoundReminderDecision(
        kind="reply", body=body, question=question
    )
    assert receipt.reminder_candidate is None
    assert receipt.answer == "\n\n".join(part for part in (body.strip(), question) if part)
    assert receipt.clarification_question == question
    assert_no_other_actions(receipt)


@pytest.mark.parametrize(
    "change",
    [
        "old_full_payload",
        "fake_task",
        "fake_date",
        "extra_field",
        "unknown_kind",
        "missing_kind",
        "missing_decision",
        "missing_question",
        "missing_body",
        "grant_metadata",
        "execution_receipt",
        "wrong_language",
        "wrong_question_language",
        "incomplete",
        "failed",
        "cancelled",
        "deep_json",
        "surrogate_body",
        "surrogate_question",
        "model_surrogate",
        "model_nonascii",
        "model_empty",
        "model_not_string",
        "model_too_long",
        "model_control",
        "output_cap",
        "function_call",
    ],
)
async def test_invalid_output_keeps_verified_raw_usage_once_without_retry_or_action(
    change: str,
) -> None:
    result = payload()
    decision: dict[str, Any] = {"kind": "prepare"}
    if change == "old_full_payload":
        result = text_payload(
            json.dumps(
                {
                    "body": "",
                    "question": None,
                    "notice_communicated": False,
                    "reminder": request().candidate.model_dump(mode="json"),
                }
            )
        )
    elif change in {"fake_task", "fake_date"}:
        decision["content" if change == "fake_task" else "due_at"] = "model-owned replacement"
    elif change in {"extra_field", "grant_metadata", "execution_receipt"}:
        decision[
            {
                "extra_field": "unused",
                "grant_metadata": "grant_authorized",
                "execution_receipt": "execution_receipt",
            }[change]
        ] = True
    elif change == "unknown_kind":
        decision["kind"] = "send"
    elif change == "missing_kind":
        decision = {}
    elif change == "missing_decision":
        result = text_payload("{}")
    elif change in {"missing_question", "missing_body"}:
        decision = {"kind": "reply", "body": "Не могу помочь.", "question": None}
        del decision["question" if change == "missing_question" else "body"]
    elif change in {"wrong_language", "wrong_question_language"}:
        decision = {
            "kind": "reply",
            "body": "Hello. I cannot help your child with that reminder."
            if change == "wrong_language"
            else "",
            "question": "Hello. What does your child mean?"
            if change == "wrong_question_language"
            else None,
        }
        assert parent_language(decision["body"] or decision["question"]) == "en"
    elif change in {"incomplete", "failed", "cancelled"}:
        result["status"] = change
    elif change == "deep_json":
        result = text_payload("[" * 16000 + "]" * 16000)
    elif change in {"surrogate_body", "surrogate_question"}:
        decision = {"kind": "reply", "body": "Не могу помочь.", "question": None}
        decision["body" if change == "surrogate_body" else "question"] = (
            "\ud800" if change == "surrogate_body" else "\ud800?"
        )
    elif change.startswith("model_"):
        result["model"] = {
            "model_surrogate": "\ud800",
            "model_nonascii": "модель",
            "model_empty": "",
            "model_not_string": False,
            "model_too_long": "m" * 129,
            "model_control": "fake-model\ncontrol",
        }[change]
    elif change == "output_cap":
        result["usage"] = {"input_tokens": 100, "output_tokens": 257, "total_tokens": 357}
    elif change == "function_call":
        result["output"] = [
            {
                "type": "function_call",
                "name": "approve_reminder",
                "call_id": "call_fake",
                "arguments": "{}",
            }
        ]
    else:
        raise AssertionError("Unknown fictional invalid case")
    if change not in {"old_full_payload", "missing_decision", "deep_json", "function_call"}:
        result["output"][1]["content"][0]["text"] = json.dumps({"decision": decision})
    async with fake_model(result) as (model, calls):
        receipt = await model.respond(prompt(), max_output_tokens=256)
    assert len(calls) == 1 and receipt.usage.total == result["usage"]["total_tokens"]
    assert not receipt.completed and receipt.failure_code is not None
    assert receipt.bound_reminder_decision is None
    assert receipt.reminder_candidate is None and receipt.answer is None
    assert receipt.clarification_question is None
    assert_no_other_actions(receipt)
    if change.startswith("model_"):
        assert receipt.model == "fake-model"


@pytest.mark.parametrize("status", ["queued", "in_progress"])
async def test_provisional_zero_receipt_cannot_authorize_prepare_or_release_unknown_usage(
    status: str,
) -> None:
    result = payload()
    result["status"] = status
    result["usage"] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    async with fake_model(result) as (model, calls):
        with pytest.raises(ValueError, match="terminal"):
            await model.respond(prompt(), max_output_tokens=256)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        "manager_missing",
        "route",
        "child_safety",
        "upsell",
        "reminder_missing",
        "question",
        "upsell_scope",
        "retention_scope",
        "native_protocol",
        "safety_review",
    ],
)
@pytest.mark.parametrize("operation", ["count", "generate"])
async def test_nonowning_prompt_rejects_before_any_http(change: str, operation: str) -> None:
    original = prompt()
    manager = original.manager_scope
    assert manager is not None
    if change == "manager_missing":
        original = replace(original, manager_scope=None)
    elif change in {"route", "child_safety", "upsell"}:
        original = replace(original, manager_scope=manager.model_copy(update={"stage": change}))
    elif change == "reminder_missing":
        original = replace(original, reminder_scope=None)
    elif change == "question":
        original = replace(
            original,
            question=FamilyQuestion(
                question_id=uuid4(),
                parent_id="4",
                child_id=None,
                scope="parent",
                information_key="parent.intent",
                question="Уточните?",
                reason="Fictional slot.",
                priority=1,
                status="awaiting_reply",
                observed_at=NOW,
                created_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            ),
        )
    elif change == "upsell_scope":
        original = replace(original, upsell_scope=UpsellScope())
    elif change == "retention_scope":
        original = replace(
            original,
            retention_scope=RetentionIntent(
                intent_id=uuid4(),
                parent_id="4",
                request_id=uuid4(),
                anchor_turn_id=1,
                last_parent_message_at=NOW - timedelta(days=14),
                admitted_at=NOW,
                expires_at=NOW + timedelta(minutes=3),
                language="ru",
                contact_digest="a" * 64,
            ),
        )
    elif change == "native_protocol":
        original = replace(
            original,
            manager_scope=manager.model_copy(update={"compact_decision_protocol": 2}),
        )
    elif change == "safety_review":
        original = replace(original, safety_parent_review=True)
    async with fake_model(payload()) as (model, calls):
        with pytest.raises(ValueError):
            if operation == "count":
                await model.count_input(original)
            else:
                await model.respond(original, max_output_tokens=256)
    assert calls == []


async def test_question_requires_the_captured_clarification_bit() -> None:
    original = prompt()
    assert original.manager_scope is not None
    original = replace(
        original,
        manager_scope=original.manager_scope.model_copy(update={"clarifications_enabled": False}),
    )
    async with fake_model(
        payload({"kind": "reply", "body": "", "question": "Что вы имеете в виду?"})
    ) as (model, calls):
        assert await model.count_input(original) == 100
        receipt = await model.respond(original, max_output_tokens=256)
    question_schema = calls[0]["text"]["format"]["schema"]["$defs"]["BoundReminderReplyWire"][
        "properties"
    ]["question"]
    assert question_schema == {"type": "null"}
    assert len(calls) == 2 and not receipt.completed and receipt.usage.total == 150


async def test_legacy_prompt_without_bound_metadata_keeps_the_old_reminder_schema() -> None:
    original = replace(prompt(), bound_reminder_request=None)
    old_reply = {
        "body": "Не могу помочь.",
        "question": None,
        "notice_communicated": False,
        "reminder": None,
    }
    async with fake_model(text_payload(json.dumps(old_reply))) as (model, calls):
        assert await model.count_input(original) == 100
        receipt = await model.respond(original, max_output_tokens=256)
    assert calls[0]["text"] == calls[1]["text"]
    old_schema = calls[0]["text"]["format"]["schema"]
    assert set(old_schema["properties"]) == {"body", "question", "notice_communicated", "reminder"}
    assert "decision" not in old_schema["properties"]
    assert receipt.completed and receipt.answer == "Не могу помочь."
    assert receipt.bound_reminder_decision is None and receipt.usage.total == 150
    assert_no_other_actions(receipt)
