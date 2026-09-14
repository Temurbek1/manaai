import pytest
from pytest import FixtureRequest, MonkeyPatch


@pytest.fixture(autouse=True)
def isolate_local_secrets(monkeypatch: MonkeyPatch, request: FixtureRequest) -> None:
    """Prevent an ignored developer .env from changing test behavior."""

    if (
        request.node.get_closest_marker("live_meta") is not None
        or request.node.get_closest_marker("live_product_activity") is not None
    ):
        return
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("META_ACCESS_TOKEN", "")
    monkeypatch.setenv("OPERATION_ADS_PROVIDER", "fake_meta")
    monkeypatch.setenv("OPERATION_PRODUCT_ACTIVITY_PROVIDER", "fake")
    monkeypatch.setenv("MANA_TELEGRAM_AUTH_ENABLED", "0")
    monkeypatch.setenv("OPERATION_ALLOW_INSECURE_DEV_HEADERS", "1")
    monkeypatch.setenv("META_LIVE_READONLY_VERIFY", "0")
    monkeypatch.setenv("AUDIO_MODERATION_ENABLED", "0")
    monkeypatch.setenv("AI_AUDIO_MODERATION_AUTH_TOKEN", "")
