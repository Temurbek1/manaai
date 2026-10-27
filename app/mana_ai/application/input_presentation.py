"""Versioned host presentation; never a source, context summary or action grant."""

import copy
import json
from typing import Any, Literal, Protocol

from app.mana_ai.application.chat_ports import ParentChatError


class FamilyInputPresentationPort(Protocol):
    async def input_presentation(self, parent_id: str, turn_id: int) -> Literal[1] | None: ...


def without_schema_titles(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove annotations only, preserving property names and literal data objects."""
    result = copy.deepcopy(schema)
    result.pop("title", None)
    for key in ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas"):
        value = result.get(key)
        if isinstance(value, dict):
            result[key] = {
                name: without_schema_titles(item) if isinstance(item, dict) else item
                for name, item in value.items()
            }
    for key in (
        "items",
        "additionalItems",
        "additionalProperties",
        "unevaluatedItems",
        "unevaluatedProperties",
        "contains",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
        "contentSchema",
    ):
        value = result.get(key)
        if isinstance(value, dict):
            result[key] = without_schema_titles(value)
        elif isinstance(value, list):
            result[key] = [
                without_schema_titles(item) if isinstance(item, dict) else item for item in value
            ]
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        value = result.get(key)
        if isinstance(value, list):
            result[key] = [
                without_schema_titles(item) if isinstance(item, dict) else item for item in value
            ]
    return result


def compact_native_host_messages(
    messages: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    """The native builder emits one host JSON envelope; quoted strings stay exact."""
    if len(messages) != 1 or messages[0][0] != "user":
        raise ParentChatError("native_input_presentation_invalid", 409)
    payload = json.loads(messages[0][1])
    if not isinstance(payload, dict):
        raise ParentChatError("native_input_presentation_invalid", 409)
    return (("user", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),)
