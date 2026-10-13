"""Conservative coverage of authoritative runtime snapshots, not semantic history pruning."""

import hashlib

from app.mana_operation_ai.domain.goals import GoalEvidence, OperationGoal
from app.mana_operation_ai.domain.session import SessionMemory

PARTIAL_TEXT_NOTE = "Evidence shortened; complete coverage cannot be assumed."


def _memory_facts(memory: SessionMemory | None) -> object:
    if memory is None:
        return None
    # Freshness is recalculated by the existing serializer, not a changed historical quote.
    return memory.model_dump(
        mode="json",
        exclude={"checkpoints": {"__all__": {"sources": {"__all__": {"refresh_status"}}}}},
    )


def _evidence_covered(previous: GoalEvidence, current: GoalEvidence) -> bool:
    metadata = {"summary", "shortened", "report_read_progress", "refresh_status", "limitations"}
    if previous.model_dump(exclude=metadata) != current.model_dump(exclude=metadata):
        return False
    if not current.summary.startswith(previous.summary):
        return False
    before, after = previous.report_read_progress, current.report_read_progress
    if before is not None and (
        after is None
        or (
            before.source_fingerprint != after.source_fingerprint
            or before.full_text_sha256 != after.full_text_sha256
            or before.total_characters != after.total_characters
            or before.next_offset > after.next_offset
            or (before.quality_notes_complete and not after.quality_notes_complete)
        )
    ):
        return False
    if after is not None and (
        after.loaded_text_sha256 != hashlib.sha256(current.summary.encode()).hexdigest()
        or after.next_offset != len(current.summary)
    ):
        return False
    for note in previous.limitations:
        if note not in current.limitations and not (
            note == PARTIAL_TEXT_NOTE
            and previous.shortened
            and not current.shortened
            and after is not None
            and after.quality_notes_complete
            and after.loaded_text_sha256 == after.full_text_sha256
        ):
            return False
    return previous.shortened or not current.shortened


def snapshot_superseded(previous: OperationGoal, current: OperationGoal) -> bool:
    """Replace only a full earlier state whose user/evidence facts still occur verbatim.

    Status, current plan/draft, controls, costs and grants use the newest SQL state.
    Provider decisions, reasoning and tool outputs are independently retained by the
    continuation adapter. A shrinking tool projection or changed source refuses replacement.
    """
    if (
        (previous.goal_id, previous.topic_id, previous.agent_id, previous.product)
        != (current.goal_id, current.topic_id, current.agent_id, current.product)
        or previous.request != current.request
        or previous.report_discovery_enabled != current.report_discovery_enabled
        or previous.snapshot_replacement_enabled != current.snapshot_replacement_enabled
        or previous.page_projection_enabled != current.page_projection_enabled
        or previous.instructions != current.instructions[: len(previous.instructions)]
        or _memory_facts(previous.session_memory) != _memory_facts(current.session_memory)
        or len(previous.tools) > len(current.tools)
    ):
        return False
    for before, after in zip(previous.tools, current.tools, strict=False):
        if before != after:
            return False
    evidence = {item.report_id: item for item in current.evidence}
    if len(evidence) != len(current.evidence):
        return False
    return all(
        item.report_id in evidence and _evidence_covered(item, evidence[item.report_id])
        for item in previous.evidence
    )
