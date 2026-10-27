"""Minimized location evidence: no coordinates, address, route or present-danger claim."""

import hashlib
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from app.mana_ai.domain.chat import ChatContract

LOCATION_SOURCE: Literal["firebase.child_location.v1"] = "firebase.child_location.v1"
LOCATION_QUALIFICATION = (
    "Location is one last stored point, not coordinates/address/route analysis. Preserve its "
    "observation date: collection/server-write time never proves current presence. Mock/sample "
    "or unknown flags remain qualified. Movement is about that observation only, not current "
    "motion, safety, a geofence event or danger. No verified accuracy/distance is supplied. "
    "Never invent a place or risk; suggest checking the app map or contacting the child "
    "when appropriate."
)


class ChildLocationFacts(ChatContract):
    child_id: int = Field(gt=0, le=2**63 - 1, strict=True)
    status: Literal["available", "missing"]
    position_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    observed_at: AwareDatetime | None = None
    source_updated_at: AwareDatetime | None = None
    collected_at: AwareDatetime
    quality: Literal["dated", "unknown_measurement_time", "no_observation"]
    mock: bool | None = Field(default=None, strict=True)
    sample: bool | None = Field(default=None, strict=True)
    is_moving: bool | None = Field(default=None, strict=True)
    accuracy_reported: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def coherent_point(self) -> "ChildLocationFacts":
        if self.status == "missing":
            if (
                any(
                    value is not None
                    for value in (
                        self.position_fingerprint,
                        self.observed_at,
                        self.source_updated_at,
                        self.mock,
                        self.sample,
                        self.is_moving,
                    )
                )
                or self.accuracy_reported
                or self.quality != "no_observation"
            ):
                raise ValueError("An absent location contains no selected observation")
        elif self.position_fingerprint is None or self.source_updated_at is None:
            raise ValueError("A point requires verified identity and a server update")
        elif self.quality != (
            "dated" if self.observed_at is not None else "unknown_measurement_time"
        ):
            raise ValueError("A point's quality must preserve its measurement date")
        if self.source_updated_at is not None and self.source_updated_at > self.collected_at:
            raise ValueError("A source update cannot be in the future")
        if self.observed_at is not None and (
            self.source_updated_at is None or self.observed_at > self.source_updated_at
        ):
            raise ValueError("A measurement cannot be later than its server update")
        return self

    def fingerprint(self) -> str:
        return hashlib.sha256(self.model_dump_json(exclude={"collected_at"}).encode()).hexdigest()


class LocationObservationView(ChatContract):
    """Public-to-model dates and quality; no child ID, position hash or coordinates."""

    observed_at: AwareDatetime | None
    source_updated_at: AwareDatetime | None
    snapshot_collected_at: AwareDatetime
    quality: Literal["dated", "unknown_measurement_time", "no_observation"]
    mock: bool | None
    sample: bool | None
    is_moving: bool | None
    accuracy_reported: bool = Field(strict=True)


class LocationComparisonView(ChatContract):
    previous: LocationObservationView
    current: LocationObservationView
    chronology: Literal[
        "ordered_measurements",
        "same_measurement_time",
        "regressed_measurement_time",
        "unknown_measurement_time",
        "missing_observation",
    ]
    stored_point_relation: Literal["same", "different", "not_comparable"]
    verified_movement: Literal[False] = False
    route_reconstructed: Literal[False] = False

    @model_validator(mode="after")
    def qualified_relation(self) -> "LocationComparisonView":
        previous, current = self.previous, self.current
        if previous.snapshot_collected_at > current.snapshot_collected_at:
            raise ValueError("Saved observations must preserve collection order")
        expected = (
            "missing_observation"
            if "no_observation" in {previous.quality, current.quality}
            else "unknown_measurement_time"
            if previous.observed_at is None or current.observed_at is None
            else "ordered_measurements"
            if previous.observed_at < current.observed_at
            else "same_measurement_time"
            if previous.observed_at == current.observed_at
            else "regressed_measurement_time"
        )
        if self.chronology != expected or (
            (self.stored_point_relation != "not_comparable") != (expected == "ordered_measurements")
        ):
            raise ValueError("A point relation requires strictly ordered measurement dates")
        return self


LOCATION_COMPARISON_QUALIFICATION = (
    "saved_location_comparison contains exactly two stored point observations, not a route. "
    "Keep both measurement dates and distinguish source-update/collection dates. A same/different "
    "stored point is not verified movement, presence, distance, speed, arrival, a geofence event "
    "or danger; sensor accuracy/authenticity are unverified. Unknown, equal or regressed "
    "measurement times are not comparable. Mock/sample flags qualify the record, never prove "
    "the child's behavior. No observations between the two points or future tracking are supplied. "
    "Suggest checking the app map or calmly confirming plans when useful, "
    "without inventing a place."
)
