from datetime import datetime

from app.mana_ai.domain.enums import (
    AnalysisVerdict,
    AppCategory,
    CheckStatus,
    FindingCategory,
    ReputationVerdict,
)
from app.mana_ai.domain.requests import (
    AdaptiveScreenTimeInput,
    AIGamingSafetyInput,
    BehaviourAnomalyInput,
    CapabilityInput,
    ChildSafetyAssistantInput,
    FamilyAgreementInput,
    FamilyDigestInput,
    LocationIntelligenceInput,
    ParentCopilotInput,
    SafetyMonitorInput,
    ScamPrivacyShieldInput,
    SmartContentFilterInput,
)
from app.mana_ai.domain.responses import (
    AdaptiveScreenTimeDetails,
    AIGamingSafetyDetails,
    AppClassification,
    BehaviourAnomalyDetails,
    CapabilityDetailsValue,
    CheckResult,
    ChildSafetyAssistantDetails,
    FamilyAgreementDetails,
    FamilyDigestDetails,
    FindingDraft,
    LocationIntelligenceDetails,
    ParentCopilotDetails,
    SafetyMonitorDetails,
    ScamPrivacyShieldDetails,
    SmartContentFilterDetails,
)


def fallback_details(
    payload: CapabilityInput,
    *,
    summary: str,
    findings: list[FindingDraft],
    evaluated_at: datetime,
    verdict: AnalysisVerdict = AnalysisVerdict.INSUFFICIENT_DATA,
) -> CapabilityDetailsValue:
    if isinstance(payload, SafetyMonitorInput):
        return SafetyMonitorDetails(
            parent_context=summary,
            significant_event_count=len(findings),
        )
    if isinstance(payload, FamilyDigestInput):
        return FamilyDigestDetails(
            period_summary=summary,
        )
    if isinstance(payload, AdaptiveScreenTimeInput):
        return AdaptiveScreenTimeDetails(
            app_classifications=[
                AppClassification(
                    package_name=item.package_name,
                    category=item.category,
                    explanation="Classification was supplied by the application.",
                )
                for item in payload.app_usage
                if item.category is not AppCategory.UNKNOWN
            ],
        )
    if isinstance(payload, LocationIntelligenceInput):
        route_status: str = "unknown"
        if payload.route is not None:
            if (
                payload.route.distance_from_usual_route_meters is not None
                and payload.route.distance_from_usual_route_meters
                > payload.route.unusual_route_threshold_meters
            ):
                route_status = "deviated"
            elif (
                payload.route.expected_arrival_at is not None
                and evaluated_at > payload.route.expected_arrival_at
            ):
                route_status = "delayed"
            else:
                route_status = "usual"
        return LocationIntelligenceDetails(
            route_status=route_status,
            explanation=summary,
        )
    if isinstance(payload, SmartContentFilterInput):
        decision = "observe"
        if verdict is AnalysisVerdict.BLOCK:
            decision = "block"
        elif verdict in {AnalysisVerdict.ALERT, AnalysisVerdict.WARN}:
            decision = "warn"
        elif payload.resource.reputation is ReputationVerdict.SAFE:
            decision = "allow"
        return SmartContentFilterDetails(
            decision=decision,
            category=payload.resource.category,
            reputation=payload.resource.reputation,
            explanation=summary,
        )
    if isinstance(payload, ScamPrivacyShieldInput):
        return ScamPrivacyShieldDetails(
            explanation=summary,
        )
    if isinstance(payload, AIGamingSafetyInput):
        affected = [
            item.package_name
            for item in payload.app_usage
            if item.category in {AppCategory.AI_SERVICE, AppCategory.GAME}
        ]
        return AIGamingSafetyDetails(
            ai_service_summary=summary,
            gaming_summary=summary,
            affected_packages=affected,
        )
    if isinstance(payload, ParentCopilotInput):
        return ParentCopilotDetails(
            answer=summary,
        )
    if isinstance(payload, ChildSafetyAssistantInput):
        return ChildSafetyAssistantDetails(
            answer=summary,
            explanation=summary,
            should_contact_parent=False,
        )
    if isinstance(payload, FamilyAgreementInput):
        return FamilyAgreementDetails(
            request_context=summary,
        )
    if isinstance(payload, BehaviourAnomalyInput):
        return BehaviourAnomalyDetails(
            changed_metrics=[item.metric for item in payload.metrics],
            explanation=summary,
        )
    raise AssertionError("Unhandled MANA AI capability input")


