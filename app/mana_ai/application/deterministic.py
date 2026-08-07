from datetime import datetime

from pydantic import Field

from app.mana_ai.domain.enums import (
    ActionKind,
    AnalysisVerdict,
    AppCategory,
    CheckStatus,
    FindingCategory,
    ReputationVerdict,
    RiskLevel,
)
from app.mana_ai.domain.requests import (
    AdaptiveScreenTimeInput,
    AIGamingSafetyInput,
    BehaviourAnomalyInput,
    CapabilityInput,
    FamilyDigestInput,
    LocationIntelligenceInput,
    SafetyMonitorInput,
    ScamPrivacyShieldInput,
    SmartContentFilterInput,
)
from app.mana_ai.domain.responses import (
    ActionValue,
    CheckResult,
    FamilyReportAction,
    FindingDraft,
    NotifyParentAction,
    ResourceBlockAction,
    WarnChildAction,
)
from app.mana_ai.domain.signals import (
    AppLimit,
    AppUsageSignal,
    BatterySignal,
    MetricComparison,
    ProtectionStateSignal,
    ResourceSignal,
    StrictModel,
)


class DeterministicAnalysis(StrictModel):
    findings: list[FindingDraft] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    proposed_actions: list[ActionValue] = Field(default_factory=list)
    data_quality_notes: list[str] = Field(default_factory=list)


def analyze_deterministically(
    payload: CapabilityInput,
    *,
    evaluated_at: datetime,
) -> DeterministicAnalysis:
    if isinstance(payload, SafetyMonitorInput):
        return _analyze_safety_monitor(payload)
    if isinstance(payload, FamilyDigestInput):
        return _analyze_family_digest(payload)
    if isinstance(payload, AdaptiveScreenTimeInput):
        return _analyze_screen_time(payload)
    if isinstance(payload, LocationIntelligenceInput):
        return _analyze_location(payload, evaluated_at=evaluated_at)
    if isinstance(payload, SmartContentFilterInput):
        return _analyze_content(payload)
    if isinstance(payload, ScamPrivacyShieldInput):
        return _analyze_scam(payload)
    if isinstance(payload, AIGamingSafetyInput):
        return _analyze_ai_gaming(payload)
    if isinstance(payload, BehaviourAnomalyInput):
        return _analyze_behaviour(payload)
    return DeterministicAnalysis()


def required_checks(payload: CapabilityInput) -> list[CheckResult]:
    return [
        CheckResult(
            category=category,
            status=CheckStatus.INSUFFICIENT_DATA,
            explanation=(
                f"Analyze the supplied {source}."
                if available
                else f"No {source} were supplied for this check."
            ),
        )
        for category, available, source in _check_requirements(payload)
    ]


def unavailable_check_categories(payload: CapabilityInput) -> set[FindingCategory]:
    return {
        category for category, available, _source in _check_requirements(payload) if not available
    }


def _check_requirements(
    payload: CapabilityInput,
) -> list[tuple[FindingCategory, bool, str]]:
    requirements: list[tuple[FindingCategory, bool, str]] = []
    if isinstance(payload, SafetyMonitorInput):
        has_text = bool(payload.notifications)
        has_resources = bool(payload.resources or payload.websites)
        requirements = [
            (FindingCategory.BULLYING, has_text, "notification previews"),
            (FindingCategory.THREAT, has_text, "notification previews"),
            (FindingCategory.PRESSURE_OR_MANIPULATION, has_text, "notification previews"),
            (FindingCategory.PERSONAL_DATA_REQUEST, has_text, "notification previews"),
            (FindingCategory.SCAM, has_text or has_resources, "notification or resource signals"),
            (FindingCategory.PHISHING, has_resources, "resource or website signals"),
            (FindingCategory.UNSAFE_LINK_OR_SITE, has_resources, "resource or website signals"),
            (
                FindingCategory.PROTECTION_DISABLED,
                payload.protection_state is not None,
                "protection state",
            ),
        ]
    elif isinstance(payload, SmartContentFilterInput):
        requirements = [
            (FindingCategory.UNSAFE_LINK_OR_SITE, True, "resource signal"),
            (FindingCategory.UNSAFE_CONTENT, True, "resource signal"),
            (FindingCategory.SUSPICIOUS_DOWNLOAD, True, "resource signal"),
        ]
    elif isinstance(payload, ScamPrivacyShieldInput):
        has_text = bool(payload.notifications)
        has_resources = bool(payload.resources)
        requirements = [
            (FindingCategory.SCAM, has_text or has_resources, "notification or resource signals"),
            (
                FindingCategory.PHISHING,
                has_text or has_resources,
                "notification or resource signals",
            ),
            (FindingCategory.PERSONAL_DATA_REQUEST, has_text, "notification previews"),
            (FindingCategory.SUSPICIOUS_DOWNLOAD, has_resources, "resource signals"),
        ]

    return requirements


