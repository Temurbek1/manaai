import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.parent_chat import PARENT_CHAT_INSTRUCTIONS, ParentChatService
from app.mana_ai.domain.chat import (
    ChatChild,
    ChatTokens,
    ChildChatObservation,
    ParentChatRequest,
    ParentChildContext,
)
from app.services.parent_chat_store import SqliteParentChatStore

NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


class Children:
    def __init__(self) -> None:
        self.calls = 0
        self.owner_mismatch = False

    async def read(self, parent_id: str) -> ParentChildContext:
        self.calls += 1
        return ParentChildContext(
            parent_id="456" if self.owner_mismatch else parent_id,
            children=[
                ChatChild(
                    child_id=int(parent_id) + 1, name="Synthetic child", age=8, connected=True
                )
            ],
            collected_at=NOW,
            limitations=["Synthetic profiles only"],
        )


class Model:
    def __init__(self) -> None:
        self.calls = 0
        self.counts = 0
        self.input_tokens = 100
        self.output_tokens = 50
        self.complete = True
        self.oversized_history = False
        self.error: Exception | None = None
        self.prompts: list[ChatPrompt] = []
        self.caps: list[int] = []
        self.started = asyncio.Event()
        self.release: asyncio.Event | None = None

    async def count_input(self, prompt: ChatPrompt) -> int:
        self.counts += 1
        self.prompts.append(prompt)
        if self.oversized_history and len(prompt.messages) > 2:
            return 3000
        return self.input_tokens

    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        self.calls += 1
        self.caps.append(max_output_tokens)
        self.started.set()
        if self.release is not None:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        assert prompt == self.prompts[-1]
        return ChatModelReceipt(
            usage=ChatTokens(input_tokens=self.input_tokens, output_tokens=self.output_tokens),
            answer="Synthetic answer" if self.complete else None,
            completed=self.complete,
            model="fake-model",
        )


async def make_service(
    path: Path, *, limit: int = 2000, attempts: int = 20
) -> tuple[ParentChatService, Model, Children]:
    store = SqliteParentChatStore(
        path, daily_limit=limit, timezone="Asia/Tashkent", max_attempts=attempts
    )
    await store.initialize()
    model, children = Model(), Children()
    return (
        ParentChatService(
            store=store,
            children=children,
            model=model,
            clock=lambda: NOW,
            max_output_tokens=512,
            history_turn_limit=2,
        ),
        model,
        children,
    )


def message(parent_id: str = "123", text: str = "Как помочь ребёнку?") -> ParentChatRequest:
    return ParentChatRequest(parent_id=parent_id, request_id=uuid4(), message=text)


async def test_single_chat_persists_and_exact_replay_has_no_provider_or_child_reads(
    tmp_path: Path,
) -> None:
    service, model, children = await make_service(tmp_path / "chat.db")
    request = message()
    result = await service.send(request)
    assert result.quota.used_tokens == 150
    assert result.quota.remaining_tokens == 1850
    assert result.quota.reserved_tokens == 0
    assert result.quota.resets_at == datetime(2026, 10, 16, 19, tzinfo=UTC)
    assert await service.send(request) == result
    assert model.calls == children.calls == 1
    second, second_model, second_children = await make_service(tmp_path / "chat.db")
    assert await second.send(request) == result
    assert second_model.calls == second_children.calls == 0
    await second.send(message(text="Что ещё посоветуешь?"))
    history = await second.store.history("123", before=None, limit=30, now=NOW)
    assert len(history.messages) == 4
    assert [item.role for item in history.messages] == ["user", "assistant"] * 2
    assert history.quota.used_tokens == 300
    assert second_model.prompts[0].messages[-3:] == (
        ("user", request.message),
        ("assistant", result.answer),
        ("user", "Что ещё посоветуешь?"),
    )


async def test_conflict_and_parent_isolation_and_pagination(tmp_path: Path) -> None:
    service, model, _ = await make_service(tmp_path / "chat.db")
    original = message()
    await service.send(original)
    with pytest.raises(ParentChatError, match="request_id_conflict"):
        await service.send(original.model_copy(update={"message": "Different message"}))
    for index in range(3):
        await service.send(message(text=f"Next {index}"))
    other = await service.store.history("456", before=None, limit=30, now=NOW)
    assert other.messages == []
    assert other.quota.used_tokens == 0
    latest = await service.store.history("123", before=None, limit=2, now=NOW)
    assert len(latest.messages) == 4
    assert latest.next_before_turn_id is not None
    previous = await service.store.history(
        "123", before=latest.next_before_turn_id, limit=2, now=NOW
    )
    assert len(previous.messages) == 4
    assert previous.next_before_turn_id is None
    assert previous.messages[-1].turn_id < latest.messages[0].turn_id
    assert model.calls == 4
    assert len(model.prompts[-1].messages) == 6


