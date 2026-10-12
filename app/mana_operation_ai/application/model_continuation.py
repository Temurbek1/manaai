"""Bind private continuation to its owner and unchanged objective/quoted conditions."""

import hashlib
import json

from app.mana_operation_ai.domain.goals import OperationGoal


def continuation_scope_digest(owner: str, goal: OperationGoal) -> str:
    payload = {
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
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def public_goal(goal: OperationGoal) -> OperationGoal:
    return goal.model_copy(update={"model_continuation": None})
