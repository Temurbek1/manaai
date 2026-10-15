"""Stateless Responses pairing. Provider output never creates a SQL tool result."""

import hashlib
import json
from typing import Literal, cast

from openai.types.responses import ResponseInputItemParam
from pydantic import TypeAdapter

from app.mana_operation_ai.domain.contact_continuation import (
    ContactModelWindow,
    ContactPreparationResult,
    window_digest,
)
from app.mana_operation_ai.domain.contact_preparation import CONTACT_TOOL
from app.mana_operation_ai.infrastructure.contact_tool_schema import parse_contact_function

ITEMS = TypeAdapter(list[ResponseInputItemParam])


def _pending_items(values: object) -> list[ResponseInputItemParam]:
    if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
        raise ValueError("Expected exact pending item dictionaries")
    for raw in values:
        if raw.get("type") == "reasoning" and (raw.get("content") or raw.get("summary")):
            raise ValueError("Raw or summarized reasoning cannot enter the private window")
    validated = ITEMS.validate_python(values, strict=True)
    items = cast(
        list[ResponseInputItemParam], ITEMS.dump_python(validated, mode="json", warnings="error")
    )
    if not 1 <= len(items) <= 16:
        raise ValueError("Contact continuation item bound exceeded")
    for item in items:
        if item.get("type") == "reasoning":
            if (
                not item.get("encrypted_content")
                or item.get("content")
                or item.get("summary")
                or item.get("status") not in (None, "completed")
            ):
                raise ValueError("Only opaque completed reasoning can be retained")
        elif item.get("type") != "function_call":
            raise ValueError("Unexpected pending contact continuation item")
    parse_contact_function({"output": items})
    if len([item for item in items if item.get("type") == "function_call"]) != 1:
        raise ValueError("Exactly one pending invocation is required")
    return items


def capture_contact_window(
    *,
    output: object,
    model: str,
    effort: Literal["none", "low", "medium", "high", "xhigh"],
    instructions: str,
    context: str,
) -> ContactModelWindow:
    if not isinstance(output, list):
        raise ValueError("Expected provider output array")
    if any(
        not isinstance(item, dict)
        or item.get("type") not in {"message", "reasoning", "function_call"}
        for item in output
    ):
        raise ValueError("Provider cannot supply execution receipts or unsupported history")
    # Prose has no runtime authority and is not needed to pair the selected call.
    # Raw/summary reasoning is rejected, not shortened; encrypted reasoning is retained.
    items = json.dumps(
        _pending_items([item for item in output if item.get("type") != "message"]),
        ensure_ascii=False,
    )
    return ContactModelWindow(
        model=model,
        effort=effort,
        instructions=instructions,
        context=context,
        items=items,
        digest=window_digest(model, effort, instructions, context, items),
    )


def contact_result_input(
    window: ContactModelWindow, result: ContactPreparationResult, *, call_sha256: str
) -> list[ResponseInputItemParam]:
    window = ContactModelWindow.model_validate(window.model_dump())
    items = _pending_items(json.loads(window.items))
    call = next(item for item in items if item.get("type") == "function_call")
    call_id = str(call.get("call_id"))
    if (
        call.get("name") != CONTACT_TOOL
        or hashlib.sha256(call_id.encode()).hexdigest() != call_sha256
    ):
        raise ValueError("Original native invocation does not match its frozen request")
    return [
        {"type": "message", "role": "user", "content": window.context},
        *items,
        {
            "type": "function_call_output",
            "call_id": call_id,
            "output": result.model_dump_json(),
        },
    ]
