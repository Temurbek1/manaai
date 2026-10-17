"""Durable preparation admission, never a send/source/Goal grant."""

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field

from app.mana_operation_ai.domain.models import DomainModel
from app.mana_operation_ai.domain.retention_contact import RetentionContactPrepare

PreparationFailureCode = Literal[
    "contact_preparation_stopped",
    "contact_preparation_pending",
    "contact_preparation_limit",
    "contact_preparation_conflict",
    "contact_preparation_history_unavailable",
]


class ContactPreparationLimits(DomainModel):
    model_config = ConfigDict(frozen=True)
    per_turn: int = Field(default=3, strict=True, ge=1, le=3)
    per_owner_hour: int = Field(default=10, strict=True, ge=1, le=100)
    per_day: int = Field(default=100, strict=True, ge=1, le=1000)
    legacy_scan_limit: int = Field(default=400, strict=True, ge=1, le=10000)


class ContactPreparationBinding(DomainModel):
    model_config = ConfigDict(frozen=True)
    owner: str = Field(min_length=1, max_length=128)
    topic_id: str = Field(min_length=1, max_length=64)
    turn_id: str | None = Field(default=None, min_length=1, max_length=64)
    request_id: UUID
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def preparation_binding(
    owner: str, topic_id: str, turn_id: str | None, request: RetentionContactPrepare
) -> ContactPreparationBinding:
    value = {
        "owner": owner,
        "topic_id": topic_id,
        "turn_id": turn_id,
        "request": request.model_dump(mode="json"),
    }
    return ContactPreparationBinding(
        owner=owner,
        topic_id=topic_id,
        turn_id=turn_id,
        request_id=request.request_id,
        request_sha256=hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        target_sha256=hashlib.sha256(request.parameters.account_ref.encode()).hexdigest(),
    )


class ContactPreparationClaim(DomainModel):
    model_config = ConfigDict(frozen=True)
    claim_id: UUID
    binding: ContactPreparationBinding
    admitted_at: AwareDatetime
    limits: ContactPreparationLimits


class ContactPreparationAvailability(DomainModel):
    state: Literal["requires_confirmation", "stopped", "pending"]


class ContactPreparationFailure(DomainModel):
    code: PreparationFailureCode
    message: str = Field(min_length=1, max_length=500)