async def test_budget_admission_happens_before_generation(tmp_path: Path) -> None:
    service, model, _ = await make_service(tmp_path / "chat.db", limit=256)
    model.input_tokens = 230
    request = message()
    with pytest.raises(ParentChatError, match="daily_token_budget_exceeded"):
        await service.send(request)
    assert model.calls == 0
    assert (await service.store.quota("123", NOW)).reserved_tokens == 0
    assert (await service.store.quota("123", NOW)).used_tokens == 0
    with pytest.raises(ParentChatError) as replay:
        await service.send(request)
    assert replay.value.status_code == 429
    assert model.counts == 1
    model.input_tokens = 100
    await service.send(message())
    assert model.caps == [156]
    model.input_tokens = 80
    with pytest.raises(ParentChatError):
        await service.send(message())
    assert model.calls == 1


async def test_unknown_usage_keeps_hold_and_blocks_after_restart_and_midnight(
    tmp_path: Path,
) -> None:
    service, model, children = await make_service(tmp_path / "chat.db")
    model.error = TimeoutError("Never expose provider details or credentials")
    request = message()
    with pytest.raises(ParentChatError, match="model_receipt_unknown"):
        await service.send(request)
    quota = await service.store.quota("123", NOW)
    assert quota.used_tokens == 0
    assert quota.reserved_tokens == 612
    assert quota.blocked_by_unresolved_request
    replacement, fresh_model, fresh_children = await make_service(tmp_path / "chat.db")
    for attempt in (request, message()):
        with pytest.raises(ParentChatError):
            await replacement.send(attempt)
    with pytest.raises(ParentChatError):
        await replacement.store.admit(message(), NOW + timedelta(days=1))
    tomorrow = await replacement.store.quota("123", NOW + timedelta(days=1))
    assert tomorrow.blocked_by_unresolved_request
    assert fresh_model.calls == fresh_children.calls == 0
    assert model.calls == children.calls == 1


async def test_concurrent_independent_workers_cannot_double_spend(tmp_path: Path) -> None:
    service, model, _ = await make_service(tmp_path / "chat.db")
    second, second_model, second_children = await make_service(tmp_path / "chat.db")
    model.release = asyncio.Event()
    original = message()
    task = asyncio.create_task(service.send(original))
    await model.started.wait()
    for request in (original, message()):
        with pytest.raises(ParentChatError):
            await second.send(request)
    assert second_model.calls == second_children.calls == 0
    model.release.set()
    result = await task
    assert await second.send(original) == result
    assert (await second.store.quota("123", NOW)).used_tokens == 150


async def test_incomplete_answer_is_charged_once_but_not_exposed_or_retried(tmp_path: Path) -> None:
    service, model, _ = await make_service(tmp_path / "chat.db")
    model.complete = False
    request = message()
    with pytest.raises(ParentChatError, match="model_answer_unavailable"):
        await service.send(request)
    assert (await service.store.quota("123", NOW)).used_tokens == 150
    with pytest.raises(ParentChatError):
        await service.send(request)
    assert (await service.store.quota("123", NOW)).used_tokens == 150
    assert model.calls == 1
    history = await service.store.history("123", before=None, limit=30, now=NOW)
    assert len(history.messages) == 1
    assert history.messages[0].status == "failed"
    model.complete = True
    await service.send(message())
    assert len(model.prompts[-1].messages) == 2


async def test_child_owner_mismatch_never_reaches_model(tmp_path: Path) -> None:
    service, model, children = await make_service(tmp_path / "chat.db")
    children.owner_mismatch = True
    with pytest.raises(ParentChatError, match="owner_mismatch"):
        await service.send(message())
    assert model.calls == model.counts == 0
    assert (await service.store.quota("123", NOW)).reserved_tokens == 0


async def test_attempt_limit_includes_failed_preflights_and_survives_restart(
    tmp_path: Path,
) -> None:
    service, model, _ = await make_service(tmp_path / "chat.db", attempts=1)
    model.input_tokens = 3000
    with pytest.raises(ParentChatError):
        await service.send(message())
    second, fresh_model, fresh_children = await make_service(tmp_path / "chat.db", attempts=1)
    with pytest.raises(ParentChatError, match="daily_request_limit_exceeded") as error:
        await second.send(message())
    assert error.value.retry_after is not None
    assert fresh_model.calls == fresh_children.calls == 0
    turn = await second.store.admit(message(), NOW + timedelta(days=1))
    assert turn.reserved_tokens == 2000


async def test_cancelled_inflight_model_remains_unknown(tmp_path: Path) -> None:
    service, model, _ = await make_service(tmp_path / "chat.db")
    model.release = asyncio.Event()
    task = asyncio.create_task(service.send(message()))
    await model.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await service.store.quota("123", NOW)).blocked_by_unresolved_request


async def test_abandoned_preparation_can_be_released_but_cannot_dispatch_late(
    tmp_path: Path,
) -> None:
    service, _, _ = await make_service(tmp_path / "chat.db")
    old = await service.store.admit(message(), NOW)
    await service.store.admit(message(), NOW + timedelta(minutes=6))
    with pytest.raises(ParentChatError, match="no_longer_admitted"):
        await service.store.submit(old, reserved_tokens=100, now=NOW + timedelta(minutes=6))


