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


def test_live_ga4_activity_requires_property_and_dedicated_credentials(tmp_path: Path) -> None:
    values = {
        "operation_product_activity_provider": "manakids_ga4",
        "manakids_api_username": "service-user",
        "manakids_api_password": "test-password-fixture",
    }
    with pytest.raises(ValidationError, match="GA4_PROPERTY_ID"):
        base_settings(**values)

    service_account = tmp_path / "ga4-service-account.json"
    service_account.write_text("{}", encoding="utf-8")
    with pytest.raises(ValidationError, match="GA4_API_BASE_URL"):
        base_settings(
            **values,
            ga4_property_id="123456789",
            ga4_service_account_file=service_account,
            ga4_api_base_url="https://user:secret@analyticsdata.googleapis.test/v1beta",
        )
    configured = base_settings(
        **values,
        ga4_property_id="123456789",
        ga4_service_account_file=service_account,
    )
    assert configured.operation_product_activity_provider == "manakids_ga4"
    assert configured.ga4_dimension_limit == 50


def test_operational_firestore_requires_live_provider_and_credentials(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="requires a live product activity provider"):
        base_settings(firebase_operational_telemetry_enabled=True)

    service_account = tmp_path / "firebase-service-account.json"
    service_account.write_text("{}", encoding="utf-8")
    configured = base_settings(
        operation_product_activity_provider="manakids_ga4",
        manakids_api_username="service-user",
        manakids_api_password="test-password-fixture",
        ga4_property_id="123456789",
        ga4_service_account_file=service_account,
        firebase_operational_telemetry_enabled=True,
        firebase_project_id="bosstracker-dev",
        firebase_service_account_file=service_account,
    )
    assert configured.firebase_operational_telemetry_enabled is True