def verdict_from(findings: list[FindingDraft], actions: list[ActionValue]) -> AnalysisVerdict:
    if any(action.kind is ActionKind.PROPOSE_RESOURCE_BLOCK for action in actions):
        return AnalysisVerdict.BLOCK
    levels = {finding.risk_level for finding in findings}
    if RiskLevel.CRITICAL in levels or RiskLevel.HIGH in levels:
        return AnalysisVerdict.ALERT
    if RiskLevel.MEDIUM in levels:
        return AnalysisVerdict.WARN
    if levels:
        return AnalysisVerdict.OBSERVE
    return AnalysisVerdict.NO_RISK_DETECTED


def _analyze_safety_monitor(payload: SafetyMonitorInput) -> DeterministicAnalysis:
    result = DeterministicAnalysis()
    if payload.protection_state is not None:
        _add_protection_finding(result, payload.protection_state)
    for resource in payload.resources:
        _add_resource_finding(result, resource)
    for website in payload.websites:
        if website.reputation is ReputationVerdict.MALICIOUS:
            result.findings.append(
                _finding(
                    FindingCategory.UNSAFE_LINK_OR_SITE,
                    RiskLevel.CRITICAL,
                    100,
                    "Known malicious website",
                    "A visited domain was marked malicious by the supplied reputation signal.",
                    website.evidence_id,
                    "Prevent access and notify the parent with minimized context.",
                )
            )
    for usage in payload.app_usage:
        _add_usage_findings(result, usage)
    _add_battery_findings(result, payload.battery)
    _notify_for_high_risk(result)
    return result


def _analyze_family_digest(payload: FamilyDigestInput) -> DeterministicAnalysis:
    result = DeterministicAnalysis()
    for metric in payload.metrics:
        _add_metric_finding(result, metric)
    for usage in payload.app_usage:
        _add_usage_findings(result, usage)
    for event in payload.safety_events:
        result.findings.append(
            _finding(
                FindingCategory.INFORMATIONAL,
                _risk_from_score(event.severity),
                100,
                "Safety event in digest period",
                event.summary,
                event.evidence_id,
                "Review the originating safety event and its evidence.",
            )
        )
    if payload.protection_state is not None:
        _add_protection_finding(result, payload.protection_state)
    _add_battery_findings(result, payload.battery)
    period_days = (payload.period_end - payload.period_start).total_seconds() / 86_400
    result.proposed_actions.append(
        FamilyReportAction(
            kind=ActionKind.GENERATE_FAMILY_REPORT,
            period="weekly" if period_days > 2 else "daily",
        )
    )
    return result


def _analyze_screen_time(payload: AdaptiveScreenTimeInput) -> DeterministicAnalysis:
    result = DeterministicAnalysis()
    for usage in payload.app_usage:
        limit = _effective_limit(usage, payload.limits)
        _add_usage_findings(result, usage, explicit_limit=limit)
    return result


