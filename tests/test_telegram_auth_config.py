import pytest
from pydantic import ValidationError

from app.core.config import Settings


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "app_env": "production",
        "openai_api_key": "test-openai-key",
        "mana_telegram_auth_enabled": True,
        "MANA_TELEGRAM_BOT_TOKEN": "test-bot-token",
        "mana_telegram_bot_username": "mana_test_bot",
        "mana_otp_hmac_secret": "test-strong-hmac-secret-with-enough-entropy-123456",
        "mana_trusted_origins": ["https://admin.example"],
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_production_requires_strong_complete_telegram_configuration() -> None:
    with pytest.raises(ValidationError, match="MANA_OTP_HMAC_SECRET"):
        production_settings(mana_otp_hmac_secret=None)
    with pytest.raises(ValidationError, match="MANA_OTP_HMAC_SECRET"):
        production_settings(mana_otp_hmac_secret="change-me")
    with pytest.raises(ValidationError, match="MANA_TELEGRAM_BOT_TOKEN"):
        production_settings(MANA_TELEGRAM_BOT_TOKEN=None)
    with pytest.raises(ValidationError, match="MANA_TRUSTED_ORIGINS"):
        production_settings(mana_trusted_origins=[])


def test_test_sender_mode_is_local_only_and_requires_an_explicit_sink() -> None:
    with pytest.raises(ValidationError, match="allowed only in the local"):
        production_settings(
            mana_auth_test_mode=True,
            mana_auth_test_otp_sink_path="/tmp/test-only-otp-sink",
        )
    with pytest.raises(ValidationError, match="MANA_AUTH_TEST_OTP_SINK_PATH is required"):
        Settings(
            _env_file=None,
            app_env="local",
            openai_api_key="test-openai-key",
            mana_auth_test_mode=True,
            mana_auth_test_otp_sink_path=None,
        )


def test_bootstrap_ids_and_fixed_security_ttls_are_typed() -> None:
    settings = production_settings()
    assert settings.bootstrap_admin_telegram_ids == (976835256, 51456737)
    assert settings.mana_otp_ttl_seconds == 60
    assert settings.mana_session_ttl_seconds == 28_800
    with pytest.raises(ValidationError):
        production_settings(mana_otp_ttl_seconds=61)
    with pytest.raises(ValidationError, match="cannot contain duplicates"):
        production_settings(mana_bootstrap_admin_telegram_ids="976835256,976835256")
