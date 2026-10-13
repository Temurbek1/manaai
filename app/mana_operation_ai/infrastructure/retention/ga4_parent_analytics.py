"""Bounded parent-stream reports, independent of the legacy Manakids inventory."""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.mana_operation_ai.application.ports import Clock, ProviderPermanentError
from app.mana_operation_ai.domain.first_party_analytics import (
    PARENT_BREAKDOWN_FIELDS,
    PARENT_LABEL_MAX_LENGTH,
    CohortDay,
    NotificationEngagementFunnel,
    ParentActivityWindow,
    ParentAnalyticsBreakdown,
    ParentAnalyticsFacts,
    ParentBreakdownKind,
    ParentBreakdownRow,
    ParentRetentionCohort,
)
from app.mana_operation_ai.infrastructure.retention.analytics_http import AnalyticsReadHttp

_EVENTS = {
    "screen_view",
    "button_click",
    "first_open",
    "session_start",
    "user_engagement",
    "notification_receive",
    "notification_open",
    "notification_foreground",
    "notification_dismiss",
    "app_remove",
    "app_exception",
    "app_update",
    "os_update",
    "app_clear_data",
    "purchase",
    "in_app_purchase",
    "sign_up",
    "login",
}

# Fixed provider fields, never dimensions, filters or URLs supplied by the model.
_BREAKDOWN_API_FIELDS: dict[ParentBreakdownKind, tuple[list[str], list[str]]] = {
    "screens": (
        ["unifiedScreenName", "unifiedScreenClass"],
        ["screenPageViews", "userEngagementDuration"],
    ),
    "devices": (
        [
            "mobileDeviceModel",
            "mobileDeviceBranding",
            "operatingSystem",
            "operatingSystemVersion",
            "appVersion",
            "language",
            "deviceCategory",
        ],
        ["activeUsers", "eventCount"],
    ),
    "geography": (["country", "region", "city"], ["activeUsers", "eventCount"]),
    "acquisition": (
        [
            "firstUserSource",
            "firstUserMedium",
            "firstUserCampaignName",
            "firstUserSourcePlatform",
            "firstUserDefaultChannelGroup",
        ],
        ["newUsers", "activeUsers", "eventCount"],
    ),
    "weekday_hour": (["dayOfWeek", "hour"], ["activeUsers", "sessions", "eventCount"]),
    "notification_open_minutes": (["dateHourMinute"], ["eventCount"]),
}


