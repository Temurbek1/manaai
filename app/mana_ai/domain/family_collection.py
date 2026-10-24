"""Governed family collection windows, not agent tasks or contact authority."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId
from app.mana_ai.domain.family_sources import FamilySourceKey, FamilySourceTarget


class FamilyCollectionPolicy(ChatContract):
    timezone: Literal["Asia/Tashkent"] = "Asia/Tashkent"
    start_grace_seconds: int = Field(default=300, ge=1, le=900, strict=True)
    duration_seconds: int = Field(default=1800, ge=60, le=3600, strict=True)
    page_size: int = Field(default=25, ge=1, le=100, strict=True)
    pages_per_window: int = Field(default=100, ge=1, le=10000, strict=True)
    inventory_attempts_per_24h: int = Field(default=400, ge=2, le=40000, strict=True)
    reads_per_window: int = Field(default=50, ge=1, le=10000, strict=True)
    maximum_queued_targets: int = Field(default=10000, ge=1, le=100000, strict=True)
    claim_seconds: int = Field(default=120, ge=60, le=300, strict=True)

    @model_validator(mode="after")
    def valid_window(self) -> "FamilyCollectionPolicy":
        if self.start_grace_seconds > self.duration_seconds:
            raise ValueError("Collection start grace cannot exceed its duration")
        return self


def next_family_collection_window(after: datetime) -> datetime:
    if after.utcoffset() is None:
        raise ValueError("Collection clocks must be timezone-aware")
    zone = ZoneInfo("Asia/Tashkent")
    day = after.astimezone(zone).date()
    for delta in (0, 1):
        for hour in (9, 15):
            candidate = datetime.combine(day + timedelta(days=delta), datetime.min.time(), zone)
            candidate = candidate.replace(hour=hour).astimezone(UTC)
            if candidate > after:
                return candidate
    raise ValueError("A next collection window is required")


class InventoryFamily(ChatContract):
    parent_id: ParentChatId
    connected_child_ids: tuple[int, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def canonical_family(self) -> "InventoryFamily":
        if (
            int(self.parent_id) > 2**63 - 1
            or any(
                type(value) is not int or not 0 < value <= 2**63 - 1
                for value in self.connected_child_ids
            )
            or len(set(self.connected_child_ids)) != len(self.connected_child_ids)
        ):
            raise ValueError("Invalid canonical inventory family")
        return self


class FamilyInventoryPage(ChatContract):
    offset: int = Field(ge=0, strict=True)
    limit: int = Field(ge=1, le=100, strict=True)
    total_parents: int = Field(ge=0, le=100000000, strict=True)
    families: tuple[InventoryFamily, ...] = Field(max_length=100)
    collected_at: AwareDatetime

    @model_validator(mode="after")
    def bounded_page(self) -> "FamilyInventoryPage":
        if len(self.families) != min(self.limit, max(0, self.total_parents - self.offset)) or (
            len({p.parent_id for p in self.families}) != len(self.families)
        ):
            raise ValueError("Inventory pagination is inconsistent")
        return self

    @property
    def exhausted(self) -> bool:
        return self.offset + len(self.families) >= self.total_parents


class CollectionSourceCounts(ChatContract):
    source: FamilySourceKey
    target_reads: int = 0
    completed: int = 0
    cache_hits: int = 0
    failed: int = 0
    unknown: int = 0
    skipped: int = 0
    available: int = 0
    undated: int = 0
    low_battery_records: int = 0
    partial_counter_pages: int = 0
    oldest_snapshot_collection_at: AwareDatetime | None = None
    latest_provider_check_at: AwareDatetime | None = None
    first_observation_at: AwareDatetime | None = None
    last_observation_at: AwareDatetime | None = None


class FamilyCollectionWindow(ChatContract):
    window_id: UUID
    scheduled_at: AwareDatetime
    deadline: AwareDatetime
    status: Literal["collecting", "completed", "partial", "skipped", "unknown"]
    reason: str | None = None
    published_at: AwareDatetime | None = None
    inventory_start_offset: int
    total_parents_reported: int | None
    pending_targets: int
    pages: int
    parents_seen: int
    targets: int
    inventory_exhausted: bool
    inventory_changed: bool
    population_complete: Literal[False] = False
    counts: tuple[CollectionSourceCounts, ...]
    limitations: tuple[str, ...] = (
        "MANA connected-child source targets, not parent behavioral analytics or 360REC.",
        "Pagination is not a point-in-time population snapshot; coverage can be partial.",
        "Cached/collected records are not fresh sensor measurements; preserve their own dates.",
        "App counters have an unverified period and are not summed into screen time.",
        "Collection creates no model, contact, payment or control authority.",
    )


class FamilyCollectionWork(ChatContract):
    window_id: UUID
    claim_id: UUID
    kind: Literal["inventory", "source", "observe_source"]
    position: int
    offset: int = 0
    target: FamilySourceTarget | None = None
    deadline: AwareDatetime
