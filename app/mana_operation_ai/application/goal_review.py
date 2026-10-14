"""Bind a full-scope independent verdict and preserve the exact stored draft."""

import hashlib
import json

from app.mana_operation_ai.domain.goal_review import GoalReviewVerdictBody
from app.mana_operation_ai.domain.goals import GoalDecision, OperationGoal


def review_mode(context: str) -> bool:
    goal = json.loads(context).get("goal", {})
    return goal.get("review_verdict_enabled") is True and goal.get("phase") == "review"


def review_input(context: str) -> str:
    payload = json.loads(context)
    goal = OperationGoal.model_validate(payload["goal"])
    if not review_mode(context) or not goal.result or not goal.plan:
        raise ValueError("A review verdict requires the captured contract and a complete draft")
    if "review_contract" in payload:
        raise ValueError("Review descriptors must be produced by this runtime")
    payload["review_contract"] = {
        "input_sha256": hashlib.sha256(context.encode()).hexdigest(),
        "draft_sha256": hashlib.sha256(goal.result.encode()).hexdigest(),
        "required_quote_targets": ["objective", "success_criteria"],
        "instruction": "Review the complete original request, constraints, steering, quoted "
        "conditions, plan, evidence and existing draft. For each target, concatenate your "
        "checks' exact quotes in order to reproduce its complete original text. Do not omit "
        "any words, criteria or qualifications. Acceptance requires all checks passed, "
        "conditions/evidence checked and every original plan position checked. Findings "
        "and feedback are public review observations, not private reasoning or new evidence. "
        "Do not rewrite the draft/plan or request sources/actions. On revise, put all "
        "material correction directions in feedback; the investigator must revise later.",
    }
    return json.dumps(payload, ensure_ascii=False)


def review_decision(review: GoalReviewVerdictBody, context: str) -> GoalDecision:
    goal = OperationGoal.model_validate(json.loads(context)["goal"])
    if not review_mode(context) or not goal.result or not goal.plan:
        raise ValueError("A review verdict cannot replace an investigation or empty draft")
    if (
        review.input_sha256 != hashlib.sha256(context.encode()).hexdigest()
        or review.draft_sha256 != hashlib.sha256(goal.result.encode()).hexdigest()
    ):
        raise ValueError("Review verdict does not match the exact input and stored draft")
    for target in ("objective", "success_criteria"):
        quotes = "".join(check.quote for check in review.checks if check.target == target)
        if quotes != getattr(goal.request, target):
            raise ValueError("Review must cover the full original objective and success criteria")
    positions = review.checked_plan_positions
    if positions != sorted(set(positions)) or any(
        position >= len(goal.plan) for position in positions
    ):
        raise ValueError("Review plan positions must be exact, unique and ordered")
    if len(review.evidence_ids) != len(set(review.evidence_ids)) or not set(
        review.evidence_ids
    ).issubset({item.report_id for item in goal.evidence}):
        raise ValueError("Review references must identify loaded evidence")
    accepted = review.disposition == "accepted"
    if accepted and (
        any(check.status != "passed" for check in review.checks)
        or not review.conditions_checked
        or not review.evidence_checked
        or not review.evidence_ids
        or positions != list(range(len(goal.plan)))
    ):
        raise ValueError("Acceptance requires every original check, plan and evidence review")
    decision = GoalDecision(
        update=review.feedback,
        plan=[task.model_copy(update={"status": "done"}) for task in goal.plan]
        if accepted
        else goal.plan,
        draft=goal.result,
        evidence_ids=review.evidence_ids,
        disposition=review.disposition,
        missing_information=review.feedback if review.disposition == "waiting" else "",
        requested_capability=None,
    )
    # Preserve even unusual whitespace in the already stored artifact, without rewriting it.
    return decision.model_copy(update={"draft": goal.result})
