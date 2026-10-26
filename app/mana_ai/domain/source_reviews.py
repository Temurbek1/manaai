"""Host-owned source snapshots; collection dates never imply measurement periods."""

import hashlib
import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId
from app.mana_ai.domain.child_location import ChildLocationFacts
from app.mana_ai.domain.family_day_usage import DAY_USAGE_SOURCE, day_child_fingerprint
from app.mana_ai.domain.family_sources import (
    ChildAppUsageFacts,
    ChildSourceFacts,
    ObservedSourceKey,
)


class SourceAnalysisOwner(ChatContract):
    parent_id: ParentChatId
    job_id: UUID


class SourceReviewSnapshot(ChatContract):
    source: ObservedSourceKey
    snapshot_id: UUID
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    facts: ChildSourceFacts
    requested_day: date | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def verified_snapshot(self) -> "SourceReviewSnapshot":
        from app.mana_ai.domain.family_sources import ChildBatteryFacts

        expected = self.facts.fingerprint()
        if self.source == DAY_USAGE_SOURCE:
            if not isinstance(self.facts, ChildAppUsageFacts) or self.requested_day is None:
                raise ValueError("Dated review snapshots require app facts and a query day")
            expected = day_child_fingerprint(self.facts, self.requested_day)
            if any(
                not e.provider_recorded_at.startswith(self.requested_day.isoformat() + " ")
                for e in self.facts.entries
            ):
                raise ValueError("Counter labels must match the exact query day")
        elif self.requested_day is not None:
            raise ValueError("Undated sources cannot acquire a query day")
        if expected != self.fingerprint or (
            isinstance(self.facts, ChildBatteryFacts)
            != (self.source == "firebase.child_battery.v1")
        ):
            raise ValueError("Snapshot provenance and source kind must match")
        if isinstance(self.facts, ChildLocationFacts) != (
            self.source == "firebase.child_location.v1"
        ):
            raise ValueError("Location snapshot provenance must match")
        return self


class SavedUsageComparison(ChatContract):
    """One exact preceding query-day snapshot, not a verified behavioral baseline."""

    current_snapshot_id: UUID
    current_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    previous: SourceReviewSnapshot


class ReportedCounterChange(ChatContract):
    app_name: str = Field(min_length=1, max_length=160, strict=True)
    previous_reported_seconds: int = Field(ge=0, le=31 * 86400, strict=True)
    current_reported_seconds: int = Field(ge=0, le=31 * 86400, strict=True)
    change_seconds: int = Field(ge=-31 * 86400, le=31 * 86400, strict=True)

    @model_validator(mode="after")
    def exact_arithmetic(self) -> "ReportedCounterChange":
        if self.change_seconds != self.current_reported_seconds - self.previous_reported_seconds:
            raise ValueError("A reported difference must preserve its exact operands")
        return self


class CounterComparisonView(ChatContract):
    previous_query_calendar_day: date
    current_query_calendar_day: date
    previous_snapshot_collected_at: AwareDatetime
    previous_app_page_complete: bool = Field(strict=True)
    current_app_page_complete: bool = Field(strict=True)
    matched_single_rows: tuple[ReportedCounterChange, ...] = Field(max_length=10)
    unmatched_or_ambiguous_rows_are_not_zero: Literal[True] = True
    verified_behavioral_change: Literal[False] = False

    @model_validator(mode="after")
    def adjacent_days(self) -> "CounterComparisonView":
        if self.previous_query_calendar_day + timedelta(
            days=1
        ) != self.current_query_calendar_day or len(
            {r.app_name for r in self.matched_single_rows}
        ) != len(self.matched_single_rows):
            raise ValueError("Reported comparisons need adjacent query days and unique app rows")
        return self


def reported_counter_changes(
    current: ChildAppUsageFacts, previous: ChildAppUsageFacts
) -> tuple[ReportedCounterChange, ...]:
    """Compare single matched rows only; never sum overlaps or fill absent apps with zero."""
    if current.child_id != previous.child_id:
        raise ValueError("A counter comparison requires the same child")
    left: dict[str, list[int]] = defaultdict(list)
    right: dict[str, list[int]] = defaultdict(list)
    for entry in previous.entries:
        left[entry.app_name].append(entry.reported_seconds)
    for entry in current.entries:
        right[entry.app_name].append(entry.reported_seconds)
    rows = tuple(
        ReportedCounterChange(
            app_name=app,
            previous_reported_seconds=left[app][0],
            current_reported_seconds=right[app][0],
            change_seconds=right[app][0] - left[app][0],
        )
        for app in sorted(left.keys() & right.keys())
        if len(left[app]) == len(right[app]) == 1
    )
    if len(rows) > 10:
        raise ValueError("Counter comparison exceeds the admitted app-page bound")
    return rows


class SourceReviewBundle(ChatContract):
    parent_id: ParentChatId
    child_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    snapshots: tuple[SourceReviewSnapshot, ...] = Field(min_length=1, max_length=4)
    changed_sources: tuple[ObservedSourceKey, ...] = Field(min_length=1, max_length=4)
    frozen_at: AwareDatetime
    usage_comparison: SavedUsageComparison | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

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
        comparison = self.usage_comparison
        if comparison is not None:
            current = next((s for s in self.snapshots if s.source == DAY_USAGE_SOURCE), None)
            previous = comparison.previous
            if (
                current is None
                or current.requested_day is None
                or previous.requested_day != current.requested_day - timedelta(days=1)
                or previous.source != DAY_USAGE_SOURCE
                or previous.facts.child_id != self.child_id
                or previous.facts.collected_at > self.frozen_at
                or comparison.current_snapshot_id != current.snapshot_id
                or comparison.current_fingerprint != current.fingerprint
                or DAY_USAGE_SOURCE not in self.changed_sources
            ):
                raise ValueError("Saved comparisons require exact own-child adjacent query days")
            assert isinstance(current.facts, ChildAppUsageFacts)
            assert isinstance(previous.facts, ChildAppUsageFacts)
            reported_counter_changes(current.facts, previous.facts)
        return self

    def digest(self) -> str:
        # IDs, recollection and trigger labels cannot manufacture a new factual context.
        value: list[tuple[str, str]] = sorted((s.source, s.fingerprint) for s in self.snapshots)
        if self.usage_comparison is not None:
            value.append(("saved_previous_query_day", self.usage_comparison.previous.fingerprint))
        return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


def counter_comparison_view(bundle: SourceReviewBundle) -> CounterComparisonView | None:
    comparison = bundle.usage_comparison
    if comparison is None:
        return None
    current = next(s for s in bundle.snapshots if s.source == DAY_USAGE_SOURCE)
    previous = comparison.previous
    assert isinstance(current.facts, ChildAppUsageFacts)
    assert isinstance(previous.facts, ChildAppUsageFacts)
    assert previous.requested_day is not None and current.requested_day is not None
    return CounterComparisonView(
        previous_query_calendar_day=previous.requested_day,
        current_query_calendar_day=current.requested_day,
        previous_snapshot_collected_at=previous.facts.collected_at,
        previous_app_page_complete=previous.facts.complete,
        current_app_page_complete=current.facts.complete,
        matched_single_rows=reported_counter_changes(current.facts, previous.facts),
    )


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
