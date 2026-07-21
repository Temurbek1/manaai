from pathlib import Path

from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.schemas.ai import ChatRequest, ChatResponse


class FakeOpenAIService:
    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(answer=f"echo: {request.message}", model="fake-model")


def configure_test_env(
    monkeypatch: MonkeyPatch,
    database_path: Path,
    *,
    app_api_key: str | None,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(database_path))
    if app_api_key is None:
        monkeypatch.delenv("APP_API_KEY", raising=False)
    else:
        monkeypatch.setenv("APP_API_KEY", app_api_key)
    get_settings.cache_clear()


async def test_api_key_required_for_protected_routes(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db", app_api_key="server-key")
    app = create_app()

    async with app.router.lifespan_context(app):
        app.state.openai_service = FakeOpenAIService()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            health_response = await client.get("/api/v1/health/live")
            missing_key_response = await client.post("/api/v1/ai/chat", json={"message": "hello"})
            wrong_key_response = await client.post(
                "/api/v1/ai/chat",
                headers={"X-API-Key": "wrong-key"},
                json={"message": "hello"},
            )
            valid_key_response = await client.post(
                "/api/v1/ai/chat",
                headers={"X-API-Key": "server-key"},
                json={"message": "hello"},
            )

    assert health_response.status_code == 200
    assert missing_key_response.status_code == 401
    assert missing_key_response.headers["X-Request-ID"]
    assert float(missing_key_response.headers["X-Process-Time-Ms"]) >= 0
    assert wrong_key_response.status_code == 401
    assert valid_key_response.status_code == 200
    assert valid_key_response.json() == {"answer": "echo: hello", "model": "fake-model"}
    get_settings.cache_clear()


async def test_production_api_auth_requires_configured_key(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "marketing.db", app_api_key=None)
    app = create_app()

    async with app.router.lifespan_context(app):
        app.state.openai_service = FakeOpenAIService()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post("/api/v1/ai/chat", json={"message": "hello"})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "APP_API_KEY must be configured when API authentication is required"
    )
    get_settings.cache_clear()
