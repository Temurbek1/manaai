"""Saved, minimized collection coverage; never a population or child-risk assessment."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.mana_operation_ai.domain.models import DomainModel

Count = Annotated[int, Field(ge=0, le=100_000_000, strict=True)]
CollectionSource = Literal[
    "firebase.child_battery.v1",
    "manakids.child_app_usage.v1",
    "manakids.family_day_app_usage.v1",
    "firebase.child_location.v1",
]


class SavedCollectionConfiguration(DomainModel):
    maximum_age_seconds: int = Field(default=86_400, ge=60, le=604_800, strict=True)


class SavedSourceCoverage(DomainModel):
    source: CollectionSource
    target_scope: Literal["child", "family"]
    target_reads: Count
    completed: Count
    cache_hits: Count
    failed: Count
    unknown: Count
    skipped: Count
    unavailable: Count
    available: Count
    undated: Count
    low_battery_records: Count
    partial_counter_pages: Count
    oldest_snapshot_collection_at: AwareDatetime | None
    latest_provider_check_at: AwareDatetime | None
    first_observation_at: AwareDatetime | None
    last_observation_at: AwareDatetime | None

    @model_validator(mode="after")
    def coherent_counts(self) -> "SavedSourceCoverage":
        if (
            self.completed + self.failed + self.unknown + self.skipped + self.unavailable
            != self.target_reads
            or self.cache_hits > self.completed
            or self.available > self.completed
            or self.undated > self.available
            or self.low_battery_records > self.available
            or self.partial_counter_pages > self.available
            or (self.source == "manakids.family_day_app_usage.v1")
            != (self.target_scope == "family")
        ):
            raise ValueError("Saved source coverage counts are inconsistent")
        if (
            self.first_observation_at is not None
            and self.last_observation_at is not None
            and self.first_observation_at > self.last_observation_at
        ):
            raise ValueError("Saved observation dates are inconsistent")
        return self


class SavedCollectionFacts(DomainModel):
    schema_version: Literal["saved-family-collection-v1"] = "saved-family-collection-v1"
    product: Literal["MANA"] = "MANA"
    mode: Literal["saved_aggregate"] = "saved_aggregate"
    window_id: UUID
    scheduled_at: AwareDatetime
    deadline: AwareDatetime
    published_at: AwareDatetime
    inspected_at: AwareDatetime
    status: Literal["completed", "partial", "skipped", "unknown"]
    parents_seen: Count
    total_parents_reported: Count | None
    inventory_start_offset: Count
    inventory_exhausted: bool = Field(strict=True)
    inventory_changed: bool = Field(strict=True)
    pages: Count
    targets: Count
    pending_targets: Count
    counts: tuple[SavedSourceCoverage, ...] = Field(max_length=4)
    population_complete: Literal[False] = False
    external_reads: Literal[0] = 0
    inference_calls: Literal[0] = 0

    @model_validator(mode="after")
    def coherent_window(self) -> "SavedCollectionFacts":
        if (
            self.scheduled_at > self.published_at
            or self.published_at > self.inspected_at
            or self.deadline <= self.scheduled_at
            or len({item.source for item in self.counts}) != len(self.counts)
            or sum(item.target_reads for item in self.counts) != self.targets
        ):
            raise ValueError("Saved collection coverage is inconsistent")
        for item in self.counts:
            for value in (
                item.oldest_snapshot_collection_at,
                item.latest_provider_check_at,
                item.first_observation_at,
                item.last_observation_at,
            ):
                if value is not None and value > self.published_at:
                    raise ValueError("A saved observation cannot follow publication")
        return self

    def age_seconds(self, now: datetime) -> int:
        return max(0, int((now - self.published_at).total_seconds()))
