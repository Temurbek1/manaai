"""Exact Responses history append; no provider-generated execution outputs or summaries."""

import json
from typing import cast

from openai.types.responses import ResponseInputItemParam

from app.mana_operation_ai.domain.contact_continuation import ContactModelWindow, window_digest
from app.mana_operation_ai.domain.contact_loop import ContactLoopState, loop_result_prefix
from app.mana_operation_ai.domain.session import SessionMemory
from app.mana_operation_ai.infrastructure.contact_model_continuation import (
    ITEMS,
    _pending_items,
)


def loop_input(
    window: ContactModelWindow, loop: ContactLoopState, memory: SessionMemory | None
) -> list[ResponseInputItemParam]:
    values = [
        {"type": "message", "role": "user", "content": window.context},
        *loop_result_prefix(window, loop, memory),
    ]
    validated = ITEMS.validate_python(values, strict=True)
    return cast(
        list[ResponseInputItemParam], ITEMS.dump_python(validated, mode="json", warnings="error")
    )


def capture_loop_append(
    window: ContactModelWindow, *, input_items: list[ResponseInputItemParam], output: object
) -> ContactModelWindow:
    if not isinstance(output, list) or any(
        not isinstance(item, dict)
        or item.get("type") not in {"message", "reasoning", "function_call"}
        for item in output
    ):
        raise ValueError("The provider cannot create host execution receipts")
    pending = _pending_items([item for item in output if item.get("type") != "message"])
    items = json.dumps([*input_items[1:], *pending], ensure_ascii=False)
    return ContactModelWindow(
        model=window.model,
        effort=window.effort,
        instructions=window.instructions,
        context=window.context,
        items=items,
        digest=window_digest(
            window.model, window.effort, window.instructions, window.context, items
        ),
    )
