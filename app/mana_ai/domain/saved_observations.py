"""Separate local-SQL inspection authority; never an external source-read receipt."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId
from app.mana_ai.domain.family_day_usage import DAY_USAGE_SOURCE, day_child_fingerprint
from app.mana_ai.domain.family_sources import (
    ChildAppUsageFacts,
    ChildSourceFacts,
    ObservedSourceKey,
    source_facts,
)


class SavedObservationLimits(ChatContract):
    version: Literal[1] = 1
    global_inspections_per_24h: int = Field(default=1000, ge=1, le=10000, strict=True)
    parent_inspections_per_24h: int = Field(default=20, ge=1, le=100, strict=True)


class SavedObservationTarget(ChatContract):
    operation: Literal["saved_observation_inspection"] = "saved_observation_inspection"
    parent_id: ParentChatId
    child_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    request_id: UUID
    source: ObservedSourceKey
    requested_day: date | None = None

    @model_validator(mode="after")
    def exact_kind(self) -> "SavedObservationTarget":
        if (self.source == DAY_USAGE_SOURCE) != (self.requested_day is not None):
            raise ValueError("Only a saved query-day observation carries its exact calendar label")
        return self


SavedObservationReason = Literal[
    "source_not_enabled",
    "source_unresolved",
    "source_stopped",
    "saved_observation_missing",
    "saved_observation_stale",
    "saved_child_not_returned",
]


class SavedObservationProvenance(ChatContract):
    source: ObservedSourceKey
    provider_checked_at: AwareDatetime | None
    snapshot_collected_at: AwareDatetime | None
    inspected_at: AwareDatetime
    provider_refreshed: Literal[False] = False
    inspection_scope: Literal["saved_sql_only"] = "saved_sql_only"


class SavedObservationReceipt(SavedObservationTarget):
    status: Literal["completed", "unavailable"]
    inspected_at: AwareDatetime
    provider_checked_at: AwareDatetime | None = None
    snapshot_id: UUID | None = None
    fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    facts: ChildSourceFacts | None = None
    reason: SavedObservationReason | None = None

    @model_validator(mode="after")
    def coherent_result(self) -> "SavedObservationReceipt":
        if self.status == "completed":
            if (
                self.reason is not None
                or self.provider_checked_at is None
                or self.snapshot_id is None
                or self.fingerprint is None
                or self.facts is None
                or self.facts.child_id != self.child_id
                or self.facts.collected_at > self.provider_checked_at
                or self.provider_checked_at > self.inspected_at
            ):
                raise ValueError("A saved inspection preserves exact original source provenance")
            source_facts(
                self.facts.model_dump(),
                ("manakids.child_app_usage.v1" if self.source == DAY_USAGE_SOURCE else self.source),
            )
            if self.source == DAY_USAGE_SOURCE and self.requested_day is not None:
                if not isinstance(self.facts, ChildAppUsageFacts):
                    raise ValueError("A saved query-day result requires exact app facts")
                expected = day_child_fingerprint(self.facts, self.requested_day)
            else:
                expected = self.facts.fingerprint()
            if expected != self.fingerprint:
                raise ValueError("A saved inspection must retain its original fingerprint")
        elif self.reason is None or any(
            v is not None
            for v in (self.snapshot_id, self.fingerprint, self.facts, self.provider_checked_at)
        ):
            raise ValueError("An unavailable saved inspection carries no substitute evidence")
        return self

    def provenance(self) -> SavedObservationProvenance:
        return SavedObservationProvenance(
            source=self.source,
            provider_checked_at=self.provider_checked_at,
            snapshot_collected_at=self.facts.collected_at if self.facts else None,
            inspected_at=self.inspected_at,
        )
