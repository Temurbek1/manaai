import asyncio
import sqlite3
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.application.family_agent_registry import (
    FamilyAgentRegistry,
    default_family_agents,
)
from app.mana_ai.domain.chat import ChatTokens
from app.mana_ai.domain.enums import ManaAICapability
from app.mana_ai.domain.family_agents import (
    AgentQuestionRequest,
    FamilyAgentDefinition,
    ParentTouchModelReply,
    ParentTouchRequest,
)
from app.services.family_agent_store import SqliteFamilyAgentStore
from app.services.parent_chat_store import SqliteParentChatStore
from tests.test_parent_chat import NOW, make_service, message


async def store(path: Path, *, ceiling: int = 100) -> SqliteFamilyAgentStore:
    result = SqliteFamilyAgentStore(
        path, daily_limit=2000, timezone="Asia/Tashkent", question_limit=ceiling
    )
    await result.initialize()
    return result


def intent(
    information: str = "sleep.schedule",
    *,
    parent: str = "123",
    child: int = 124,
    agent: str = "child-safety",
    priority: int = 1,
) -> AgentQuestionRequest:
    return AgentQuestionRequest(
        parent_id=parent,
        child_id=child,
        agent_id=agent,
        request_id=uuid4(),
        information_key=information,
        question="What time does your child usually go to sleep?",
        reason="A routine is missing from the supplied dated observations.",
        source_revision="synthetic-source-1",
        priority=priority,
        observed_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )


async def complete(
    repository: SqliteFamilyAgentStore, turn_id: int, request_id: object, parent: str = "123"
) -> None:
    # Test-only selection from admitted rows; no inference or provider call.
    history = await repository.history(parent, before=None, limit=30, now=NOW)
    assert history.latest_request_id == request_id
    with repository._connect() as connection:
        row = connection.execute(
            "SELECT * FROM parent_chat_turns WHERE id=? AND parent_id=?", (turn_id, parent)
        ).fetchone()
    turn = repository._turn(row)
    selected = await repository.question_for_turn(parent, turn_id)
    await repository.submit(turn, reserved_tokens=200, now=NOW)
    await repository.settle(
        turn,
        receipt=ChatModelReceipt(
            usage=ChatTokens(input_tokens=100, output_tokens=20),
            model="fake",
            answer="Question?",
            completed=True,
            question_id=selected.question_id if selected else None,
        ),
        now=NOW,
        history_turns=0,
        context_at=NOW,
    )


def test_only_parent_touch_can_speak_and_child_safety_owns_protection_capabilities() -> None:
    registry = default_family_agents()
    assert [agent.agent_id for agent in registry.definitions()] == ["parent-touch", "child-safety"]
    safety = registry.require_specialist("child-safety")
    assert set(safety.capabilities) == set(ManaAICapability) - {ManaAICapability.PARENT_COPILOT}
    for identity in ("parent-touch", "operations-orchestrator", "other"):
        with pytest.raises(ParentChatError, match="specialist_not_registered"):
            registry.require_specialist(identity)
    with pytest.raises(ValueError, match="only family"):
        FamilyAgentRegistry(
            (
                FamilyAgentDefinition(
                    agent_id="child-safety", title="Bad speaker", speaks_to_parent=True
                ),
            )
        )


async def test_replay_coalescing_multiple_agents_and_exact_answer_binding(tmp_path: Path) -> None:
    repository = await store(tmp_path / "family.db")
    request = intent()
    first = await repository.enqueue(request, NOW)
    assert await repository.enqueue(request, NOW + timedelta(days=3)) == first
    with pytest.raises(ParentChatError, match="request_id_conflict"):
        await repository.enqueue(request.model_copy(update={"reason": "Changed"}), NOW)
    subscribed = await repository.enqueue(intent(agent="future-specialist", priority=3), NOW)
    assert subscribed.coalesced and subscribed.question.question_id == first.question.question_id
    assert subscribed.question.priority == 3
    other = await repository.enqueue(intent("school.schedule"), NOW)
    assert other.question.question_id != first.question.question_id
    assert (await repository.questions("456")).questions == []

    question_turn = await repository.admit(message(), NOW)
    chosen = await repository.offer_next("123", turn_id=question_turn.turn_id, now=NOW)
    assert chosen and chosen.question_id == first.question.question_id
    assert await repository.offer_next("123", turn_id=question_turn.turn_id, now=NOW) == chosen
    assert (await repository.questions("123")).questions[0].status == "offered"
    await complete(repository, question_turn.turn_id, question_turn.request_id)
    published = (await repository.questions("123")).questions[0]
    assert published.status == "awaiting_reply"

    response = await repository.admit(message(text="At 9 pm."), NOW)
    assert await repository.offer_next("123", turn_id=response.turn_id, now=NOW) is None
    await repository.fail(response, code="synthetic pre-inference refusal")
    with pytest.raises(ParentChatError, match="question_reply_mismatch"):
        await repository.admit(
            ParentTouchRequest(
                parent_id="456",
                request_id=uuid4(),
                message="Wrong family",
                reply_to_question_id=chosen.question_id,
            ),
            NOW,
        )
    reply = ParentTouchRequest(
        parent_id="123",
        request_id=uuid4(),
        message="At 9 pm.",
        reply_to_question_id=chosen.question_id,
    )
    response = await repository.admit(reply, NOW)
    answered = (await repository.questions("123")).questions[0]
    assert answered.status == "answered"
    assert answered.answer_turn_id == response.turn_id
    assert (await repository.history("456", before=None, limit=30, now=NOW)).messages == []
    with pytest.raises(ParentChatError, match="request_in_progress"):
        await repository.admit(reply, NOW)
    next_question = await repository.offer_next("123", turn_id=response.turn_id, now=NOW)
    assert next_question and next_question.question_id == other.question.question_id


