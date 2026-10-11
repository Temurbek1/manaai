"""A human decision lane, separate from read-only Goals and provider credentials."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.mana_operation_ai.domain.enums import ActionStatus, ExecutionStatus, VerificationStatus
from app.mana_operation_ai.domain.models import CreateExperimentActionParameters, DomainModel

SANDBOX_MANA_FUNNEL_SCOPE = "sandbox:mana:parent_acquisition_funnel_cohort"


class WorkspaceActionDecision(DomainModel):
    request_id: UUID
    confirmed: Literal[True]
    approve: bool
    reason: str = Field(min_length=1, max_length=1000)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def require_reason(self) -> "WorkspaceActionDecision":
        if not self.reason.strip():
            raise ValueError("A decision requires a nonblank reason")
        return self


class WorkspaceActionReceipt(DomainModel):
    receipt_id: str
    topic_id: str
    turn_id: str
    proposal_id: str
    product: Literal["mana"] = "mana"
    synthetic: Literal[True] = True
    provider: Literal["fake_experiments"] = "fake_experiments"
    parameters: CreateExperimentActionParameters
    request: WorkspaceActionDecision
    created_at: datetime
    state: Literal["dispatching", "resolved", "unknown", "refused"] = "dispatching"
    message: str = Field(default="Решение принято в обработку.", max_length=1000)


class WorkspaceActionHistory(DomainModel):
    proposal_id: str
    product: Literal["mana"] = "mana"
    mode: Literal["sandbox"] = "sandbox"
    operation: Literal["create_experiment"] = "create_experiment"
    at: datetime
    status: ActionStatus
    execution_status: ExecutionStatus | None = None
    verification_status: VerificationStatus | None = None
    message: str = Field(max_length=1000)
    business_outcome: Literal["not_measured"] = "not_measured"


class WorkspaceActionView(DomainModel):
    proposal_id: str
    product: Literal["mana"] = "mana"
    synthetic: Literal[True] = True
    provider: Literal["fake_experiments"] = "fake_experiments"
    status: ActionStatus
    parameters: CreateExperimentActionParameters
    reasoning: str = Field(max_length=2000)
    expected_effect: str = Field(max_length=2000)
    risks: list[str] = Field(max_length=10)
    expires_at: datetime
    fingerprint: str
    self_approval_forbidden: bool
    receipt: WorkspaceActionReceipt | None = None
    execution_status: ExecutionStatus | None = None
    verification_status: VerificationStatus | None = None
    business_outcome: Literal["not_measured"] = "not_measured"


class WorkspaceActionPage(DomainModel):
    items: list[WorkspaceActionView] = Field(default_factory=list, max_length=3)
    catalog_bounded: Literal[True] = True
    more_omitted: bool = False
