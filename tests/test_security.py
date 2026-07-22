from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.core.config import Settings, get_settings
from app.main import create_app
from app.schemas.ai import ChatRequest, ChatResponse


class FakeOpenAIService:
    async def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(answer=f"echo: {request.message}", model="fake-model")


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="Wildcard CORS origins"):
        Settings(
            _env_file=None,
            app_env="production",
            openai_api_key="test-openai-key",
            cors_origins=["*"],
        )


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
        monkeypatch.setenv("APP_API_KEY", "")
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
    assert missing_key_response.headers["X-Content-Type-Options"] == "nosniff"
    assert missing_key_response.headers["X-Frame-Options"] == "DENY"
    assert missing_key_response.headers["Referrer-Policy"] == "no-referrer"
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


async def test_repeated_authentication_failures_are_throttled_and_valid_key_recovers(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "rate-limit.db", app_api_key="server-key")
    monkeypatch.setenv("AUTH_FAILURE_LIMIT", "2")
    get_settings.cache_clear()
    app = create_app()

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        first = await client.post(
            "/api/v1/ai/chat",
            headers={"X-API-Key": "wrong"},
            json={"message": "hello"},
        )
        throttled = await client.post(
            "/api/v1/ai/chat",
            headers={"X-API-Key": "still-wrong"},
            json={"message": "hello"},
        )
        app.state.openai_service = FakeOpenAIService()
        valid = await client.post(
            "/api/v1/ai/chat",
            headers={"X-API-Key": "server-key"},
            json={"message": "hello"},
        )
        after_clear = await client.post(
            "/api/v1/ai/chat",
            headers={"X-API-Key": "wrong-again"},
            json={"message": "hello"},
        )

    assert first.status_code == 401
    assert throttled.status_code == 429
    assert int(throttled.headers["Retry-After"]) >= 1
    assert valid.status_code == 200
    assert after_clear.status_code == 401
    get_settings.cache_clear()
