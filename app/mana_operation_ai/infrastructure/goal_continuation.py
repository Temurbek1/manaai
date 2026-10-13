"""Translate bounded private continuation into stateless Responses items."""

import hashlib
import json
from dataclasses import dataclass
from typing import cast

from openai.types.responses import ResponseInputItemParam
from pydantic import JsonValue, TypeAdapter

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.model_continuation import (
    continuation_protocol,
    continuation_scope_digest,
)
from app.mana_operation_ai.application.page_projection import page_output_covered, page_reference
from app.mana_operation_ai.application.runtime_snapshots import snapshot_superseded
from app.mana_operation_ai.domain.agent_tools import AgentToolCall
from app.mana_operation_ai.domain.goals import OperationGoal
from app.mana_operation_ai.domain.model_continuation import ModelContinuation, RuntimeSnapshotRef
from app.mana_operation_ai.domain.page_projection import PageOutputRef
from app.mana_operation_ai.infrastructure.agent_tool_schema import parse_agent_function

ITEMS = TypeAdapter(list[ResponseInputItemParam])
ALLOWED = {"message", "reasoning", "compaction", "function_call", "function_call_output"}


def validate_items(
    values: object, *, report_discovery_enabled: bool = False
) -> list[ResponseInputItemParam]:
    validated = ITEMS.validate_python(values, strict=True)
    # SDK TypedDicts declare nested Iterables. Materialize their validated
    # iterators before JSON hashing/storage or sending the window a second time.
    items = cast(
        list[ResponseInputItemParam], ITEMS.dump_python(validated, mode="json", warnings="error")
    )
    if len(items) > 128:
        raise ValueError("Model window has too many items")
    pending: dict[str, AgentToolCall] = {}
    seen_calls: set[str] = set()
    for item in items:
        kind = item.get("type")
        if kind not in ALLOWED:
            raise ValueError("Unsupported continuation item")
        if kind == "message" and item.get("role") not in ("user", "assistant"):
            raise ValueError("Continuation cannot carry system or developer authority")
        if kind in ("reasoning", "compaction"):
            if not item.get("encrypted_content"):
                raise ValueError("Opaque continuation lacks encrypted content")
            if item.get("content"):
                raise ValueError("Raw hidden reasoning is not retained")
        if kind == "function_call":
            call = parse_agent_function(
                str(item.get("name")),
                str(item.get("arguments")),
                report_discovery_enabled=report_discovery_enabled,
            )
            call_id = str(item.get("call_id"))
            if call_id in seen_calls:
                raise ValueError("Duplicate provider tool identifier")
            seen_calls.add(call_id)
            pending[call_id] = call
        elif kind == "function_call_output":
            if pending.pop(str(item.get("call_id")), None) is None:
                raise ValueError("Tool output has no matching invocation")
    if len(pending) > 1:
        raise ValueError("Parallel pending tools are not allowed")
    return items


@dataclass(frozen=True)
class PreparedContinuation:
    goal: OperationGoal
    scope_digest: str
    items: list[ResponseInputItemParam]
    prior_compactions: int
    runtime_snapshots: tuple[RuntimeSnapshotRef, ...] = ()
    page_outputs: tuple[PageOutputRef, ...] = ()


