from enum import StrEnum


class ManaAICapability(StrEnum):
    SAFETY_MONITOR = "safety_monitor"
    FAMILY_DIGEST = "family_digest"
    ADAPTIVE_SCREEN_TIME = "adaptive_screen_time"
    LOCATION_INTELLIGENCE = "location_intelligence"
    SMART_CONTENT_FILTER = "smart_content_filter"
    SCAM_PRIVACY_SHIELD = "scam_privacy_shield"
    AI_GAMING_SAFETY = "ai_gaming_safety"
    PARENT_COPILOT = "parent_copilot"
    CHILD_SAFETY_ASSISTANT = "child_safety_assistant"
    FAMILY_AGREEMENT = "family_agreement"
    BEHAVIOUR_ANOMALY = "behaviour_anomaly"


class RiskLevel(StrEnum):
    INFORMATIONAL = "informational"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AnalysisVerdict(StrEnum):
    NO_RISK_DETECTED = "no_risk_detected"
    OBSERVE = "observe"
    WARN = "warn"
    ALERT = "alert"
    BLOCK = "block"
    INSUFFICIENT_DATA = "insufficient_data"


class AnalysisStatus(StrEnum):
    COMPLETED = "completed"
    DEGRADED = "degraded"


class CheckStatus(StrEnum):
    RISK_DETECTED = "risk_detected"
    NO_RISK_DETECTED = "no_risk_detected"
    INSUFFICIENT_DATA = "insufficient_data"
    NOT_APPLICABLE = "not_applicable"


class FindingCategory(StrEnum):
    BULLYING = "bullying"
    THREAT = "threat"
    PRESSURE_OR_MANIPULATION = "pressure_or_manipulation"
    PERSONAL_DATA_REQUEST = "personal_data_request"
    SCAM = "scam"
    PHISHING = "phishing"
    UNSAFE_LINK_OR_SITE = "unsafe_link_or_site"
    UNSAFE_CONTENT = "unsafe_content"
    SUSPICIOUS_DOWNLOAD = "suspicious_download"
    PROTECTION_DISABLED = "protection_disabled"
    SCREEN_TIME_CHANGE = "screen_time_change"
    NIGHT_ACTIVITY = "night_activity"
    LIMIT_EXCEEDED = "limit_exceeded"
    APP_USAGE_CHANGE = "app_usage_change"
    WEBSITE_USAGE_CHANGE = "website_usage_change"
    LOCATION_DEVIATION = "location_deviation"
    DELAYED_ARRIVAL = "delayed_arrival"
    LONG_STOP = "long_stop"
    UNUSUAL_SPEED = "unusual_speed"
    LOCATION_SPOOFING = "location_spoofing"
    BATTERY_ANOMALY = "battery_anomaly"
    DEVICE_OFFLINE = "device_offline"
    EXTRA_TIME_REQUEST_CHANGE = "extra_time_request_change"
    SUDDEN_SILENCE = "sudden_silence"
    POSITIVE_CHANGE = "positive_change"
    FAMILY_RULE_CONFLICT = "family_rule_conflict"
    INFORMATIONAL = "informational"


class SignalSource(StrEnum):
    APP_USAGE = "app_usage"
    NOTIFICATION_PREVIEW = "notification_preview"
    WEBSITE = "website"
    LINK_CHECK = "link_check"
    QR_CHECK = "qr_check"
    LOCATION = "location"
    BATTERY = "battery"
    CONNECTIVITY = "connectivity"
    PROTECTION_STATE = "protection_state"
    FAMILY_RULE = "family_rule"
    SAFETY_EVENT = "safety_event"
    USER_MESSAGE = "user_message"
    APPLICATION = "application"


class AppCategory(StrEnum):
    EDUCATION = "education"
    MESSAGING = "messaging"
    SOCIAL = "social"
    GAME = "game"
    AI_SERVICE = "ai_service"
    VIDEO = "video"
    BROWSER = "browser"
    PRODUCTIVITY = "productivity"
    OTHER = "other"
    UNKNOWN = "unknown"


class ResourceKind(StrEnum):
    URL = "url"
    DOMAIN = "domain"
    QR_CODE = "qr_code"
    APK = "apk"


class ReputationVerdict(StrEnum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    MALICIOUS = "malicious"
    UNKNOWN = "unknown"


class LocationSource(StrEnum):
    PHONE = "phone"
    MANA_TRACKER = "mana_tracker"


class AgeBand(StrEnum):
    UNDER_7 = "under_7"
    AGE_7_12 = "age_7_12"
    AGE_13_15 = "age_13_15"
    AGE_16_17 = "age_16_17"


class ScheduleKind(StrEnum):
    SLEEP = "sleep"
    SCHOOL = "school"
    EXAM = "exam"
    STUDY = "study"
    FREE_TIME = "free_time"


class AgreementMode(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    CHILD_REQUEST = "child_request"


class ActionKind(StrEnum):
    NOTIFY_PARENT = "notify_parent"
    WARN_CHILD = "warn_child"
    REQUEST_CHECK_IN = "request_check_in"
    PROPOSE_LIMIT_CHANGE = "propose_limit_change"
    PROPOSE_STUDY_MODE = "propose_study_mode"
    PROPOSE_GEOFENCE = "propose_geofence"
    PROPOSE_APP_RESTRICTION = "propose_app_restriction"
    PROPOSE_TEMPORARY_ACCESS = "propose_temporary_access"
    GENERATE_FAMILY_REPORT = "generate_family_report"
    PROPOSE_RESOURCE_BLOCK = "propose_resource_block"
    CONTACT_PARENT = "contact_parent"
    SUBMIT_EXTRA_TIME_REQUEST = "submit_extra_time_request"
    SUBMIT_INCIDENT_REPORT = "submit_incident_report"
    PROPOSE_AGREEMENT_UPDATE = "propose_agreement_update"


class ExecutionPolicy(StrEnum):
    INFORMATION_ONLY = "information_only"
    APPLICATION_POLICY_REQUIRED = "application_policy_required"
    PARENT_CONFIRMATION_REQUIRED = "parent_confirmation_required"
