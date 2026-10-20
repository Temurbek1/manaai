import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from pytest import MonkeyPatch

from app import product_ai_main
from app.core.config import Settings, get_settings
from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.family_agents import ParentTouchDeliveryRequest
from app.services.child_safety_store import SqliteChildSafetyStore
from tests.test_child_safety_store import store
from tests.test_family_agent_queue import intent
from tests.test_parent_chat import NOW, Children, message
from tests.test_parent_chat_api import BACKEND_TOKEN, HEADERS
from tests.test_parent_touch_evidence import TouchModel, completed_report


@dataclass
class Clock:
    current: datetime = NOW

    def now(self) -> datetime:
        return self.current


def service(
    repository: SqliteChildSafetyStore,
    model: TouchModel,
    children: Children,
    clock: Clock,
) -> ParentTouchService:
    return ParentTouchService(
        store=repository,
        model=model,
        children=children,
        clock=clock.now,
        max_output_tokens=512,
        history_turn_limit=2,
    )


async def refused_delivery(
    path: Path,
    *,
    notice: bool = False,
) -> tuple[
    SqliteChildSafetyStore,
    ParentTouchService,
    TouchModel,
    Children,
    Clock,
    ParentTouchDeliveryRequest,
]:
    repository, model, children, clock = await store(path), TouchModel(), Children(), Clock()
    touch = service(repository, model, children, clock)
    await touch.send(message(text="Salom"))
    if notice:
        await completed_report(repository)
    else:
        await repository.enqueue(intent(), NOW)
    with repository._transaction() as connection:
        connection.execute("UPDATE parent_chat_quota SET used=1750 WHERE parent_id='123'")
    request = await repository.next_delivery(NOW)
    assert request
    with pytest.raises(ParentChatError, match="daily_token_budget_exceeded"):
        await touch.deliver(request)
    return repository, touch, model, children, clock, request


@pytest.mark.parametrize("notice", [False, True])
async def test_explicit_next_day_delivery_preserves_original_refusal_and_has_no_auto_retry(
    tmp_path: Path,
    notice: bool,
) -> None:
    path = tmp_path / "resume.db"
    repository, touch, model, children, clock, refused = await refused_delivery(path, notice=notice)
    before = model.calls, children.calls
    continued = ParentTouchDeliveryRequest(
        parent_id="123", request_id=uuid4(), resume_deferred_request_id=refused.request_id
    )
    with pytest.raises(ParentChatError, match="resume_not_eligible"):
        await touch.deliver(continued)
    assert (model.calls, children.calls) == before
    with repository._connect() as connection:
        original = dict(
            connection.execute(
                "SELECT * FROM parent_chat_turns WHERE request_id=?", (str(refused.request_id),)
            ).fetchone()
        )
    clock.current += timedelta(hours=8)  # 19:00 UTC local-day reset, still before choice expiry.
    restarted = await store(path)
    touch = service(restarted, model, children, clock)
    assert await restarted.next_delivery(clock.current) is None
    result = await touch.deliver(continued)
    assert result.delivered_notice if notice else result.asked_question
    assert result.quota.used_tokens == 150 and result.quota.daily_limit == 2000
    assert await touch.deliver(continued) == result
    assert (model.calls, children.calls) == (before[0] + 1, before[1] + 1)
    assert await restarted.next_delivery(clock.current) is None
    with pytest.raises(ParentChatError, match="daily_token_budget_exceeded"):
        await touch.deliver(refused)  # Original refusal remains an exact refusal, not upgraded.
    with restarted._connect() as connection:
        assert (
            dict(
                connection.execute(
                    "SELECT * FROM parent_chat_turns WHERE request_id=?", (str(refused.request_id),)
                ).fetchone()
            )
            == original
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM parent_chat_turns WHERE parent_id='123' AND message!=''"
            ).fetchone()[0]
            == 1
        )
    assert (await restarted.safety_budget("123", clock.current)).server_used_tokens == 0


