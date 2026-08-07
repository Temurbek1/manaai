from typing import Any

from app.mana_ai.domain.enums import ManaAICapability

OCCURRED_AT = "2026-08-07T14:20:00+05:00"

COMMON_USAGE = {
    "evidence_id": "usage-481",
    "observed_at": OCCURRED_AT,
    "source": "app_usage",
    "package_name": "org.example.learning",
    "display_name": "Learning App",
    "category": "education",
    "foreground_seconds": 1_800,
}
COMMON_LOCATION = {
    "evidence_id": "location-481",
    "observed_at": OCCURRED_AT,
    "source": "location",
    "latitude": 41.3111,
    "longitude": 69.2797,
    "accuracy_meters": 18,
    "speed_meters_per_second": 0,
    "location_source": "phone",
    "is_mocked": False,
    "online": True,
}
COMMON_NOTIFICATION = {
    "evidence_id": "notification-481",
    "observed_at": OCCURRED_AT,
    "source": "notification_preview",
    "application": "Telegram",
    "excerpt": "A minimized notification preview supplied by the application.",
}
COMMON_RESOURCE = {
    "evidence_id": "resource-481",
    "observed_at": OCCURRED_AT,
    "source": "link_check",
    "kind": "url",
    "normalized_value": "https://example.test/path",
    "reputation": "safe",
}

CAPABILITY_TITLES: dict[ManaAICapability, str] = {
    ManaAICapability.SAFETY_MONITOR: "Analyze available family-safety signals",
    ManaAICapability.FAMILY_DIGEST: "Generate a daily family digest",
    ManaAICapability.ADAPTIVE_SCREEN_TIME: "Assess adaptive screen-time limits",
    ManaAICapability.LOCATION_INTELLIGENCE: "Analyze a route deviation",
    ManaAICapability.SMART_CONTENT_FILTER: "Check a URL, domain, QR payload, or APK",
    ManaAICapability.SCAM_PRIVACY_SHIELD: "Check for scam and privacy risks",
    ManaAICapability.AI_GAMING_SAFETY: "Analyze AI-service and gaming usage metadata",
    ManaAICapability.PARENT_COPILOT: "Answer a parent using supplied family context",
    ManaAICapability.CHILD_SAFETY_ASSISTANT: "Give child-safe contextual guidance",
    ManaAICapability.FAMILY_AGREEMENT: "Draft transparent family rules",
    ManaAICapability.BEHAVIOUR_ANOMALY: "Analyze changes against supplied baselines",
}

CAPABILITY_INPUT_EXAMPLES: dict[ManaAICapability, dict[str, Any]] = {
    ManaAICapability.SAFETY_MONITOR: {
        "notifications": [COMMON_NOTIFICATION],
        "resources": [COMMON_RESOURCE],
    },
    ManaAICapability.FAMILY_DIGEST: {
        "period_start": "2026-08-07T00:00:00+05:00",
        "period_end": OCCURRED_AT,
        "app_usage": [COMMON_USAGE],
    },
    ManaAICapability.ADAPTIVE_SCREEN_TIME: {
        "app_usage": [COMMON_USAGE],
    },
    ManaAICapability.LOCATION_INTELLIGENCE: {
        "points": [COMMON_LOCATION],
        "route": {
            "expected_arrival_at": "2026-08-07T13:45:00+05:00",
            "distance_from_usual_route_meters": 850,
            "unusual_route_threshold_meters": 500,
        },
    },
    ManaAICapability.SMART_CONTENT_FILTER: {"resource": COMMON_RESOURCE},
    ManaAICapability.SCAM_PRIVACY_SHIELD: {"notifications": [COMMON_NOTIFICATION]},
    ManaAICapability.AI_GAMING_SAFETY: {
        "app_usage": [{**COMMON_USAGE, "category": "game"}],
    },
    ManaAICapability.PARENT_COPILOT: {
        "message": "Explain today's important changes and suggest the next step."
    },
    ManaAICapability.CHILD_SAFETY_ASSISTANT: {"message": "Why was this website blocked?"},
    ManaAICapability.FAMILY_AGREEMENT: {
        "mode": "draft",
        "preferences": {"goals": ["No games during sleep time"]},
    },
    ManaAICapability.BEHAVIOUR_ANOMALY: {
        "metrics": [
            {
                "evidence_id": "metric-481",
                "metric": "night_screen_time_seconds",
                "current_value": 300,
                "baseline_value": 120,
                "unit": "seconds",
            }
        ],
    },
}


def request_examples(capability: ManaAICapability) -> dict[str, dict[str, Any]]:
    return {
        "default": {
            "summary": CAPABILITY_TITLES[capability],
            "value": {
                "request_id": f"req-{capability.value}-20260807-001",
                "occurred_at": OCCURRED_AT,
                "locale": "ru",
                "subject": {
                    "subject_id": "child_opaque_12",
                    "age_band": "age_7_12",
                    "timezone": "Asia/Samarkand",
                    "policy_version": "family-policy-7",
                },
                "input": CAPABILITY_INPUT_EXAMPLES[capability],
                "data_minimized": True,
            },
        }
    }
