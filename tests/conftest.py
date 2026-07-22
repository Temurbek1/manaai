import pytest
from pytest import FixtureRequest, MonkeyPatch


@pytest.fixture(autouse=True)
def isolate_local_secrets(monkeypatch: MonkeyPatch, request: FixtureRequest) -> None:
    """Prevent an ignored developer .env from changing test behavior."""

    if request.node.get_closest_marker("live_meta") is not None:
        return
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("META_ACCESS_TOKEN", "")
    monkeypatch.setenv("OPERATION_ADS_PROVIDER", "fake_meta")
    monkeypatch.setenv("META_LIVE_READONLY_VERIFY", "0")
