import hashlib

from pydantic import BaseModel, TypeAdapter

from app.mana_ai.domain.enums import (
    ActionKind,
    ExecutionPolicy,
    ManaAICapability,
)
from app.mana_ai.domain.requests import CapabilityInput, ManaAIRequest, ParentCopilotInput
from app.mana_ai.domain.responses import (
    ActionValue,
    AppRestrictionAction,
    FindingDraft,
    LimitChangeAction,
    ManaAIActionProposal,
    ManaAIFinding,
    SubmitExtraTimeRequestAction,
    TemporaryAccessAction,
)
from app.mana_ai.domain.signals import AppLimit, AppUsageSignal, ExtraTimeRequest, FamilyPreferences

ACTION_ADAPTER: TypeAdapter[ActionValue] = TypeAdapter(ActionValue)

PARENT_CONFIRMATION_ACTIONS = {
    ActionKind.PROPOSE_LIMIT_CHANGE,
    ActionKind.PROPOSE_STUDY_MODE,
    ActionKind.PROPOSE_GEOFENCE,
    ActionKind.PROPOSE_APP_RESTRICTION,
    ActionKind.PROPOSE_TEMPORARY_ACCESS,
    ActionKind.PROPOSE_AGREEMENT_UPDATE,
}

INFORMATION_ONLY_ACTIONS = {
    ActionKind.GENERATE_FAMILY_REPORT,
}

ALLOWED_ACTIONS: dict[ManaAICapability, frozenset[ActionKind]] = {
    ManaAICapability.SAFETY_MONITOR: frozenset(
        {
            ActionKind.NOTIFY_PARENT,
            ActionKind.WARN_CHILD,
            ActionKind.REQUEST_CHECK_IN,
            ActionKind.PROPOSE_RESOURCE_BLOCK,
            ActionKind.CONTACT_PARENT,
            ActionKind.SUBMIT_INCIDENT_REPORT,
        }
    ),
    ManaAICapability.FAMILY_DIGEST: frozenset(
        {
            ActionKind.NOTIFY_PARENT,
            ActionKind.REQUEST_CHECK_IN,
            ActionKind.GENERATE_FAMILY_REPORT,
        }
    ),
    ManaAICapability.ADAPTIVE_SCREEN_TIME: frozenset(
        {
            ActionKind.NOTIFY_PARENT,
            ActionKind.WARN_CHILD,
            ActionKind.PROPOSE_LIMIT_CHANGE,
            ActionKind.PROPOSE_STUDY_MODE,
            ActionKind.PROPOSE_APP_RESTRICTION,
            ActionKind.PROPOSE_TEMPORARY_ACCESS,
        }
    ),
    ManaAICapability.LOCATION_INTELLIGENCE: frozenset(
        {
            ActionKind.NOTIFY_PARENT,
            ActionKind.REQUEST_CHECK_IN,
            ActionKind.PROPOSE_GEOFENCE,
        }
    ),
    ManaAICapability.SMART_CONTENT_FILTER: frozenset(
        {
            ActionKind.NOTIFY_PARENT,
            ActionKind.WARN_CHILD,
            ActionKind.PROPOSE_RESOURCE_BLOCK,
        }
    ),
    ManaAICapability.SCAM_PRIVACY_SHIELD: frozenset(
        {
            ActionKind.NOTIFY_PARENT,
            ActionKind.WARN_CHILD,
            ActionKind.PROPOSE_RESOURCE_BLOCK,
            ActionKind.CONTACT_PARENT,
            ActionKind.SUBMIT_INCIDENT_REPORT,
        }
    ),
    ManaAICapability.AI_GAMING_SAFETY: frozenset(
        {
            ActionKind.NOTIFY_PARENT,
            ActionKind.WARN_CHILD,
            ActionKind.PROPOSE_LIMIT_CHANGE,
            ActionKind.PROPOSE_APP_RESTRICTION,
        }
    ),
    ManaAICapability.PARENT_COPILOT: frozenset(
        {
            ActionKind.PROPOSE_LIMIT_CHANGE,
            ActionKind.PROPOSE_STUDY_MODE,
            ActionKind.PROPOSE_GEOFENCE,
            ActionKind.PROPOSE_APP_RESTRICTION,
            ActionKind.PROPOSE_TEMPORARY_ACCESS,
            ActionKind.GENERATE_FAMILY_REPORT,
        }
    ),
    ManaAICapability.CHILD_SAFETY_ASSISTANT: frozenset(
        {
            ActionKind.WARN_CHILD,
            ActionKind.CONTACT_PARENT,
            ActionKind.SUBMIT_EXTRA_TIME_REQUEST,
            ActionKind.SUBMIT_INCIDENT_REPORT,
        }
    ),
    ManaAICapability.FAMILY_AGREEMENT: frozenset(
        {
            ActionKind.PROPOSE_AGREEMENT_UPDATE,
            ActionKind.SUBMIT_EXTRA_TIME_REQUEST,
        }
    ),
    ManaAICapability.BEHAVIOUR_ANOMALY: frozenset(
        {
            ActionKind.NOTIFY_PARENT,
            ActionKind.WARN_CHILD,
            ActionKind.REQUEST_CHECK_IN,
        }
    ),
}


