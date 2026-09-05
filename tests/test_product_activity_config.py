from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def base_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "app_env": "local",
        "openai_api_key": "test-openai-key",
        "mana_telegram_auth_enabled": False,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_live_product_activity_requires_both_first_party_sources(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="MANAKIDS_API_USERNAME"):
        base_settings(operation_product_activity_provider="manakids_firebase")

    service_account = tmp_path / "firebase-service-account.json"
    service_account.write_text("{}", encoding="utf-8")
    configured = base_settings(
        operation_product_activity_provider="manakids_firebase",
        manakids_api_username="service-user",
        manakids_api_password="test-password-fixture",
        firebase_project_id="bosstracker-dev",
        firebase_service_account_file=service_account,
    )
    assert configured.operation_product_activity_provider == "manakids_firebase"
    assert configured.firebase_activity_collection == "app_activity_events"


def test_live_product_activity_rejects_insecure_or_missing_files(tmp_path: Path) -> None:
    values = {
        "operation_product_activity_provider": "manakids_firebase",
        "manakids_api_username": "service-user",
        "manakids_api_password": "test-password-fixture",
        "firebase_project_id": "bosstracker-dev",
    }
    with pytest.raises(ValidationError, match="HTTPS origin"):
        base_settings(
            **values,
            manakids_api_base_url="http://api.manakids.test",
            firebase_service_account_file=tmp_path / "missing.json",
        )
    with pytest.raises(ValidationError, match="readable file"):
        base_settings(
            **values,
            firebase_service_account_file=tmp_path / "missing.json",
        )
