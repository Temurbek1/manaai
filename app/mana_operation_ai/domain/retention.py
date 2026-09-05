import re
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from app.mana_operation_ai.domain.enums import ActivityEventType
from app.mana_operation_ai.domain.models import DomainModel, EvidenceRef

_TAXONOMY = r"[a-z][a-z0-9_.-]{0,63}"
_DIMENSION_CATEGORIES = {
    "screen_views",
    "button_clicks",
    "feature_uses",
    "navigation",
    "forms_completed",
    "uploads_by_type",
    "search_usage",
    "screen_time_seconds_by_screen",
}
_SEARCH_DIMENSIONS = {"with_query", "with_filters", "with_sort"}


class RetentionEngagementConfiguration(DomainModel):
    schedule: str = "20 */6 * * *"
    timezone: str = "UTC"
    lookback_days: int = Field(default=7, ge=1, le=30)
    minimum_completeness: Decimal = Field(
        default=Decimal("0.90"),
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    minimum_active_child_ratio: Decimal = Field(
        default=Decimal("0.20"),
        ge=Decimal("0"),
        le=Decimal("1"),
    )


class BackendActivityFacts(DomainModel):
    """PII-free aggregate facts translated from the Manakids Admin API."""

    source: str
    period_start: datetime
    period_end: datetime
    collected_at: datetime
    parent_accounts_joined: int = Field(ge=0)
    child_accounts_joined: int = Field(ge=0)
    total_children: int = Field(ge=0)
    children_with_app_usage: int = Field(ge=0)
    children_with_realtime_feature_usage: int = Field(ge=0)
    completeness: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    source_request_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_period(self) -> "BackendActivityFacts":
        if self.period_end <= self.period_start:
            raise ValueError("Activity period end must be after its start")
        return self


class MobileActivityFacts(DomainModel):
    """Aggregates mobile events in memory; raw user and session identifiers are discarded."""

    source: str
    period_start: datetime
    period_end: datetime
    collected_at: datetime
    event_counts: dict[ActivityEventType, int]
    dimension_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    sequence_counts: dict[str, int] = Field(default_factory=dict)
    active_subjects: int = Field(ge=0)
    sessions: int = Field(ge=0)
    screen_time_seconds: int = Field(ge=0)
    documents_scanned: int = Field(ge=0)
    invalid_documents: int = Field(ge=0)
    completeness: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    source_request_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_facts(self) -> "MobileActivityFacts":
        if self.period_end <= self.period_start:
            raise ValueError("Activity period end must be after its start")
        if any(value < 0 for value in self.event_counts.values()):
            raise ValueError("Mobile event counts cannot be negative")
        if any(value < 0 for values in self.dimension_counts.values() for value in values.values()):
            raise ValueError("Mobile dimension counts cannot be negative")
        if any(value < 0 for value in self.sequence_counts.values()):
            raise ValueError("Mobile sequence counts cannot be negative")
        if set(self.dimension_counts).difference(_DIMENSION_CATEGORIES):
            raise ValueError("Unsupported mobile dimension category")
        for category, values in self.dimension_counts.items():
            if category == "search_usage":
                valid_keys = set(values).issubset(_SEARCH_DIMENSIONS)
            elif category == "navigation":
                valid_keys = all(
                    re.fullmatch(rf"{_TAXONOMY}>{_TAXONOMY}", key) is not None for key in values
                )
            else:
                valid_keys = all(re.fullmatch(_TAXONOMY, key) is not None for key in values)
            if not valid_keys:
                raise ValueError("Invalid bounded taxonomy in a mobile dimension")
        allowed_events = "|".join(re.escape(item.value) for item in ActivityEventType)
        if any(
            re.fullmatch(rf"(?:{allowed_events})>(?:{allowed_events})", key) is None
            for key in self.sequence_counts
        ):
            raise ValueError("Mobile sequence keys must contain supported event-type transitions")
        return self


class RetentionEngagementSnapshot(DomainModel):
    schema_version: Literal["retention-engagement-v1"] = "retention-engagement-v1"
    period_start: datetime
    period_end: datetime
    collected_at: datetime
    parent_accounts_joined: int = Field(ge=0)
    child_accounts_joined: int = Field(ge=0)
    total_children: int = Field(ge=0)
    backend_active_children: int = Field(ge=0)
    mobile_active_subjects: int = Field(ge=0)
    mobile_sessions: int = Field(ge=0)
    mobile_screen_time_seconds: int = Field(ge=0)
    mobile_event_counts: dict[ActivityEventType, int]
    mobile_dimension_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    mobile_sequence_counts: dict[str, int] = Field(default_factory=dict)
    completeness: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    evidence_refs: list[EvidenceRef]
    limitations: list[str] = Field(default_factory=list)