async def test_two_backend_nonces_cannot_resume_the_same_delivery_twice(tmp_path: Path) -> None:
    path = tmp_path / "race.db"
    repository, first, model, children, clock, refused = await refused_delivery(path)
    clock.current += timedelta(hours=8)
    second = service(await store(path), model, children, clock)
    requests = [
        ParentTouchDeliveryRequest(
            parent_id="123", request_id=uuid4(), resume_deferred_request_id=refused.request_id
        )
        for _ in range(2)
    ]
    before = model.calls
    outcomes = await asyncio.gather(
        first.deliver(requests[0]), second.deliver(requests[1]), return_exceptions=True
    )
    assert sum(not isinstance(item, BaseException) for item in outcomes) == 1
    assert model.calls == before + 1
    assert len((await first.read_touch_history("123", before=None, limit=30)).messages) == 3
    assert (await repository.quota("123", clock.current)).used_tokens == 150


@pytest.mark.parametrize("failure", ["unknown", "known_invalid", "source"])
async def test_paid_unknown_and_other_failures_never_qualify_for_resume(
    tmp_path: Path,
    failure: str,
) -> None:
    repository, model, children, clock = (
        await store(tmp_path / "denied.db"),
        TouchModel(),
        Children(),
        Clock(),
    )
    touch = service(repository, model, children, clock)
    await touch.send(message())
    await repository.enqueue(intent(), NOW)
    request = await repository.next_delivery(NOW)
    assert request
    if failure == "unknown":
        model.error = TimeoutError("Synthetic missing receipt")
    elif failure == "known_invalid":
        model.complete = False
    else:
        children.owner_mismatch = True
    with pytest.raises(ParentChatError):
        await touch.deliver(request)
    before = model.calls, children.calls
    model.error, model.complete, children.owner_mismatch = None, True, False
    clock.current += timedelta(hours=8)
    with pytest.raises(ParentChatError):
        await touch.deliver(
            ParentTouchDeliveryRequest(
                parent_id="123", request_id=uuid4(), resume_deferred_request_id=request.request_id
            )
        )
    assert (model.calls, children.calls) == before
    quota = await repository.quota("123", clock.current)
    assert quota.blocked_by_unresolved_request == (failure == "unknown")


async def test_changed_question_or_parent_language_context_refuses_before_source_io(
    tmp_path: Path,
) -> None:
    repository, touch, model, children, clock, refused = await refused_delivery(
        tmp_path / "changed.db"
    )
    clock.current += timedelta(hours=8)
    await repository.enqueue(intent("new.need", priority=3), clock.current)
    before = model.calls, children.calls
    with pytest.raises(ParentChatError, match="resume_not_eligible"):
        await touch.deliver(
            ParentTouchDeliveryRequest(
                parent_id="123", request_id=uuid4(), resume_deferred_request_id=refused.request_id
            )
        )
    assert (model.calls, children.calls) == before


async def test_unknown_resumed_delivery_keeps_its_hold_across_another_day(tmp_path: Path) -> None:
    repository, touch, model, children, clock, refused = await refused_delivery(
        tmp_path / "late.db"
    )
    clock.current += timedelta(hours=8)
    continuation = ParentTouchDeliveryRequest(
        parent_id="123", request_id=uuid4(), resume_deferred_request_id=refused.request_id
    )
    model.error = TimeoutError("Synthetic lost resumed receipt")
    with pytest.raises(ParentChatError, match="receipt_unknown"):
        await touch.deliver(continuation)
    before = model.calls, children.calls
    hold = (await repository.quota("123", clock.current)).reserved_tokens
    assert hold > 0
    model.error = None
    clock.current += timedelta(days=1)
    for request in (continuation, continuation.model_copy(update={"request_id": uuid4()})):
        with pytest.raises(ParentChatError):
            await touch.deliver(request)
    quota = await repository.quota("123", clock.current)
    assert quota.blocked_by_unresolved_request
    assert (
        await repository.quota("123", clock.current - timedelta(days=1))
    ).reserved_tokens == hold
    with repository._connect() as connection:
        assert (
            connection.execute(
                "SELECT reserved FROM parent_chat_turns WHERE request_id=? AND status='unknown'",
                (str(continuation.request_id),),
            ).fetchone()[0]
            == hold
        )
    assert (model.calls, children.calls) == before


