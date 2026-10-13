"""Translate schema validation to closed application facts, not provider prose."""

from typing import cast, get_args

from pydantic import ValidationError

from app.mana_operation_ai.application.goal_ports import (
    DecisionField,
    DecisionIssueCode,
    GoalDecisionIssue,
)


def is_decision_validation(error: ValidationError) -> bool:
    return error.title in {"GoalDecision", "GoalDecisionBody"}


def decision_issues(error: ValidationError) -> tuple[GoalDecisionIssue, ...]:
    if not is_decision_validation(error):
        return ()
    fields = get_args(DecisionField)
    codes = get_args(DecisionIssueCode)
    result: list[GoalDecisionIssue] = []
    for item in error.errors(include_input=False, include_context=False, include_url=False):
        code = item["type"]
        if code not in codes:
            continue
        location = item["loc"]
        # A nested plan index is not persisted; extra field names remain opaque.
        field = "decision"
        if location and location[0] in fields:
            field = str(location[0])
            if (
                field == "plan"
                and len(location) == 3
                and type(location[1]) is int
                and location[2] in {"title", "status"}
            ):
                field += "." + str(location[2])
        issue = GoalDecisionIssue(cast(DecisionField, field), cast(DecisionIssueCode, code))
        if issue not in result:
            result.append(issue)
        if len(result) == 3:
            break
    return tuple(result)
