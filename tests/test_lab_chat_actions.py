"""Exercise durable card decisions through the guarded HTTP lab and real SQLite."""

import asyncio
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from app.mana_ai.application.chat_actions import ChatActionService
from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat_actions import (
    ChatActionClaim,
    ChatActionClick,
    ChatActionCreate,
    ChatActionResult,
)
from app.services.lab_chat_action_store import SqliteLabChatActionStore
from app.services.location_safety_store import SqliteClosedLocationSafetyStore
from app.services.mana_chat_lab import LAB_PARENT, ChatLab, LabOptions
from scripts.mana_chat_lab import create_app

BASE = "http://127.0.0.1:8098"
PATH = "/api/v1/mana-ai/parent-touch/action-cards"


class Clock:
    value = datetime(2026, 10, 26, 9, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


def options(directory: Path, clock: Clock) -> LabOptions:
    return LabOptions(
        directory,
        clock=clock,
        worker_enabled=False,
        native_sources=True,
        native_observations=True,
        source_reviews=True,
        reminders=True,
        retention=True,
        upsell=True,
        tariff_context=True,
        expiry=True,
        manager=True,
        action_cards=True,
        expiry_fixture_days=30,
    )


def definition() -> dict[str, object]:
    return {
        "parent_id": LAB_PARENT,
        "request_id": str(uuid4()),
        "action_type": "sandbox_demo",
        "title": "Test confirmation",
        "text": "Only a simulation.",
        "buttons": [
            {"id": "confirm", "label": "Confirm test"},
            {"id": "cancel", "label": "Dismiss"},
        ],
        "expires_in_seconds": 60,
    }


async def session(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.get("/")
    match = re.search(r'name="lab-csrf" content="([A-Za-z0-9_-]+)"', response.text)
    assert match
    return {"Origin": BASE, "X-Lab-CSRF": match.group(1)}


def click(card: dict[str, object], button: str = "confirm") -> dict[str, object]:
    return {
        "parent_id": LAB_PARENT,
        "request_id": str(uuid4()),
        "button_id": button,
        "definition_hash": card["definition_hash"],
    }


async def test_confirmation_http_concurrency_replay_restart_and_same_history(
    tmp_path: Path,
) -> None:
    clock = Clock()
    app = create_app(options=options(tmp_path / "lab", clock))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        body = definition()
        card_response = await client.post(PATH, headers=headers, json=body)
        assert card_response.status_code == 200, card_response.text
        card = card_response.json()
        assert card["status"] == "pending" and card["mode"] == "simulation"
        assert (await client.post(PATH, headers=headers, json=body)).json() == card
        conflicting = await client.post(PATH, headers=headers, json=body | {"text": "Changed"})
        assert conflicting.status_code == 409
        assert (await client.post(PATH, headers=headers, json=definition())).status_code == 409
        # Text is not a substitute for pressing the displayed, bound button.
        plain = await client.post(
            "/api/v1/mana-ai/parent-touch/messages",
            headers=headers,
            json={"parent_id": LAB_PARENT, "request_id": str(uuid4()), "message": "да"},
        )
        assert plain.status_code == 409
        url = PATH + f"/{card['card_id']}/click"
        payload = click(card)
        responses = await asyncio.gather(
            *(client.post(url, headers=headers, json=payload) for _ in range(8))
        )
        assert all(item.status_code == 200 for item in responses)
        result = (await client.get(PATH + f"/{card['card_id']}?parent_id={LAB_PARENT}")).json()
        assert result["status"] == "completed"
        assert result["result"]["outcome"] == "simulated_success"
        assert (await client.post(url, headers=headers, json=click(card))).json() == result
        assert (
            await client.post(url, headers=headers, json=click(card, "cancel"))
        ).status_code == 409
        service = app.state.chat_lab.action_cards
        assert service._executor.calls == 1
        state = (await client.get("/lab/state")).json()
        assert state["action_cards"] == [result]
        messages = state["history"]["messages"]
        assert len(messages) == 1 and messages[0]["role"] == "assistant"
        assert messages[0]["turn_id"] == card["turn_id"]
        assert state["history"]["quota"]["used_tokens"] == 0
        assert state["safety_budget"]["server_used_tokens"] == 0
        assert app.state.chat_lab.touch.conversion.grants is None
        assert app.state.chat_lab.touch.proactive._gateway is None
    restarted = create_app(options=options(tmp_path / "lab", clock))
    async with (
        restarted.router.lifespan_context(restarted),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url=BASE) as client,
    ):
        headers = await session(client)
        assert (await client.post(url, headers=headers, json=payload)).json() == result
        assert restarted.state.chat_lab.action_cards._executor.calls == 0
        assert (await client.get("/lab/state")).json()["history"]["messages"] == messages


async def test_cancel_expiry_binding_auth_csrf_and_ownership(tmp_path: Path) -> None:
    clock = Clock()
    app = create_app(options=options(tmp_path / "lab", clock))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        assert (await client.get(PATH + f"?parent_id={LAB_PARENT}")).status_code == 401
        headers = await session(client)
        assert (await client.post(PATH, json=definition())).status_code == 403
        assert (
            await client.post(PATH, headers=headers, json=definition() | {"parent_id": "4"})
        ).status_code == 403
        assert (await client.get(PATH + "?parent_id=4")).status_code == 403
        assert (await client.get(PATH + f"?parent_id={LAB_PARENT}&limit=101")).status_code == 422
        for changes in (
            {"action_type": "grant_tariff"},
            {"text": " "},
            {"callback_url": "https://example.com"},
            {"buttons": [{"id": "confirm", "label": "Yes"}]},
            {"buttons": [{"id": "confirm", "label": "Yes"}, {"id": "confirm", "label": "No"}]},
        ):
            assert (
                await client.post(PATH, headers=headers, json=definition() | changes)
            ).status_code == 422
        card = (await client.post(PATH, headers=headers, json=definition())).json()
        url = PATH + f"/{card['card_id']}/click"
        assert (
            await client.post(
                url, headers=headers, json=click(card) | {"definition_hash": "0" * 64}
            )
        ).status_code == 409
        cancelled = await client.post(url, headers=headers, json=click(card, "cancel"))
        assert cancelled.json()["status"] == "cancelled"
        assert (await client.post(url, headers=headers, json=click(card))).status_code == 409
        second = (await client.post(PATH, headers=headers, json=definition())).json()
        clock.value += timedelta(seconds=61)
        assert (await client.get(PATH + f"/{second['card_id']}?parent_id={LAB_PARENT}")).json()[
            "status"
        ] == "expired"
        assert (
            await client.post(
                PATH + f"/{second['card_id']}/click", headers=headers, json=click(second)
            )
        ).status_code == 409
        assert app.state.chat_lab.action_cards._executor.calls == 0
        page = (await client.get(PATH + f"?parent_id={LAB_PARENT}&limit=1")).json()
        assert len(page["cards"]) == 1 and page["next_after"] == card["sequence"]
        tail = (
            await client.get(PATH + f"?parent_id={LAB_PARENT}&after={page['next_after']}")
        ).json()
        assert tail["cards"][0]["card_id"] == second["card_id"]
        with pytest.raises(ParentChatError, match="action_card_not_found"):
            await app.state.chat_lab.action_cards.read("4", UUID(card["card_id"]))


class LostExecutor:
    calls = 0

    async def execute(self, claim: ChatActionClaim) -> ChatActionResult:
        self.calls += 1
        raise TimeoutError("Synthetic lost provider acknowledgement")


async def test_unknown_or_lost_executing_claim_never_dispatches_on_new_nonce_or_restart(
    tmp_path: Path,
) -> None:
    clock, directory, lost = Clock(), tmp_path / "lab", LostExecutor()
    lab = ChatLab(options(directory, clock))
    await lab.start()
    try:
        assert isinstance(lab.store, SqliteLabChatActionStore)
        service = ChatActionService(lab.store, lost, clock)
        card = await service.create(ChatActionCreate.model_validate(definition()))
        request = ChatActionClick.model_validate(click(card.model_dump(mode="json")))
        unknown = await service.click(card.card_id, request)
        assert unknown.status == "unknown" and lost.calls == 1
        assert (
            await service.click(card.card_id, request.model_copy(update={"request_id": uuid4()}))
        ) == unknown
        assert lost.calls == 1
        # Simulate process death between the committed claim and the external call.
        second = await service.create(
            ChatActionCreate.model_validate(definition() | {"parent_id": "900003"})
        )
        second_click = ChatActionClick.model_validate(
            click(second.model_dump(mode="json")) | {"parent_id": "900003"}
        )
        claim = await lab.store.claim_card(second.card_id, second_click, clock.now())
        assert isinstance(claim, ChatActionClaim)
    finally:
        await lab.close()
    lab = ChatLab(options(directory, clock))
    await lab.start()
    try:
        assert isinstance(lab.store, SqliteLabChatActionStore)
        service = ChatActionService(lab.store, lost, clock)
        prior = await service.read("900003", second.card_id)
        assert prior.status == "executing"
        assert await service.click(second.card_id, second_click) == prior
        assert lost.calls == 1
        with pytest.raises(RuntimeError, match="dedicated database"):
            await SqliteClosedLocationSafetyStore(
                directory / "family.sqlite3", daily_limit=2000, timezone="Asia/Samarkand"
            ).initialize()
        assert await service.read("900003", second.card_id) == prior
        assert (await service.read(LAB_PARENT, card.card_id)).status == "unknown"
    finally:
        await lab.close()


async def test_card_and_assistant_message_are_one_transaction(tmp_path: Path) -> None:
    lab = ChatLab(options(tmp_path / "lab", Clock()))
    await lab.start()
    try:
        assert isinstance(lab.store, SqliteLabChatActionStore)
        assert lab.action_cards is not None
        with lab.store._transaction() as db:
            db.execute(
                "CREATE TRIGGER reject_card BEFORE INSERT ON lab_action_cards "
                "BEGIN SELECT RAISE(ABORT,'synthetic disk write refusal'); END"
            )
        with pytest.raises(sqlite3.IntegrityError):
            await lab.action_cards.create(ChatActionCreate.model_validate(definition()))
        with lab.store._connect() as db:
            assert db.execute("SELECT count(*) FROM parent_chat_turns").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM lab_action_events").fetchone()[0] == 0
    finally:
        await lab.close()


async def test_cancelled_execution_retains_unknown_and_never_calls_again(tmp_path: Path) -> None:
    started = asyncio.Event()

    class Executor:
        calls = 0

        async def execute(self, claim: ChatActionClaim) -> ChatActionResult:
            self.calls += 1
            started.set()
            await asyncio.Event().wait()
            raise AssertionError("Not reached")

    clock, executor = Clock(), Executor()
    lab = ChatLab(options(tmp_path / "lab", clock))
    await lab.start()
    try:
        assert isinstance(lab.store, SqliteLabChatActionStore)
        service = ChatActionService(lab.store, executor, clock)
        card = await service.create(ChatActionCreate.model_validate(definition()))
        request = ChatActionClick.model_validate(click(card.model_dump(mode="json")))
        task = asyncio.create_task(service.click(card.card_id, request))
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await service.read(LAB_PARENT, card.card_id)).status == "unknown"
        assert (await service.click(card.card_id, request)).status == "unknown"
        assert executor.calls == 1
        with lab.store._connect() as db:
            events = [
                row[0] for row in db.execute("SELECT kind FROM lab_action_events ORDER BY sequence")
            ]
            assert events == ["created", "executing", "unknown"]
    finally:
        await lab.close()