@pytest.mark.parametrize(
    "text",
    [
        "Как дела у ребёнка?",
        "Farzandimga qanday yordam beraman?",
        "How can I help my child?",
        "كيف أساعد طفلي؟",
    ],
)
async def test_language_instruction_and_exact_user_message_are_preserved(
    tmp_path: Path, text: str
) -> None:
    service, model, _ = await make_service(tmp_path / "chat.db")
    await service.send(message(text=text))
    assert model.prompts[-1].messages[-1] == ("user", text)
    assert model.prompts[-1].instructions == PARENT_CHAT_INSTRUCTIONS
    assert "same language and script" in PARENT_CHAT_INSTRUCTIONS
    assert "child_id" not in model.prompts[-1].messages[0][1]


async def test_backend_observations_are_owner_checked_and_bound_to_exact_replay(
    tmp_path: Path,
) -> None:
    service, model, _ = await make_service(tmp_path / "chat.db")
    request = message().model_copy(
        update={
            "child_observations": [
                ChildChatObservation(
                    child_id=124,
                    observed_at=NOW,
                    battery_percent=30,
                    screen_time_minutes=60,
                    activity_period_start=NOW - timedelta(hours=2),
                    activity_period_end=NOW,
                )
            ]
        }
    )
    result = await service.send(request)
    prompt = model.prompts[-1].messages[0][1]
    assert '"battery_percent": 30' in prompt
    assert '"screen_time_minutes": 60' in prompt
    assert "child_id" not in prompt
    assert await service.send(request) == result
    changed = request.model_copy(
        update={
            "child_observations": [
                ChildChatObservation(
                    child_id=124,
                    observed_at=NOW,
                    battery_percent=40,
                )
            ]
        }
    )
    with pytest.raises(ParentChatError, match="request_id_conflict"):
        await service.send(changed)
    foreign = message().model_copy(
        update={
            "child_observations": [
                ChildChatObservation(
                    child_id=999,
                    observed_at=NOW,
                    battery_percent=30,
                )
            ]
        }
    )
    with pytest.raises(ParentChatError, match="child_observation_not_authorized"):
        await service.send(foreign)
    future = message().model_copy(
        update={
            "child_observations": [
                ChildChatObservation(
                    child_id=124,
                    observed_at=NOW + timedelta(days=1),
                    battery_percent=30,
                )
            ]
        }
    )
    with pytest.raises(ParentChatError, match="child_observation_in_future"):
        await service.send(future)
    assert model.calls == 1


async def test_excess_provider_usage_is_recorded_and_blocks_further_calls(tmp_path: Path) -> None:
    service, model, _ = await make_service(tmp_path / "chat.db")
    model.output_tokens = 3000
    with pytest.raises(ParentChatError, match="model_usage_exceeded_hold"):
        await service.send(message())
    quota = await service.store.quota("123", NOW)
    assert quota.used_tokens == 3100
    assert quota.blocked_by_unresolved_request
    with pytest.raises(ParentChatError):
        await service.send(message())
    assert model.calls == 1


async def test_missing_model_receipt_after_restart_does_not_expire_like_preparation(
    tmp_path: Path,
) -> None:
    service, _, _ = await make_service(tmp_path / "chat.db")
    request = message()
    turn = await service.store.admit(request, NOW)
    await service.store.submit(turn, reserved_tokens=612, now=NOW)
    other, other_model, other_children = await make_service(tmp_path / "chat.db")
    with pytest.raises(ParentChatError, match="model_receipt_unknown"):
        await other.store.admit(request, NOW + timedelta(minutes=6))
    quota = await other.store.quota("123", NOW)
    assert quota.reserved_tokens == 612
    assert other_model.calls == other_children.calls == 0


async def test_expired_preparation_cannot_submit_even_without_another_reader(
    tmp_path: Path,
) -> None:
    service, _, _ = await make_service(tmp_path / "chat.db")
    old = await service.store.admit(message(), NOW)
    with pytest.raises(ParentChatError, match="no_longer_admitted"):
        await service.store.submit(old, reserved_tokens=100, now=NOW + timedelta(minutes=6))


async def test_storage_refuses_foreign_database_without_changing_its_journal(
    tmp_path: Path,
) -> None:
    import sqlite3

    path = tmp_path / "foreign.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE important_data (id INTEGER)")
        connection.execute("INSERT INTO important_data VALUES (42)")
    original = path.read_bytes()
    with pytest.raises(RuntimeError, match="dedicated database"):
        await make_service(path)
    assert path.read_bytes() == original


async def test_long_history_cannot_permanently_lock_a_chat_out_of_its_daily_budget(
    tmp_path: Path,
) -> None:
    service, model, children = await make_service(tmp_path / "chat.db")
    await service.send(message(text="Previous condition one"))
    await service.send(message(text="Previous condition two"))
    model.oversized_history = True
    current = message(text="Current exact question")
    result = await service.send(current)
    assert result.history_turns_included == 0
    assert model.calls == children.calls == 3
    assert model.counts == 4  # two ordinary counts + two successful sizing reads
    assert model.prompts[-1].messages == (model.prompts[-2].messages[0], ("user", current.message))
    assert len((await service.history("123", before=None, limit=30)).messages) == 6
