"""Minimized, topic/turn-owned contact review; not a Goal tool or a live recipient API."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.mana_operation_ai.domain.contact_admission import (
    ContactPreparationAvailability,
    ContactPreparationFailure,
)
from app.mana_operation_ai.domain.contact_continuation import ContactContinuationView
from app.mana_operation_ai.domain.contact_preparation import ContactToolRequest
from app.mana_operation_ai.domain.models import DomainModel
from app.mana_operation_ai.domain.retention_contact import (
    ContactStatus,
    RetentionContactMessage,
)
from app.mana_operation_ai.domain.retention_contact import (
    ContactTemplate as ContactTemplate,
)
from app.mana_operation_ai.domain.retention_contact import (
    SandboxRecipient as SandboxRecipient,
)


class WorkspaceContactPrepare(DomainModel):
    request_id: UUID
    confirmed: Literal[True]
    recipient: SandboxRecipient
    template: ContactTemplate
    selection_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("confirmed", mode="before")
    @classmethod
    def literal_confirmation(cls, value: object) -> bool:
        if value is not True:
            raise ValueError("Contact preparation requires a literal human confirmation")
        return True


class WorkspaceContactReconcile(DomainModel):
    confirmed: Literal[True]
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("confirmed", mode="before")
    @classmethod
    def literal_confirmation(cls, value: object) -> bool:
        if value is not True:
            raise ValueError("Receipt observation requires a literal human confirmation")
        return True


class WorkspaceContactRecipient(DomainModel):
    key: SandboxRecipient
    language: Literal["ru", "uz"]
    synthetic: Literal[True] = True


class WorkspaceContactView(DomainModel):
    action_id: str
    topic_id: str
    turn_id: str
    recipient: SandboxRecipient
    product: Literal["mana"] = "mana"
    synthetic: Literal[True] = True
    provider: Literal["fake_retention_contact"] = "fake_retention_contact"
    message: RetentionContactMessage
    fingerprint: str
    expires_at: datetime
    status: ContactStatus
    revision: int
    result_code: str
    policy_reasons: list[str] = Field(max_length=30)
    self_approval_forbidden: bool
    decision_recorded: bool
    business_outcome: Literal["not_measured"] = "not_measured"


class WorkspaceContactPage(DomainModel):
    items: list[WorkspaceContactView] = Field(max_length=3)
    recipients: tuple[WorkspaceContactRecipient, WorkspaceContactRecipient]
    templates: tuple[Literal["onboarding_help"], Literal["renewal_reminder"]] = (
        "onboarding_help",
        "renewal_reminder",
    )
    more_omitted: bool = False
    peer_reviews_enabled: bool = False
    preparation_request: ContactToolRequest | None = None
    continuation_available: bool = False
    continuation: ContactContinuationView | None = None
    preparation_availability: ContactPreparationAvailability | None = None


class WorkspacePreparationObservation(DomainModel):
    request_id: UUID
    state: Literal["absent", "pending", "recorded"]
    action: WorkspaceContactView | None = None

    @model_validator(mode="after")
    def exact_recorded_result(self) -> Self:
        if (self.state == "recorded") != (self.action is not None):
            raise ValueError("Only a recorded preparation has an exact SQL action result")
        return self


class WorkspacePreparationFailure(DomainModel):
    detail: ContactPreparationFailure


class WorkspaceContactHistory(DomainModel):
    """A frozen SQL event, not permission or proof of real delivery."""

    action_id: str
    turn_id: str
    product: Literal["mana"] = "mana"
    mode: Literal["sandbox"] = "sandbox"
    provider: Literal["fake_retention_contact"] = "fake_retention_contact"
    at: AwareDatetime
    revision: int = Field(ge=0)
    status: ContactStatus
    template: ContactTemplate
    language: Literal["ru", "uz"]
    message_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    business_outcome: Literal["not_measured"] = "not_measured"
