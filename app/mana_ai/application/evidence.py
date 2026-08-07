from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from app.mana_ai.domain.responses import ActionValue, FindingDraft


def collect_evidence_ids(value: Any) -> set[str]:
    result: set[str] = set()
    _collect(value, result)
    return result


def _collect(value: Any, result: set[str]) -> None:
    if isinstance(value, BaseModel):
        evidence_id = getattr(value, "evidence_id", None)
        if isinstance(evidence_id, str):
            result.add(evidence_id)
        for field_name in type(value).model_fields:
            _collect(getattr(value, field_name), result)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect(item, result)
        return
    if isinstance(value, Iterable) and not isinstance(value, str | bytes):
        for item in value:
            _collect(item, result)


def validate_finding_evidence(
    findings: list[FindingDraft],
    evidence_ids: set[str],
) -> tuple[list[FindingDraft], list[str]]:
    accepted: list[FindingDraft] = []
    notes: list[str] = []
    for finding in findings:
        unknown = set(finding.evidence_ids) - evidence_ids
        if unknown:
            notes.append(
                "A finding with unknown evidence references was removed: "
                + ", ".join(sorted(unknown))
            )
            continue
        accepted.append(finding)
    return accepted, notes


def validate_action_evidence(
    actions: list[ActionValue],
    evidence_ids: set[str],
) -> tuple[list[ActionValue], list[str]]:
    accepted: list[ActionValue] = []
    notes: list[str] = []
    for action in actions:
        referenced = _action_evidence_ids(action)
        unknown = referenced - evidence_ids
        if unknown:
            notes.append(
                "An action with unknown evidence references was removed: "
                + ", ".join(sorted(unknown))
            )
            continue
        accepted.append(action)
    return accepted, notes


def _action_evidence_ids(action: ActionValue) -> set[str]:
    ids: set[str] = set()
    evidence = getattr(action, "evidence_ids", None)
    if isinstance(evidence, list):
        ids.update(item for item in evidence if isinstance(item, str))
    resource_evidence_id = getattr(action, "resource_evidence_id", None)
    if isinstance(resource_evidence_id, str):
        ids.add(resource_evidence_id)
    center_evidence_id = getattr(action, "center_evidence_id", None)
    if isinstance(center_evidence_id, str):
        ids.add(center_evidence_id)
    return ids
