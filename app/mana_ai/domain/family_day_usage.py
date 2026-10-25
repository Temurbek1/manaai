"""A requested calendar label is not a verified screen-time measurement period."""

from datetime import date, datetime
from typing import Final, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, SecretStr, field_validator, model_validator

from app.mana_ai.domain.chat import ChatContract, ParentChatId
from app.mana_ai.domain.family_sources import ChildAppUsageFacts


class ParentUsageLookup(ChatContract):
    """Ephemeral server lookup; the username is never serialized or model-visible."""

    parent_id: ParentChatId
    username: SecretStr = Field(exclude=True, repr=False)
    connected_child_ids: tuple[int, ...] = Field(max_length=20)
    collected_at: AwareDatetime

    @field_validator("username")
    @classmethod
    def bounded_username(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not 1 <= len(raw) <= 80 or any(ord(c) < 32 or ord(c) == 127 for c in raw):
            raise ValueError("A bounded server-only account lookup is required")
        return value

    @model_validator(mode="after")
    def canonical_scope(self) -> "ParentUsageLookup":
        if (
            int(self.parent_id) > 2**63 - 1
            or len(set(self.connected_child_ids)) != len(self.connected_child_ids)
            or any(type(c) is not int or not 0 < c <= 2**63 - 1 for c in self.connected_child_ids)
        ):
            raise ValueError("Invalid canonical family lookup")
        return self


class FamilyDayUsagePage(ChatContract):
    parent_id: ParentChatId
    requested_day: date
    ownership_collected_at: AwareDatetime
    collected_at: AwareDatetime
    owned_children_count: int = Field(ge=0, le=20, strict=True)
    provider_children_count: int = Field(ge=0, le=20, strict=True)
    children: tuple[ChildAppUsageFacts, ...] = Field(max_length=10)
    complete_family: bool = Field(strict=True)
    provider_timezone: None = None
    verified_measurement_period: None = None

    @model_validator(mode="after")
    def coherent_page(self) -> "FamilyDayUsagePage":
        if (
            int(self.parent_id) > 2**63 - 1
            or len({c.child_id for c in self.children}) != len(self.children)
            or len(self.children) > self.provider_children_count
            or self.provider_children_count > self.owned_children_count
            or self.complete_family
            != (len(self.children) == self.provider_children_count == self.owned_children_count)
            or not 0 <= (self.collected_at - self.ownership_collected_at).total_seconds() <= 180
            or any(c.collected_at != self.collected_at for c in self.children)
            or any(
                datetime.strptime(e.provider_recorded_at, "%Y-%m-%d %H:%M:%S").date()
                != self.requested_day
                for c in self.children
                for e in c.entries
            )
        ):
            raise ValueError("Invalid own-family day-page coverage or dates")
        return self


DAY_USAGE_SOURCE: Final = "manakids.family_day_app_usage.v1"


class DayUsageTarget(ChatContract):
    parent_id: ParentChatId
    child_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    request_id: UUID
    requested_day: date
    source: Literal["manakids.family_day_app_usage.v1"] = DAY_USAGE_SOURCE

    @model_validator(mode="after")
    def canonical_parent(self) -> "DayUsageTarget":
        if int(self.parent_id) > 2**63 - 1:
            raise ValueError("A canonical profile ID is required")
        return self


class DayUsageReceipt(DayUsageTarget):
    status: Literal["pending", "completed", "unavailable", "failed", "unknown"]
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    cache_hit: bool = Field(strict=True)
    snapshot_id: UUID | None = None
    family_snapshot_id: UUID | None = None
    child_returned: bool | None = Field(default=None, strict=True)
    facts: ChildAppUsageFacts | None = None
    error_code: (
        Literal[
            "family_day_child_not_returned",
            "family_source_auth_denied",
            "family_source_ownership_denied",
            "family_source_invalid",
            "family_source_unavailable",
            "family_source_cancelled",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def exact_receipt(self) -> "DayUsageReceipt":
        known = (
            self.status in {"completed", "unavailable"}
            or self.status == "pending"
            and self.cache_hit
        )
        if (self.status == "pending") != (self.finished_at is None) or (
            self.finished_at is not None and self.finished_at < self.started_at
        ):
            raise ValueError("Invalid day-read receipt dates")
        if known:
            if (
                self.snapshot_id is None
                or self.family_snapshot_id is None
                or self.child_returned is None
            ):
                raise ValueError("Known day facts need their original family snapshot")
            if self.child_returned != (self.facts is not None):
                raise ValueError("Absent child rows must not become zero counters")
        elif any(
            v is not None
            for v in (self.snapshot_id, self.family_snapshot_id, self.child_returned, self.facts)
        ):
            raise ValueError("Unverified day receipts cannot expose facts")
        if (
            self.status == "completed"
            and not self.child_returned
            or self.status == "unavailable"
            and self.child_returned
        ):
            raise ValueError("Day-read outcome must match its exact child row")
        if (self.status in {"unavailable", "failed", "unknown"}) != (self.error_code is not None):
            raise ValueError("Only closed unsuccessful outcomes carry a reason")
        if self.status == "unavailable" and self.error_code != "family_day_child_not_returned":
            raise ValueError("An absent child is a bounded-page outcome")
        if self.facts is not None and (
            self.facts.child_id != self.child_id
            or any(
                datetime.strptime(e.provider_recorded_at, "%Y-%m-%d %H:%M:%S").date()
                != self.requested_day
                for e in self.facts.entries
            )
        ):
            raise ValueError("Day facts require the exact child and calendar label")
        return self


class DayUsageClaim(ChatContract):
    receipt: DayUsageReceipt
    admitted: bool
    read_provider: bool
