import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from pytest import MonkeyPatch

from app import product_ai_main
from app.api.mana_ai_examples import request_examples
from app.core.config import Settings, get_settings
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.enums import ManaAICapability
from app.services import parent_chat_runtime as runtime_module
from tests.test_child_safety_service import SafetyModel, make_safety
from tests.test_child_safety_store import analysis, limits, target
from tests.test_parent_chat import NOW, Children
from tests.test_parent_chat_api import BACKEND_TOKEN, HEADERS
from tests.test_parent_touch_api import TouchModel

PREFIX = "/api/v1/mana-ai"


async def test_http_jobs_are_private_idempotent_and_have_capability_specific_results(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key=SecretStr("unit-openai"),
        app_api_key=SecretStr(BACKEND_TOKEN),
    )
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: settings)
    safety, repository, children, model = await make_safety(tmp_path)
    touch = ParentTouchService(
        store=repository,
        children=children,
        model=TouchModel(),
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
        safety=safety,
    )
    app = product_ai_main.create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.parent_chat_service = touch
    body = target().model_dump(mode="json") | {"analysis": analysis().model_dump(mode="json")}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (
            await client.post(PREFIX + "/child-safety/safety-monitor", json=body)
        ).status_code == 401
        admitted = await client.post(
            PREFIX + "/child-safety/safety-monitor", json=body, headers=HEADERS
        )
        assert admitted.status_code == 202 and admitted.json()["status"] == "queued"
        assert admitted.json()["visibility"] == "internal"
        assert admitted.headers["cache-control"] == "no-store"
        assert children.calls == model.calls == 0
        job_id = admitted.json()["job_id"]
        route = PREFIX + f"/child-safety/assessments/{job_id}"
        for _ in range(2):
            assert (await client.get(route + "?parent_id=123", headers=HEADERS)).status_code == 200
        assert children.calls == model.calls == 0
        await safety.process_one()
        replay = await client.post(
            PREFIX + "/child-safety/safety-monitor", json=body, headers=HEADERS
        )
        assert (
            replay.status_code == 202
            and replay.json()["analysis"]["capability"] == "safety_monitor"
        )
        assert replay.json()["question_id"]
        assert "data_revision" not in replay.json() and "context" not in replay.json()
        assert children.calls == model.calls == 1
        assert (await client.get(route + "?parent_id=456", headers=HEADERS)).status_code == 404
        listed = (
            await client.get(PREFIX + "/child-safety/assessments?parent_id=123", headers=HEADERS)
        ).json()
        assert len(listed["assessments"]) == 1 and "data_revision" not in listed["assessments"][0]
        budget = (
            await client.get(PREFIX + "/child-safety/budget?parent_id=123", headers=HEADERS)
        ).json()
        assert budget["parent_used_tokens"] == 150
        for change in ({"chat_id": "another"}, {"parent_id": "0123"}, {"child_id": "124"}):
            response = await client.post(
                PREFIX + "/child-safety/safety-monitor", json=body | change, headers=HEADERS
            )
            assert response.status_code == 422


