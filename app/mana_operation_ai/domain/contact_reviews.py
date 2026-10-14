"""One explicit review disclosure; no topic, source or future-action authority."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.mana_operation_ai.domain.models import DomainModel
from app.mana_operation_ai.domain.retention_contact import RetentionContactAction
from app.mana_operation_ai.domain.workspace_retention_contacts import WorkspaceContactView


class ContactReviewCreate(DomainModel):
    request_id: UUID
    reviewer_id: UUID
    confirmed: Literal[True]
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("confirmed", mode="before")
    @classmethod
    def confirmation(cls, value: object) -> bool:
        if value is not True:
            raise ValueError("Sharing a single action requires literal human confirmation")
        return True


class ContactReviewer(DomainModel):
    user_id: str
    label: str = Field(max_length=160)


class ContactReviewGrant(DomainModel):
    version: Literal[1] = 1
    review_id: str
    owner: str
    action_id: str
    topic_id: str
    turn_id: str
    request: ContactReviewCreate
    created_at: AwareDatetime
    expires_at: AwareDatetime
    revoked_at: AwareDatetime | None = None
    revision: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def valid_grant(self) -> "ContactReviewGrant":
        if self.owner == str(self.request.reviewer_id) or self.created_at >= self.expires_at:
            raise ValueError("A review requires another person and a bounded future expiry")
        if (self.revision == 1) != (self.revoked_at is not None):
            raise ValueError("Revocation and its revision must match")
        if self.revoked_at is not None and self.revoked_at < self.created_at:
            raise ValueError("Revocation cannot precede sharing")
        return self

    def matches(self, action: RetentionContactAction) -> bool:
        return (
            action.version == 2
            and (self.owner, self.action_id, self.topic_id, self.turn_id)
            == (action.owner, action.action_id, action.topic_id, action.turn_id)
            and self.request.fingerprint == action.fingerprint
            and self.expires_at == action.expires_at
        )


class ContactReviewReceipt(DomainModel):
    review_id: str
    reviewer: ContactReviewer
    expires_at: AwareDatetime
    revoked: bool


class ContactReviewOptions(DomainModel):
    reviewers: list[ContactReviewer] = Field(max_length=20)
    more_omitted: bool = False
    review: ContactReviewReceipt | None = None


class ContactReviewItem(DomainModel):
    review_id: str
    action: WorkspaceContactView


class ContactReviewPage(DomainModel):
    items: list[ContactReviewItem] = Field(max_length=20)
    more_omitted: bool = False
