"""Host-owned source snapshots; collection dates never imply measurement periods."""

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId
from app.mana_ai.domain.family_sources import ChildSourceFacts, FamilySourceKey


class SourceAnalysisOwner(ChatContract):
    parent_id: ParentChatId
    job_id: UUID


class SourceReviewSnapshot(ChatContract):
    source: FamilySourceKey
    snapshot_id: UUID
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    facts: ChildSourceFacts

    @model_validator(mode="after")
    def verified_snapshot(self) -> "SourceReviewSnapshot":
        from app.mana_ai.domain.family_sources import ChildBatteryFacts

        if self.facts.fingerprint() != self.fingerprint or (
            isinstance(self.facts, ChildBatteryFacts)
            != (self.source == "firebase.child_battery.v1")
        ):
            raise ValueError("Snapshot provenance and source kind must match")
        return self


class SourceReviewBundle(ChatContract):
    parent_id: ParentChatId
    child_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    snapshots: tuple[SourceReviewSnapshot, ...] = Field(min_length=1, max_length=2)
    changed_sources: tuple[FamilySourceKey, ...] = Field(min_length=1, max_length=2)
    frozen_at: AwareDatetime

    @model_validator(mode="after")
    def own_child_sources(self) -> "SourceReviewBundle":
        sources = {s.source for s in self.snapshots}
        if (
            len(sources) != len(self.snapshots)
            or len(set(self.changed_sources)) != len(self.changed_sources)
            or not set(self.changed_sources) <= sources
            or any(s.facts.child_id != self.child_id for s in self.snapshots)
            or any(s.facts.collected_at > self.frozen_at for s in self.snapshots)
        ):
            raise ValueError("A review contains unique own-child snapshots captured before freeze")
        return self

    def digest(self) -> str:
        # IDs, recollection and trigger labels cannot manufacture a new factual context.
        value = sorted((s.source, s.fingerprint) for s in self.snapshots)
        return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


class SourceReviewPolicy(ChatContract):
    version: Literal[1] = 1
    coalesce_seconds: int = Field(default=3, ge=0, le=60, strict=True)
    maximum_collection_age_seconds: int = Field(default=21600, ge=60, le=86400, strict=True)
    maximum_events: int = Field(default=100, ge=1, le=1000, strict=True)
    preparation_lease_seconds: int = Field(
        default=180, ge=30, le=600, strict=True, exclude_if=lambda value: value == 180
    )


class SourceReviewWork(ChatContract):
    review_id: UUID
    bundle: SourceReviewBundle
    phase: Literal["preparing", "prepared", "dispatching", "admitted", "skipped", "unknown"]
    reason: str | None = None
    job_id: UUID | None = None
    profile_collected_at: AwareDatetime | None = None
    child_age: int | None = Field(default=None, ge=1, le=17, strict=True)
    dispatch_now: bool = False

    @model_validator(mode="after")
    def phase_metadata(self) -> "SourceReviewWork":
        if (self.phase == "admitted") != (self.job_id is not None):
            raise ValueError("Only a verified admission carries a job ID")
        if (self.phase in {"skipped", "unknown"}) != (self.reason is not None):
            raise ValueError("Skipped/unknown source reviews need a closed reason")
        if self.phase in {"prepared", "dispatching", "admitted"} and (
            self.profile_collected_at is None or self.child_age is None
        ):
            raise ValueError("Dispatch requires a captured ownership profile")
        return self