def _analyze_location(
    payload: LocationIntelligenceInput,
    *,
    evaluated_at: datetime,
) -> DeterministicAnalysis:
    result = DeterministicAnalysis()
    for point in payload.points:
        if point.is_mocked:
            result.findings.append(
                _finding(
                    FindingCategory.LOCATION_SPOOFING,
                    RiskLevel.HIGH,
                    100,
                    "Possible location spoofing",
                    "The application marked a supplied location point as mocked.",
                    point.evidence_id,
                    "Verify device protection state and contact the child if appropriate.",
                )
            )
        if not point.online:
            result.findings.append(
                _finding(
                    FindingCategory.DEVICE_OFFLINE,
                    RiskLevel.MEDIUM,
                    100,
                    "Location device offline",
                    "A location source was reported offline.",
                    point.evidence_id,
                    "Check connectivity and the freshness of the last valid location.",
                )
            )
    route = payload.route
    latest = max(payload.points, key=lambda point: point.observed_at)
    if route is not None:
        if (
            route.distance_from_usual_route_meters is not None
            and route.distance_from_usual_route_meters > route.unusual_route_threshold_meters
        ):
            result.findings.append(
                _finding(
                    FindingCategory.LOCATION_DEVIATION,
                    RiskLevel.HIGH,
                    100,
                    "Route deviation",
                    "The supplied route distance exceeded the configured deviation threshold.",
                    latest.evidence_id,
                    "Show the parent the derived deviation, not the full location history.",
                )
            )
        if route.expected_arrival_at is not None and evaluated_at > route.expected_arrival_at:
            result.findings.append(
                _finding(
                    FindingCategory.DELAYED_ARRIVAL,
                    RiskLevel.MEDIUM,
                    100,
                    "Expected arrival time passed",
                    "The expected arrival time passed before the current evaluation.",
                    latest.evidence_id,
                    "Suggest a check-in while avoiding assumptions about the reason.",
                )
            )
        if (
            route.stopped_duration_seconds is not None
            and route.stopped_duration_seconds > route.long_stop_threshold_seconds
        ):
            result.findings.append(
                _finding(
                    FindingCategory.LONG_STOP,
                    RiskLevel.MEDIUM,
                    100,
                    "Unusually long stop",
                    "The supplied stop duration exceeded the configured threshold.",
                    latest.evidence_id,
                    "Compare with the known schedule before alerting.",
                )
            )
        speed = latest.speed_meters_per_second
        if (
            speed is not None
            and route.usual_max_speed_meters_per_second is not None
            and speed > route.usual_max_speed_meters_per_second
        ):
            result.findings.append(
                _finding(
                    FindingCategory.UNUSUAL_SPEED,
                    RiskLevel.MEDIUM,
                    100,
                    "Unusual movement speed",
                    "The latest speed exceeded the supplied usual maximum.",
                    latest.evidence_id,
                    "Treat speed as approximate and account for GPS accuracy.",
                )
            )
    _add_battery_findings(result, payload.battery)
    _notify_for_high_risk(result)
    return result


def _analyze_content(payload: SmartContentFilterInput) -> DeterministicAnalysis:
    result = DeterministicAnalysis()
    _add_resource_finding(result, payload.resource)
    if payload.resource.category in payload.blocked_categories:
        result.findings.append(
            _finding(
                FindingCategory.UNSAFE_CONTENT,
                RiskLevel.HIGH,
                100,
                "Blocked content category",
                "The supplied resource category is blocked by the application policy.",
                payload.resource.evidence_id,
                "Ask the application policy layer to prevent access.",
            )
        )
        result.proposed_actions.append(
            ResourceBlockAction(
                kind=ActionKind.PROPOSE_RESOURCE_BLOCK,
                resource_evidence_id=payload.resource.evidence_id,
                rationale="The resource category is blocked by the supplied policy.",
            )
        )
    return result


def _analyze_scam(payload: ScamPrivacyShieldInput) -> DeterministicAnalysis:
    result = DeterministicAnalysis()
    for resource in payload.resources:
        _add_resource_finding(result, resource)
    _notify_for_high_risk(result)
    return result


