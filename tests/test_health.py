from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app


def configure_test_env(monkeypatch: MonkeyPatch, database_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(database_path))
    get_settings.cache_clear()


async def test_liveness_endpoint(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db")
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/v1/health/live")
        request_id_response = await client.get(
            "/api/v1/health/live",
            headers={"X-Request-ID": "test-request-id"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]
    assert float(response.headers["X-Process-Time-Ms"]) >= 0
    assert request_id_response.status_code == 200
    assert request_id_response.headers["X-Request-ID"] == "test-request-id"
    get_settings.cache_clear()
