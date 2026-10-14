"""Exactly one native fictional-parameter request; no provider payload or grants."""

import hashlib
import json
import re
from typing import TypedDict

from openai.types.responses import FunctionToolParam
from pydantic import ValidationError

from app.mana_operation_ai.application.inference_errors import InferenceProviderError
from app.mana_operation_ai.domain.contact_preparation import CONTACT_TOOL, ContactToolSelection


class ContactToolOptions(TypedDict, total=False):
    tools: list[FunctionToolParam]
    parallel_tool_calls: bool


def contact_function_tools() -> list[FunctionToolParam]:
    return [
        {
            "type": "function",
            "name": CONTACT_TOOL,
            "description": (
                "Request human-confirmed preparation of one fictional MANA adult contact. "
                "Saves parameters only; cannot read sources, send, approve, share "
                "or choose a reviewer."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string", "enum": ["sample_ru", "sample_uz"]},
                    "template": {"type": "string", "enum": ["onboarding_help", "renewal_reminder"]},
                },
                "required": ["recipient", "template"],
                "additionalProperties": False,
            },
        }
    ]


def parse_contact_function(payload: dict[str, object]) -> tuple[ContactToolSelection, str] | None:
    output = payload.get("output")
    if not isinstance(output, list):
        raise InferenceProviderError("invalid_response")
    if any(
        isinstance(item, dict) and item.get("type") == "function_call_output" for item in output
    ):
        raise InferenceProviderError("invalid_response")
    calls = [
        item for item in output if isinstance(item, dict) and item.get("type") == "function_call"
    ]
    if not calls:
        return None
    if len(calls) != 1:
        raise InferenceProviderError("invalid_response")
    call = calls[0]
    call_id, arguments = call.get("call_id"), call.get("arguments")
    if (
        call.get("name") != CONTACT_TOOL
        or call.get("status") not in (None, "completed")
        or not isinstance(call_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call_id)
        or not isinstance(arguments, str)
        or len(arguments.encode()) > 512
    ):
        raise InferenceProviderError("invalid_response")
    try:
        selection = ContactToolSelection.model_validate(
            json.loads(arguments, object_pairs_hook=_unique_fields)
        )
    except (ValueError, ValidationError):
        raise InferenceProviderError("invalid_response") from None
    return selection, hashlib.sha256(call_id.encode()).hexdigest()


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("Duplicate native argument field")
        fields[key] = value
    return fields
