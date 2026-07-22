from collections.abc import Mapping
from enum import StrEnum
from typing import TypeVar

from app.mana_operation_ai.domain.enums import (
    ActionStatus,
    AgentRunStatus,
    ApprovalStatus,
    ExecutionStatus,
)


class InvalidStateTransition(ValueError):
    """Raised when a persisted lifecycle transition is not allowed."""


StateT = TypeVar("StateT", bound=StrEnum)


RUN_TRANSITIONS: Mapping[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.QUEUED: frozenset(
        {AgentRunStatus.COLLECTING, AgentRunStatus.CANCELLED, AgentRunStatus.FAILED},
    ),
    AgentRunStatus.COLLECTING: frozenset(
        {AgentRunStatus.NORMALIZING, AgentRunStatus.FAILED},
    ),
    AgentRunStatus.NORMALIZING: frozenset(
        {AgentRunStatus.ANALYZING, AgentRunStatus.FAILED},
    ),
    AgentRunStatus.ANALYZING: frozenset(
        {AgentRunStatus.PROPOSING, AgentRunStatus.FAILED},
    ),
    AgentRunStatus.PROPOSING: frozenset(
        {AgentRunStatus.POLICY_CHECK, AgentRunStatus.FAILED},
    ),
    AgentRunStatus.POLICY_CHECK: frozenset(
        {
            AgentRunStatus.WAITING_APPROVAL,
            AgentRunStatus.EXECUTING,
            AgentRunStatus.REPORTING,
            AgentRunStatus.FAILED,
        },
    ),
    AgentRunStatus.WAITING_APPROVAL: frozenset(
        {AgentRunStatus.EXECUTING, AgentRunStatus.REPORTING, AgentRunStatus.CANCELLED},
    ),
    AgentRunStatus.EXECUTING: frozenset(
        {AgentRunStatus.VERIFYING, AgentRunStatus.REPORTING, AgentRunStatus.FAILED},
    ),
    AgentRunStatus.VERIFYING: frozenset(
        {AgentRunStatus.REPORTING, AgentRunStatus.FAILED},
    ),
    AgentRunStatus.REPORTING: frozenset(
        {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED},
    ),
    AgentRunStatus.COMPLETED: frozenset(),
    AgentRunStatus.FAILED: frozenset({AgentRunStatus.QUEUED}),
    AgentRunStatus.CANCELLED: frozenset(),
}

ACTION_TRANSITIONS: Mapping[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.PROPOSED: frozenset(
        {
            ActionStatus.POLICY_REJECTED,
            ActionStatus.AWAITING_APPROVAL,
            ActionStatus.APPROVED,
            ActionStatus.DRY_RUN,
        },
    ),
    ActionStatus.AWAITING_APPROVAL: frozenset(
        {ActionStatus.APPROVED, ActionStatus.REJECTED, ActionStatus.EXPIRED},
    ),
    ActionStatus.APPROVED: frozenset(
        {
            ActionStatus.EXECUTING,
            ActionStatus.DRY_RUN,
            ActionStatus.EXPIRED,
            ActionStatus.CANCELLED,
        },
    ),
    ActionStatus.EXECUTING: frozenset(
        {ActionStatus.SUCCEEDED, ActionStatus.PARTIALLY_APPLIED, ActionStatus.FAILED},
    ),
    ActionStatus.POLICY_REJECTED: frozenset(),
    ActionStatus.REJECTED: frozenset(),
    ActionStatus.SUCCEEDED: frozenset(),
    ActionStatus.PARTIALLY_APPLIED: frozenset(),
    ActionStatus.FAILED: frozenset(),
    ActionStatus.EXPIRED: frozenset(),
    ActionStatus.CANCELLED: frozenset(),
    ActionStatus.DRY_RUN: frozenset(),
}

APPROVAL_TRANSITIONS: Mapping[ApprovalStatus, frozenset[ApprovalStatus]] = {
    ApprovalStatus.PENDING: frozenset(
        {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED},
    ),
    ApprovalStatus.APPROVED: frozenset(),
    ApprovalStatus.REJECTED: frozenset(),
    ApprovalStatus.EXPIRED: frozenset(),
}

EXECUTION_TRANSITIONS: Mapping[ExecutionStatus, frozenset[ExecutionStatus]] = {
    ExecutionStatus.PENDING: frozenset(
        {ExecutionStatus.EXECUTING, ExecutionStatus.DRY_RUN, ExecutionStatus.FAILED},
    ),
    ExecutionStatus.EXECUTING: frozenset(
        {
            ExecutionStatus.SUCCEEDED,
            ExecutionStatus.PARTIALLY_APPLIED,
            ExecutionStatus.FAILED,
        },
    ),
    ExecutionStatus.SUCCEEDED: frozenset(),
    ExecutionStatus.PARTIALLY_APPLIED: frozenset(),
    ExecutionStatus.FAILED: frozenset(),
    ExecutionStatus.DRY_RUN: frozenset(),
}


def require_transition(
    current: StateT,
    target: StateT,
    transitions: Mapping[StateT, frozenset[StateT]],
) -> None:
    if target not in transitions[current]:
        raise InvalidStateTransition(f"Invalid transition: {current.value} -> {target.value}")