def _label(value: str) -> str | None:
    if value.strip().casefold() in {"", "(not set)", "(other)", "(data not available)"}:
        return None
    # Minimize accidental identifiers in free-form screen/campaign labels. This is not
    # a general-purpose DLP guarantee; raw custom dimensions are never requested.
    if (
        len(value) > PARENT_LABEL_MAX_LENGTH
        or not value.isprintable()
        or re.search(r"@|https?://|\b[0-9]{7,}\b|\b[a-fA-F0-9]{24,}\b", value)
        or re.search(r"[+-]?\d{1,2}\.\d{4,}\s*[,;]\s*[+-]?\d{1,3}\.\d{4,}", value)
        or re.search(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b", value)
    ):
        raise ValueError("Potential private identifier in an aggregate label")
    return value.strip()


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderPermanentError("GA4 report is not an object")
    return value


def _number(value: object, *, integer: bool = False) -> Decimal:
    if not isinstance(value, str) or len(value) > 40:
        raise ProviderPermanentError("GA4 report has a missing numeric value")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ProviderPermanentError("GA4 report has an invalid numeric value") from exc
    if (
        not result.is_finite()
        or result < 0
        or result > Decimal("1e18")
        or (integer and result != result.to_integral_value())
    ):
        raise ProviderPermanentError("GA4 report has an invalid nonnegative numeric value")
    return result


def _rows(
    payload: dict[str, Any],
    dimensions: list[str],
    metrics: list[str],
    *,
    limit: int,
    repeated_metric_headers: bool = False,
) -> list[tuple[dict[str, str], dict[str, str]]]:
    raw_rows = payload.get("rows", [])
    if not isinstance(raw_rows, list) or len(raw_rows) > limit:
        raise ProviderPermanentError("GA4 exceeded the report row limit")
    # An empty scoped report may omit all headers. It is missing evidence, not zero.
    if not raw_rows and not payload.get("dimensionHeaders") and not payload.get("metricHeaders"):
        return []
    dimension_headers = payload.get("dimensionHeaders", [])
    metric_headers = payload.get("metricHeaders", [])
    if not isinstance(dimension_headers, list) or not isinstance(metric_headers, list):
        raise ProviderPermanentError("GA4 report headers are invalid")
    observed_dimensions = [_object(item).get("name") for item in dimension_headers]
    observed_metrics = [_object(item).get("name") for item in metric_headers]
    repeat = len(observed_metrics) // len(metrics)
    if observed_dimensions != dimensions or (
        observed_metrics != metrics
        and not (
            repeated_metric_headers and 1 <= repeat <= 2 and observed_metrics == metrics * repeat
        )
    ):
        raise ProviderPermanentError("GA4 report schema differs from the requested fields")
    result = []
    for raw in raw_rows:
        row = _object(raw)
        dim_values = row.get("dimensionValues", [])
        metric_values = row.get("metricValues", [])
        if not isinstance(dim_values, list) or not isinstance(metric_values, list):
            raise ProviderPermanentError("GA4 row values are invalid")
        dims = [_object(value).get("value") for value in dim_values]
        values = [_object(value).get("value") for value in metric_values]
        if repeated_metric_headers and len(values) == len(metrics) * 2:
            if values[: len(metrics)] != values[len(metrics) :]:
                raise ProviderPermanentError("Repeated GA4 metrics disagree")
            values = values[: len(metrics)]
        if (
            len(dims) != len(dimensions)
            or len(values) != len(metrics)
            or not all(isinstance(value, str) for value in [*dims, *values])
        ):
            raise ProviderPermanentError("GA4 row is incomplete")
        result.append(
            (
                dict(zip(dimensions, [str(value) for value in dims], strict=True)),
                dict(zip(metrics, [str(value) for value in values], strict=True)),
            )
        )
    count = payload.get("rowCount", len(raw_rows))
    if isinstance(count, bool) or not isinstance(count, int) or count < len(raw_rows):
        raise ProviderPermanentError("GA4 report row count is invalid")
    return result


def _quality(
    payload: dict[str, Any], *, timezone: str | None = None
) -> Literal["complete", "sampled", "thresholded"]:
    metadata = _object(payload.get("metadata", {}))
    if timezone is not None and metadata.get("timeZone") != timezone:
        raise ProviderPermanentError("GA4 report timezone does not match the approved binding")
    if metadata.get("samplingMetadatas"):
        return "sampled"
    if metadata.get("subjectToThresholding"):
        return "thresholded"
    return "complete"


class Ga4ParentAnalyticsAdapter:
    """Five sequential HTTP attempts at most; never retries or report pagination."""

    def __init__(
        self,
        *,
        http: AnalyticsReadHttp,
        clock: Clock,
        property_id: str,
        stream_id: str,
        timezone: str,
    ) -> None:
        if not re.fullmatch(r"[0-9]+", property_id) or not re.fullmatch(r"[0-9]+", stream_id):
            raise ValueError("Approved GA4 property and parent stream IDs must be numeric")
        self._http, self._clock = http, clock
        self._property, self._stream = property_id, stream_id
        self._timezone = ZoneInfo(timezone)
        self._filter = {
            "filter": {
                "fieldName": "streamId",
                "stringFilter": {
                    "matchType": "EXACT",
                    "value": stream_id,
                },
            }
        }

    def _report(
        self, end: date, days: int, dimensions: list[str], metrics: list[str], limit: int
    ) -> dict[str, Any]:
        return {
            "dateRanges": [
                {
                    "startDate": (end - timedelta(days=days - 1)).isoformat(),
                    "endDate": end.isoformat(),
                }
            ],
            "dimensionFilter": self._filter,
            "dimensions": [{"name": field} for field in dimensions],
            "metrics": [{"name": field} for field in metrics],
            "limit": str(limit),
            "returnPropertyQuota": True,
        }

    async def _batch(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        value = await self._http.request(
            "POST",
            f"https://analyticsdata.googleapis.com/v1beta/properties/{self._property}:batchRunReports",
            json={"requests": requests},
        )
        reports = _object(value).get("reports")
        if not isinstance(reports, list) or len(reports) != len(requests):
            raise ProviderPermanentError("GA4 batch returned an unexpected number of reports")
        return [_object(report) for report in reports]

    async def collect(self) -> ParentAnalyticsFacts:
        if self._clock.now().utcoffset() is None:
            raise ProviderPermanentError("GA4 analytics requires a timezone-aware clock")
        try:
            return await self._collect()
        except ValueError as exc:
            raise ProviderPermanentError("GA4 aggregate contract validation failed") from exc

    async def _collect(self) -> ParentAnalyticsFacts:
        end = self._clock.now().astimezone(self._timezone).date() - timedelta(days=1)
        metric_names = ["activeUsers", "sessions", "engagedSessions", "userEngagementDuration"]
        window_days: tuple[Literal[1, 7, 30], ...] = (1, 7, 30)
        requests = [self._report(end, days, ["streamId"], metric_names, 1) for days in window_days]
        requests.append(self._report(end, 30, ["streamId", "eventName"], ["eventCount"], 64))
        reports = await self._batch(requests)
        windows = []
        notes = [
            "GA4 describes the approved parent-app analytics stream, not backend accounts, "
            "children or an identity join. Other streams are excluded.",
            "Reports end on a completed property-timezone day; no raw identities or "
            "individual event sequences are collected. Missing observations are not zero.",
        ]
        for days, report in zip(window_days, reports[:3], strict=True):
            quality = _quality(report, timezone=str(self._timezone))
            rows = _rows(report, ["streamId"], metric_names, limit=1)
            if not rows or quality != "complete":
                notes.append(
                    f"The {days}-day window is unavailable or {quality}; "
                    "no point estimate supplied."
                )
                continue
            dimensions, metrics = rows[0]
            self._verify_stream(dimensions)
            active, sessions, engaged = [
                int(_number(metrics[name], integer=True)) for name in metric_names[:3]
            ]
            if engaged > sessions:
                raise ProviderPermanentError("GA4 engaged sessions exceed all sessions")
            windows.append(
                ParentActivityWindow(
                    days=days,
                    start_date=end - timedelta(days=days - 1),
                    end_date=end,
                    active_users=active,
                    sessions=sessions,
                    engaged_sessions=engaged,
                    engagement_seconds=_number(metrics["userEngagementDuration"]),
                )
            )
        event_report = reports[3]
        event_quality = _quality(event_report, timezone=str(self._timezone))
        event_rows = _rows(event_report, ["streamId", "eventName"], ["eventCount"], limit=64)
        event_counts: dict[str, int] = {}
        unknown_nonzero_events = False
        for dimensions, metrics in event_rows:
            self._verify_stream(dimensions)
            name = dimensions["eventName"]
            value = int(_number(metrics["eventCount"], integer=True))
            if name in _EVENTS:
                if name in event_counts:
                    raise ProviderPermanentError("GA4 returned duplicate scoped event rows")
                event_counts[name] = value
            elif value:
                unknown_nonzero_events = True
        event_complete = event_quality == "complete" and event_report.get(
            "rowCount", len(event_rows)
        ) == len(event_rows)
        event_complete = event_complete and not unknown_nonzero_events and bool(event_rows)
        event_status: Literal["complete", "partial", "missing", "sampled", "thresholded"] = (
            event_quality
        )
        if event_quality == "complete" and not event_complete:
            event_status = "partial" if event_rows else "missing"
        if not event_complete:
            notes.append("Event inventory is partial; absence does not prove an unrecorded event.")
        cohort_dates = [end - timedelta(days=31), end - timedelta(days=30)]
        cohort_requests = [self._cohort_request(first) for first in cohort_dates]
        cohort_reports = await self._batch(cohort_requests)
        cohorts = [
            self._cohort(first, report)
            for first, report in zip(cohort_dates, cohort_reports, strict=True)
        ]
        if any(cohort.quality != "complete" for cohort in cohorts):
            notes.append(
                "Some exact-day return cohorts are incomplete/qualified; missing days are not zero."
            )
        funnel_payload = await self._http.request(
            "POST",
            f"https://analyticsdata.googleapis.com/v1alpha/properties/{self._property}:runFunnelReport",
            json=self._funnel_request(end),
        )
        funnel = self._funnel(_object(funnel_payload))
        notes.append(
            "Push conversion ends at button_click within 24 hours per step, not a purchase "
            "or causal notification effect. Unknown payments remain unknown."
        )
        breakdowns = await self._breakdowns(end)
        notes.extend(
            [
                "Dimension reports retain at most ten groups each, not the whole population. "
                "Distinct users overlap across groups; never sum them into unique users. Missing "
                "labels and withheld private-looking values explicitly reduce coverage.",
                "Geography describes approximate app activity, not GPS, orders or sales. "
                "First-user attribution is not advertising spend or paid conversion; screen "
                "engagement is not per-user time. Minute buckets are aggregate opens, not "
                "notification delivery receipts or individual timelines.",
            ]
        )
        # A collection failure never returns an incomplete successful snapshot. The durable
        # source gate retains admission; the caller cannot redispatch a lost result.
        return ParentAnalyticsFacts(
            collected_at=self._clock.now(),
            stream_id=self._stream,
            property_timezone=str(self._timezone),
            period_start=end - timedelta(days=29),
            period_end=end,
            windows=windows,
            event_counts=event_counts,
            event_inventory_complete=event_complete,
            event_quality=event_status,
            cohorts=cohorts,
            notification_funnel=funnel,
            breakdowns=breakdowns,
            limitations=notes,
        )

    async def _breakdowns(self, end: date) -> list[ParentAnalyticsBreakdown]:
        kinds = list(_BREAKDOWN_API_FIELDS)
        requests = []
        for kind in kinds:
            dimensions, metrics = _BREAKDOWN_API_FIELDS[kind]
            request = self._report(end, 30, ["streamId", *dimensions], metrics, 10)
            request["orderBys"] = [{"metric": {"metricName": metrics[0]}, "desc": True}]
            if kind == "notification_open_minutes":
                request["dimensionFilter"] = {
                    "andGroup": {
                        "expressions": [
                            self._filter,
                            {
                                "filter": {
                                    "fieldName": "eventName",
                                    "stringFilter": {
                                        "matchType": "EXACT",
                                        "value": "notification_open",
                                    },
                                }
                            },
                        ]
                    }
                }
                request["orderBys"] = [
                    {"dimension": {"dimensionName": "dateHourMinute"}, "desc": True}
                ]
            requests.append(request)
        # Google permits at most five reports in a batch. No paging through groups.
        results = []
        for start in range(0, len(requests), 5):
            reports = await self._batch(requests[start : start + 5])
            # Validate this batch before admitting the next external request.
            for kind, report in zip(kinds[start : start + 5], reports, strict=True):
                results.append(self._breakdown(kind, report, end))
        return results

    def _breakdown(
        self, kind: ParentBreakdownKind, report: dict[str, Any], end: date
    ) -> ParentAnalyticsBreakdown:
        dimensions, metrics = _BREAKDOWN_API_FIELDS[kind]
        quality: Literal["complete", "partial", "missing", "sampled", "thresholded"] = _quality(
            report, timezone=str(self._timezone)
        )
        raw_rows = _rows(report, ["streamId", *dimensions], metrics, limit=10)
        rows = []
        withheld = 0
        label_names, measure_names = PARENT_BREAKDOWN_FIELDS[kind]
        for labels, values in raw_rows:
            self._verify_stream(labels)
            converted_values = {
                name: _number(values[api], integer=name != "engagement_seconds")
                for name, api in zip(measure_names, metrics, strict=True)
            }
            try:
                converted_labels = {
                    name: labels[api]
                    if kind == "notification_open_minutes"
                    else _label(labels[api])
                    for name, api in zip(label_names, dimensions, strict=True)
                }
            except ValueError:
                withheld += 1
                continue
            if kind == "weekday_hour" and (
                not re.fullmatch(r"[0-6]", labels["dayOfWeek"])
                or not re.fullmatch(r"(?:[01][0-9]|2[0-3])", labels["hour"])
            ):
                raise ProviderPermanentError("GA4 weekday/hour bucket is invalid")
            if kind == "notification_open_minutes":
                value = labels["dateHourMinute"]
                if not re.fullmatch(r"[0-9]{12}", value):
                    raise ProviderPermanentError("GA4 notification minute bucket is invalid")
                observed = datetime.strptime(value, "%Y%m%d%H%M").date()
                if not end - timedelta(days=29) <= observed <= end:
                    raise ProviderPermanentError("GA4 notification bucket is outside its period")
            rows.append(ParentBreakdownRow(labels=converted_labels, measures=converted_values))
        groups = report.get("rowCount", len(raw_rows))
        if quality == "complete":
            if not rows and not groups:
                quality = "missing"
            elif groups != len(rows) or any(
                value is None for row in rows for value in row.labels.values()
            ):
                quality = "partial"
        if quality == "complete" and _object(report.get("metadata", {})).get(
            "dataLossFromOtherRow"
        ):
            quality = "partial"
        return ParentAnalyticsBreakdown(
            kind=kind,
            rows=rows,
            total_groups=groups,
            withheld_rows=withheld,
            quality=quality,
        )

    def _verify_stream(self, dimensions: dict[str, str]) -> None:
        if dimensions.get("streamId") != self._stream:
            raise ProviderPermanentError("GA4 returned a different application stream")

    def _cohort_request(self, first: date) -> dict[str, Any]:
        return {
            "dimensions": [{"name": name} for name in ["cohort", "cohortNthDay", "streamId"]],
            "metrics": [{"name": name} for name in ["cohortActiveUsers", "cohortTotalUsers"]],
            "dimensionFilter": self._filter,
            "cohortSpec": {
                "cohorts": [
                    {
                        "name": "parent_" + first.strftime("%Y%m%d"),
                        "dimension": "firstSessionDate",
                        "dateRange": {"startDate": first.isoformat(), "endDate": first.isoformat()},
                    }
                ],
                "cohortsRange": {"granularity": "DAILY", "startOffset": 0, "endOffset": 30},
            },
            "limit": "31",
            "keepEmptyRows": True,
            "returnPropertyQuota": True,
        }

    def _cohort(self, first: date, report: dict[str, Any]) -> ParentRetentionCohort:
        quality: Literal["complete", "incomplete", "sampled", "thresholded"] = _quality(
            report, timezone=str(self._timezone)
        )
        rows = _rows(
            report,
            ["cohort", "cohortNthDay", "streamId"],
            ["cohortActiveUsers", "cohortTotalUsers"],
            limit=31,
        )
        days = []
        for dimensions, metrics in rows:
            self._verify_stream(dimensions)
            if dimensions["cohort"] != "parent_" + first.strftime("%Y%m%d") or not re.fullmatch(
                r"[0-9]{4}", dimensions["cohortNthDay"]
            ):
                raise ProviderPermanentError("GA4 returned a different cohort or invalid day")
            days.append(
                CohortDay(
                    day=int(dimensions["cohortNthDay"]),
                    active_users=int(_number(metrics["cohortActiveUsers"], integer=True)),
                    total_users=int(_number(metrics["cohortTotalUsers"], integer=True)),
                )
            )
        if quality == "complete" and (
            len(days) != 31 or report.get("rowCount", len(rows)) != len(rows)
        ):
            quality = "incomplete"
        return ParentRetentionCohort(first_session_date=first, days=days, quality=quality)

    def _funnel_request(self, end: date) -> dict[str, Any]:
        steps = []
        for index, name in enumerate(["notification_receive", "notification_open", "button_click"]):
            step: dict[str, Any] = {
                "name": name,
                "filterExpression": {
                    "andGroup": {
                        "expressions": [
                            {"funnelEventFilter": {"eventName": name}},
                            {"funnelFieldFilter": self._filter["filter"]},
                        ]
                    }
                },
            }
            if index:
                step["withinDurationFromPriorStep"] = "86400s"
            steps.append(step)
        return {
            "dateRanges": [
                {"startDate": (end - timedelta(days=29)).isoformat(), "endDate": end.isoformat()}
            ],
            "dimensionFilter": self._filter,
            "funnel": {"isOpenFunnel": False, "steps": steps},
            "limit": "3",
            "returnPropertyQuota": True,
        }

    def _funnel(self, payload: dict[str, Any]) -> NotificationEngagementFunnel | None:
        table = _object(payload.get("funnelTable", {}))
        quality = _quality(table)
        metrics = [
            "activeUsers",
            "funnelStepCompletionRate",
            "funnelStepAbandonments",
            "funnelStepAbandonmentRate",
        ]
        rows = _rows(table, ["funnelStepName"], metrics, limit=3, repeated_metric_headers=True)
        if not rows:
            return None
        if len(rows) != 3:
            raise ProviderPermanentError("GA4 returned an incomplete push funnel")
        by_step = {dims["funnelStepName"]: values for dims, values in rows}
        names = ["1. notification_receive", "2. notification_open", "3. button_click"]
        if set(by_step) != set(names):
            raise ProviderPermanentError("GA4 returned unknown or duplicate funnel steps")
        users = tuple(int(_number(by_step[name]["activeUsers"], integer=True)) for name in names)
        for index in [0, 1]:
            values = by_step[names[index]]
            completion = _number(values["funnelStepCompletionRate"])
            abandoned = int(_number(values["funnelStepAbandonments"], integer=True))
            abandon_rate = _number(values["funnelStepAbandonmentRate"])
            if (
                abandoned != users[index] - users[index + 1]
                or completion > 1
                or abandon_rate > 1
                or (
                    users[index]
                    and abs(completion - Decimal(users[index + 1]) / users[index]) > Decimal("1e-9")
                )
                or (users[index] and abs(completion + abandon_rate - 1) > Decimal("1e-9"))
            ):
                raise ProviderPermanentError("GA4 funnel users, rates and abandonments disagree")
        return NotificationEngagementFunnel(users=users, quality=quality)
