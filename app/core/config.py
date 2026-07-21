from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["local", "development", "staging", "production"] = "local"
    app_name: str = "manaai-api"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=list)

    openai_api_key: SecretStr
    openai_model: str = "gpt-5.4-nano"
    openai_timeout_seconds: float = Field(default=30.0, gt=0)
    openai_max_output_tokens: int = Field(default=512, ge=16, le=4096)
    openai_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    marketing_database_path: Path = Path("data/manaai.db")
    marketing_conversion_action_types: list[str] = Field(
        default_factory=lambda: [
            "purchase",
            "lead",
            "complete_registration",
            "offsite_conversion.fb_pixel_purchase",
            "onsite_conversion.lead_grouped",
        ],
    )
    marketing_value_action_types: list[str] = Field(
        default_factory=lambda: [
            "purchase",
            "offsite_conversion.fb_pixel_purchase",
        ],
    )

    meta_graph_base_url: str = "https://graph.facebook.com"
    meta_graph_api_version: str = "v25.0"
    meta_app_id: str | None = None
    meta_business_id: str | None = None
    meta_access_token: SecretStr | None = None
    meta_ad_account_ids: list[str] = Field(default_factory=list)
    meta_request_timeout_seconds: float = Field(default=30.0, gt=0)
    meta_page_limit: int = Field(default=100, ge=1, le=500)
    meta_max_pages: int = Field(default=25, ge=1, le=500)
    meta_campaign_fields: list[str] = Field(
        default_factory=lambda: [
            "id",
            "name",
            "objective",
            "status",
            "effective_status",
            "created_time",
            "updated_time",
            "start_time",
            "stop_time",
            "daily_budget",
            "lifetime_budget",
            "bid_strategy",
        ],
    )
    meta_adset_fields: list[str] = Field(
        default_factory=lambda: [
            "id",
            "name",
            "campaign_id",
            "status",
            "effective_status",
            "optimization_goal",
            "billing_event",
            "bid_strategy",
            "daily_budget",
            "lifetime_budget",
            "targeting",
            "created_time",
            "updated_time",
            "start_time",
            "end_time",
        ],
    )
    meta_ad_fields: list[str] = Field(
        default_factory=lambda: [
            "id",
            "name",
            "campaign_id",
            "adset_id",
            "creative",
            "status",
            "effective_status",
            "created_time",
            "updated_time",
        ],
    )
    meta_creative_fields: list[str] = Field(
        default_factory=lambda: [
            "id",
            "name",
            "title",
            "body",
            "object_type",
            "object_url",
            "call_to_action_type",
            "thumbnail_url",
            "image_url",
            "object_story_id",
            "effective_object_story_id",
            "object_story_spec",
            "asset_feed_spec",
            "instagram_permalink_url",
        ],
    )
    meta_ad_account_fields: list[str] = Field(
        default_factory=lambda: [
            "id",
            "name",
            "currency",
            "timezone_name",
            "account_status",
            "business",
        ],
    )
    meta_insights_fields: list[str] = Field(
        default_factory=lambda: [
            "account_id",
            "account_name",
            "campaign_id",
            "campaign_name",
            "adset_id",
            "adset_name",
            "ad_id",
            "ad_name",
            "date_start",
            "date_stop",
            "spend",
            "impressions",
            "reach",
            "clicks",
            "inline_link_clicks",
            "actions",
            "action_values",
        ],
    )
    meta_action_attribution_windows: list[str] = Field(
        default_factory=lambda: ["1d_click", "7d_click"],
    )

    @property
    def is_docs_enabled(self) -> bool:
        return self.app_env != "production"

    @property
    def is_openai_configured(self) -> bool:
        return bool(self.openai_api_key.get_secret_value())

    @property
    def is_meta_configured(self) -> bool:
        return self.meta_access_token is not None and bool(
            self.meta_access_token.get_secret_value(),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
