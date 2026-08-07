from datetime import datetime, time
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.mana_ai.domain.enums import (
    AgeBand,
    AppCategory,
    LocationSource,
    ReputationVerdict,
    ResourceKind,
    ScheduleKind,
    SignalSource,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubjectContext(StrictModel):
    subject_id: str = Field(
        min_length=1,
        max_length=128,
        description="Opaque application-scoped child identifier; do not send a name or email.",
    )
    age_band: AgeBand
    timezone: str = Field(min_length=1, max_length=64, examples=["Asia/Samarkand"])
    policy_version: str | None = Field(default=None, min_length=1, max_length=64)


class EvidenceSignal(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    observed_at: AwareDatetime
    source: SignalSource


class AppUsageSignal(EvidenceSignal):
    source: Literal[SignalSource.APP_USAGE] = SignalSource.APP_USAGE
    package_name: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    category: AppCategory = AppCategory.UNKNOWN
    foreground_seconds: int = Field(ge=0, le=604_800)
    night_seconds: int = Field(default=0, ge=0, le=604_800)
    launch_count: int = Field(default=0, ge=0, le=100_000)
    configured_limit_seconds: int | None = Field(default=None, ge=60, le=604_800)
    extra_time_request_count: int = Field(default=0, ge=0, le=1_000)

    @model_validator(mode="after")
    def validate_usage_parts(self) -> "AppUsageSignal":
        if self.night_seconds > self.foreground_seconds:
            raise ValueError("night_seconds cannot exceed foreground_seconds")
        return self


class UsageBaseline(StrictModel):
    key: str = Field(min_length=1, max_length=255)
    average_seconds: int = Field(ge=0, le=604_800)
    average_night_seconds: int = Field(default=0, ge=0, le=604_800)
    average_launch_count: int = Field(default=0, ge=0, le=100_000)
    average_extra_time_requests: float = Field(default=0, ge=0, le=1_000)


class NotificationPreviewSignal(EvidenceSignal):
    source: Literal[SignalSource.NOTIFICATION_PREVIEW] = SignalSource.NOTIFICATION_PREVIEW
    application: str = Field(min_length=1, max_length=120)
    excerpt: str = Field(
        min_length=1,
        max_length=2_000,
        description="Minimized notification excerpt. Do not send full conversation history.",
    )
    sender_is_known: bool | None = None
    link_evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class ResourceSignal(EvidenceSignal):
    kind: ResourceKind
    normalized_value: str = Field(
        min_length=1,
        max_length=2_048,
        description="Normalized URL, domain, QR payload, or APK package identifier.",
    )
    reputation: ReputationVerdict = ReputationVerdict.UNKNOWN
    category: str | None = Field(default=None, min_length=1, max_length=80)
    source_application: str | None = Field(default=None, min_length=1, max_length=120)
    requests_sensitive_permissions: bool | None = None


class WebsiteActivitySignal(EvidenceSignal):
    source: Literal[SignalSource.WEBSITE] = SignalSource.WEBSITE
    domain: str = Field(min_length=1, max_length=253)
    category: str = Field(min_length=1, max_length=80)
    reputation: ReputationVerdict = ReputationVerdict.UNKNOWN
    blocked: bool = False


class NotificationActivity(StrictModel):
    application: str = Field(min_length=1, max_length=120)
    count: int = Field(ge=0, le=1_000_000)
    baseline_count: float | None = Field(default=None, ge=0, le=1_000_000)


class BatterySignal(EvidenceSignal):
    source: Literal[SignalSource.BATTERY] = SignalSource.BATTERY
    percent: int = Field(ge=0, le=100)
    charging: bool | None = None
    drain_percent_per_hour: float | None = Field(default=None, ge=0, le=100)
    online: bool = True


class ProtectionStateSignal(EvidenceSignal):
    source: Literal[SignalSource.PROTECTION_STATE] = SignalSource.PROTECTION_STATE
    location_permission: bool
    notification_access: bool
    vpn_enabled: bool
    usage_access: bool
    disable_attempt_count: int = Field(default=0, ge=0, le=10_000)


class LocationPoint(EvidenceSignal):
    source: Literal[SignalSource.LOCATION] = SignalSource.LOCATION
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float | None = Field(default=None, ge=0, le=100_000)
    speed_meters_per_second: float | None = Field(default=None, ge=0, le=500)
    location_source: LocationSource
    is_mocked: bool = False
    online: bool = True


class Geofence(StrictModel):
    geofence_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: int = Field(ge=25, le=50_000)


class RouteContext(StrictModel):
    destination_geofence_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_arrival_at: AwareDatetime | None = None
    distance_from_usual_route_meters: float | None = Field(default=None, ge=0, le=1_000_000)
    unusual_route_threshold_meters: float = Field(default=500, ge=25, le=100_000)
    stopped_duration_seconds: int | None = Field(default=None, ge=0, le=604_800)
    long_stop_threshold_seconds: int = Field(default=3_600, ge=60, le=604_800)
    usual_max_speed_meters_per_second: float | None = Field(default=None, ge=0, le=500)
    left_school_early: bool = False
    missed_usual_waypoint: bool = False


class ScheduleWindow(StrictModel):
    schedule_id: str = Field(min_length=1, max_length=128)
    kind: ScheduleKind
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def validate_window(self) -> "ScheduleWindow":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        return self


class DailyTimeWindow(StrictModel):
    starts_at: time
    ends_at: time


class AppLimit(StrictModel):
    package_name: str | None = Field(default=None, min_length=1, max_length=255)
    category: AppCategory | None = None
    daily_limit_seconds: int = Field(ge=60, le=604_800)

    @model_validator(mode="after")
    def validate_target(self) -> "AppLimit":
        if (self.package_name is None) == (self.category is None):
            raise ValueError("Exactly one of package_name or category must be set")
        return self


class FamilyRule(StrictModel):
    rule_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1_000)
    enabled: bool = True
    requires_parent_confirmation: bool = True


class SafetyEventSignal(EvidenceSignal):
    source: Literal[SignalSource.SAFETY_EVENT] = SignalSource.SAFETY_EVENT
    category: str = Field(min_length=1, max_length=80)
    severity: int = Field(ge=0, le=100)
    summary: str = Field(min_length=1, max_length=500)


class MetricComparison(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=120)
    current_value: float
    baseline_value: float
    unit: str = Field(min_length=1, max_length=40)
    higher_is_positive: bool = False
    significant_change_percent: float = Field(default=50, ge=1, le=10_000)

    @property
    def change_percent(self) -> float | None:
        if self.baseline_value == 0:
            return None
        return ((self.current_value - self.baseline_value) / abs(self.baseline_value)) * 100


class ExtraTimeRequest(StrictModel):
    request_id: str = Field(min_length=1, max_length=128)
    package_name: str = Field(min_length=1, max_length=255)
    requested_minutes: int = Field(ge=1, le=1_440)
    reason: str = Field(min_length=1, max_length=500)
    requested_at: AwareDatetime
    previous_request_count_7d: int = Field(default=0, ge=0, le=1_000)


class FamilyPreferences(StrictModel):
    goals: list[str] = Field(default_factory=list, max_length=20)
    allowed_applications: list[str] = Field(default_factory=list, max_length=200)
    blocked_applications: list[str] = Field(default_factory=list, max_length=200)
    night_window: DailyTimeWindow | None = None
    parent_visible_data: list[str] = Field(default_factory=list, max_length=50)
    control_relaxation_notes: str | None = Field(default=None, max_length=1_000)


Percentage = Annotated[float, Field(ge=0, le=100)]
HttpResource = Annotated[HttpUrl, Field(max_length=2_048)]


def ensure_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a timezone offset")
    return value
