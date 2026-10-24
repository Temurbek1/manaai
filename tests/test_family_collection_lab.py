"""Fictional collection through the real cache, safety worker and single-chat API."""

import asyncio
from pathlib import Path

import httpx
import pytest

from app.services.lab_collection import LabCollectionClock
from app.services.mana_chat_lab import LAB_PARENT, ChatLab, LabOptions
from scripts.mana_chat_lab import create_app
from tests.test_mana_chat_lab import BASE, session


def options(directory: Path, *, worker: bool = True) -> LabOptions:
    return LabOptions(
        directory,
        clock=LabCollectionClock(),
        native_sources=True,
        native_observations=True,
        scheduled_collection=True,
        worker_enabled=worker,
    )


async def test_collection_initiates_chat_without_parent_message_and_deduplicates(
    tmp_path: Path,
) -> None:
    app = create_app(options=options(tmp_path / "collection"))
    first = None
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        lab = app.state.chat_lab
        assert not (await lab.state()).history.messages
        assert (await client.get("/lab/state")).status_code == 200
        assert lab.battery.calls == lab.app_usage.calls == 0
        early = await client.post(
            "/lab/collection", headers=headers, json={"parent_id": LAB_PARENT, "hour": 15}
        )
        assert early.status_code == 409
        body = {"parent_id": LAB_PARENT, "hour": 9}
        first = await client.post("/lab/collection", headers=headers, json=body)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "completed" and first.json()["targets"] == 2
        for _ in range(100):
            state = await lab.state()
            if state.history.messages:
                break
            await asyncio.sleep(0.03)
        assert state.history.messages and all(m.role == "assistant" for m in state.history.messages)
        assert "12" in state.history.messages[0].content
        assert state.safety_budget.server_used_tokens > 0
        messages = state.history.messages
        spent = state.safety_budget.server_used_tokens
        assert (
            await client.post("/lab/collection", headers=headers, json=body)
        ).json() == first.json()
        assert lab.battery.calls == lab.app_usage.calls == lab.collection.inventory.calls == 1
        afternoon = await client.post(
            "/lab/collection", headers=headers, json={"parent_id": LAB_PARENT, "hour": 15}
        )
        assert afternoon.status_code == 200 and afternoon.json()["status"] == "completed"
        await asyncio.sleep(0.3)
        state = await lab.state()
        assert (
            state.history.messages == messages and state.safety_budget.server_used_tokens == spent
        )
        assert lab.battery.calls == lab.app_usage.calls == 2
        assert lab.touch.proactive._gateway is None and lab.touch.conversion.grants is None
    restarted = ChatLab(options(tmp_path / "collection", worker=False))
    await restarted.start()
    try:
        assert restarted.options.clock.now().hour == 10
        assert (await restarted.state()).history.messages == messages
        assert restarted.collection is not None
        assert (await restarted.collection.collect(9)).model_dump(mode="json") == first.json()
        assert restarted.battery.calls == restarted.app_usage.calls == 0
    finally:
        await restarted.close()


def test_fictional_collection_clock_cannot_reset_real_model_quotas(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="fictional"):
        ChatLab(
            LabOptions(
                tmp_path,
                real_model=True,
                native_sources=True,
                native_observations=True,
                scheduled_collection=True,
                clock=LabCollectionClock(),
            )
        )
