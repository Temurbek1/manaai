"""Actual product lifespan and unchanged chat API, all upstreams fictional."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from app import product_ai_main
from app.core.config import Settings, get_settings
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services import parent_chat_runtime as runtime_module
from app.services.child_source_model import OpenAIChildSourceModel
from app.services.family_source_runtime import FamilySourceRuntime
from tests.test_child_app_usage import Usage
from tests.test_child_source_model import NOW
from tests.test_family_sources import Clock
from tests.test_observation_tool_workflow import ObservationProvider
from tests.test_parent_chat import Model
from tests.test_parent_chat_api import BACKEND_TOKEN, HEADERS
from tests.test_source_tool_workflow import request, setup


def settings(path: Path, key: Path, **changes: object) -> Settings:
    return Settings.model_validate(
        {
            "openai_api_key": "fake-key",
            "app_api_key": BACKEND_TOKEN,
            "mana_parent_chat_enabled": True,
            "mana_parent_touch_enabled": True,
            "mana_parent_touch_review_first_enabled": True,
            "mana_child_safety_enabled": True,
            "mana_child_safety_source_tools_enabled": True,
            "mana_parent_chat_database_path": path / "family.sqlite3",
            "mana_child_safety_limits": ChildSafetyLimits(
                server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=2000
            ),
            "mana_child_safety_max_output_tokens": 512,
            "mana_child_safety_poll_seconds": 0.05,
            "manakids_api_username": "fake-user",
            "manakids_api_password": "fake-password",
            "mana_family_sources_enabled": True,
            "mana_family_firebase_mana_confirmed": True,
            "mana_family_source_database_path": path / "sources.sqlite3",
            "firebase_project_id": "test-project",
            "firebase_service_account_file": key,
        }
        | changes
    )


@pytest.mark.parametrize("observations", [False, True])
async def test_lifespan_worker_runs_native_source_review_through_existing_chat_api(
    tmp_path: Path, monkeypatch: MonkeyPatch, observations: bool
) -> None:
    usage = Usage(Clock())
    runtime = await setup(
        tmp_path,
        observation=observations,
        provider=ObservationProvider() if observations else None,
        app_usage=usage if observations else None,
    )
    key = tmp_path / "not-used-credentials.json"
    key.write_text("{}")
    config = settings(tmp_path, key, mana_family_app_usage_enabled=observations)
    reads = FamilySourceService(
        runtime.source_store,
        runtime.profiles,
        runtime.battery,
        clock=runtime.clock.now,
        app_usage=usage if observations else None,
    )

    async def source_factory(*args: object, **kwargs: object) -> FamilySourceRuntime:
        return FamilySourceRuntime(reads, runtime.source_store, SourceSafetyPolicy())

    class Speaker(Model):
        async def close(self) -> None:
            pass

    speaker = Speaker()
    monkeypatch.setattr(runtime_module, "family_source_runtime", source_factory)
    monkeypatch.setattr(
        runtime_module, "ManakidsChatChildrenSource", lambda **kwargs: runtime.profiles
    )
    monkeypatch.setattr(runtime_module, "OpenAIParentChatModel", lambda settings: speaker)
    # Keep the genuine class for isinstance while giving it the already-owned mock SDK client.
    monkeypatch.setattr(runtime_module, "OpenAIChildSourceModel", type(runtime.adapter))
    original_init = type(runtime.adapter).__init__

    def native_init(self: OpenAIChildSourceModel, settings: Settings) -> None:
        original_init(self, settings, client=runtime.adapter._client)

    monkeypatch.setattr(type(runtime.adapter), "__init__", native_init)
    monkeypatch.setattr(runtime_module, "SystemManaAIClock", lambda: runtime.clock)
    monkeypatch.setattr(runtime_module, "datetime", SimpleNamespace(now=lambda _: NOW))
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: config)
    app = product_ai_main.create_app()
    app.dependency_overrides[get_settings] = lambda: config
    prefix = "/api/v1/mana-ai/parent-touch"
    original = request()
    body = original.model_dump(mode="json")
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        assert runtime.provider.requests == [] and runtime.battery.calls == 0
        assert (await client.post(prefix + "/messages", json=body)).status_code == 401
        admitted = await client.post(prefix + "/messages", json=body, headers=HEADERS)
        assert admitted.status_code == 202
        status_url = prefix + f"/messages/{original.request_id}"
        state = {}
        for _ in range(80):
            response = await client.get(status_url, params={"parent_id": "123"}, headers=HEADERS)
            assert response.status_code == 200
            state = response.json()
            if state["phase"] in {"completed", "failed", "unknown"}:
                break
            await asyncio.sleep(0.025)
        assert state["phase"] == "completed" and state["response"]["answer"]
        count = len(runtime.provider.requests)
        replay = await client.post(prefix + "/messages", json=body, headers=HEADERS)
        assert replay.json() == state
        assert len(runtime.provider.requests) == count and runtime.battery.calls == int(
            not observations
        )
        assert usage.calls == int(observations)
        private = await client.get(status_url, params={"parent_id": "456"}, headers=HEADERS)
        assert private.status_code == 404
        history = await client.get(prefix + "/chat", params={"parent_id": "123"}, headers=HEADERS)
        assert history.status_code == 200 and len(history.json()["messages"]) == 2
        assert speaker.prompts[-1].required_observation_dates == (
            () if observations else ("2026-10-24",)
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"mana_family_sources_enabled": False},
        {"mana_parent_touch_review_first_enabled": False},
        {"openai_timeout_seconds": 120},
    ],
)
def test_native_source_configuration_requires_captured_runtime_and_lease_budget(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    key = tmp_path / "not-used-credentials.json"
    key.write_text("{}")
    with pytest.raises(ValidationError):
        settings(tmp_path, key, **changes)
