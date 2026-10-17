"""Bounded fictional requests after SQL results, never automatic preparation or sends."""

import hashlib
import json
import re
from typing import Literal, cast

from pydantic import ConfigDict, Field, model_validator

from app.mana_operation_ai.domain.contact_continuation import (
    ContactModelWindow,
    ContactPreparationResult,
    contact_result_output,
)
from app.mana_operation_ai.domain.contact_preparation import (
    CONTACT_TOOL,
    CONTACT_TOOL_LOOP_CONTRACT,
    ContactToolRequest,
    contact_selection_fingerprint,
)
from app.mana_operation_ai.domain.models import DomainModel
from app.mana_operation_ai.domain.retention_contact import SandboxRecipient
from app.mana_operation_ai.domain.session import SessionMemory

SESSION_PREFIX = (
    "Frozen same-owner/topic session conditions and historical context, "
    "not fresh evidence or permissions:\n"
)


class ContactLoopReceipt(DomainModel):
    model_config = ConfigDict(frozen=True)
    request: ContactToolRequest
    result: ContactPreparationResult

    @model_validator(mode="after")
    def binding(self) -> "ContactLoopReceipt":
        if (
            self.request.contract != CONTACT_TOOL_LOOP_CONTRACT
            or self.result.selection_fingerprint != self.request.selection_fingerprint
            or self.result.template != self.request.template
            or self.result.message.template != self.request.template
        ):
            raise ValueError("Loop receipt must bind its original native choice and SQL result")
        return self


class ContactLoopState(DomainModel):
    model_config = ConfigDict(frozen=True)
    root_turn_id: str = Field(min_length=1, max_length=100)
    maximum_invocations: Literal[2] = 2
    receipts: tuple[ContactLoopReceipt, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def history(self) -> "ContactLoopState":
        origins = [item.result.origin_turn_id for item in self.receipts]
        recipients = [item.request.recipient for item in self.receipts]
        if (
            (origins and origins[0] != self.root_turn_id)
            or len(set(origins)) != len(origins)
            or len(set(recipients)) != len(recipients)
            or any(item.result.status != "verified" for item in self.receipts[:-1])
            or any(
                later.result.observed_at < earlier.result.observed_at
                for earlier, later in zip(self.receipts, self.receipts[1:], strict=False)
            )
        ):
            raise ValueError(
                "Contact loop history cannot repeat, broaden or bypass a pending action"
            )
        return self

    def allowed_recipients(self) -> tuple[SandboxRecipient, ...]:
        if len(self.receipts) >= self.maximum_invocations or (
            self.receipts and self.receipts[-1].result.status != "verified"
        ):
            return ()
        used = {item.request.recipient for item in self.receipts}
        candidates: tuple[SandboxRecipient, ...] = ("sample_ru", "sample_uz")
        return tuple(item for item in candidates if item not in used)

    def advance(
        self, request: ContactToolRequest, result: ContactPreparationResult
    ) -> "ContactLoopState":
        if request.recipient not in self.allowed_recipients():
            raise ValueError("This invocation cannot continue the frozen contact loop")
        return ContactLoopState(
            root_turn_id=self.root_turn_id,
            receipts=(*self.receipts, ContactLoopReceipt(request=request, result=result)),
        )


def session_condition_item(memory: SessionMemory) -> dict[str, object]:
    return {
        "type": "message",
        "role": "user",
        "content": SESSION_PREFIX + memory.model_dump_json(),
    }


def result_output_item(result: ContactPreparationResult, *, call_id: str) -> dict[str, object]:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": contact_result_output(result),
    }


def loop_result_prefix(
    window: ContactModelWindow,
    loop: ContactLoopState,
    memory: SessionMemory | None,
) -> list[dict[str, object]]:
    """Exact retained items plus the new host-owned SQL result and frozen conditions."""
    if not loop.receipts:
        raise ValueError("A continuation needs its admitted SQL result")
    raw_items = json.loads(window.items, object_pairs_hook=_unique_fields)
    if not isinstance(raw_items, list) or any(not isinstance(item, dict) for item in raw_items):
        raise ValueError("Invalid retained contact loop items")
    items = cast(list[dict[str, object]], raw_items)
    calls = [item for item in items if item.get("type") == "function_call"]
    receipt = loop.receipts[-1]
    if not calls or hashlib.sha256(str(calls[-1].get("call_id")).encode()).hexdigest() != (
        receipt.request.provider_call_sha256
    ):
        raise ValueError("The SQL result lost its pending invocation")
    items.append(result_output_item(receipt.result, call_id=str(calls[-1]["call_id"])))
    if memory is not None:
        topic = json.loads(window.context)["topic"]
        if (memory.topic_id, memory.product) != (topic["topic_id"], "mana"):
            raise ValueError("Conditions belong to another room")
        items.append(session_condition_item(memory))
    return items


