"""Current compatible specialists share real HTTP, queues, history and quota SQL."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.mana_ai.domain.conversion_catalog import ConversionCatalogObservation
from app.services import mana_chat_lab as lab_runtime
from app.services.inline_upsell_store import SqliteInlineUpsellStore
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import LAB_PARENT, ChatLab
from app.services.usage_comparison_cache import SqliteUsageComparisonCache
from scripts.mana_chat_lab import create_app
from tests.test_mana_chat_lab import BASE, PREFIX, Clock, observed_state, session, settled
from tests.test_trial_action_cards import snapshot


async def send(
    client: httpx.AsyncClient, headers: dict[str, str], text: str, **binding: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    body = {"parent_id": LAB_PARENT, "request_id": str(uuid4()), "message": text, **binding}
    admitted = await client.post(PREFIX + "/parent-touch/messages", headers=headers, json=body)
    assert admitted.status_code == 202, admitted.json()
    return body, await settled(client, body["request_id"])


async def urgent(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    scenario = next(
        item
        for item in (await client.get("/lab/bootstrap")).json()["scenarios"]
        if item["key"] == "safety"
    )
    admitted = await client.post(PREFIX + scenario["path"], headers=headers, json=scenario["body"])
    assert admitted.status_code == 202, admitted.json()
    for _ in range(150):
        state = await observed_state(client)
        if any(notice["kind"] == "urgent" for notice in state["history"]["message_notices"]):
            return scenario, state
        await asyncio.sleep(0.02)
    raise AssertionError("Safety did not reach the same parent chat")


async def test_current_workspace_one_chat_question_safety_tariff_source_reminder_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def denied_settings() -> None:
        raise AssertionError("The default workspace must not load deployment credentials")

    monkeypatch.setattr(lab_runtime, "get_settings", denied_settings)
    clock = Clock()
    clock.value = datetime(2026, 10, 27, 9, tzinfo=UTC)
    options = workspace_options(tmp_path / "workspace", clock=clock)
    app = create_app(options=options)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        lab: ChatLab = app.state.chat_lab
        assert isinstance(lab.store, SqliteInlineUpsellStore)
        assert isinstance(lab.source_store, SqliteUsageComparisonCache)
        assert lab._worker and lab._worker._parallel_enabled
        assert not options.real_model and lab.touch.proactive
        assert lab.touch.proactive._gateway is None and lab.touch.conversion
        assert lab.touch.conversion.grants is None and lab.trial_gateway is None
        assert lab.collection is None and lab.action_cards is None

        first_body, first = await send(client, headers, "Как настроить MANA?")
        question = first["response"]["asked_question"]
        assert question["child_id"] is None and question["scope"] == "parent"
        scenario, interrupted = await urgent(client, headers)
        assert interrupted["history"]["active_question"]["question_id"] == question["question_id"]
        assert len(interrupted["history"]["messages"]) == 3
        replay = await client.post(
            PREFIX + scenario["path"], headers=headers, json=scenario["body"]
        )
        assert replay.status_code == 202
        _, answered = await send(
            client, headers, "Android", reply_to_question_id=question["question_id"]
        )
        assert "разрешение" in answered["response"]["answer"]
        assert (await observed_state(client))["history"]["active_question"] is None

        _, price_question = await send(client, headers, "Покажи тарифы на 90 дней до 200000")
        currency = price_question["response"]["asked_question"]
        answer_body, quote = await send(
            client, headers, "UZS", reply_to_question_id=currency["question_id"]
        )
        assert "162 000.00 UZS" in quote["response"]["answer"]
        assert quote["response"]["usage"]["input_tokens"] == 0
        assert len((await observed_state(client))["history"]["messages"]) == 9
        assert lab.catalog.calls == 1

        _, battery = await send(client, headers, "Какой заряд у ребёнка?")
        assert "12%" in battery["response"]["answer"]
        assert lab.battery.calls == 1
        _, reminder = await send(client, headers, "Напомни завтра в 9 купить тетради")
        state = await observed_state(client)
        confirmation = state["history"]["active_confirmation"]
        assert reminder["response"] and confirmation["kind"] == "approval"
        used = state["history"]["quota"]["used_tokens"]
        _, confirmed = await send(
            client, headers, "Да", reply_to_confirmation_id=confirmation["confirmation_id"]
        )
        assert "запланировано" in confirmed["response"]["answer"]
        assert (await observed_state(client))["history"]["quota"]["used_tokens"] == used
        clock.value = datetime.fromisoformat(confirmation["candidate"]["due_at"]) + timedelta(
            seconds=1
        )
        for _ in range(150):
            state = await observed_state(client)
            if state["history"]["messages"][-1]["content"] == "Напоминание: «купить тетради».":
                break
            await asyncio.sleep(0.02)
        assert state["history"]["messages"][-1]["content"] == "Напоминание: «купить тетради»."
        assert not state["history"].get("reminders")
        assert state["history"]["speaker"] == "parent-touch"
        assert state["history"]["active_question"] is None
        assert state["history"].get("active_confirmation") is None
        for body, expected in ((first_body, first), (answer_body, quote)):
            replay = await client.post(
                PREFIX + "/parent-touch/messages", headers=headers, json=body
            )
            assert replay.status_code == 202 and replay.json() == expected
        assert lab.battery.calls == 1 and lab.catalog.calls == 1
        before = snapshot(lab.store)
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM assistant_reminders").fetchone()[0] == "delivered"
            assert db.execute("SELECT SUM(used) FROM parent_chat_quota").fetchone()[0] == used
            assert used <= 2000
            assert not db.execute("SELECT 1 FROM conversion_trial_grants").fetchone()
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()

    restarted = create_app(options=options)
    async with (
        restarted.router.lifespan_context(restarted),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url=BASE) as client,
    ):
        await session(client)
        assert await observed_state(client) == state
        assert snapshot(restarted.state.chat_lab.store) == before
        assert restarted.state.chat_lab.catalog.calls == 0
        assert restarted.state.chat_lab.battery.calls == 0


async def test_urgent_safety_interrupts_waiting_catalog_without_waiting_for_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    clock.value = datetime(2026, 10, 27, 9, tzinfo=UTC)
    app = create_app(options=workspace_options(tmp_path / "interrupt", clock=clock))
    entered, release = asyncio.Event(), asyncio.Event()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        lab: ChatLab = app.state.chat_lab
        original = lab.catalog.read

        async def blocked() -> ConversionCatalogObservation:
            entered.set()
            await release.wait()
            return await original()

        monkeypatch.setattr(lab.catalog, "read", blocked)
        body = {
            "parent_id": LAB_PARENT,
            "request_id": str(uuid4()),
            "message": "Тариф на 90 дней UZS",
        }
        try:
            admitted = await client.post(
                PREFIX + "/parent-touch/messages", headers=headers, json=body
            )
            assert admitted.status_code == 202
            await asyncio.wait_for(entered.wait(), 5)
            _, state = await urgent(client, headers)
            assert not release.is_set()
            stopped = await client.get(
                PREFIX + f"/parent-touch/messages/{body['request_id']}?parent_id={LAB_PARENT}"
            )
            assert stopped.json()["phase"] == "failed", stopped.json()
            assert len(state["history"]["messages"]) == 2
            with lab.store._connect() as db:
                assert (
                    db.execute("SELECT status FROM upsell_catalog_reads").fetchone()[0] == "reading"
                )
            release.set()
            for _ in range(150):
                with lab.store._connect() as db:
                    status = db.execute("SELECT status FROM upsell_catalog_reads").fetchone()[0]
                if status == "recorded":
                    break
                await asyncio.sleep(0.02)
            assert status == "recorded"
            assert lab.catalog.calls == 1
            assert len((await observed_state(client))["history"]["messages"]) == 2
            with sqlite3.connect(tmp_path / "interrupt/family.sqlite3") as db:
                assert (
                    db.execute("SELECT status FROM upsell_inline_replies").fetchone()[0]
                    == "cancelled"
                )
        finally:
            release.set()


async def test_combined_lab_rejects_a_free_offer_when_its_current_profile_is_paid(
    tmp_path: Path,
) -> None:
    clock = Clock()
    clock.value = datetime(2026, 10, 27, 9, tzinfo=UTC)
    app = create_app(
        options=workspace_options(tmp_path / "billing", clock=clock, worker_enabled=False)
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        observed = await client.post(
            "/lab/expiry-profile", headers=headers, json={"parent_id": LAB_PARENT}
        )
        assert observed.status_code == 200
        scenario = next(
            item
            for item in (await client.get("/lab/bootstrap")).json()["scenarios"]
            if item["key"] == "conversion"
        )
        admitted = await client.post(
            PREFIX + scenario["path"], headers=headers, json=scenario["body"]
        )
        assert admitted.status_code == 202
        assert admitted.json()["decision"] == "shared_profile_paid"
        assert admitted.json()["proposal"] is None
        lab: ChatLab = app.state.chat_lab
        assert lab.touch.conversion
        await lab.touch.process_conversion()
        proposals = await lab.touch.conversion.proposals(LAB_PARENT, after=0, limit=20)
        assert proposals.proposals == []
        assert not (await observed_state(client))["history"]["messages"]
