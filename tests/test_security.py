from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.core.config import Settings, get_settings
from app.main import create_app
from app.schemas.ai import ChatRequest, ChatResponse

_TEST_API_KEY = "test-server-api-key-with-at-least-32-characters"


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
    configure_test_env(monkeypatch, tmp_path / "marketing.db", app_api_key=_TEST_API_KEY)
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
                headers={"Authorization": "Bearer wrong-key"},
                json={"message": "hello"},
            )
            valid_key_response = await client.post(
                "/api/v1/ai/chat",
                headers={"Authorization": f"Bearer {_TEST_API_KEY}"},
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
    with pytest.raises(RuntimeError, match="APP_API_KEY is required"):
        create_app()
    get_settings.cache_clear()


async def test_repeated_authentication_failures_are_throttled_and_valid_key_recovers(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "rate-limit.db", app_api_key=_TEST_API_KEY)
    monkeypatch.setenv("AUTH_FAILURE_LIMIT", "2")
    get_settings.cache_clear()
    app = create_app()

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        first = await client.post(
            "/api/v1/ai/chat",
            headers={"Authorization": "Bearer wrong"},
            json={"message": "hello"},
        )
        throttled = await client.post(
            "/api/v1/ai/chat",
            headers={"Authorization": "Bearer still-wrong"},
            json={"message": "hello"},
        )
        app.state.openai_service = FakeOpenAIService()
        valid = await client.post(
            "/api/v1/ai/chat",
            headers={"Authorization": f"Bearer {_TEST_API_KEY}"},
            json={"message": "hello"},
        )
        after_clear = await client.post(
            "/api/v1/ai/chat",
            headers={"Authorization": "Bearer wrong-again"},
            json={"message": "hello"},
        )

    assert first.status_code == 401
    assert throttled.status_code == 429
    assert int(throttled.headers["Retry-After"]) >= 1
    assert valid.status_code == 200
    assert after_clear.status_code == 401
    get_settings.cache_clear()


async def test_retired_api_key_header_is_rejected(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The product API layer accepts bearer tokens only; X-API-Key must no longer authenticate."""
    configure_test_env(monkeypatch, tmp_path / "retired-header.db", app_api_key=_TEST_API_KEY)
    app = create_app()

    async with app.router.lifespan_context(app):
        app.state.openai_service = FakeOpenAIService()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            legacy = await client.post(
                "/api/v1/ai/chat",
                headers={"X-API-Key": _TEST_API_KEY},
                json={"message": "hello"},
            )
            bearer = await client.post(
                "/api/v1/ai/chat",
                headers={"Authorization": f"Bearer {_TEST_API_KEY}"},
                json={"message": "hello"},
            )

    assert legacy.status_code == 401
    assert legacy.headers["WWW-Authenticate"] == "Bearer"
    assert bearer.status_code == 200
    get_settings.cache_clear()


async def test_authenticated_requests_are_rate_limited(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A valid token still gets a bounded request budget, so a leaked token cannot drain spend."""
    configure_test_env(monkeypatch, tmp_path / "request-budget.db", app_api_key=_TEST_API_KEY)
    monkeypatch.setenv("API_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("API_RATE_LIMIT_WINDOW_SECONDS", "60")
    get_settings.cache_clear()
    app = create_app()

    async with app.router.lifespan_context(app):
        app.state.openai_service = FakeOpenAIService()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            statuses = []
            for _ in range(3):
                response = await client.post(
                    "/api/v1/ai/chat",
                    headers={"Authorization": f"Bearer {_TEST_API_KEY}"},
                    json={"message": "hello"},
                )
                statuses.append(response)

    assert [item.status_code for item in statuses] == [200, 200, 429]
    assert int(statuses[-1].headers["Retry-After"]) >= 1
    assert statuses[-1].json()["detail"] == "Request rate limit exceeded"
    get_settings.cache_clear()


async def test_local_environment_without_token_stays_open(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Local development stays frictionless: no token configured means no auth and no budget."""
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(tmp_path / "local-open.db"))
    monkeypatch.setenv("API_RATE_LIMIT_REQUESTS", "1")
    get_settings.cache_clear()
    app = create_app()

    async with app.router.lifespan_context(app):
        app.state.openai_service = FakeOpenAIService()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            first = await client.post("/api/v1/ai/chat", json={"message": "hello"})
            second = await client.post("/api/v1/ai/chat", json={"message": "hello"})

    assert first.status_code == 200
    assert second.status_code == 200
    get_settings.cache_clear()
