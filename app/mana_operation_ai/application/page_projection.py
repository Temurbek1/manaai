"""Prove exact duplicate page coverage without modifying saved evidence or SQL receipts."""

import hashlib
import json

from app.mana_operation_ai.domain.agent_tools import AgentToolRecord
from app.mana_operation_ai.domain.goals import OperationGoal
from app.mana_operation_ai.domain.page_projection import (
    EvidenceTextPointer,
    PageOutputRef,
    ProjectedSavedPageReceipt,
    SavedPageReceipt,
)


def page_reference(
    goal: OperationGoal, record: AgentToolRecord
) -> ProjectedSavedPageReceipt | None:
    if (
        not goal.page_projection_enabled
        or record.call.name != "read_saved_report_page"
        or record.status != "completed"
        or record.result_shortened
    ):
        return None
    try:
        value = json.loads(record.result)
        if (
            not isinstance(value, dict)
            or value.get("loaded_into_evidence") is not True
            or value.get("reading_not_population_coverage") is not True
        ):
            return None
        projected = "text_reference" in value
        receipt = (
            ProjectedSavedPageReceipt.model_validate(value, strict=True)
            if projected
            else SavedPageReceipt.model_validate(value, strict=True)
        )
    except (ValueError, TypeError):
        return None
    if receipt.report_id != record.call.report_id or receipt.offset != record.call.offset:
        return None
    matches = [item for item in goal.evidence if item.report_id == receipt.report_id]
    if len(matches) != 1 or matches[0].product != goal.product:
        return None
    evidence = matches[0]
    progress = evidence.report_read_progress
    if progress is None or progress.total_characters != receipt.total_characters:
        return None
    if progress.loaded_text_sha256 != hashlib.sha256(
        evidence.summary.encode()
    ).hexdigest() or progress.next_offset != len(evidence.summary):
        return None
    characters = (
        receipt.text_reference.characters
        if isinstance(receipt, ProjectedSavedPageReceipt)
        else len(receipt.text)
    )
    end = receipt.offset + characters
    if end > len(evidence.summary):
        return None
    text = evidence.summary[receipt.offset : end]
    pointer = EvidenceTextPointer(
        characters=characters,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        source_fingerprint=progress.source_fingerprint,
        full_text_sha256=progress.full_text_sha256,
    )
    if isinstance(receipt, ProjectedSavedPageReceipt):
        return receipt if receipt.text_reference == pointer else None
    if text != receipt.text:
        return None
    reference = ProjectedSavedPageReceipt(
        **receipt.model_dump(exclude={"text"}), text_reference=pointer
    )
    # Never enlarge a small receipt or silently substitute a less informative representation.
    return reference if len(reference.model_dump_json()) < len(record.result) else None


def page_output_covered(goal: OperationGoal, ref: PageOutputRef) -> bool:
    if ref.tool_position >= len(goal.tools):
        return False
    record = goal.tools[ref.tool_position]
    return record.call_id == ref.tool_call_id and page_reference(goal, record) == ref.page
