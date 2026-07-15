from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app


async def test_swagger_docs_enabled_outside_production() -> None:
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
    assert {tag["name"] for tag in schema["tags"]} == {"ai", "health"}


async def test_swagger_docs_disabled_in_production(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
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
