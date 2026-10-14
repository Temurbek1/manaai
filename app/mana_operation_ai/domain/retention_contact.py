"""Private, sandbox-only adult contact contracts; no recipients, benefits or provider payloads."""

import hashlib
import json
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.mana_operation_ai.domain.models import DomainModel
from app.mana_operation_ai.domain.retention_risk import CustomerRetentionFacts, RetentionRiskZone

SandboxRecipient = Literal["sample_ru", "sample_uz"]
ContactTemplate = Literal["onboarding_help", "renewal_reminder"]


class RetentionContactActionType(StrEnum):
    SEND_MESSAGE = "send_retention_message"


class RetentionContactParameters(DomainModel):
    kind: Literal[RetentionContactActionType.SEND_MESSAGE] = RetentionContactActionType.SEND_MESSAGE
    product: Literal["mana"] = "mana"
    mode: Literal["sandbox"] = "sandbox"
    account_ref: str = Field(pattern=r"^acct_[a-f0-9]{64}$")
    channel: Literal["push"] = "push"
    template: Literal["onboarding_help", "renewal_reminder"]
    language: Literal["ru", "uz"] = "ru"


class RetentionContactPrepare(DomainModel):
    request_id: UUID
    parameters: RetentionContactParameters


class RetentionContactDecision(DomainModel):
    request_id: UUID
    confirmed: Literal[True]
    approve: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=1000)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("confirmed", mode="before")
    @classmethod
    def require_literal_confirmation(cls, value: object) -> bool:
        if value is not True:
            raise ValueError("Confirmation must be the literal boolean true")
        return True

    @model_validator(mode="after")
    def validate_reason(self) -> "RetentionContactDecision":
        if not self.reason.strip():
            raise ValueError("A human decision requires a nonblank reason")
        return self


class RetentionContactMessage(DomainModel):
    template: Literal["onboarding_help", "renewal_reminder"]
    version: Literal["retention-contact-ru-v1", "retention-contact-uz-v1"] = (
        "retention-contact-ru-v1"
    )
    language: Literal["ru", "uz"] = "ru"
    text: str = Field(min_length=1, max_length=280)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_digest(self) -> "RetentionContactMessage":
        if self.version != f"retention-contact-{self.language}-v1":
            raise ValueError("The message version must match its explicit language")
        if self.sha256 != hashlib.sha256(self.text.encode()).hexdigest():
            raise ValueError("The exact message text must match its digest")
        return self


