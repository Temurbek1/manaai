from typing import Any

API_DESCRIPTION = """
ManaAI exposes physically separated product-inference and internal operation
bounded contexts. The operation API manages typed agents, schedules, runs,
evidence, approvals, guarded actions, verification, reports, and audit events.
Legacy product and marketing endpoints remain backward compatible. Provider and
OpenAI model selection remain configurable rather than embedded in domain logic.
"""

OPENAPI_TAGS: list[dict[str, Any]] = [
    {
        "name": "mana-chat",
        "description": "Recommended single-chat integration: submit a message, "
        "observe its status, read history. Child-Safety reviews before Parent-Touch responds.",
    },
    {
        "name": "mana-chat-compatibility",
        "description": "Existing synchronous contracts retained "
        "without behavior changes. New integrations should not mix different send protocols.",
    },
    {
        "name": "mana-coordination",
        "description": "Trusted backend specialist coordination and "
        "diagnostics, not additional chats or mobile UI operations.",
    },
    {
        "name": "mana-child-safety",
        "description": "Dated child-data ingestion and saved internal "
        "assessments. Results reach the same chat through Parent-Touch.",
    },
    {
        "name": "mana-conversion",
        "description": "Trusted backend account events, offer attribution "
        "and separately gated non-paid grants. Never model-selected payment tools.",
    },
    {
        "name": "mana-notifications",
        "description": "Trusted backend contact preferences and saved "
        "push observations. Provider queueing does not prove delivery.",
    },
    {
        "name": "health",
        "description": "Service liveness and readiness probes for orchestration.",
    },
    {
        "name": "ai",
        "description": "AI integration endpoints backed by the configured OpenAI model.",
        "externalDocs": {
            "description": "OpenAI API documentation",
            "url": "https://platform.openai.com/docs",
        },
    },
    {
        "name": "marketing",
        "description": (
            "Meta Marketing API sync, raw marketing data preservation, deterministic KPIs, "
            "and structured AI analytics outputs."
        ),
        "externalDocs": {
            "description": "Meta Marketing API documentation",
            "url": "https://developers.facebook.com/documentation/ads-commerce/marketing-api",
        },
    },
    {
        "name": "mana-ai",
        "description": (
            "Read-only request/response product inference for family safety, digital wellbeing, "
            "location, content protection, assistants, agreements, and behavior anomalies. "
            "Action proposals are never executed by this API."
        ),
    },
    {
        "name": "audio-moderation",
        "description": (
            "Server-to-server intake for private 360REC audio safety moderation jobs and "
            "asynchronous one-time callbacks."
        ),
    },
    {
        "name": "operation-admin",
        "description": "RBAC-protected internal operational-agent management and audit API.",
    },
]

SWAGGER_UI_PARAMETERS: dict[str, Any] = {
    "defaultModelsExpandDepth": -1,
    "displayRequestDuration": True,
    "docExpansion": "none",
    "filter": True,
    "operationsSorter": "method",
    "persistAuthorization": False,
    "tagsSorter": "alpha",
}