def _analyze_ai_gaming(payload: AIGamingSafetyInput) -> DeterministicAnalysis:
    result = DeterministicAnalysis()
    for usage in payload.app_usage:
        if usage.category not in {AppCategory.AI_SERVICE, AppCategory.GAME}:
            continue
        limit = _effective_limit(usage, payload.limits)
        _add_usage_findings(result, usage, explicit_limit=limit)
    return result


def _analyze_behaviour(payload: BehaviourAnomalyInput) -> DeterministicAnalysis:
    result = DeterministicAnalysis()
    for metric in payload.metrics:
        _add_metric_finding(result, metric)
    if payload.protection_state is not None:
        _add_protection_finding(result, payload.protection_state)
    baselines = {item.key: item for item in payload.usage_baselines}
    for usage in payload.app_usage:
        baseline = baselines.get(usage.package_name)
        if baseline is None or baseline.average_seconds == 0:
            continue
        change = (
            (usage.foreground_seconds - baseline.average_seconds) / baseline.average_seconds
        ) * 100
        if abs(change) >= 50:
            result.findings.append(
                _finding(
                    FindingCategory.APP_USAGE_CHANGE,
                    RiskLevel.MEDIUM,
                    100,
                    "Significant application usage change",
                    f"Usage changed by {change:.0f}% relative to the supplied baseline.",
                    usage.evidence_id,
                    "Present the change without inferring a psychological or medical cause.",
                )
            )
    _add_battery_findings(result, payload.battery)
    return result


def _add_protection_finding(
    result: DeterministicAnalysis,
    protection: ProtectionStateSignal,
) -> None:
    disabled = [
        name
        for name, enabled in {
            "location permission": protection.location_permission,
            "notification access": protection.notification_access,
            "VPN": protection.vpn_enabled,
            "usage access": protection.usage_access,
        }.items()
        if not enabled
    ]
    if not disabled and protection.disable_attempt_count == 0:
        return
    result.findings.append(
        _finding(
            FindingCategory.PROTECTION_DISABLED,
            RiskLevel.HIGH,
            100,
            "Protection component disabled",
            "Unavailable protection components: " + ", ".join(disabled or ["disable attempt"]),
            protection.evidence_id,
            "Ask the application to restore the required permission or protection component.",
        )
    )


def _add_resource_finding(result: DeterministicAnalysis, resource: ResourceSignal) -> None:
    if resource.reputation is ReputationVerdict.SAFE:
        return
    if resource.reputation is ReputationVerdict.MALICIOUS:
        risk = RiskLevel.CRITICAL
        confidence = 100
        action: ActionValue = ResourceBlockAction(
            kind=ActionKind.PROPOSE_RESOURCE_BLOCK,
            resource_evidence_id=resource.evidence_id,
            rationale="The supplied reputation verdict is malicious.",
        )
    elif resource.reputation is ReputationVerdict.SUSPICIOUS:
        risk = RiskLevel.HIGH
        confidence = 90
        action = WarnChildAction(
            kind=ActionKind.WARN_CHILD,
            message="This resource is suspicious. Do not share personal or payment data.",
            evidence_ids=[resource.evidence_id],
        )
    else:
        return
    category = (
        FindingCategory.SUSPICIOUS_DOWNLOAD
        if resource.kind.value == "apk"
        else FindingCategory.UNSAFE_LINK_OR_SITE
    )
    result.findings.append(
        _finding(
            category,
            risk,
            confidence,
            "Unsafe resource reputation",
            "The application supplied a non-safe reputation verdict for this resource.",
            resource.evidence_id,
            "Apply the family policy before allowing access.",
        )
    )
    result.proposed_actions.append(action)


