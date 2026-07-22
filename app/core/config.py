from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
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
    app_api_key: SecretStr | None = None
    auth_failure_limit: int = Field(default=10, ge=2, le=1_000)
    auth_failure_window_seconds: int = Field(default=60, ge=10, le=86_400)

    mana_telegram_auth_enabled: bool = True
    mana_telegram_bot_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("MANA_TELEGRAM_BOT_TOKEN", "BOT_TOKEN"),
    )
    mana_telegram_bot_username: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z][A-Za-z0-9_]{4,31}$",
    )
    mana_otp_hmac_secret: SecretStr | None = None
    mana_bootstrap_admin_telegram_ids: str = "976835256,51456737"
    mana_otp_ttl_seconds: Literal[60] = 60
    mana_otp_resend_cooldown_seconds: int = Field(default=30, ge=5, le=300)
    mana_otp_max_verify_attempts: int = Field(default=5, ge=3, le=10)
    mana_otp_request_limit_per_user: int = Field(default=5, ge=1, le=100)
    mana_otp_request_limit_per_ip: int = Field(default=20, ge=2, le=1_000)
    mana_otp_verify_limit_per_ip: int = Field(default=30, ge=5, le=2_000)
    mana_otp_global_request_limit: int = Field(default=1_000, ge=20, le=100_000)
    mana_otp_rate_window_seconds: int = Field(default=900, ge=60, le=86_400)
    mana_otp_lockout_failures: int = Field(default=10, ge=5, le=100)
    mana_otp_lockout_seconds: int = Field(default=900, ge=30, le=86_400)
    mana_session_ttl_seconds: int = Field(default=28_800, ge=900, le=604_800)
    mana_trusted_origins: list[str] = Field(default_factory=list)
    mana_auth_test_mode: bool = False
    mana_auth_test_otp_sink_path: Path | None = None
    operation_allow_insecure_dev_headers: bool = False

    openai_api_key: SecretStr
    openai_model: str = "gpt-5.4-nano"
    openai_timeout_seconds: float = Field(default=30.0, gt=0)
    openai_max_output_tokens: int = Field(default=512, ge=16, le=4096)
    openai_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    marketing_database_path: Path = Path("data/manaai.db")
    operation_database_url: str | None = None
    operation_auto_create_schema: bool = True
    operation_scheduler_enabled: bool = False
    operation_scheduler_poll_seconds: float = Field(default=30.0, gt=0, le=300)
    operation_job_timeout_seconds: int = Field(default=900, ge=10, le=86_400)
    operation_data_retention_days: int = Field(default=90, ge=7, le=3_650)
    operation_verification_attempts: int = Field(default=4, ge=1, le=20)
    operation_verification_delay_seconds: float = Field(default=1.0, ge=0, le=60)
    operation_dry_run: bool = True
    operation_global_kill_switch: bool = False
    operation_global_execution_limit_per_day: int = Field(default=20, ge=0, le=10_000)
    operation_agent_execution_limit_per_day: int = Field(default=10, ge=0, le=1_000)
    operation_allow_self_approval: bool = False
    operation_default_actor_id: str = "local-admin"
    operation_default_role: Literal["viewer", "operator", "approver", "admin"] = "viewer"
    operation_ads_provider: Literal["fake_meta", "meta"] = "fake_meta"
    operation_viewer_api_key: SecretStr | None = None
    operation_operator_api_key: SecretStr | None = None
    operation_approver_api_key: SecretStr | None = None
    operation_admin_api_key: SecretStr | None = None
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
    marketing_measurement_stale_after_days: int = Field(default=14, ge=1, le=365)

    meta_graph_base_url: str = "https://graph.facebook.com"
    meta_graph_api_version: str = "v25.0"
    meta_live_mode: Literal["read_only"] = "read_only"
    meta_live_readonly_verify: bool = False
    meta_live_max_requests: int = Field(default=40, ge=1, le=200)
    meta_live_max_duration_seconds: int = Field(default=120, ge=10, le=900)
    meta_live_max_total_retries: int = Field(default=8, ge=0, le=50)
    meta_live_max_pages: int = Field(default=40, ge=1, le=50)
    meta_live_max_accounts: int = Field(default=1, ge=1, le=10)
    meta_live_initial_lookback_days: int = Field(default=7, ge=3, le=14)
    meta_live_evidence_path: Path = Path("data/meta-live-readonly-evidence.json")
    meta_app_id: str | None = None
    meta_business_id: str | None = None
    meta_access_token: SecretStr | None = None
    meta_ad_account_ids: list[str] = Field(default_factory=list)
    meta_request_timeout_seconds: float = Field(default=30.0, gt=0)
    meta_max_retries: int = Field(default=4, ge=0, le=10)
    meta_retry_backoff_seconds: float = Field(default=0.5, ge=0.01, le=30)
    meta_real_writes_enabled: bool = False
    meta_page_limit: int = Field(default=100, ge=1, le=500)
    meta_max_pages: int = Field(default=25, ge=1, le=500)
    meta_business_fields: list[str] = Field(
        default_factory=lambda: [
            "id",
            "name",
        ],
    )
    meta_pixel_fields: list[str] = Field(
        default_factory=lambda: [
            "id",
            "name",
            "owner_business",
            "last_fired_time",
            "is_unavailable",
        ],
    )
    meta_custom_conversion_fields: list[str] = Field(
        default_factory=lambda: [
            "id",
            "name",
            "description",
            "custom_event_type",
            "event_source_type",
            "pixel",
            "rule",
            "default_conversion_value",
            "creation_time",
            "last_fired_time",
            "is_archived",
        ],
    )
    meta_custom_audience_fields: list[str] = Field(
        default_factory=lambda: [
            "id",
            "name",
            "description",
            "subtype",
            "customer_file_source",
            "data_source",
            "delivery_status",
            "operation_status",
            "permission_for_actions",
            "approximate_count",
            "lookalike_spec",
            "retention_days",
            "time_content_updated",
            "time_created",
            "time_updated",
        ],
    )
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
            "timezone_offset_hours_utc",
            "min_daily_budget",
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

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.app_env == "production" and "*" in self.cors_origins:
            raise ValueError("Wildcard CORS origins are forbidden in production")
        if self.meta_real_writes_enabled:
            raise ValueError("META_REAL_WRITES_ENABLED must remain false in read-only Meta mode")
        if self.operation_ads_provider == "meta" and not self.operation_dry_run:
            raise ValueError("OPERATION_DRY_RUN must remain true for the live Meta provider")
        if self.meta_max_retries > self.meta_live_max_total_retries:
            raise ValueError("META_MAX_RETRIES exceeds the live read-only retry budget")
        if self.meta_max_pages > self.meta_live_max_pages:
            raise ValueError("META_MAX_PAGES exceeds the live read-only page budget")
        if self.mana_auth_test_mode:
            if self.app_env != "local":
                raise ValueError("MANA_AUTH_TEST_MODE is allowed only in the local environment")
            if self.mana_auth_test_otp_sink_path is None:
                raise ValueError("MANA_AUTH_TEST_OTP_SINK_PATH is required in test mode")
        elif self.mana_auth_test_otp_sink_path is not None:
            raise ValueError("MANA_AUTH_TEST_OTP_SINK_PATH requires MANA_AUTH_TEST_MODE")
        if self.app_env in {"staging", "production"} and self.mana_telegram_auth_enabled:
            if not self.has_strong_otp_hmac_secret:
                raise ValueError(
                    "MANA_OTP_HMAC_SECRET must contain at least 32 non-placeholder characters",
                )
            if not self.is_telegram_bot_configured:
                raise ValueError(
                    "MANA_TELEGRAM_BOT_TOKEN and MANA_TELEGRAM_BOT_USERNAME are required",
                )
            if not self.mana_trusted_origins:
                raise ValueError("MANA_TRUSTED_ORIGINS is required for browser sessions")
        return self

    @field_validator("mana_bootstrap_admin_telegram_ids")
    @classmethod
    def validate_bootstrap_admin_ids(cls, value: str) -> str:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if not parts or any(not part.isdigit() for part in parts):
            raise ValueError("MANA_BOOTSTRAP_ADMIN_TELEGRAM_IDS must be comma-separated integers")
        ids = [int(part) for part in parts]
        if len(ids) != len(set(ids)):
            raise ValueError("MANA_BOOTSTRAP_ADMIN_TELEGRAM_IDS cannot contain duplicates")
        if any(item <= 0 or item > 9_007_199_254_740_991 for item in ids):
            raise ValueError("Bootstrap Telegram ID is outside the supported range")
        return ",".join(str(item) for item in ids)

    @property
    def is_docs_enabled(self) -> bool:
        return self.app_env != "production"

    @property
    def is_app_api_key_configured(self) -> bool:
        return self.app_api_key is not None and bool(self.app_api_key.get_secret_value())

    @property
    def is_api_auth_required(self) -> bool:
        return self.app_env == "production" or self.is_app_api_key_configured

    @property
    def is_openai_configured(self) -> bool:
        return bool(self.openai_api_key.get_secret_value())

    @property
    def is_meta_configured(self) -> bool:
        return self.meta_access_token is not None and bool(
            self.meta_access_token.get_secret_value(),
        )

    @property
    def bootstrap_admin_telegram_ids(self) -> tuple[int, ...]:
        return tuple(int(part) for part in self.mana_bootstrap_admin_telegram_ids.split(","))

    @property
    def has_strong_otp_hmac_secret(self) -> bool:
        if self.mana_otp_hmac_secret is None:
            return False
        value = self.mana_otp_hmac_secret.get_secret_value()
        normalized = value.strip().lower()
        weak_values = {
            "change-me",
            "changeme",
            "replace_with_secret",
            "replace-with-secret",
        }
        return len(value) >= 32 and normalized not in weak_values and len(set(value)) >= 8

    @property
    def is_telegram_bot_configured(self) -> bool:
        return (
            self.mana_telegram_bot_token is not None
            and bool(self.mana_telegram_bot_token.get_secret_value())
            and self.mana_telegram_bot_username is not None
        )

    @property
    def is_secure_cookie_environment(self) -> bool:
        return self.app_env in {"staging", "production"}

    @property
    def effective_operation_database_url(self) -> str:
        if self.operation_database_url:
            return self.operation_database_url
        return f"sqlite+aiosqlite:///{self.marketing_database_path}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