async def test_pending_priority_and_disabled_lab_do_not_dispatch(tmp_path: Path) -> None:
    app = create_app(options=options(tmp_path / "lab", Clock()))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        headers = await session(client)
        card = (await client.post(PATH, headers=headers, json=definition())).json()
        scenario = next(
            item
            for item in (await client.get("/lab/bootstrap")).json()["scenarios"]
            if item["key"] == "question"
        )
        question = await client.post(
            "/api/v1/mana-ai" + scenario["path"],
            headers=headers,
            json=scenario["body"] | {"priority": 3},
        )
        assert question.status_code in {200, 201, 202}, question.text
        assert (
            await client.post(PATH + f"/{card['card_id']}/click", headers=headers, json=click(card))
        ).status_code == 409
        assert (
            await client.post(
                PATH + f"/{card['card_id']}/click", headers=headers, json=click(card, "cancel")
            )
        ).json()["status"] == "cancelled"
        assert app.state.chat_lab.action_cards._executor.calls == 0
    disabled = create_app(options=LabOptions(tmp_path / "disabled", clock=Clock()))
    async with (
        disabled.router.lifespan_context(disabled),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=disabled), base_url=BASE) as client,
    ):
        headers = await session(client)
        assert (await client.post(PATH, headers=headers, json=definition())).status_code == 503