async def test_two_connections_coalesce_one_question_and_cannot_offer_two(tmp_path: Path) -> None:
    path = tmp_path / "race.db"
    first, second = await store(path), await store(path)
    receipts = await asyncio.gather(
        first.enqueue(intent(), NOW), second.enqueue(intent(agent="future-specialist"), NOW)
    )
    assert len({r.question.question_id for r in receipts}) == 1
    await first.enqueue(intent("another.fact"), NOW)
    turn = await first.admit(message(), NOW)
    offers = await asyncio.gather(
        first.offer_next("123", turn_id=turn.turn_id, now=NOW),
        second.offer_next("123", turn_id=turn.turn_id, now=NOW),
    )
    assert offers[0] == offers[1]
    assert len((await first.questions("123")).questions) == 2


async def test_unknown_chat_retains_offer_across_clock_and_restart(tmp_path: Path) -> None:
    path = tmp_path / "unknown.db"
    repository = await store(path)
    question = await repository.enqueue(intent(), NOW)
    turn = await repository.admit(message(), NOW)
    await repository.offer_next("123", turn_id=turn.turn_id, now=NOW)
    await repository.submit(turn, reserved_tokens=500, now=NOW)
    await repository.fail(turn, code="model_receipt_unknown", unknown=True)
    restarted = await store(path)
    await restarted.enqueue(
        intent("another.fact").model_copy(
            update={"observed_at": NOW + timedelta(days=2), "expires_at": NOW + timedelta(days=3)}
        ),
        NOW + timedelta(days=2),
    )
    restored = (await restarted.questions("123")).questions[0]
    assert restored.question_id == question.question.question_id and restored.status == "held"
    assert (await restarted.quota("123", NOW + timedelta(days=2))).blocked_by_unresolved_request
    with pytest.raises(ParentChatError, match="previous_request_unresolved"):
        await restarted.admit(message(), NOW + timedelta(days=2))