def contact_proposal_fingerprint(
    *,
    action_id: str,
    owner: str,
    topic_id: str,
    request: RetentionContactPrepare,
    message: RetentionContactMessage,
    target_sha256: str,
    policy: "RetentionContactPolicyResult",
    prepared_at: AwareDatetime,
    expires_at: AwareDatetime,
    turn_id: str | None = None,
) -> str:
    value = {
        "version": 1,
        "action_id": action_id,
        "owner": owner,
        "topic_id": topic_id,
        "request": request.model_dump(mode="json"),
        "message": message.model_dump(mode="json"),
        "target_sha256": target_sha256,
        "policy": policy.model_dump(mode="json"),
        "prepared_at": prepared_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    if turn_id is not None:
        value.update(version=2, turn_id=turn_id)
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class RetentionContactDelivery(DomainModel):
    action_id: str
    parameters_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    accepted_at: AwareDatetime
    provider_receipt_id: str = Field(pattern=r"^fake-contact-[a-f0-9]{32}$")
    state: Literal["sandbox_accepted"] = "sandbox_accepted"


class RetentionContactTarget(DomainModel):
    product: Literal["mana"] = "mana"
    provider: Literal["fake_retention_contact"] = "fake_retention_contact"
    facts: CustomerRetentionFacts
    observed_at: AwareDatetime
    consent: bool | None = Field(strict=True)
    consent_channel: Literal["push"] | None
    consent_purpose: Literal["retention_support"] | None
    consent_evidence_ref: str | None = Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    preferred_language: Literal["ru", "uz"] | None
    consent_observed_at: AwareDatetime
    consent_expires_at: AwareDatetime
    suppressed: bool | None = Field(strict=True)
    timezone: str = Field(min_length=1, max_length=80)
    # At most one approved sandbox contact per seven days; not a full contact history.
    deliveries: list[RetentionContactDelivery] = Field(default_factory=list, max_length=100)
    contact_history_complete: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_target(self) -> "RetentionContactTarget":
        if self.facts.mode != "sandbox":
            raise ValueError("The contact sandbox refuses live account facts")
        if not self.facts.collected_at <= self.observed_at:
            raise ValueError("Account facts cannot be newer than target observation")
        if not self.consent_observed_at <= self.observed_at:
            raise ValueError("Consent cannot be newer than target observation")
        if self.consent_expires_at <= self.consent_observed_at:
            raise ValueError("Consent validity must be an ordered interval")
        if any(item.accepted_at > self.observed_at for item in self.deliveries):
            raise ValueError("A contact cannot be newer than target observation")
        if len({item.action_id for item in self.deliveries}) != len(self.deliveries):
            raise ValueError("Contact action IDs must be unique")
        return self


class RetentionContactPolicyResult(DomainModel):
    eligible_for_review: bool
    zone: RetentionRiskZone
    reasons: list[str]
    customer_action_authorized: Literal[False] = False


ContactStatus = Literal["proposed", "rejected", "dispatching", "verified", "uncertain", "refused"]


class RetentionContactAction(DomainModel):
    version: Literal[1, 2] = 1
    action_id: str
    owner: str
    topic_id: str
    turn_id: str | None = None
    agent_id: Literal["retention-agent"] = "retention-agent"
    capability_key: Literal["retention.contact.sandbox"] = "retention.contact.sandbox"
    request: RetentionContactPrepare
    message: RetentionContactMessage
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy: RetentionContactPolicyResult
    prepared_at: AwareDatetime
    expires_at: AwareDatetime
    status: ContactStatus = "proposed"
    revision: int = Field(default=0, ge=0)
    decision: RetentionContactDecision | None = None
    decided_by: str | None = None
    delivery: RetentionContactDelivery | None = None
    result_code: str = "awaiting_human_decision"
    business_outcome: Literal["not_measured"] = "not_measured"

    @model_validator(mode="after")
    def validate_state(self) -> "RetentionContactAction":
        if (self.version == 2) != (self.turn_id is not None):
            raise ValueError("Only a version-two contact intent has a bound chat turn")
        if (self.message.template, self.message.language) != (
            self.request.parameters.template,
            self.request.parameters.language,
        ):
            raise ValueError("The message must belong to the requested template and language")
        if self.fingerprint != contact_proposal_fingerprint(
            action_id=self.action_id,
            owner=self.owner,
            topic_id=self.topic_id,
            request=self.request,
            message=self.message,
            target_sha256=self.target_sha256,
            policy=self.policy,
            prepared_at=self.prepared_at,
            expires_at=self.expires_at,
            turn_id=self.turn_id,
        ):
            raise ValueError("The exact proposal content must match its fingerprint")
        if self.expires_at <= self.prepared_at:
            raise ValueError("A proposal requires a future expiry")
        if (self.decision is None) != (self.decided_by is None):
            raise ValueError("A human decision requires its actor")
        if self.decision is not None and self.decision.fingerprint != self.fingerprint:
            raise ValueError("The stored human decision must bind the exact proposal")
        if self.delivery is not None and self.delivery.action_id != self.action_id:
            raise ValueError("A delivery must belong to the same action")
        if self.status == "proposed" and (self.decision is not None or self.delivery is not None):
            raise ValueError("A proposed action has no decision or delivery")
        if self.status in {"dispatching", "verified", "uncertain"} and (
            self.decision is None or not self.decision.approve
        ):
            raise ValueError("A dispatchable action requires explicit human approval")
        if self.status == "verified" and self.delivery is None:
            raise ValueError("Verification requires the exact provider receipt")
        if self.status == "rejected" and (self.decision is None or self.decision.approve):
            raise ValueError("Rejection requires a negative human decision")
        return self


class RetentionContactEvent(DomainModel):
    action_id: str
    revision: int
    at: AwareDatetime
    status: ContactStatus
    code: str