def verify_loop_append(
    original: ContactModelWindow,
    continued: ContactModelWindow,
    loop: ContactLoopState,
    memory: SessionMemory | None,
) -> None:
    prefix = loop_result_prefix(original, loop, memory)
    items = json.loads(continued.items, object_pairs_hook=_unique_fields)
    if (
        (original.model, original.effort, original.instructions, original.context)
        != (continued.model, continued.effort, continued.instructions, continued.context)
        or len(items) <= len(prefix)
        or items[: len(prefix)] != prefix
    ):
        raise ValueError("The continuation replaced original context, conditions or SQL receipts")


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate persisted loop field")
        result[key] = value
    return result


def verify_loop_window(
    window: ContactModelWindow,
    request: ContactToolRequest,
    loop: ContactLoopState,
    *,
    owner: str,
    topic_id: str,
    turn_id: str,
    root_message: str,
    response_language: str | None,
) -> None:
    """Verify every original paired receipt, not a provider-authored execution claim."""
    window = ContactModelWindow.model_validate(window.model_dump())
    loop = ContactLoopState.model_validate(loop.model_dump())
    context = json.loads(window.context, object_pairs_hook=_unique_fields)
    captured = ContactLoopState.model_validate(context.get("contact_loop"))
    if (
        captured.receipts
        or captured.root_turn_id != loop.root_turn_id
        or context.get("contact_tool_contract") != CONTACT_TOOL_LOOP_CONTRACT
        or request.contract != CONTACT_TOOL_LOOP_CONTRACT
        or context.get("topic", {}).get("topic_id") != topic_id
        or context.get("topic", {}).get("product") != "mana"
        or context.get("topic", {}).get("agent_id")
        not in {"retention-agent", "operations-orchestrator"}
        or context.get("message") != root_message
        or context.get("response_language") != response_language
        or request.recipient not in loop.allowed_recipients()
        or (not loop.receipts and loop.root_turn_id != turn_id)
    ):
        raise ValueError("Contact loop scope differs from its captured root")
    items = json.loads(window.items, object_pairs_hook=_unique_fields)
    if not isinstance(items, list) or not 1 <= len(items) <= 64:
        raise ValueError("Contact loop item bound exceeded")
    pending: dict[str, object] | None = None
    call_ids: set[str] = set()
    index = 0
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid loop item")
        kind = item.get("type")
        if kind == "reasoning":
            if (
                item.get("content")
                or item.get("summary")
                or not isinstance(item.get("encrypted_content"), str)
                or not item["encrypted_content"]
                or item.get("status") not in (None, "completed")
            ):
                raise ValueError("Only opaque completed reasoning can survive a loop")
        elif kind == "function_call":
            call_id = item.get("call_id")
            arguments = item.get("arguments")
            if (
                pending is not None
                or not isinstance(call_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call_id)
                or call_id in call_ids
                or item.get("name") != CONTACT_TOOL
                or item.get("status") not in (None, "completed")
                or not isinstance(arguments, str)
            ):
                raise ValueError("The pending invocation was replaced or repeated")
            expected = loop.receipts[index].request if index < len(loop.receipts) else request
            expected_turn = (
                loop.receipts[index].result.origin_turn_id
                if index < len(loop.receipts)
                else turn_id
            )
            if (
                hashlib.sha256(call_id.encode()).hexdigest() != expected.provider_call_sha256
                or expected.selection_fingerprint
                != contact_selection_fingerprint(
                    owner,
                    topic_id,
                    expected_turn,
                    expected,
                    expected.provider_call_sha256,
                    contract=CONTACT_TOOL_LOOP_CONTRACT,
                )
                or json.loads(arguments, object_pairs_hook=_unique_fields)
                != {"recipient": expected.recipient, "template": expected.template}
            ):
                raise ValueError("A retained native call differs from its owner-bound choice")
            pending = item
            call_ids.add(call_id)
        elif kind == "function_call_output":
            if (
                pending is None
                or index >= len(loop.receipts)
                or item
                != result_output_item(loop.receipts[index].result, call_id=str(pending["call_id"]))
            ):
                raise ValueError("A retained tool output is not the frozen SQL receipt")
            pending = None
            index += 1
        elif kind == "message":
            content = item.get("content")
            if (
                pending is not None
                or set(item) != {"type", "role", "content"}
                or item.get("role") != "user"
                or not isinstance(content, str)
                or not content.startswith(SESSION_PREFIX)
            ):
                raise ValueError("Only runtime-owned historical conditions belong in a loop")
            memory = SessionMemory.model_validate_json(content[len(SESSION_PREFIX) :])
            if (memory.topic_id, memory.product) != (topic_id, "mana"):
                raise ValueError("Historical conditions belong to another room")
        else:
            raise ValueError("Unsupported contact loop item")
    if pending is None or index != len(loop.receipts) or len(call_ids) != index + 1:
        raise ValueError("The next decision lost its exact pending invocation")
