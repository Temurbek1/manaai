"""Private, ownership-scoped source facts; never arbitrary queries or credentials."""

import hashlib
from typing import Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from app.mana_ai.domain.chat import ChatContract, ParentChatId

FamilySourceKey = Literal["firebase.child_battery.v1", "manakids.child_app_usage.v1"]


class AppUsageCounter(ChatContract):
    app_name: str = Field(min_length=1, max_length=160, strict=True)
    provider_recorded_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", strict=True)
    reported_seconds: int = Field(ge=0, le=31 * 86400, strict=True)


class ChildAppUsageFacts(ChatContract):
    """One provider page of counters, never verified daily screen time."""

    child_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    status: Literal["available", "missing"]
    entries: tuple[AppUsageCounter, ...] = Field(max_length=100)
    returned_apps: int = Field(ge=0, le=10, strict=True)
    total_apps: int = Field(ge=0, le=1000000, strict=True)
    complete: bool = Field(strict=True)
    observed_at: None = None
    source_updated_at: None = None
    collected_at: AwareDatetime
    quality: Literal["unverified_period"] = "unverified_period"

    @model_validator(mode="after")
    def coherent_counters(self) -> "ChildAppUsageFacts":
        if (
            self.returned_apps > self.total_apps
            or self.complete != (self.returned_apps == self.total_apps)
            or (self.status == "missing") != (self.total_apps == 0)
            or (self.returned_apps == 0) != (not self.entries)
            or len({(e.app_name, e.provider_recorded_at) for e in self.entries})
            != len(self.entries)
        ):
            raise ValueError("Inconsistent provider counter coverage")
        return self

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json(exclude={"collected_at"}).encode()).hexdigest()


class FamilySourceTarget(ChatContract):
    parent_id: ParentChatId
    child_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    request_id: UUID
    source: FamilySourceKey = "firebase.child_battery.v1"

    @model_serializer(mode="wrap")
    def legacy_battery_target(self, handler: SerializerFunctionWrapHandler) -> object:
        result = handler(self)
        if self.source == "firebase.child_battery.v1" and isinstance(result, dict):
            result.pop("source", None)
        return result


class FamilySourceLimits(ChatContract):
    """Conservative rolling ceilings, including failed and unknown admissions."""

    requests_per_24h: int = Field(default=100, ge=1, le=10000, strict=True)
    document_units_per_24h: int = Field(default=200, ge=2, le=20000, strict=True)
    minimum_interval_seconds: int = Field(default=21600, ge=300, le=86400, strict=True)


class ChildBatteryFacts(ChatContract):
    child_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    status: Literal["available", "missing", "ambiguous"]
    percent: int | None = Field(default=None, ge=0, le=100, strict=True)
    observed_at: AwareDatetime | None = None
    source_updated_at: AwareDatetime | None = None
    collected_at: AwareDatetime
    quality: Literal["dated", "unknown_measurement_time", "no_observation"]

    @model_validator(mode="after")
    def coherent_observation(self) -> "ChildBatteryFacts":
        if self.status != "available":
            if self.percent is not None or self.observed_at is not None:
                raise ValueError("Missing/ambiguous sources cannot contain selected observations")
            if self.quality != "no_observation":
                raise ValueError("Missing/ambiguous sources have no measurement")
        elif self.percent is None or self.source_updated_at is None:
            raise ValueError("Available battery facts require a percent and server update")
        elif self.quality != (
            "dated" if self.observed_at is not None else "unknown_measurement_time"
        ):
            raise ValueError("Measurement quality must agree with its explicit date")
        if self.source_updated_at is not None and self.source_updated_at > self.collected_at:
            raise ValueError("A source update cannot be in the future")
        if self.observed_at is not None and (
            self.source_updated_at is None or self.observed_at > self.source_updated_at
        ):
            raise ValueError("A measurement cannot be later than its server update")
        return self

    def fingerprint(self) -> str:
        # Recollection alone is not a new remote version or a fresh measurement.
        payload = self.model_dump_json(exclude={"collected_at"})
        return hashlib.sha256(payload.encode()).hexdigest()


class FamilySourceReceipt(ChatContract):
    parent_id: ParentChatId
    child_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    request_id: UUID
    source: FamilySourceKey = "firebase.child_battery.v1"
    status: Literal["pending", "completed", "failed", "unknown"]
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    cache_hit: bool = Field(strict=True)
    document_units_reserved: int = Field(ge=0, le=2, strict=True)
    snapshot_id: UUID | None = None
    error_code: (
        Literal[
            "family_source_cancelled",
            "family_source_auth_denied",
            "family_source_query_invalid",
            "family_source_invalid",
            "family_source_unavailable",
        ]
        | None
    ) = None
    facts: ChildBatteryFacts | ChildAppUsageFacts | None = None

    @model_validator(mode="after")
    def receipt_invariants(self) -> "FamilySourceReceipt":
        units = 0 if self.cache_hit or self.source == "manakids.child_app_usage.v1" else 2
        if self.document_units_reserved != units:
            raise ValueError("Only a cache hit avoids the conservative document reserve")
        if self.status == "pending":
            if self.finished_at is not None or self.error_code is not None:
                raise ValueError("Pending reads cannot have terminal metadata")
        elif self.finished_at is None or self.finished_at < self.started_at:
            raise ValueError("Terminal reads require a valid completion date")
        expected_facts = self.status == "completed" or self.status == "pending" and self.cache_hit
        if expected_facts != (self.facts is not None and self.snapshot_id is not None):
            raise ValueError("Source facts require a verified snapshot identity")
        if not expected_facts and (self.facts is not None or self.snapshot_id is not None):
            raise ValueError("Unverified results cannot expose facts")
        if (self.status in {"failed", "unknown"}) != (self.error_code is not None):
            raise ValueError("Only terminal failures contain a closed error code")
        if self.facts is not None and self.facts.child_id != self.child_id:
            raise ValueError("Source facts cannot belong to another child")
        if self.facts is not None and isinstance(self.facts, ChildBatteryFacts) != (
            self.source == "firebase.child_battery.v1"
        ):
            raise ValueError("Source facts do not match their provider kind")
        return self


class FamilySourceChange(ChatContract):
    """A version change, not a safety finding, message or permission to send."""

    event_id: UUID
    parent_id: ParentChatId
    child_id: int
    snapshot_id: UUID
    fingerprint: str
    recorded_at: AwareDatetime
    source: FamilySourceKey = "firebase.child_battery.v1"

    @model_serializer(mode="wrap")
    def legacy_battery_event(self, handler: SerializerFunctionWrapHandler) -> object:
        result = handler(self)
        if self.source == "firebase.child_battery.v1" and isinstance(result, dict):
            result.pop("source", None)
        return result


ChildSourceFacts = ChildBatteryFacts | ChildAppUsageFacts


def source_facts(payload: object, source: FamilySourceKey) -> ChildSourceFacts:
    return (
        ChildBatteryFacts.model_validate(payload)
        if source == "firebase.child_battery.v1"
        else ChildAppUsageFacts.model_validate(payload)
    )


class FamilySourceClaim(ChatContract):
    receipt: FamilySourceReceipt
    admitted: bool
    read_provider: bool
