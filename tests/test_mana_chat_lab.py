"""The real chat/application/SQL flow, isolated behind fictional sources and models."""

import asyncio
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pytest import MonkeyPatch

from app.services import mana_chat_lab as runtime
from app.services.mana_chat_lab import LAB_CHILD, LAB_PARENT, ChatLab, LabOptions
from scripts.export_mana_ai_docs import build_schema
from scripts.mana_chat_lab import create_app

BASE = "http://127.0.0.1:8092"
PREFIX = "/api/v1/mana-ai"


class Clock:
    value = datetime(2026, 10, 24, 9, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


async def session(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.get("/")
    assert response.status_code == 200
    match = re.search(r'name="lab-csrf" content="([A-Za-z0-9_-]+)"', response.text)
    assert match
    assert "HttpOnly" in response.headers["set-cookie"]
    return {"Origin": BASE, "X-Lab-CSRF": match.group(1)}


async def settled(client: httpx.AsyncClient, request: str) -> dict[str, object]:
    for _ in range(120):
        response = await client.get(
            PREFIX + f"/parent-touch/messages/{request}?parent_id={LAB_PARENT}"
        )
        assert response.status_code == 200
        body = response.json()
        if body["phase"] in {"completed", "failed", "unknown"}:
            assert body["phase"] == "completed", body
            return dict(body)
        await asyncio.sleep(0.02)
    raise AssertionError("The fictional review-first worker did not complete")


def test_three_recommended_chat_operations_keep_compatibility_contracts() -> None:
    schema = build_schema()
    recommended = {
        (path, method)
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        if operation.get("tags") == ["mana-chat"]
    }
    assert recommended == {
        (PREFIX + "/parent-touch/chat", "get"),
        (PREFIX + "/parent-touch/messages", "post"),
        (PREFIX + "/parent-touch/messages/{request_id}", "get"),
    }
    for path, method in (("/chat", "get"), ("/chat", "post"), ("/parent-touch/chat", "post")):
        operation = schema["paths"][PREFIX + path][method]
        assert operation["deprecated"] and operation["tags"] == ["mana-chat-compatibility"]
    assert len(schema["paths"]) == 42


async def test_default_lab_uses_no_deployment_settings_provider_or_live_write(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Simulation must not initialize a provider or deployment settings")

    monkeypatch.setattr(runtime, "get_settings", forbidden)
    monkeypatch.setattr(runtime, "OpenAIParentChatModel", forbidden)
    monkeypatch.setattr(runtime, "OpenAIChildSafetyModel", forbidden)
    app = create_app(options=LabOptions(tmp_path / "lab", clock=Clock()))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        assert (await client.get("/lab/state")).status_code == 401
        headers = await session(client)
        state = (await client.get("/lab/state")).json()
        assert state["mode"] == "simulation"
        assert state["history"]["quota"]["daily_limit"] == 2000
        assert state["safety_budget"]["server_daily_limit"] == 2000
        lab = app.state.chat_lab
        assert lab.touch.conversion.grants is None
        assert lab.touch.proactive._gateway is None
        denied = await client.post(
            PREFIX + "/conversion-agent/trial-acceptances",
            headers=headers,
            json={
                "parent_id": LAB_PARENT,
                "event_id": str(uuid4()),
                "proposal_id": str(uuid4()),
                "reply_turn_id": 1,
                "confirmed_by_parent": True,
            },
        )
        assert (
            denied.status_code == 503 and denied.json()["detail"]["code"] == "trial_grants_disabled"
        )
        assert (
            await client.post(
                PREFIX + "/parent-touch/chat", headers=headers, json={"parent_id": LAB_PARENT}
            )
        ).status_code == 409
        assert state["history"]["quota"]["used_tokens"] == 0


async def test_source_scenario_traverses_worker_to_first_assistant_message(tmp_path: Path) -> None:
    app = create_app(options=LabOptions(tmp_path / "lab", clock=Clock()))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        fixtures = (await client.get("/lab/bootstrap")).json()["scenarios"]
        scenario = next(item for item in fixtures if item["key"] == "battery")
        assert scenario["local"] is True
        result = await client.post(scenario["path"], headers=headers, json=scenario["body"])
        assert result.status_code == 200 and result.json()["status"] == "completed"
        for _ in range(150):
            state = (await client.get("/lab/state")).json()
            if state["history"]["message_notices"]:
                break
            await asyncio.sleep(0.02)
        assert len(state["history"]["messages"]) == 1, state
        assert state["history"]["messages"][0]["role"] == "assistant"
        assert "12%" in state["history"]["messages"][0]["content"]
        assert len(state["source_changes"]) == 1
        before = state
        replay = await client.post(scenario["path"], headers=headers, json=scenario["body"])
        assert replay.json() == result.json()
        assert (await client.get("/lab/state")).json() == before
        assert app.state.chat_lab.battery.calls == 1


async def test_message_question_answer_and_reload_use_one_durable_chat(tmp_path: Path) -> None:
    directory, clock = tmp_path / "lab", Clock()
    app = create_app(options=LabOptions(directory, clock=clock))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        request = str(uuid4())
        body = {
            "parent_id": LAB_PARENT,
            "request_id": request,
            "message": "Ребёнок плохо спит. Помоги со сном.",
        }
        assert (
            await client.post(PREFIX + "/parent-touch/messages", headers=headers, json=body)
        ).status_code == 202
        complete = await settled(client, request)
        assert complete["response"]
        history = (await client.get("/lab/state")).json()["history"]
        assert len(history["messages"]) == 2
        assert history["active_question"]
        response = await client.post(
            PREFIX + "/parent-touch/messages",
            headers=headers,
            json={
                "parent_id": LAB_PARENT,
                "request_id": str(uuid4()),
                "message": "В 21:00.",
                "reply_to_question_id": history["active_question"]["question_id"],
            },
        )
        assert response.status_code == 202
        await settled(client, response.json()["request_id"])
        before = (await client.get("/lab/state")).json()
        assert before["history"]["active_question"] is None
        assert before["history"]["quota"]["used_tokens"] == 300
        replay = await client.post(PREFIX + "/parent-touch/messages", headers=headers, json=body)
        assert replay.status_code == 202 and replay.json() == complete
        assert (await client.get("/lab/state")).json() == before
    restarted = create_app(options=LabOptions(directory, clock=clock))
    async with (
        restarted.router.lifespan_context(restarted),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url=BASE) as client,
    ):
        await session(client)
        assert (await client.get("/lab/state")).json() == before


async def test_child_scenario_publishes_only_parent_touch_and_deduplicates(tmp_path: Path) -> None:
    app = create_app(options=LabOptions(tmp_path / "lab", clock=Clock()))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        fixtures = (await client.get("/lab/bootstrap")).json()["scenarios"]
        scenario = next(item for item in fixtures if item["key"] == "safety")
        receipt = await client.post(
            PREFIX + scenario["path"], headers=headers, json=scenario["body"]
        )
        assert receipt.status_code == 202
        for _ in range(120):
            state = (await client.get("/lab/state")).json()
            if state["history"]["message_notices"]:
                break
            await asyncio.sleep(0.02)
        assert state["history"]["message_notices"][0]["kind"] == "urgent", state
        assert [m["role"] for m in state["history"]["messages"]] == ["assistant"]
        assert "тестовом уведомлении" in state["history"]["messages"][0]["content"]
        assert state["history"]["speaker"] == "parent-touch"
        replay = await client.post(
            PREFIX + scenario["path"], headers=headers, json=scenario["body"]
        )
        assert replay.status_code == 202
        assert (await client.get("/lab/state")).json() == state


async def test_fictional_conversion_offer_and_paid_update_create_no_grants(tmp_path: Path) -> None:
    app = create_app(options=LabOptions(tmp_path / "lab", clock=Clock()))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        scenarios = {
            item["key"]: item for item in (await client.get("/lab/bootstrap")).json()["scenarios"]
        }
        scenario = scenarios["conversion"]
        result = await client.post(
            PREFIX + scenario["path"], headers=headers, json=scenario["body"]
        )
        assert result.status_code == 202 and result.json()["proposal"]
        for _ in range(100):
            state = (await client.get("/lab/state")).json()
            if state["conversions"]["proposals"][0]["status"] == "published":
                break
            await asyncio.sleep(0.02)
        assert state["conversions"]["proposals"][0]["status"] == "published", state
        assert "60000.00 UZS" in state["history"]["messages"][0]["content"]
        paid = scenarios["paid"]
        assert (
            await client.post(PREFIX + paid["path"], headers=headers, json=paid["body"])
        ).status_code == 202
        assert (await client.get("/lab/state")).json()["history"]["quota"]["used_tokens"] == 0
        with sqlite3.connect(tmp_path / "lab/family.sqlite3") as db:
            assert db.execute("SELECT COUNT(*) FROM conversion_trial_grants").fetchone()[0] == 0


@pytest.mark.parametrize("change", ["csrf", "origin", "parent", "child"])
async def test_other_families_and_cross_origin_actions_are_rejected(
    tmp_path: Path, change: str
) -> None:
    app = create_app(options=LabOptions(tmp_path / "lab", clock=Clock()))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        body = {"parent_id": LAB_PARENT, "request_id": str(uuid4()), "message": "Привет"}
        if change == "csrf":
            headers["X-Lab-CSRF"] = "fake-wrong-csrf"
        elif change == "origin":
            headers["Origin"] = "https://untrusted.invalid"
        elif change == "parent":
            body["parent_id"] = "4"
        else:
            body["child_id"] = str(LAB_CHILD + 1)
        assert (
            await client.post(PREFIX + "/parent-touch/messages", headers=headers, json=body)
        ).status_code == 403
        assert (await client.get(PREFIX + "/parent-touch/chat?parent_id=4")).status_code == 403
        assert (await client.get("/lab/state")).json()["history"]["messages"] == []


@pytest.mark.parametrize("host", ["remote", "rebinding"])
async def test_remote_clients_and_rebinding_hosts_cannot_open_lab(
    tmp_path: Path, host: str
) -> None:
    app = create_app(options=LabOptions(tmp_path / "lab", clock=Clock()))
    transport = httpx.ASGITransport(
        app=app, client=("203.0.113.9" if host == "remote" else "127.0.0.1", 1234)
    )
    async with httpx.AsyncClient(
        transport=transport, base_url=BASE if host == "remote" else "http://untrusted.invalid"
    ) as client:
        assert (await client.get("/")).status_code == (403 if host == "remote" else 400)


async def test_unmarked_or_wrong_mode_state_is_never_migrated(tmp_path: Path) -> None:
    existing = tmp_path / "other"
    existing.mkdir()
    data = existing / "family.sqlite3"
    data.write_bytes(b"not-lab-user-data")
    with pytest.raises(ValueError, match="unmarked"):
        await ChatLab(LabOptions(existing)).start()
    assert data.read_bytes() == b"not-lab-user-data"
    clean = tmp_path / "lab"
    first = ChatLab(LabOptions(clean, clock=Clock()))
    await first.start()
    await first.close()
    with pytest.raises(ValueError, match="different lab mode"):
        await ChatLab(LabOptions(clean, real_model=True, clock=Clock())).start()


async def test_simulation_budget_survives_restart_and_gets_do_not_infer(tmp_path: Path) -> None:
    # Unknown/receipt preservation itself is covered by the owning store suite;
    # this checks that the lab does not reset its durable budget or execute GETs.
    options = LabOptions(tmp_path / "lab", clock=Clock())
    lab = ChatLab(options)
    await lab.start()
    try:
        before = await lab.state()
        for _ in range(3):
            lab.bootstrap()
            assert await lab.state() == before
    finally:
        await lab.close()
    assert before.safety_budget.server_daily_limit == 2000


async def test_uzbek_parent_message_keeps_the_existing_language_contract(tmp_path: Path) -> None:
    app = create_app(options=LabOptions(tmp_path / "lab", clock=Clock()))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        request = str(uuid4())
        admitted = await client.post(
            PREFIX + "/parent-touch/messages",
            headers=headers,
            json={
                "parent_id": LAB_PARENT,
                "request_id": request,
                "message": "Farzandim kech uxlaydi. Uyqusi haqida yordam bering.",
            },
        )
        assert admitted.status_code == 202
        result = await settled(client, request)
        assert "Farzandingiz" in str(result["response"])


async def test_specialist_can_start_the_same_chat_before_parent_text(tmp_path: Path) -> None:
    app = create_app(options=LabOptions(tmp_path / "lab", clock=Clock()))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        scenario = next(
            item
            for item in (await client.get("/lab/bootstrap")).json()["scenarios"]
            if item["key"] == "question"
        )
        admitted = await client.post(
            PREFIX + scenario["path"], headers=headers, json=scenario["body"]
        )
        assert admitted.status_code == 201
        for _ in range(120):
            state = (await client.get("/lab/state")).json()
            if state["history"]["active_question"]:
                break
            await asyncio.sleep(0.02)
        assert state["history"]["active_question"], state
        assert [item["role"] for item in state["history"]["messages"]] == ["assistant"]
        assert state["history"]["quota"]["used_tokens"] == 150


async def test_composite_observation_busy_is_controlled_without_generation(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from app.mana_ai.application.chat_ports import ParentChatError
    from app.services.mana_chat_lab import LabState

    app = create_app(options=LabOptions(tmp_path / "busy", clock=Clock(), worker_enabled=False))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        await session(client)

        async def busy() -> LabState:
            raise ParentChatError("lab_state_busy", 409)

        monkeypatch.setattr(app.state.chat_lab, "state", busy)
        result = await client.get("/lab/state")
        assert result.status_code == 409 and result.json()["detail"]["code"] == "lab_state_busy"
