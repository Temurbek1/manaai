"""Immutable source-to-specialist intent; no contact or inference authority."""

from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId
from app.mana_ai.domain.child_safety import SafetyTarget
from app.mana_ai.domain.family_sources import ChildBatteryFacts, FamilySourceChange
from app.mana_ai.domain.requests import SafetyMonitorRequest


class SourceSafetyPolicy(ChatContract):
    version: Literal[1] = 1
    timezone: str = Field(default="Asia/Tashkent", max_length=64)
    maximum_age_seconds: int = Field(default=21600, ge=60, le=86400, strict=True)

    @model_validator(mode="after")
    def valid_timezone(self) -> "SourceSafetyPolicy":
        ZoneInfo(self.timezone)
        return self


SourceSafetyPhase = Literal[
    "preparing", "prepared", "dispatching", "admitted", "skipped", "unknown"
]
SourceSafetyReason = Literal[
    "not_admitted",
    "no_observation",
    "undated",
    "stale",
    "duplicate",
    "prior_unresolved",
    "ownership_denied",
    "age_unknown",
    "preparation_unknown",
    "admission_unknown",
    "admission_refused",
]


class SourceSafetyIntent(ChatContract):
    target: SafetyTarget
    analysis: SafetyMonitorRequest
    child_age: int = Field(ge=1, le=17, strict=True)
    profile_collected_at: AwareDatetime


class SourceSafetyReceipt(ChatContract):
    event_id: UUID
    parent_id: ParentChatId
    child_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    snapshot_id: UUID
    phase: SourceSafetyPhase
    started_at: AwareDatetime
    updated_at: AwareDatetime
    reason: SourceSafetyReason | None = None
    job_id: UUID | None = None

    @model_validator(mode="after")
    def phase_identity(self) -> "SourceSafetyReceipt":
        if (self.phase == "admitted") != (self.job_id is not None):
            raise ValueError("Only a verified admission may carry a job ID")
        if (self.phase in {"skipped", "unknown"}) != (self.reason is not None):
            raise ValueError("Only skipped/unknown work has a closed reason")
        if self.updated_at < self.started_at:
            raise ValueError("Dispatch dates are out of order")
        return self


class SourceSafetyWork(ChatContract):
    receipt: SourceSafetyReceipt
    event: FamilySourceChange
    facts: ChildBatteryFacts
    intent: SourceSafetyIntent | None = None
    dispatch_now: bool = Field(default=False, strict=True)
