from app.core.config import Settings


def validate_production_api_settings(settings: Settings) -> None:
    """Fail before startup when the public production API cannot authenticate safely."""
    if settings.app_env != "production":
        return
    if not settings.is_app_api_key_configured or settings.app_api_key is None:
        raise RuntimeError("APP_API_KEY is required for the production API")
    if len(settings.app_api_key.get_secret_value()) < 32:
        raise RuntimeError("APP_API_KEY must contain at least 32 characters in production")
    if not settings.is_openai_configured:
        raise RuntimeError("OPENAI_API_KEY is required for the production API")