def _add_usage_findings(
    result: DeterministicAnalysis,
    usage: AppUsageSignal,
    *,
    explicit_limit: int | None = None,
) -> None:
    limit = explicit_limit or usage.configured_limit_seconds
    if limit is not None and usage.foreground_seconds > limit:
        result.findings.append(
            _finding(
                FindingCategory.LIMIT_EXCEEDED,
                RiskLevel.MEDIUM,
                100,
                "Configured usage limit exceeded",
                "Foreground usage exceeded the limit supplied by the application.",
                usage.evidence_id,
                "Notify the family and let the application enforce its existing policy.",
            )
        )
    if usage.night_seconds > 0:
        result.findings.append(
            _finding(
                FindingCategory.NIGHT_ACTIVITY,
                RiskLevel.LOW,
                100,
                "Night-time application activity",
                "The supplied usage aggregate contains night-time activity.",
                usage.evidence_id,
                "Compare it with the sleep schedule before proposing a restriction.",
            )
        )


def _add_battery_findings(
    result: DeterministicAnalysis,
    battery: list[BatterySignal],
) -> None:
    for signal in battery:
        if not signal.online:
            result.findings.append(
                _finding(
                    FindingCategory.DEVICE_OFFLINE,
                    RiskLevel.MEDIUM,
                    100,
                    "Device reported offline",
                    "A supplied battery snapshot marks the device as offline.",
                    signal.evidence_id,
                    "Check signal freshness and connectivity before escalating.",
                )
            )
        if signal.drain_percent_per_hour is not None and signal.drain_percent_per_hour >= 30:
            result.findings.append(
                _finding(
                    FindingCategory.BATTERY_ANOMALY,
                    RiskLevel.MEDIUM,
                    100,
                    "Unusual battery drain",
                    "Battery drain was at least 30 percentage points per hour.",
                    signal.evidence_id,
                    "Compare with device activity and location before escalating.",
                )
            )


def _add_metric_finding(result: DeterministicAnalysis, metric: MetricComparison) -> None:
    change = metric.change_percent
    if change is None:
        result.data_quality_notes.append(
            f"Metric {metric.metric} has a zero baseline; percentage change is unavailable."
        )
        return
    if abs(change) < metric.significant_change_percent:
        return
    positive = (change > 0) == metric.higher_is_positive
    result.findings.append(
        _finding(
            FindingCategory.POSITIVE_CHANGE if positive else FindingCategory.INFORMATIONAL,
            RiskLevel.INFORMATIONAL if positive else RiskLevel.LOW,
            100,
            "Significant metric change",
            f"{metric.metric} changed by {change:.0f}% relative to the supplied baseline.",
            metric.evidence_id,
            "Review the trend in context; do not infer a diagnosis or motive.",
        )
    )


def _effective_limit(usage: AppUsageSignal, limits: list[AppLimit]) -> int | None:
    for limit in limits:
        if limit.package_name == usage.package_name or (
            limit.category is not None and limit.category is usage.category
        ):
            return limit.daily_limit_seconds
    return usage.configured_limit_seconds


def _notify_for_high_risk(result: DeterministicAnalysis) -> None:
    evidence_ids = sorted(
        {
            evidence_id
            for finding in result.findings
            if finding.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}
            for evidence_id in finding.evidence_ids
        }
    )
    if evidence_ids:
        result.proposed_actions.append(
            NotifyParentAction(
                kind=ActionKind.NOTIFY_PARENT,
                urgency=RiskLevel.HIGH,
                message="A high-risk signal requires parent review.",
                evidence_ids=evidence_ids,
            )
        )


def _finding(
    category: FindingCategory,
    risk: RiskLevel,
    confidence: int,
    title: str,
    summary: str,
    evidence_id: str,
    recommendation: str,
) -> FindingDraft:
    return FindingDraft(
        category=category,
        risk_level=risk,
        confidence=confidence,
        title=title,
        summary=summary,
        evidence_ids=[evidence_id],
        recommendation=recommendation,
    )


def _risk_from_score(score: int) -> RiskLevel:
    if score >= 85:
        return RiskLevel.CRITICAL
    if score >= 65:
        return RiskLevel.HIGH
    if score >= 40:
        return RiskLevel.MEDIUM
    if score >= 15:
        return RiskLevel.LOW
    return RiskLevel.INFORMATIONAL