def execution_policy(action_kind: ActionKind) -> ExecutionPolicy:
    if action_kind in PARENT_CONFIRMATION_ACTIONS:
        return ExecutionPolicy.PARENT_CONFIRMATION_REQUIRED
    if action_kind in INFORMATION_ONLY_ACTIONS:
        return ExecutionPolicy.INFORMATION_ONLY
    return ExecutionPolicy.APPLICATION_POLICY_REQUIRED


def filter_actions(
    request: ManaAIRequest,
    actions: list[ActionValue],
) -> tuple[list[ActionValue], list[str]]:
    allowed = set(ALLOWED_ACTIONS[request.input.capability])
    if isinstance(request.input, ParentCopilotInput) and request.input.allowed_action_kinds:
        allowed.intersection_update(request.input.allowed_action_kinds)

    accepted: list[ActionValue] = []
    notes: list[str] = []
    seen: set[str] = set()
    for action in actions:
        if action.kind not in allowed:
            notes.append(f"Unsupported action proposal was removed: {action.kind.value}")
            continue
        if not _action_target_is_known(request.input, action):
            notes.append(f"Action proposal with an unknown target was removed: {action.kind.value}")
            continue
        serialized = ACTION_ADAPTER.dump_json(action).decode()
        if serialized in seen:
            continue
        seen.add(serialized)
        accepted.append(action)
    return accepted, notes


def build_action_proposals(
    request_id: str,
    actions: list[ActionValue],
) -> list[ManaAIActionProposal]:
    proposals: list[ManaAIActionProposal] = []
    for action in actions:
        policy = execution_policy(action.kind)
        proposals.append(
            ManaAIActionProposal(
                proposal_id=_stable_id("proposal", request_id, action.model_dump_json()),
                action=action,
                execution_policy=policy,
                requires_parent_confirmation=(
                    policy is ExecutionPolicy.PARENT_CONFIRMATION_REQUIRED
                ),
            )
        )
    return proposals


def build_findings(request_id: str, drafts: list[FindingDraft]) -> list[ManaAIFinding]:
    findings: list[ManaAIFinding] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for draft in drafts:
        key = (draft.category.value, tuple(sorted(draft.evidence_ids)))
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            ManaAIFinding(
                **draft.model_dump(),
                finding_id=_stable_id("finding", request_id, draft.model_dump_json()),
            )
        )
    return findings


def _stable_id(prefix: str, request_id: str, payload: str) -> str:
    digest = hashlib.sha256(f"{request_id}:{payload}".encode()).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _action_target_is_known(payload: CapabilityInput, action: ActionValue) -> bool:
    packages, categories = _collect_app_targets(payload)
    if isinstance(action, LimitChangeAction):
        known_targets = packages if action.target_kind == "application" else categories
        return action.target in known_targets
    if isinstance(
        action,
        AppRestrictionAction | TemporaryAccessAction | SubmitExtraTimeRequestAction,
    ):
        return action.package_name in packages
    return True


def _collect_app_targets(value: object) -> tuple[set[str], set[str]]:
    packages: set[str] = set()
    categories: set[str] = set()
    if isinstance(value, AppUsageSignal):
        packages.add(value.package_name)
        if value.category.value != "unknown":
            categories.add(value.category.value)
    elif isinstance(value, AppLimit):
        if value.package_name is not None:
            packages.add(value.package_name)
        if value.category is not None and value.category.value != "unknown":
            categories.add(value.category.value)
    elif isinstance(value, ExtraTimeRequest):
        packages.add(value.package_name)
    elif isinstance(value, FamilyPreferences):
        packages.update(value.allowed_applications)
        packages.update(value.blocked_applications)

    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            child_packages, child_categories = _collect_app_targets(getattr(value, field_name))
            packages.update(child_packages)
            categories.update(child_categories)
    elif isinstance(value, list | tuple):
        for item in value:
            child_packages, child_categories = _collect_app_targets(item)
            packages.update(child_packages)
            categories.update(child_categories)
    return packages, categories
