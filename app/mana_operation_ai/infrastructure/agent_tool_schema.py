"""Translate the bounded analysis tool catalog to native Responses function schemas."""

import json
from typing import cast, get_args

from openai.types.responses import FunctionToolParam

from app.mana_operation_ai.domain.agent_tools import (
    REPORT_DISCOVERY_TOOL,
    AgentToolCall,
    SourceReadCapability,
)

_PROPERTIES: dict[str, dict[str, object]] = {
    "inspect_sources": {},
    "read_saved_report": {"report_id": {"type": "string"}},
    "read_saved_report_page": {
        "report_id": {"type": "string"},
        "offset": {"type": "integer"},
    },
    "find_saved_tasks": {
        "query": {"type": "string"},
        "cursor": {"type": ["string", "null"]},
    },
    "find_saved_reports": {
        "query": {"type": "string", "maxLength": 120},
        "cursor": {"type": ["string", "null"], "maxLength": 1024},
        "catalog_capability": {
            "type": ["string", "null"],
            "enum": [*get_args(SourceReadCapability), None],
        },
    },
    "read_saved_task": {
        "task_id": {"type": "string"},
        "offset": {"type": "integer"},
    },
    "request_source_read": {
        "capability": {"type": "string", "enum": list(get_args(SourceReadCapability))}
    },
    "ask_user": {
        "question": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}},
    },
}
_DESCRIPTIONS = {
    "inspect_sources": (
        "List verified saved report references and permitted reads for this app. No provider call."
    ),
    "read_saved_report": "Read one scoped saved minimized report. No new source collection.",
    "read_saved_report_page": (
        "Read a contiguous page of a scoped minimized saved report, starting at offset 0. "
        "Follow next_offset until the full text is loaded into goal.evidence. SQL only, "
        "no new collection. Full text does not prove full population/payment coverage."
    ),
    "find_saved_tasks": (
        "Find up to five closed tasks in this owner's same topic/app before this task began. "
        "Query is an exact objective substring (empty lists all); cursor is a returned task ID "
        "or null. SQL history only, never evidence or permission."
    ),
    "find_saved_reports": (
        "Find up to ten scoped saved report references created before this Goal started. "
        "Query is a literal substring of title/text; empty searches all. "
        "Optional catalog_capability filters references, never requests a collection. "
        "Keep query/filter unchanged when following "
        "next_cursor; null starts a search. Empty pages can have continuation cursors. "
        "SQL only: read original reports separately before citing facts; "
        "no grants or new source call."
    ),
    "read_saved_task": (
        "Read a bounded page of one prior task's public result, starting at offset 0. "
        "Use returned next_offset for more text. Historical context only: original reports "
        "must be revalidated separately; no new source/model/action call."
    ),
    "request_source_read": (
        "Request separate human approval for one owning-agent source read. Does not execute it."
    ),
    "ask_user": (
        "Wait for one focused user clarification, optionally with up to three suggested answers."
    ),
}


def agent_function_tools(*, report_discovery_enabled: bool = False) -> list[FunctionToolParam]:
    return [
        cast(
            FunctionToolParam,
            {
                "type": "function",
                "name": name,
                "description": _DESCRIPTIONS[name],
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            },
        )
        for name, properties in _PROPERTIES.items()
        if name != REPORT_DISCOVERY_TOOL or report_discovery_enabled
    ]


def parse_agent_function(
    name: str, arguments: str, *, report_discovery_enabled: bool = False
) -> AgentToolCall:
    if name not in _PROPERTIES or (name == REPORT_DISCOVERY_TOOL and not report_discovery_enabled):
        raise ValueError("Unknown analysis function")
    payload = json.loads(arguments)
    if not isinstance(payload, dict) or set(payload) != set(_PROPERTIES[name]):
        raise ValueError("Invalid analysis function arguments")
    return AgentToolCall.model_validate({"name": name, **payload})
