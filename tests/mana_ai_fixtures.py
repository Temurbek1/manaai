from datetime import UTC, datetime
from typing import Any, cast

from app.mana_ai.application.details import fallback_details
from app.mana_ai.domain.enums import ManaAICapability
from app.mana_ai.domain.requests import (
    AdaptiveScreenTimeRequest,
    AIGamingSafetyRequest,
    BehaviourAnomalyRequest,
    ChildSafetyAssistantRequest,
    FamilyAgreementRequest,
    FamilyDigestRequest,
    LocationIntelligenceRequest,
    ManaAIRequest,
    ManaAIRequestBase,
    ParentCopilotRequest,
    SafetyMonitorRequest,
    ScamPrivacyShieldRequest,
    SmartContentFilterRequest,
)
from app.mana_ai.domain.responses import CapabilityDetailsValue

NOW = datetime(2026, 8, 7, 9, 20, tzinfo=UTC)


REQUEST_TYPE_BY_CAPABILITY: dict[
    ManaAICapability,
    type[ManaAIRequestBase[Any]],
] = {
    ManaAICapability.SAFETY_MONITOR: SafetyMonitorRequest,
    ManaAICapability.FAMILY_DIGEST: FamilyDigestRequest,
    ManaAICapability.ADAPTIVE_SCREEN_TIME: AdaptiveScreenTimeRequest,
    ManaAICapability.LOCATION_INTELLIGENCE: LocationIntelligenceRequest,
    ManaAICapability.SMART_CONTENT_FILTER: SmartContentFilterRequest,
    ManaAICapability.SCAM_PRIVACY_SHIELD: ScamPrivacyShieldRequest,
    ManaAICapability.AI_GAMING_SAFETY: AIGamingSafetyRequest,
    ManaAICapability.PARENT_COPILOT: ParentCopilotRequest,
    ManaAICapability.CHILD_SAFETY_ASSISTANT: ChildSafetyAssistantRequest,
    ManaAICapability.FAMILY_AGREEMENT: FamilyAgreementRequest,
    ManaAICapability.BEHAVIOUR_ANOMALY: BehaviourAnomalyRequest,
}


def request_for(capability: ManaAICapability) -> ManaAIRequest:
    request_type = REQUEST_TYPE_BY_CAPABILITY[capability]
    return cast(
        ManaAIRequest,
        request_type.model_validate(
            {
                "request_id": f"request-{capability.value}",
                "occurred_at": NOW.isoformat(),
                "locale": "ru",
                "subject": {
                    "subject_id": "opaque-child-12",
                    "age_band": "age_7_12",
                    "timezone": "Asia/Samarkand",
                },
                "input": _input_for(capability),
                "data_minimized": True,
            },
        ),
    )


def details_for(capability: ManaAICapability) -> CapabilityDetailsValue:
    request = request_for(capability)
    return fallback_details(
        request.input,
        summary="No risk was detected in the available signals.",
        findings=[],
        evaluated_at=NOW,
    )


def _input_for(capability: ManaAICapability) -> dict[str, Any]:
    common_usage = {
        "evidence_id": "usage-1",
        "observed_at": NOW.isoformat(),
        "source": "app_usage",
        "package_name": "org.example.learning",
        "category": "education",
        "foreground_seconds": 1_800,
    }
    common_location = {
        "evidence_id": "location-1",
        "observed_at": NOW.isoformat(),
        "source": "location",
        "latitude": 41.3111,
        "longitude": 69.2797,
        "location_source": "phone",
    }
    common_notification = {
        "evidence_id": "notification-1",
        "observed_at": NOW.isoformat(),
        "source": "notification_preview",
        "application": "Telegram",
        "excerpt": "A short minimized preview",
    }
    common_resource = {
        "evidence_id": "resource-1",
        "observed_at": NOW.isoformat(),
        "source": "link_check",
        "kind": "url",
        "normalized_value": "https://example.test/path",
        "reputation": "safe",
    }
    inputs: dict[ManaAICapability, dict[str, Any]] = {
        ManaAICapability.SAFETY_MONITOR: {
            "notifications": [common_notification],
        },
        ManaAICapability.FAMILY_DIGEST: {
            "period_start": "2026-08-06T00:00:00+05:00",
            "period_end": "2026-08-07T00:00:00+05:00",
            "app_usage": [common_usage],
        },
        ManaAICapability.ADAPTIVE_SCREEN_TIME: {
            "app_usage": [common_usage],
        },
        ManaAICapability.LOCATION_INTELLIGENCE: {
            "points": [common_location],
        },
        ManaAICapability.SMART_CONTENT_FILTER: {
            "resource": common_resource,
        },
        ManaAICapability.SCAM_PRIVACY_SHIELD: {
            "notifications": [common_notification],
        },
        ManaAICapability.AI_GAMING_SAFETY: {
            "app_usage": [{**common_usage, "category": "game"}],
        },
        ManaAICapability.PARENT_COPILOT: {
            "message": "Explain today's important changes.",
        },
        ManaAICapability.CHILD_SAFETY_ASSISTANT: {
            "message": "Why was this website blocked?",
        },
        ManaAICapability.FAMILY_AGREEMENT: {
            "mode": "draft",
            "preferences": {"goals": ["No games during sleep time"]},
        },
        ManaAICapability.BEHAVIOUR_ANOMALY: {
            "metrics": [
                {
                    "evidence_id": "metric-1",
                    "metric": "night_screen_time_seconds",
                    "current_value": 300,
                    "baseline_value": 120,
                    "unit": "seconds",
                }
            ],
        },
    }
    return inputs[capability]
