"""Scoped MANA source evidence, not identities, payments or customer actions."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.mana_operation_ai.domain.cost_control import ProductScope
from app.mana_operation_ai.domain.models import DomainModel
from app.mana_operation_ai.domain.shared_data import CollectedAggregate

PARENT_ACTIVITY_CAPABILITY = "retention.parent_activity.analyze"
CHILD_TELEMETRY_CAPABILITY = "retention.child_telemetry.analyze"
FIRST_PARTY_CAPABILITIES = (PARENT_ACTIVITY_CAPABILITY, CHILD_TELEMETRY_CAPABILITY)
PARENT_LABEL_MAX_LENGTH = 80

ParentBreakdownKind = Literal[
    "screens", "devices", "geography", "acquisition", "weekday_hour", "notification_open_minutes"
]
PARENT_BREAKDOWN_FIELDS: dict[ParentBreakdownKind, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "screens": (("screen_name", "screen_class"), ("views", "engagement_seconds")),
    "devices": (
        ("model", "manufacturer", "os", "os_version", "app_version", "language", "device_type"),
        ("active_users", "event_count"),
    ),
    "geography": (("country", "region", "city"), ("active_users", "event_count")),
    "acquisition": (
        ("source", "medium", "campaign", "platform", "channel"),
        ("new_users", "active_users", "event_count"),
    ),
    "weekday_hour": (("day_of_week", "hour"), ("active_users", "sessions", "event_count")),
    "notification_open_minutes": (("date_minute",), ("event_count",)),
}


class ManualAnalyticsConfiguration(DomainModel):
    product: Literal["mana"] = "mana"


class ParentActivityWindow(DomainModel):
    days: Literal[1, 7, 30]
    start_date: date
    end_date: date
    active_users: int = Field(ge=0, strict=True)
    sessions: int = Field(ge=0, strict=True)
    engaged_sessions: int = Field(ge=0, strict=True)
    engagement_seconds: Decimal = Field(ge=0, allow_inf_nan=False)


class CohortDay(DomainModel):
    day: int = Field(ge=0, le=30, strict=True)
    active_users: int = Field(ge=0, strict=True)
    total_users: int = Field(gt=0, strict=True)


class ParentRetentionCohort(DomainModel):
    first_session_date: date
    days: list[CohortDay] = Field(max_length=31)
    quality: Literal["complete", "incomplete", "sampled", "thresholded"]

    @model_validator(mode="after")
    def validate_cohort(self) -> "ParentRetentionCohort":
        by_day = {row.day: row for row in self.days}
        if len(by_day) != len(self.days) or any(
            row.active_users > row.total_users for row in self.days
        ):
            raise ValueError("Cohort rows must be unique with coherent counts")
        if self.quality == "complete" and (
            set(by_day) != set(range(31))
            or len({row.total_users for row in self.days}) != 1
            or by_day[0].active_users != by_day[0].total_users
        ):
            raise ValueError("Complete retention requires all 31 days and a stable D0 denominator")
        return self


class NotificationEngagementFunnel(DomainModel):
    steps: tuple[
        Literal["notification_receive"], Literal["notification_open"], Literal["button_click"]
    ] = ("notification_receive", "notification_open", "button_click")
    users: tuple[
        Annotated[int, Field(strict=True, ge=0)],
        Annotated[int, Field(strict=True, ge=0)],
        Annotated[int, Field(strict=True, ge=0)],
    ]
    maximum_seconds_between_steps: Literal[86400] = 86400
    quality: Literal["complete", "sampled", "thresholded"]

    @model_validator(mode="after")
    def validate_funnel(self) -> "NotificationEngagementFunnel":
        if any(value < 0 for value in self.users) or not (
            self.users[0] >= self.users[1] >= self.users[2]
        ):
            raise ValueError("A closed funnel must have nonnegative nonincreasing users")
        return self


class ParentBreakdownRow(DomainModel):
    labels: dict[str, str | None] = Field(max_length=7)
    measures: dict[str, Decimal] = Field(max_length=3)

    @model_validator(mode="after")
    def validate_values(self) -> "ParentBreakdownRow":
        if any(
            value is not None and (not value or len(value) > PARENT_LABEL_MAX_LENGTH)
            for value in self.labels.values()
        ):
            raise ValueError("Breakdown labels must be bounded or explicitly missing")
        if any(
            not value.is_finite()
            or value < 0
            or value > Decimal("1e18")
            or (key != "engagement_seconds" and value != value.to_integral_value())
            for key, value in self.measures.items()
        ):
            raise ValueError("Breakdown measures must be finite nonnegative counts or seconds")
        return self


class ParentAnalyticsBreakdown(DomainModel):
    kind: ParentBreakdownKind
    rows: list[ParentBreakdownRow] = Field(max_length=10)
    total_groups: int = Field(ge=0, strict=True)
    withheld_rows: int = Field(default=0, ge=0, le=10, strict=True)
    quality: Literal["complete", "partial", "missing", "sampled", "thresholded"]

    @model_validator(mode="after")
    def validate_breakdown(self) -> "ParentAnalyticsBreakdown":
        labels, measures = PARENT_BREAKDOWN_FIELDS[self.kind]
        if any(
            set(row.labels) != set(labels) or set(row.measures) != set(measures)
            for row in self.rows
        ):
            raise ValueError("Breakdown fields differ from the typed source contract")
        if self.total_groups < len(self.rows) + self.withheld_rows:
            raise ValueError("Breakdown counts disagree with the returned rows")
        if self.quality == "complete" and (
            not self.rows
            or self.total_groups != len(self.rows)
            or self.withheld_rows
            or any(value is None for row in self.rows for value in row.labels.values())
        ):
            raise ValueError("Complete breakdowns require all groups and populated labels")
        keys = [tuple(row.labels[key] for key in labels) for row in self.rows]
        if len(set(keys)) != len(keys):
            raise ValueError("Breakdown groups must be unique")
        return self


class ParentAnalyticsFacts(CollectedAggregate):
    source: Literal["mana_ga4_parent_analytics"] = "mana_ga4_parent_analytics"
    population: Literal["parent_app_analytics_identities"] = "parent_app_analytics_identities"
    product_scope: ProductScope = ProductScope.MANA
    stream_id: str = Field(pattern=r"^[0-9]+$")
    property_timezone: str
    period_start: date
    period_end: date
    windows: list[ParentActivityWindow] = Field(max_length=3)
    event_counts: dict[str, Annotated[int, Field(strict=True, ge=0)]] = Field(default_factory=dict)
    event_inventory_complete: bool
    event_quality: Literal["complete", "partial", "missing", "sampled", "thresholded"] = "partial"
    cohorts: list[ParentRetentionCohort] = Field(max_length=2)
    notification_funnel: NotificationEngagementFunnel | None = None
    breakdowns: list[ParentAnalyticsBreakdown] = Field(default_factory=list, max_length=6)
    source_request_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_parent_contract(self) -> "ParentAnalyticsFacts":
        if self.period_end - self.period_start != timedelta(days=29):
            raise ValueError("Parent analytics requires one explicit 30-day period")
        if len({window.days for window in self.windows}) != len(self.windows) or any(
            window.end_date != self.period_end
            or (window.end_date - window.start_date).days != window.days - 1
            or window.engaged_sessions > window.sessions
            for window in self.windows
        ):
            raise ValueError("Parent activity windows must be unique and period-aligned")
        if len({row.kind for row in self.breakdowns}) != len(self.breakdowns):
            raise ValueError("Parent breakdowns must be unique")
        if len({cohort.first_session_date for cohort in self.cohorts}) != len(self.cohorts) or any(
            cohort.first_session_date
            not in {self.period_end - timedelta(days=31), self.period_end - timedelta(days=30)}
            for cohort in self.cohorts
        ):
            raise ValueError("Parent return cohorts must be distinct and mature through D30")
        return self


class ChildTelemetrySample(DomainModel):
    collection: Literal["battery", "children_location"]
    sampled_documents: int = Field(ge=0, le=100, strict=True)
    more_documents: bool
    valid_observations: int = Field(ge=0, le=100, strict=True)
    invalid_observations: int = Field(ge=0, le=100, strict=True)
    source_updated_min: datetime | None = None
    source_updated_max: datetime | None = None
    recent_server_updates: int = Field(ge=0, le=100, strict=True)
    future_client_dates: int = Field(ge=0, le=100, strict=True)
    unknown_client_timezone: int = Field(ge=0, le=100, strict=True)
    low_battery_observations: int | None = Field(default=None, ge=0, le=100, strict=True)
    precise_location_observations: int | None = Field(default=None, ge=0, le=100, strict=True)
    mock_location_observations: int | None = Field(default=None, ge=0, le=100, strict=True)

    @model_validator(mode="after")
    def validate_sample(self) -> "ChildTelemetrySample":
        if self.valid_observations + self.invalid_observations != self.sampled_documents:
            raise ValueError("Every sampled document requires an explicit validation outcome")
        counts = [
            self.recent_server_updates,
            self.future_client_dates,
            self.unknown_client_timezone,
            self.mock_location_observations or 0,
        ]
        if any(value > self.sampled_documents for value in counts) or any(
            value is not None and value > self.valid_observations
            for value in [self.low_battery_observations, self.precise_location_observations]
        ):
            raise ValueError("Sample counts cannot exceed their documented population")
        if self.future_client_dates + self.unknown_client_timezone > self.sampled_documents:
            raise ValueError("Known future timestamps cannot also have an unknown timezone")
        if (
            self.collection == "battery"
            and (
                self.low_battery_observations is None
                or self.precise_location_observations is not None
                or self.mock_location_observations is not None
            )
        ) or (
            self.collection == "children_location"
            and (
                self.low_battery_observations is not None
                or self.precise_location_observations is None
                or self.mock_location_observations is None
            )
        ):
            raise ValueError("Telemetry measures must match their collection")
        return self


class ChildTelemetryFacts(CollectedAggregate):
    source: Literal["mana_firestore_child_telemetry"] = "mana_firestore_child_telemetry"
    population: Literal["child_device_prefix_sample"] = "child_device_prefix_sample"
    product_scope: ProductScope = ProductScope.MANA
    sample_limit_per_collection: int = Field(ge=1, le=100, strict=True)
    precise_accuracy_limit_meters: Decimal = Field(gt=0, allow_inf_nan=False)
    samples: tuple[ChildTelemetrySample, ChildTelemetrySample]
    source_request_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_collections(self) -> "ChildTelemetryFacts":
        if tuple(item.collection for item in self.samples) != ("battery", "children_location"):
            raise ValueError("Only the two owner-confirmed MANA collections are allowed")
        if any(item.sampled_documents > self.sample_limit_per_collection for item in self.samples):
            raise ValueError("Child sampling exceeded its admitted bound")
        return self
