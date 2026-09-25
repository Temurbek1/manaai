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

CAPABILITY_DESCRIPTIONS: dict[ManaAICapability, str] = {
    ManaAICapability.SAFETY_MONITOR: (
        "**The broad sweep.** Can screen every supplied signal type for bullying, threats, "
        "pressure or "
        "manipulation, requests for personal or banking data, scams, phishing, unsafe resources, "
        "abnormal usage or location, and disabled protection.\n\n"
        "**Send** at least one of `notifications`, `resources`, `websites`, `app_usage`, "
        "`locations`, `battery`, `protection_state`. No individual signal type is mandatory, but "
        "an empty input is invalid; a check whose signal type is absent reports "
        "`insufficient_data` instead of guessing.\n\n"
        "**Returns** `details.parent_context` (one line a parent can read), "
        "`significant_event_count`, and `all_clear_categories`. Use this when you want one verdict "
        "over everything; use a narrower capability when you already know what you are asking."
    ),
    ManaAICapability.FAMILY_DIGEST: (
        "**Periodic summary, not an alarm.** Condenses a day or week into what a parent actually "
        "needs to read, prioritizing meaningful change over raw activity.\n\n"
        "**Send** the required `period_start` and `period_end`, plus any of `app_usage`, "
        "`usage_baselines`, `notification_activity`, `websites`, `metrics`, `locations`, "
        "`battery`, `protection_state`, `safety_events`. Baselines are what make a change "
        "meaningful, so include them when you have them.\n\n"
        "**Returns** `details.period_summary`, `highlights`, `positive_changes`, and "
        "`minor_anomalies` — positives are deliberately first-class, so the digest is not purely "
        "negative."
    ),
    ManaAICapability.ADAPTIVE_SCREEN_TIME: (
        "**Limits that adapt instead of punish.** Classifies how apps are actually used and judges "
        "whether current limits still fit, recommending gradual change.\n\n"
        "**Send** the required `app_usage`, plus `usage_baselines`, `schedules`, `limits`, "
        "`extra_time_requests`, `family_rules`.\n\n"
        "**Returns** `details.app_classifications` (per-app category judgement) and "
        "`limit_assessment`. It proposes limit changes; it never enforces them — applying a "
        "proposal is always the application's decision."
    ),
    ManaAICapability.LOCATION_INTELLIGENCE: (
        "**Explains movement without guessing motive.** Interprets route deviations, arrival "
        "estimates, long stops, early departures, unusual speed, spoofing indicators, battery "
        "drain, and loss of connectivity.\n\n"
        "**Send** the required `points`, plus `geofences`, `route`, `battery`. GPS accuracy is "
        "taken into account, so pass it on each point.\n\n"
        "**Returns** `details.route_status` (`usual`/`deviated`/`delayed`/`unknown`), "
        "`estimated_arrival_at`, `eta_confidence`, and `explanation`.\n\n"
        "It reports *what* changed, never *why* — it will not infer a reason for a child's "
        "movement."
    ),
    ManaAICapability.SMART_CONTENT_FILTER: (
        "**One resource, one verdict.** Classifies a single URL, domain, QR payload, or APK "
        "against reputation, category, context, and family policy.\n\n"
        "**Send** the required `resource`, plus `notification_context`, `blocked_categories`, "
        "`family_rules`.\n\n"
        "**Returns** `details.decision` (`allow`/`observe`/`warn`/`block`), `category`, "
        "`reputation`, `explanation`.\n\n"
        "The blocking decision is deterministic: a `malicious` reputation yields `block` with a "
        "critical finding **even when the model is unavailable**, so this endpoint stays safe in "
        "degraded mode rather than failing open."
    ),
    ManaAICapability.SCAM_PRIVACY_SHIELD: (
        "**Social engineering, specifically.** Detects fake prizes, fake stores and jobs, spoofed "
        "banking pages, password and document requests, suspicious bots, QR payloads, APK "
        "downloads, and phishing patterns.\n\n"
        "**Send** at least one `notification` or `resource`; neither signal type is individually "
        "mandatory, but a request with both lists empty is invalid.\n\n"
        "**Returns** `details.detected_patterns`, `requested_data_types` (which categories of "
        "personal data are being solicited), and `explanation`.\n\n"
        "Narrower and sharper than `safety-monitor` when you already suspect fraud."
    ),
    ManaAICapability.AI_GAMING_SAFETY: (
        "**Usage metadata only.** Analyzes time spent in AI services and games: duration, night "
        "activity, changes against baseline, limits, and extra-time requests.\n\n"
        "**Send** the required `app_usage`, plus `usage_baselines`, `limits`, `schedules`, "
        "`extra_time_requests`.\n\n"
        "**Returns** `details.ai_service_summary`, `gaming_summary`, `affected_packages`.\n\n"
        "This capability has **no access to chat content or gameplay** and will never imply it "
        "does — it reasons strictly about metadata you supply."
    ),
    ManaAICapability.PARENT_COPILOT: (
        "**Conversational, for the parent.** Answers a parent's free-text question from the family "
        "context you supply and proposes a bounded next-step sequence.\n\n"
        "**Send** the required `message`, plus `safety_events`, `family_rules`, `app_usage`, "
        "`locations`, and `allowed_action_kinds` — that last field is your allowlist, and nothing "
        "outside it can be proposed.\n\n"
        "**Returns** `details.answer` and `suggested_sequence`.\n\n"
        "Proposed actions still require your policy and, where indicated, parent confirmation. "
        "Answer quality tracks the context you pass: with no signals it will say so rather than "
        "speculate."
    ),
    ManaAICapability.CHILD_SAFETY_ASSISTANT: (
        "**Conversational, for the child.** Calm, age-appropriate guidance: explains why something "
        "was blocked or limited, helps check whether a resource is safe, discourages sharing "
        "personal data, and helps ask a parent for support or extra time.\n\n"
        "**Send** the required `message`, plus `current_resource`, `active_rules`, "
        "`current_usage`.\n\n"
        "**Returns** `details.answer`, `explanation`, and `should_contact_parent` — a boolean the "
        "application can act on to offer a parent hand-off.\n\n"
        "Tone follows the `age_band` in `subject`, so set it accurately."
    ),
    ManaAICapability.FAMILY_AGREEMENT: (
        "**Rules, drafted or reviewed.** Produces transparent family rules that balance privacy "
        "against safety and relax gradually with age, or turns a child's request into a clear "
        "proposal for a parent.\n\n"
        "**Send** the required `mode` (`draft`, `review`, or `child_request`) and `preferences`, "
        "plus `current_rules`. `child_request` is required when that mode is selected.\n\n"
        "**Returns** `details.draft_rules` and `request_context`.\n\n"
        "Output is a proposal for humans to accept — the API never activates a rule."
    ),
    ManaAICapability.BEHAVIOUR_ANOMALY: (
        "**Change detection against your baselines.** Explains night usage, usage and notification "
        "shifts, disabled protection, route changes, extra-time changes, and battery or "
        "connectivity anomalies.\n\n"
        "**Send** at least one of `metrics`, `protection_state`, `app_usage`, `locations`, or "
        "`battery`; `usage_baselines` adds comparison context for app usage but is not a signal "
        "on its own. `metrics` already carries current and baseline values.\n\n"
        "**Returns** `details.changed_metrics`, `explanation`, and `diagnosis_made` — which is "
        "always `false`.\n\n"
        "**No diagnosis, ever.** It describes behavioural change and explicitly does not infer "
        "mental-health, medical, or psychological state."
    ),
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
