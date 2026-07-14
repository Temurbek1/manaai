from functools import lru_cache
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

    @property
    def is_docs_enabled(self) -> bool:
        return self.app_env != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
