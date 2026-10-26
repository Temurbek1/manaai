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
