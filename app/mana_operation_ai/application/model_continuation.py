"""Bind private continuation to its owner and unchanged objective/quoted conditions."""

import hashlib
import json

from app.mana_operation_ai.domain.goals import OperationGoal
from app.mana_operation_ai.domain.model_continuation import ContinuationProtocol


def continuation_protocol(goal: OperationGoal) -> ContinuationProtocol:
    if goal.page_projection_enabled:
        return "goal-model-continuation-v4"
    if goal.snapshot_replacement_enabled:
        return "goal-model-continuation-v3"
    if goal.report_discovery_enabled:
        return "goal-model-continuation-v2"
    return "goal-model-continuation-v1"


def continuation_scope_digest(owner: str, goal: OperationGoal) -> str:
    payload: dict[str, object] = {
        "owner": owner,
        "goal_id": goal.goal_id,
        "topic_id": goal.topic_id,
        "agent_id": goal.agent_id,
        "product": goal.product,
        "request": goal.request.model_dump(mode="json"),
        "user_context": [item.model_dump(mode="json") for item in goal.session_memory.user_context]
        if goal.session_memory
        else [],
    }
    if goal.report_discovery_enabled:
        # Preserve byte-equivalent pre-discovery scope digests for existing continuations.
        payload["report_discovery_enabled"] = True
    if goal.snapshot_replacement_enabled:
        payload["snapshot_replacement_enabled"] = True
    if goal.page_projection_enabled:
        payload["page_projection_enabled"] = True
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def public_goal(goal: OperationGoal) -> OperationGoal:
    return goal.model_copy(
        update={
            "model_continuation": None,
            "evidence": [
                item.model_copy(update={"report_read_progress": None}) for item in goal.evidence
            ],
        }
    )
