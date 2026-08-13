import re
import tomllib
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.mana_ai.application.service import ManaAIAnalysisService
from app.mana_ai.domain.enums import AnalysisVerdict, ManaAICapability
from app.mana_ai.domain.requests import ManaAIRequest
from app.mana_ai.domain.responses import CheckResult, FindingDraft, ModelAnalysis
from app.product_ai_main import create_app
from tests.mana_ai_fixtures import NOW, details_for, request_for


class FixedClock:
    def now(self) -> datetime:
        return NOW


class StandaloneGateway:
    @property
    def model_name(self) -> str:
        return "fake-model"

    async def analyze(
        self,
        request: ManaAIRequest,
        *,
        deterministic_findings: list[FindingDraft],
        required_checks: list[CheckResult],
    ) -> ModelAnalysis:
        del deterministic_findings, required_checks
        return ModelAnalysis(
            verdict=AnalysisVerdict.NO_RISK_DETECTED,
            summary="No risk was detected in the available signals.",
            details=details_for(request.input.capability),
        )


def configure_test_env(monkeypatch: MonkeyPatch, database_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MARKETING_DATABASE_PATH", str(database_path))
    get_settings.cache_clear()


async def test_standalone_runtime_has_no_database_or_operation_services(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "must-not-exist.db"
    configure_test_env(monkeypatch, database_path)
    app = create_app()

    async with app.router.lifespan_context(app):
        state = vars(app.state)["_state"]
        assert "operation_database" not in state
        assert "marketing_repository" not in state
        assert "admin_auth_repository" not in state
        assert not database_path.exists()

    get_settings.cache_clear()


async def test_standalone_runtime_serves_only_health_and_mana_ai(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_test_env(monkeypatch, tmp_path / "must-not-exist.db")
    app = create_app()

    async with app.router.lifespan_context(app):
        app.state.mana_ai_analysis_service = ManaAIAnalysisService(
            gateway=StandaloneGateway(),
            clock=FixedClock(),
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            health = await client.get("/api/v1/health/live")
            analysis = await client.post(
                "/api/v1/mana-ai/parent-copilot",
                json=request_for(ManaAICapability.PARENT_COPILOT).model_dump(mode="json"),
            )
            operation = await client.get("/api/v1/admin/operation/dashboard")

    assert health.status_code == 200
    assert analysis.status_code == 200
    assert operation.status_code == 404
    get_settings.cache_clear()


def test_standalone_production_fails_fast_without_api_key(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MANA_TELEGRAM_AUTH_ENABLED", "false")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="APP_API_KEY is required"):
        create_app()

    get_settings.cache_clear()


def test_standalone_production_fails_fast_without_openai_key(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_API_KEY", "test-internal-api-key-with-enough-entropy-123456")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("MANA_TELEGRAM_AUTH_ENABLED", "false")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is required"):
        create_app()

    get_settings.cache_clear()


def test_standalone_production_rejects_weak_api_key(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_API_KEY", "too-short")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MANA_TELEGRAM_AUTH_ENABLED", "false")
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match="at least 32 characters"):
        create_app()

    get_settings.cache_clear()


async def test_standalone_production_secures_ai_routes_and_hides_docs(
    monkeypatch: MonkeyPatch,
) -> None:
    api_key = "test-internal-api-key-with-enough-entropy-123456"
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_API_KEY", api_key)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MANA_TELEGRAM_AUTH_ENABLED", "false")
    get_settings.cache_clear()
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        health = await client.get("/api/v1/health/live")
        unauthenticated = await client.get("/api/v1/mana-ai/capabilities")
        authenticated = await client.get(
            "/api/v1/mana-ai/capabilities",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        docs = await client.get("/docs")
        openapi = await client.get("/openapi.json")

    assert health.status_code == 200
    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
    assert docs.status_code == 404
    assert openapi.status_code == 404
    get_settings.cache_clear()


async def test_standalone_rejects_oversized_request_before_validation(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MANA_AI_MAX_REQUEST_BODY_BYTES", "16384")
    get_settings.cache_clear()
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/v1/mana-ai/parent-copilot",
            content=b"x" * 16_385,
            headers={"Content-Type": "application/json"},
        )
        chunked_response = await client.post(
            "/api/v1/mana-ai/parent-copilot",
            content=_oversized_chunks(),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body is too large"}
    assert chunked_response.status_code == 413
    assert chunked_response.json() == {"detail": "Request body is too large"}
    get_settings.cache_clear()


async def _oversized_chunks() -> AsyncIterator[bytes]:
    yield b"x" * 10_000
    yield b"x" * 10_000


def test_standalone_lock_contains_exact_direct_dependency_versions() -> None:
    root = Path(__file__).resolve().parents[1]
    configuration = tomllib.loads((root / "pyproject.toml").read_text())
    lock_lines = (root / "requirements.mana-ai.lock").read_text().splitlines()
    locked = {
        _normalized_package_name(name): version
        for line in lock_lines
        if line and not line.startswith("#")
        for name, version in [line.split("==", maxsplit=1)]
    }

    for dependency in configuration["project"]["dependencies"]:
        name_with_extras, version = dependency.split("==", maxsplit=1)
        name = name_with_extras.split("[", maxsplit=1)[0]
        assert locked[_normalized_package_name(name)] == version


def _normalized_package_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()