def reconcile_details(
    payload: CapabilityInput,
    details: CapabilityDetailsValue,
    *,
    summary: str,
    findings: list[FindingDraft],
    checks: list[CheckResult],
    evaluated_at: datetime,
    verdict: AnalysisVerdict,
) -> CapabilityDetailsValue:
    """Make model-authored details consistent with validated application facts."""
    if isinstance(payload, SafetyMonitorInput) and isinstance(details, SafetyMonitorDetails):
        all_clear = [
            check.category for check in checks if check.status is CheckStatus.NO_RISK_DETECTED
        ]
        return details.model_copy(
            update={
                "parent_context": summary,
                "significant_event_count": len(findings),
                "all_clear_categories": all_clear,
            }
        )

    if isinstance(payload, AdaptiveScreenTimeInput) and isinstance(
        details, AdaptiveScreenTimeDetails
    ):
        supplied_packages = {item.package_name for item in payload.app_usage}
        return details.model_copy(
            update={
                "app_classifications": [
                    item
                    for item in details.app_classifications
                    if item.package_name in supplied_packages
                ]
            }
        )

    if isinstance(payload, LocationIntelligenceInput) and isinstance(
        details, LocationIntelligenceDetails
    ):
        fallback = fallback_details(
            payload,
            summary=summary,
            findings=findings,
            evaluated_at=evaluated_at,
            verdict=verdict,
        )
        assert isinstance(fallback, LocationIntelligenceDetails)
        return details.model_copy(
            update={
                "route_status": fallback.route_status,
                "explanation": summary,
            }
        )

    if isinstance(payload, SmartContentFilterInput) and isinstance(
        details, SmartContentFilterDetails
    ):
        fallback = fallback_details(
            payload,
            summary=summary,
            findings=findings,
            evaluated_at=evaluated_at,
            verdict=verdict,
        )
        assert isinstance(fallback, SmartContentFilterDetails)
        return details.model_copy(
            update={
                "decision": fallback.decision,
                "category": payload.resource.category or details.category,
                "reputation": payload.resource.reputation,
                "explanation": summary,
            }
        )

    if isinstance(payload, ScamPrivacyShieldInput) and isinstance(
        details, ScamPrivacyShieldDetails
    ):
        supported_categories = {
            FindingCategory.SCAM,
            FindingCategory.PHISHING,
            FindingCategory.PERSONAL_DATA_REQUEST,
            FindingCategory.SUSPICIOUS_DOWNLOAD,
        }
        has_supported_finding = any(
            finding.category in supported_categories for finding in findings
        )
        return details.model_copy(
            update={
                "detected_patterns": details.detected_patterns if has_supported_finding else [],
                "requested_data_types": (
                    details.requested_data_types if has_supported_finding else []
                ),
                "explanation": summary,
            }
        )

    if isinstance(payload, AIGamingSafetyInput) and isinstance(details, AIGamingSafetyDetails):
        supplied_packages = {item.package_name for item in payload.app_usage}
        return details.model_copy(
            update={
                "affected_packages": list(
                    dict.fromkeys(
                        package
                        for package in details.affected_packages
                        if package in supplied_packages
                    )
                )
            }
        )

    if isinstance(payload, BehaviourAnomalyInput) and isinstance(details, BehaviourAnomalyDetails):
        supplied_metrics = {item.metric for item in payload.metrics}
        return details.model_copy(
            update={
                "changed_metrics": [
                    metric for metric in details.changed_metrics if metric in supplied_metrics
                ],
                "explanation": summary,
            }
        )

    if details_match_input(payload, details):
        return details
    return fallback_details(
        payload,
        summary=summary,
        findings=findings,
        evaluated_at=evaluated_at,
        verdict=verdict,
    )


def details_match_input(
    payload: CapabilityInput,
    details: CapabilityDetailsValue,
) -> bool:
    return (
        isinstance(payload, SafetyMonitorInput)
        and isinstance(details, SafetyMonitorDetails)
        or isinstance(payload, FamilyDigestInput)
        and isinstance(details, FamilyDigestDetails)
        or isinstance(payload, AdaptiveScreenTimeInput)
        and isinstance(details, AdaptiveScreenTimeDetails)
        or isinstance(payload, LocationIntelligenceInput)
        and isinstance(details, LocationIntelligenceDetails)
        or isinstance(payload, SmartContentFilterInput)
        and isinstance(details, SmartContentFilterDetails)
        or isinstance(payload, ScamPrivacyShieldInput)
        and isinstance(details, ScamPrivacyShieldDetails)
        or isinstance(payload, AIGamingSafetyInput)
        and isinstance(details, AIGamingSafetyDetails)
        or isinstance(payload, ParentCopilotInput)
        and isinstance(details, ParentCopilotDetails)
        or isinstance(payload, ChildSafetyAssistantInput)
        and isinstance(details, ChildSafetyAssistantDetails)
        or isinstance(payload, FamilyAgreementInput)
        and isinstance(details, FamilyAgreementDetails)
        or isinstance(payload, BehaviourAnomalyInput)
        and isinstance(details, BehaviourAnomalyDetails)
    )