async def test_pre_generation_resumption_refusal_cannot_be_repeated_in_the_same_day(
    tmp_path: Path,
) -> None:
    repository, touch, model, children, clock, refused = await refused_delivery(
        tmp_path / "twice.db"
    )
    clock.current += timedelta(hours=8)
    day, _ = repository._period(clock.current)
    with repository._transaction() as connection:
        connection.execute(
            "INSERT INTO parent_chat_quota(parent_id,day,used) VALUES('123',?,1750)", (day,)
        )
    continuation = ParentTouchDeliveryRequest(
        parent_id="123", request_id=uuid4(), resume_deferred_request_id=refused.request_id
    )
    with pytest.raises(ParentChatError, match="daily_token_budget_exceeded"):
        await touch.deliver(continuation)
    before = model.calls, children.calls
    with pytest.raises(ParentChatError, match="resume_not_eligible"):
        await touch.deliver(continuation.model_copy(update={"request_id": uuid4()}))
    assert (model.calls, children.calls) == before


async def test_new_parent_language_context_cannot_resume_an_old_choice(tmp_path: Path) -> None:
    repository, touch, model, children, clock, refused = await refused_delivery(
        tmp_path / "language.db"
    )
    clock.current += timedelta(hours=8)
    turn = await repository.admit(message(text="Привет, новая тема."), clock.current)
    await repository.fail(turn, code="synthetic_pre_dispatch")
    before = model.calls, children.calls
    with pytest.raises(ParentChatError, match="resume_not_eligible"):
        await touch.deliver(
            ParentTouchDeliveryRequest(
                parent_id="123", request_id=uuid4(), resume_deferred_request_id=refused.request_id
            )
        )
    assert (model.calls, children.calls) == before


async def test_http_resume_is_backend_only_and_does_not_upgrade_the_refused_request(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, touch, model, children, clock, refused = await refused_delivery(tmp_path / "http.db")
    config = Settings(
        _env_file=None,
        openai_api_key=SecretStr("unit-openai"),
        app_api_key=SecretStr(BACKEND_TOKEN),
    )
    monkeypatch.setattr(product_ai_main, "get_settings", lambda: config)
    app = product_ai_main.create_app()
    app.state.parent_chat_service = touch
    app.dependency_overrides[get_settings] = lambda: config
    body = {
        "parent_id": "123",
        "request_id": str(uuid4()),
        "resume_deferred_request_id": str(refused.request_id),
    }
    path = "/api/v1/mana-ai/parent-touch/deliver"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://unit"
    ) as client:
        assert (await client.post(path, json=body)).status_code == 401
        denied = await client.post(path, json=body, headers=HEADERS)
        assert (
            denied.status_code == 409
            and denied.json()["detail"]["code"] == "delivery_resume_not_eligible"
        )
        before = model.calls, children.calls
        clock.current += timedelta(hours=8)
        published = await client.post(path, json=body, headers=HEADERS)
        assert published.status_code == 200 and published.json()["asked_question"]
        assert published.headers["cache-control"] == "no-store"
        assert (model.calls, children.calls) == (before[0] + 1, before[1] + 1)
        assert (await client.post(path, json=body, headers=HEADERS)).json() == published.json()
        original = await client.post(path, json=refused.model_dump(mode="json"), headers=HEADERS)
        assert original.status_code == 429
        assert original.json()["detail"]["code"] == "daily_token_budget_exceeded"
        assert (model.calls, children.calls) == (before[0] + 1, before[1] + 1)