async def test_legacy_history_and_quota_survive_additive_migration(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    legacy, model, source = await make_service(path)
    request = message()
    expected = await legacy.send(request)
    before = await legacy.history("123", before=None, limit=30)
    upgraded = await store(path)
    assert await upgraded.history("123", before=None, limit=30, now=NOW) == before
    assert (await upgraded.admit(request, NOW)).result == expected
    touch_replay = ParentTouchRequest.model_validate(request.model_dump())
    assert (await upgraded.admit(touch_replay, NOW)).result == expected
    assert model.calls == source.calls == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    old_reader = SqliteParentChatStore(path, daily_limit=2000, timezone="Asia/Tashkent")
    with pytest.raises(RuntimeError, match="dedicated database"):
        await old_reader.initialize()
    assert await upgraded.history("123", before=None, limit=30, now=NOW) == before


async def test_expiration_queue_limit_and_paging_are_not_silent_truncation(tmp_path: Path) -> None:
    repository = await store(tmp_path / "limits.db", ceiling=2)
    await repository.enqueue(intent(), NOW)
    await repository.enqueue(intent("another.fact"), NOW)
    with pytest.raises(ParentChatError, match="parent_question_queue_full"):
        await repository.enqueue(intent("third.fact"), NOW)
    first = await repository.questions("123", limit=1)
    assert first.next_after is not None and len(first.questions) == 1
    second = await repository.questions("123", after=first.next_after, limit=1)
    assert (
        second.next_after is None
        and first.questions[0].question_id != second.questions[0].question_id
    )
    late = NOW + timedelta(days=2)
    await repository.enqueue(
        intent("third.fact").model_copy(
            update={"observed_at": late, "expires_at": late + timedelta(days=1)}
        ),
        late,
    )
    assert [q.status for q in (await repository.questions("123")).questions] == [
        "expired",
        "expired",
        "queued",
    ]
    with pytest.raises(ParentChatError, match="question_outside_observation_window"):
        await repository.enqueue(intent("fourth.fact"), late)
    with pytest.raises(ValidationError):
        AgentQuestionRequest.model_validate(intent().model_dump() | {"parent_id": "../123"})


@pytest.mark.parametrize(
    "reply",
    [
        {"body": "First? Second?", "question": None, "question_id": None},
        {"body": "", "question": "First? Second?", "question_id": str(uuid4())},
        {"body": "", "question": "No question boundary", "question_id": str(uuid4())},
        {"body": "", "question": "A question?", "question_id": None},
    ],
)
def test_single_question_reply_contract_refuses_unpaired_or_multiple_questions(
    reply: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ParentTouchModelReply.model_validate(reply)


async def test_foreign_question_decision_keeps_verified_charge_but_publishes_nothing(
    tmp_path: Path,
) -> None:
    repository = await store(tmp_path / "wrong-choice.db")
    await repository.enqueue(intent(), NOW)
    turn = await repository.admit(message(), NOW)
    await repository.submit(turn, reserved_tokens=200, now=NOW)
    with pytest.raises(ParentChatError, match="model_answer_unavailable"):
        await repository.settle(
            turn,
            receipt=ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=20),
                model="fake",
                answer="An unadmitted question?",
                completed=True,
                question_id=uuid4(),
            ),
            now=NOW,
            history_turns=0,
            context_at=NOW,
        )
    history = await repository.history("123", before=None, limit=30, now=NOW)
    assert [entry.role for entry in history.messages] == ["user"]
    assert history.quota.used_tokens == 120 and history.quota.reserved_tokens == 0
    assert (await repository.questions("123")).questions[0].status == "queued"


async def test_question_publication_and_accounting_rollback_as_one_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = await store(tmp_path / "atomic.db")
    await repository.enqueue(intent(), NOW)
    turn = await repository.admit(message(), NOW)
    chosen = await repository.question_for_turn("123", turn.turn_id)
    assert chosen is not None
    await repository.submit(turn, reserved_tokens=200, now=NOW)
    original = repository._on_settled

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Synthetic failure before atomic commit")

    monkeypatch.setattr(repository, "_on_settled", broken)
    with pytest.raises(RuntimeError, match="before atomic commit"):
        await repository.settle(
            turn,
            receipt=ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=20),
                model="fake",
                answer="Question?",
                completed=True,
                question_id=chosen.question_id,
            ),
            now=NOW,
            history_turns=0,
            context_at=NOW,
        )
    history = await repository.history("123", before=None, limit=30, now=NOW)
    assert history.quota.used_tokens == 0 and history.quota.reserved_tokens == 200
    assert [entry.role for entry in history.messages] == ["user"]
    assert (await repository.questions("123")).questions[0].status == "offered"
    monkeypatch.setattr(repository, "_on_settled", original)


async def test_abandoned_pre_inference_offer_recovers_without_releasing_submitted_holds(
    tmp_path: Path,
) -> None:
    repository = await store(tmp_path / "abandoned.db")
    await repository.enqueue(intent(), NOW)
    original = await repository.admit(message(), NOW)
    restarted = await store(tmp_path / "abandoned.db")
    replacement = await restarted.admit(message(), NOW + timedelta(minutes=6))
    question = await restarted.question_for_turn("123", replacement.turn_id)
    assert question is not None and question.offered_turn_id != original.turn_id
    with pytest.raises(ParentChatError, match="request_no_longer_admitted"):
        await repository.submit(original, reserved_tokens=200, now=NOW + timedelta(minutes=6))


async def test_persisted_question_cannot_cross_its_sql_owner_binding(tmp_path: Path) -> None:
    import json

    repository = await store(tmp_path / "corrupt-owner.db")
    await repository.enqueue(intent(), NOW)
    with repository._transaction() as connection:
        row = connection.execute("SELECT payload FROM family_questions").fetchone()
        payload = json.loads(row["payload"]) | {"parent_id": "456"}
        connection.execute("UPDATE family_questions SET payload=?", (json.dumps(payload),))
    with pytest.raises(ParentChatError, match="question_state_unavailable"):
        await repository.questions("123")
