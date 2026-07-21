from typing import Any

API_DESCRIPTION = """
ManaAI API is the backend AI integration layer for application features.

The current public surface includes health checks and test OpenAI-powered
endpoints. OpenAI model selection remains configurable through environment
variables so deployments can change pricing/performance tradeoffs without code
changes.
"""

OPENAPI_TAGS: list[dict[str, Any]] = [
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