def _item_digest(item: ResponseInputItemParam) -> str:
    return hashlib.sha256(json.dumps(item, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _replace_snapshots(
    items: list[ResponseInputItemParam], refs: list[RuntimeSnapshotRef], goal: OperationGoal
) -> tuple[list[ResponseInputItemParam], list[RuntimeSnapshotRef], set[int]]:
    discarded: set[int] = set()
    for ref in refs:
        if ref.position >= len(items):
            raise ChatError("Квитанция контекста не соответствует сохранённому окну.")
        item = items[ref.position]
        if (
            item.get("type") != "message"
            or item.get("role") != "user"
            or not isinstance(item.get("content"), str)
            or _item_digest(item) != ref.item_digest
        ):
            raise ChatError("Квитанция контекста не соответствует сохранённому окну.")
        # Provenance comes only from SQL metadata written before appending provider output.
        # A provider-created lookalike is never selected by role, text or JSON shape.
        try:
            previous = OperationGoal.model_validate(json.loads(str(item.get("content")))["goal"])
        except (ValueError, TypeError, KeyError):
            raise ChatError("Сохранённый снимок контекста повреждён. AI не вызван.") from None
        if snapshot_superseded(previous, goal):
            discarded.add(ref.position)
    retained = [item for index, item in enumerate(items) if index not in discarded]
    rebound = [
        ref.model_copy(
            update={"position": ref.position - sum(index < ref.position for index in discarded)}
        )
        for ref in refs
        if ref.position not in discarded
    ]
    return retained, rebound, discarded


def _validate_page_outputs(
    items: list[ResponseInputItemParam], refs: list[PageOutputRef], goal: OperationGoal
) -> None:
    for ref in refs:
        if ref.position >= len(items):
            raise ChatError("Квитанция страницы не соответствует сохранённому окну.")
        item = items[ref.position]
        expected = json.dumps(
            {
                "status": "completed",
                "result": ref.page.model_dump_json(),
                "result_shortened": False,
            },
            ensure_ascii=False,
        )
        if (
            item.get("type") != "function_call_output"
            or item.get("output") != expected
            or _item_digest(item) != ref.item_digest
            or not page_output_covered(goal, ref)
        ):
            raise ChatError("Точный текст страницы больше не подтверждён. AI не вызван.")


def prepare_continuation(
    *, context: str, owner: str, state: ModelContinuation | None, model: str, maximum_bytes: int
) -> PreparedContinuation:
    goal = OperationGoal.model_validate(json.loads(context)["goal"])
    if goal.request.execution_mode != "agent":
        raise ChatError("Продолжение модели доступно только в рабочем режиме.")
    scope = continuation_scope_digest(owner, goal)
    items: list[ResponseInputItemParam] = []
    refs: list[RuntimeSnapshotRef] = []
    pages: list[PageOutputRef] = []
    if state:
        if state.protocol != continuation_protocol(goal):
            raise ChatError(
                "Протокол продолжения не соответствует сохранённому набору инструментов."
            )
        if state.scope_digest != scope:
            raise ChatError("Контекст модели не принадлежит этой цели.")
        if state.model != model and goal.phase != "review":
            raise ChatError("Модель изменилась. Сохранённый контекст нельзя переносить молча.")
        items = validate_items(
            json.loads(state.payload), report_discovery_enabled=goal.report_discovery_enabled
        )
        if goal.snapshot_replacement_enabled:
            items, refs, removed = _replace_snapshots(items, state.runtime_snapshots, goal)
            pages = [
                ref.model_copy(
                    update={
                        "position": ref.position - sum(index < ref.position for index in removed)
                    }
                )
                for ref in state.page_outputs
            ]
            _validate_page_outputs(items, pages, goal)
        pending = [item for item in items if item.get("type") == "function_call"]
        outputs = {
            item.get("call_id") for item in items if item.get("type") == "function_call_output"
        }
        pending = [item for item in pending if item.get("call_id") not in outputs]
        if state.pending_tool_position is not None:
            position = state.pending_tool_position
            if len(pending) != 1 or position >= len(goal.tools):
                raise ChatError("Подтверждение инструмента в журнале не найдено.")
            record = goal.tools[position]
            call = parse_agent_function(
                str(pending[0].get("name")),
                str(pending[0].get("arguments")),
                report_discovery_enabled=goal.report_discovery_enabled,
            )
            if (
                record.call != state.pending_tool_call
                or call != record.call
                or record.status == "started"
            ):
                raise ChatError("Результат инструмента ещё не подтверждён. Повтор не запущен.")
            reference = page_reference(goal, record)
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": str(pending[0].get("call_id")),
                    "output": json.dumps(
                        {
                            "status": record.status,
                            "result": reference.model_dump_json()
                            if reference is not None
                            else record.result,
                            "result_shortened": record.result_shortened,
                        },
                        ensure_ascii=False,
                    ),
                }
            )
            if reference is not None:
                pages.append(
                    PageOutputRef(
                        position=len(items) - 1,
                        item_digest=_item_digest(items[-1]),
                        tool_position=position,
                        tool_call_id=record.call_id,
                        page=reference,
                    )
                )
        elif pending:
            raise ChatError("Контекст модели содержит неподтверждённый инструмент.")
    # Review is intentionally independent of the investigator's opaque reasoning.
    if goal.phase == "review":
        items = []
        refs = []
        pages = []
    # Reassert every original condition and the current evidence/permission snapshot.
    items.append({"type": "message", "role": "user", "content": context})
    if goal.snapshot_replacement_enabled:
        refs.append(
            RuntimeSnapshotRef(position=len(items) - 1, item_digest=_item_digest(items[-1]))
        )
    if len(json.dumps(items, ensure_ascii=False).encode()) > maximum_bytes:
        raise ChatError("Окно продолжения достигло лимита. История сохранена; AI не вызван.")
    return PreparedContinuation(
        goal,
        scope,
        validate_items(items, report_discovery_enabled=goal.report_discovery_enabled),
        state.compactions if state else 0,
        tuple(refs),
        tuple(pages),
    )


def finish_continuation(
    prepared: PreparedContinuation,
    output: list[dict[str, JsonValue]],
    *,
    model: str,
    call: AgentToolCall | None,
    maximum_bytes: int,
) -> ModelContinuation:
    # Provider history is pruned only before the latest actual server compaction item.
    # Separately proven runtime snapshots are handled by _replace_snapshots, never by shape.
    # Standalone /compact output must not be pruned; that endpoint is not used here.
    values = [*prepared.items, *output]
    compactions = [index for index, item in enumerate(values) if item.get("type") == "compaction"]
    new_count = sum(item.get("type") == "compaction" for item in output)
    refs = list(prepared.runtime_snapshots)
    pages = list(prepared.page_outputs)
    if compactions:
        cutoff = compactions[-1]
        values = values[cutoff:]
        refs = [
            ref.model_copy(update={"position": ref.position - cutoff})
            for ref in refs
            if ref.position >= cutoff
        ]
        pages = [
            ref.model_copy(update={"position": ref.position - cutoff})
            for ref in pages
            if ref.position >= cutoff
        ]
    items = validate_items(values, report_discovery_enabled=prepared.goal.report_discovery_enabled)
    payload = json.dumps(items, ensure_ascii=False)
    if len(payload.encode()) > maximum_bytes:
        raise ValueError("Returned model window exceeds the configured limit")
    invocations = [item for item in output if item.get("type") == "function_call"]
    if bool(invocations) != (call is not None) or len(invocations) > 1:
        raise ValueError("Continuation and durable decision disagree")
    return ModelContinuation(
        protocol=continuation_protocol(prepared.goal),
        model=model,
        scope_digest=prepared.scope_digest,
        payload=payload,
        payload_digest=hashlib.sha256(payload.encode()).hexdigest(),
        compactions=prepared.prior_compactions + new_count,
        pending_tool_position=len(prepared.goal.tools) if call is not None else None,
        pending_tool_call=call,
        runtime_snapshots=refs,
        page_outputs=pages,
    )
