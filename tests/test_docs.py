from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app


async def test_swagger_docs_enabled_outside_production(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("APP_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(tmp_path / "marketing.db"))
    get_settings.cache_clear()
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        docs_response = await client.get("/docs")
        schema_response = await client.get("/openapi.json")

    assert docs_response.status_code == 200
    assert schema_response.status_code == 200
    schema = schema_response.json()
    assert schema["info"]["title"] == "manaai-api"
    assert {tag["name"] for tag in schema["tags"]} == {"ai", "health", "marketing"}
    assert schema["components"]["securitySchemes"]["APIKeyHeader"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    get_settings.cache_clear()


async def test_swagger_docs_disabled_in_production(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("APP_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(tmp_path / "marketing.db"))
    get_settings.cache_clear()
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        docs_response = await client.get("/docs")
        schema_response = await client.get("/openapi.json")

    assert docs_response.status_code == 404
    assert schema_response.status_code == 404
    get_settings.cache_clear()
