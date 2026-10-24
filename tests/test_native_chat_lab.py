"""Browser-facing lab uses the actual native SQL/SDK path and fictional sources only."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from app.services.mana_chat_lab import LAB_PARENT, ChatLab, LabOptions
from scripts.mana_chat_lab import create_app
from tests.test_mana_chat_lab import BASE, PREFIX, Clock, session, settled


@pytest.mark.parametrize(
    "text,fragment,observations",
    [
        ("Какой заряд у ребёнка?", "заряд 12%", False),
        ("Farzandim telefonining quvvatini tekshiring", "quvvat 12%", False),
        ("В каких приложениях ребёнок проводит время?", "часть счётчиков", True),
        ("Farzandim qaysi ilovalardan foydalanadi?", "Ilovalar hisoblagichlarining", True),
    ],
)
async def test_native_lab_selects_source_without_an_extra_ui_control(
    tmp_path: Path, text: str, fragment: str, observations: bool
) -> None:
    options = LabOptions(
        tmp_path / "native-lab",
        clock=Clock(),
        native_sources=True,
        native_observations=observations,
    )
    app = create_app(options=options)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        identity = str(uuid4())
        body = {"parent_id": LAB_PARENT, "request_id": identity, "message": text}
        admitted = await client.post(PREFIX + "/parent-touch/messages", headers=headers, json=body)
        assert admitted.status_code == 202
        done = await settled(client, identity)
        response = done["response"]
        assert isinstance(response, dict) and fragment in response["answer"]
        if not observations:
            assert "2026-10-24" in response["answer"]
        lab = app.state.chat_lab
        state = await lab.state()
        assert lab.battery.calls == int(not observations)
        assert lab.app_usage.calls == int(observations)
        assert state.safety_budget.server_used_tokens == 300
        assert state.history.quota.used_tokens == 150
        assert lab.touch.proactive._gateway is None and lab.touch.conversion.grants is None
        assert (
            await client.post(PREFIX + "/parent-touch/messages", headers=headers, json=body)
        ).json() == done
        assert lab.battery.calls == int(not observations)
        assert lab.app_usage.calls == int(observations)
    with sqlite3.connect(options.directory / "family.sqlite3") as sql:
        assert sql.execute("PRAGMA user_version").fetchone()[0] == (12 if observations else 11)
    restarted = ChatLab(
        LabOptions(
            options.directory,
            clock=Clock(),
            native_sources=True,
            worker_enabled=False,
            native_observations=observations,
        )
    )
    await restarted.start()
    assert (await restarted.state()).safety_budget.server_used_tokens == 300
    assert restarted.battery.calls == 0
    await restarted.close()


async def test_existing_lab_cannot_silently_acquire_native_execution(tmp_path: Path) -> None:
    original = ChatLab(LabOptions(tmp_path / "ordinary", clock=Clock(), worker_enabled=False))
    await original.start()
    await original.close()
    changed = ChatLab(LabOptions(tmp_path / "ordinary", clock=Clock(), native_sources=True))
    with pytest.raises(ValueError, match="different lab mode"):
        await changed.start()
    await changed.close()


async def test_usage_change_does_not_stop_battery_consumer_or_following_chat(
    tmp_path: Path,
) -> None:
    import asyncio

    options = LabOptions(
        tmp_path / "observation-worker",
        clock=Clock(),
        native_sources=True,
        native_observations=True,
    )
    app = create_app(options=options)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        for text in (
            "В каких приложениях ребёнок проводит время?",
            "Farzandim qaysi ilovalardan foydalanadi?",
        ):
            identity = str(uuid4())
            body = {"parent_id": LAB_PARENT, "request_id": identity, "message": text}
            admitted = await client.post(
                PREFIX + "/parent-touch/messages", headers=headers, json=body
            )
            assert admitted.status_code == 202
            assert (await settled(client, identity))["phase"] == "completed"
            await asyncio.sleep(0.2)
            assert app.state.chat_lab.safety.worker_available
        lab = app.state.chat_lab
        state = await lab.state()
        assert state.safety_budget.server_used_tokens == 600
        assert state.history.quota.used_tokens == 300 and len(state.history.messages) == 4
        assert lab.app_usage.calls == 1 and lab.battery.calls == 0


async def test_observation_simulation_selects_latest_intent_after_an_app_conversation() -> None:
    import json
    from dataclasses import replace

    from app.mana_ai.domain.source_tools import ObservationSourceCall, observation_arguments
    from app.services.lab_native_source_model import LabNativeSourceModel
    from tests.test_child_source_model import prompt
    from tests.test_parent_chat import Model

    original = prompt()
    selected = replace(
        original,
        scope=original.scope.model_copy(update={"protocol": 2}),
        input=replace(
            original.input,
            messages=(
                (
                    "user",
                    json.dumps(
                        {
                            "kind": "parent_message",
                            "children": [{"alias": "child-1"}],
                            "chat": [
                                {
                                    "role": "user",
                                    "content": "В каких приложениях ребёнок проводит время?",
                                },
                                {
                                    "role": "assistant",
                                    "content": "Есть часть счётчиков приложений.",
                                },
                                {"role": "user", "content": "Какой заряд у ребёнка?"},
                            ],
                        },
                        ensure_ascii=False,
                    ),
                ),
            ),
        ),
    )
    model = LabNativeSourceModel(Model())
    receipt = await model.respond_source(selected, max_output_tokens=512)
    assert receipt.completed and receipt.continuation
    call = receipt.continuation.call
    assert (
        isinstance(call, ObservationSourceCall)
        and observation_arguments(call.arguments).kind == "battery"
    )
    await model.close()