async def test_actual_lifespan_worker_delivers_one_question_and_reads_the_parent_reply(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FreshChildren(Children):
        async def read(self, parent_id: str) -> ParentChildContext:
            return (await super().read(parent_id)).model_copy(
                update={"collected_at": datetime.now(UTC)}
            )

    class RuntimeSafetyModel(SafetyModel):
        async def close(self) -> None:
            pass

    settings = Settings(
        _env_file=None,
        openai_api_key=SecretStr("unit-openai"),
        app_api_key=SecretStr(BACKEND_TOKEN),
        mana_parent_chat_enabled=True,
        mana_parent_touch_enabled=True,
        mana_child_safety_enabled=True,
        mana_child_safety_limits=limits(
            server_daily_tokens=20_000, parent_daily_tokens=10_000, job_tokens=4000
        ),
        mana_child_safety_poll_seconds=0.05,
        mana_parent_chat_database_path=tmp_path / "runtime.db",
        manakids_api_username="unit-backend",
        manakids_api_password=SecretStr("unit-secret"),
    )
    parent_model, safety_model, children = TouchModel(), RuntimeSafetyModel(), FreshChildren()
    monkeypatch.setattr(runtime_module, "OpenAIParentChatModel", lambda settings: parent_model)
    monkeypatch.setattr(runtime_module, "OpenAIChildSafetyModel", lambda settings: safety_model)
    monkeypatch.setattr(runtime_module, "ManakidsChatChildrenSource", lambda **kwargs: children)
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: settings)
    app = product_ai_main.create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        hello = {"parent_id": "123", "request_id": str(uuid4()), "message": "Salom"}
        assert (
            await client.post(PREFIX + "/parent-touch/chat", json=hello, headers=HEADERS)
        ).status_code == 200
        body = target().model_dump(mode="json") | {"analysis": analysis().model_dump(mode="json")}
        admitted = await client.post(
            PREFIX + "/child-safety/safety-monitor", json=body, headers=HEADERS
        )
        assert admitted.status_code == 202
        active = None
        for _ in range(150):
            chat = (
                await client.get(PREFIX + "/parent-touch/chat?parent_id=123", headers=HEADERS)
            ).json()
            active = chat["active_question"]
            if active:
                break
            await asyncio.sleep(0.02)
        assert active and [m["role"] for m in chat["messages"]] == [
            "user",
            "assistant",
            "assistant",
        ]
        reply = {
            "parent_id": "123",
            "request_id": str(uuid4()),
            "message": "Ha, zaryad olayapti.",
            "reply_to_question_id": active["question_id"],
        }
        sent = await client.post(PREFIX + "/parent-touch/chat", json=reply, headers=HEADERS)
        assert sent.status_code == 200 and sent.json()["asked_question"] is None
        for _ in range(150):
            jobs = (
                await client.get(
                    PREFIX + "/child-safety/assessments?parent_id=123", headers=HEADERS
                )
            ).json()["assessments"]
            if len(jobs) == 3 and all(j["status"] == "completed" for j in jobs):
                break
            await asyncio.sleep(0.02)
        assert len(jobs) == 3 and all(j["status"] == "completed" for j in jobs)
        assert "Ha, zaryad olayapti." in safety_model.prompts[-1].messages[0][1]
        counts = children.calls, parent_model.calls, safety_model.calls
        replay = await client.post(PREFIX + "/parent-touch/chat", json=reply, headers=HEADERS)
        assert (
            replay.json() == sent.json()
            and (children.calls, parent_model.calls, safety_model.calls) == counts
        )
        assert parent_model.calls == 3 and safety_model.calls == 3


async def test_all_ten_protective_contracts_admit_through_their_own_endpoints(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key=SecretStr("unit-openai"),
        app_api_key=SecretStr(BACKEND_TOKEN),
    )
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: settings)
    safety, repository, children, model = await make_safety(tmp_path)
    app = product_ai_main.create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.parent_chat_service = ParentTouchService(
        store=repository,
        children=children,
        model=TouchModel(),
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
        safety=safety,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for capability in ManaAICapability:
            if capability == ManaAICapability.PARENT_COPILOT:
                continue
            payload = deepcopy(request_examples(capability)["default"]["value"])
            payload["subject"]["subject_id"] = "124"
            response = await client.post(
                PREFIX + "/child-safety/" + capability.value.replace("_", "-"),
                json=target().model_dump(mode="json") | {"analysis": payload},
                headers=HEADERS,
            )
            assert response.status_code == 202, response.text
            assert response.json()["capability"] == capability.value
        assert (
            await client.post(PREFIX + "/child-safety/parent-copilot", json={}, headers=HEADERS)
        ).status_code == 404
    assert children.calls == model.calls == 0


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"mana_parent_touch_enabled": True},
        {"mana_parent_touch_enabled": True, "mana_child_safety_limits": limits()},
    ],
)
def test_enabled_safety_requires_explicit_configuration(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "openai_api_key": "unit-openai",
                "app_api_key": BACKEND_TOKEN,
                "mana_child_safety_enabled": True,
                **extra,
            }
        )
