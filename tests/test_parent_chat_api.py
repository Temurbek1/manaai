from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from pytest import MonkeyPatch

from app import product_ai_main
from app.core.config import Settings, get_settings
from tests.test_parent_chat import make_service

BACKEND_TOKEN = "synthetic-backend-only-api-key-for-parent-chat"
HEADERS = {"Authorization": f"Bearer {BACKEND_TOKEN}"}


async def test_backend_auth_required_and_get_is_local_only(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configuration = Settings(
        _env_file=None,
        openai_api_key=SecretStr("unit-openai"),
        app_api_key=SecretStr(BACKEND_TOKEN),
    )
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: configuration)
    app = product_ai_main.create_app()
    app.dependency_overrides[get_settings] = lambda: configuration
    service, model, children = await make_service(tmp_path / "chat.db")
    app.state.parent_chat_service = service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unauthorized = await client.get("/api/v1/mana-ai/chat?parent_id=123")
        assert unauthorized.status_code == 401
        malformed = await client.get(
            "/api/v1/mana-ai/chat?parent_id=123",
            headers=[(b"Authorization", b"Bearer \xff")],
        )
        assert malformed.status_code == 401
        history = await client.get("/api/v1/mana-ai/chat?parent_id=123", headers=HEADERS)
        assert history.status_code == 200
        assert history.headers["cache-control"] == "no-store"
        assert history.json()["messages"] == []
        assert model.calls == children.calls == 0
        request = {"parent_id": "123", "request_id": str(uuid4()), "message": "Salom!"}
        sent = await client.post("/api/v1/mana-ai/chat", headers=HEADERS, json=request)
        assert sent.status_code == 200
        assert sent.json()["answer"] == "Synthetic answer"
        assert sent.json()["quota"]["used_tokens"] == 150
        replay = await client.post("/api/v1/mana-ai/chat", headers=HEADERS, json=request)
        assert replay.json() == sent.json()
        history = await client.get("/api/v1/mana-ai/chat?parent_id=123", headers=HEADERS)
        assert len(history.json()["messages"]) == 2
        assert history.json()["quota"]["used_tokens"] == 150
        assert (await client.get("/api/v1/mana-ai/chat?parent_id=456", headers=HEADERS)).json()[
            "messages"
        ] == []
        for change in (
            {"chat_id": "another"},
            {"message": "   "},
            {"parent_id": "0123"},
            {"parent_id": "123/../../456"},
            {"message": "x" * 2001},
        ):
            invalid = await client.post(
                "/api/v1/mana-ai/chat", headers=HEADERS, json=request | change
            )
            assert invalid.status_code == 422
    assert model.calls == children.calls == 1


async def test_disabled_chat_does_not_initialize_storage_or_provider(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configuration = Settings(
        _env_file=None,
        openai_api_key=SecretStr("unit-openai"),
        app_api_key=SecretStr(BACKEND_TOKEN),
        mana_parent_chat_database_path=tmp_path / "not-created.db",
    )
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: configuration)
    app = product_ai_main.create_app()
    app.dependency_overrides[get_settings] = lambda: configuration
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get("/api/v1/mana-ai/chat?parent_id=123", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "parent_chat_disabled"
    assert not configuration.mana_parent_chat_database_path.exists()


@pytest.mark.parametrize(
    "change",
    [
        {"app_api_key": None},
        {"app_api_key": SecretStr("weak")},
        {"mana_parent_chat_timezone": "not-a-timezone"},
        {"mana_parent_chat_database_path": Path(":memory:")},
    ],
)
def test_enabled_chat_requires_explicit_safe_configuration(change: dict[str, object]) -> None:
    from pydantic import ValidationError

    raw: dict[str, object] = {
        "openai_api_key": "unit-openai",
        "app_api_key": BACKEND_TOKEN,
        "mana_parent_chat_enabled": True,
        "manakids_api_username": "unit-backend",
        "manakids_api_password": "unit-secret",
    }
    with pytest.raises(ValidationError):
        Settings.model_validate(raw | change)


async def test_enabled_runtime_wires_chat_and_restarts_without_losing_history(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    from app.services import parent_chat_runtime as runtime_module
    from tests.test_parent_chat import Children, Model

    class RuntimeModel(Model):
        async def close(self) -> None:
            pass

    configuration = Settings(
        _env_file=None,
        openai_api_key=SecretStr("unit-openai"),
        app_api_key=SecretStr(BACKEND_TOKEN),
        mana_parent_chat_enabled=True,
        mana_parent_chat_database_path=tmp_path / "persistent.db",
        manakids_api_username="unit-backend",
        manakids_api_password=SecretStr("unit-backend"),
    )
    model, source = RuntimeModel(), Children()
    monkeypatch.setattr(runtime_module, "OpenAIParentChatModel", lambda settings: model)
    monkeypatch.setattr(runtime_module, "ManakidsChatChildrenSource", lambda **kwargs: source)
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: configuration)
    original = {"parent_id": "123", "request_id": str(uuid4()), "message": "Salom!"}
    for _ in range(2):
        app = product_ai_main.create_app()
        app.dependency_overrides[get_settings] = lambda: configuration
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            sent = await client.post("/api/v1/mana-ai/chat", json=original, headers=HEADERS)
            assert sent.status_code == 200
            read = await client.get("/api/v1/mana-ai/chat?parent_id=123", headers=HEADERS)
            assert len(read.json()["messages"]) == 2
    assert model.calls == source.calls == 1


@pytest.mark.parametrize(
    "observation",
    [
        {"child_id": 1, "observed_at": "2026-10-16T12:00:00Z", "battery_percent": 101},
        {"child_id": 1, "observed_at": "2026-10-16T12:00:00Z", "screen_time_minutes": 60},
        {
            "child_id": 1,
            "observed_at": "2026-10-16T12:00:00Z",
            "screen_time_minutes": 60,
            "activity_period_start": "2026-10-16T11:59:00Z",
            "activity_period_end": "2026-10-16T12:00:00Z",
        },
    ],
)
def test_backend_observations_require_minimized_valid_dated_facts(
    observation: dict[str, object],
) -> None:
    from pydantic import ValidationError

    from app.mana_ai.domain.chat import ChildChatObservation

    with pytest.raises(ValidationError):
        ChildChatObservation.model_validate(observation)
