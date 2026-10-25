"""Actual private chat workflow; all families, clocks and model receipts are fictional."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from pytest import MonkeyPatch

from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.proactive_parent import ParentContactContext
from app.services.mana_chat_lab import LAB_PARENT, ChatLab, LabOptions
from tests.test_mana_chat_lab import Clock


async def test_retention_reengages_one_inactive_chat_through_parent_touch(tmp_path: Path) -> None:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        LabOptions(
            tmp_path / "lab",
            clock=clock,
            worker_enabled=False,
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
            retention=True,
        )
    )
    await lab.start()
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Спасибо за помощь с учебой."
        )
        await lab.touch.admit_message(request)
        await lab.safety.process_one()
        assert await lab.touch.process_reviewed_message()
        assert not await lab.touch.process_retention()
        clock.value += timedelta(days=15)
        assert lab.touch.proactive
        await lab.touch.proactive.register(
            ParentContactContext(
                parent_id=LAB_PARENT,
                event_id=uuid4(),
                revision=int(clock.now().timestamp() * 1000000),
                observed_at=clock.now(),
                valid_until=clock.now() + timedelta(days=1),
                language="uz-Latn",
                timezone="Asia/Samarkand",
                safety_chat_consent=True,
                safety_push_consent=False,
                marketing_push_consent=False,
                retention_chat_consent=True,
            )
        )
        assert await lab.touch.process_retention()
        state = await lab.state()
        assert len(state.history.messages) == 3
        assert state.history.messages[-1].role == "assistant"
        assert state.history.messages[-1].content.startswith("Avvalgi suhbatimizga")
        assert state.history.quota.used_tokens == 150
        assert state.safety_budget.server_used_tokens == 0  # No new safety inference.
        assert not await lab.touch.process_retention()
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM retention_intents").fetchone()[0] == "published"
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
    finally:
        await lab.close()


async def inactive_lab(path: Path, *, consent: bool = True) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        LabOptions(
            path,
            clock=clock,
            worker_enabled=False,
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
            retention=True,
        )
    )
    await lab.start()
    request = ParentTouchMessageRequest(
        parent_id=LAB_PARENT, request_id=uuid4(), message="Как помочь ребёнку с учебой?"
    )
    await lab.touch.admit_message(request)
    await lab.safety.process_one()
    assert await lab.touch.process_reviewed_message()
    clock.value += timedelta(days=15)
    assert lab.touch.proactive
    await lab.touch.proactive.register(
        ParentContactContext(
            parent_id=LAB_PARENT,
            event_id=uuid4(),
            revision=int(clock.now().timestamp() * 1000000),
            observed_at=clock.now(),
            valid_until=clock.now() + timedelta(days=1),
            language="ru",
            timezone="Asia/Samarkand",
            safety_chat_consent=True,
            safety_push_consent=True,
            marketing_push_consent=True,
            retention_chat_consent=consent,
        )
    )
    return lab, clock


async def test_other_consents_do_not_grant_retention_contact(tmp_path: Path) -> None:
    lab, _ = await inactive_lab(tmp_path / "no-consent", consent=False)
    try:
        assert not await lab.touch.process_retention()
        assert len((await lab.state()).history.messages) == 2
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM retention_intents").fetchone()[0] == 0
    finally:
        await lab.close()


async def test_retention_publication_and_parent_reply_are_one_shared_chat(tmp_path: Path) -> None:
    lab, _ = await inactive_lab(tmp_path / "returned")
    try:
        assert await lab.touch.process_retention()
        response = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Спасибо, уже разобрались."
        )
        await lab.touch.admit_message(response)
        await lab.safety.process_one()
        assert await lab.touch.process_reviewed_message()
        assert not await lab.touch.process_retention()
        assert len((await lab.state()).history.messages) == 5
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM retention_intents").fetchone()[0] == "responded"
            returned = db.execute(
                "SELECT turn_id FROM retention_events WHERE kind='parent_returned_to_chat'"
            ).fetchall()
            assert len(returned) == 1
        await lab.touch.admit_message(response)
        with lab.store._connect() as db:
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM retention_events WHERE kind='parent_returned_to_chat'"
                ).fetchone()[0]
                == 1
            )
    finally:
        await lab.close()


async def test_unknown_retention_model_cannot_reinfer_after_restart_or_midnight(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt

    lab, clock = await inactive_lab(tmp_path / "unknown")
    calls = 0

    async def lost(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        nonlocal calls
        calls += 1
        raise TimeoutError("fictional lost model receipt")

    monkeypatch.setattr(lab.touch._model, "respond", lost)
    try:
        assert await lab.touch.process_retention()
        state = await lab.state()
        assert state.history.quota.reserved_tokens > 0
        held = state.history.quota.reserved_tokens
        assert not await lab.touch.process_retention()
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        clock.value += timedelta(days=1)
        assert not await lab.touch.process_retention()
        assert calls == 1
        assert (await lab.state()).history.quota.blocked_by_unresolved_request
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM retention_intents").fetchone()[0] == "unknown"
            assert (
                db.execute(
                    "SELECT SUM(reserved) FROM parent_chat_turns WHERE status='unknown'"
                ).fetchone()[0]
                == held
            )
    finally:
        await lab.close()


async def test_two_workers_create_one_model_call_and_one_assistant_message(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    import asyncio

    from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt

    lab, _ = await inactive_lab(tmp_path / "race")
    original = lab.touch._model.respond
    calls = 0

    async def slow(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return await original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(lab.touch._model, "respond", slow)
    try:
        results = await asyncio.gather(lab.touch.process_retention(), lab.touch.process_retention())
        assert sum(results) == 1 and calls == 1
        assert len((await lab.state()).history.messages) == 3
    finally:
        await lab.close()


async def test_opt_out_during_generation_fences_late_text_but_keeps_known_usage(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt

    lab, _ = await inactive_lab(tmp_path / "stop-race")
    original = lab.touch._model.respond
    stop = ParentTouchMessageRequest(
        parent_id=LAB_PARENT, request_id=uuid4(), message="не пиши первым"
    )

    async def revoked(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        await lab.touch.admit_message(stop)
        return await original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(lab.touch._model, "respond", revoked)
    try:
        assert await lab.touch.process_retention()
        assert not await lab.touch.process_retention()
        state = await lab.state()
        assert (
            state.history.messages[-1].content == "Больше не буду первым напоминать об этом чате."
        )
        assert state.history.quota.used_tokens == 150 and state.history.quota.reserved_tokens == 0
        assert len(state.history.messages) == 4  # No late check-in; stop request and ack remain.
        assert (await lab.touch.admit_message(stop)).phase == "completed"
        assert len((await lab.state()).history.messages) == 4
    finally:
        await lab.close()


async def test_retention_push_requires_own_permission_and_opt_out_suppresses_queue(
    tmp_path: Path,
) -> None:
    lab, clock = await inactive_lab(tmp_path / "push")
    try:
        lab.store._push_enabled = True  # Claims only; no push gateway in the lab.
        assert await lab.touch.process_retention()
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
        # The above check-in is not repeated for a later consent update.
        assert lab.touch.proactive
        old = await lab.store.contact_context(LAB_PARENT, clock.now())
        assert old
        await lab.touch.proactive.register(
            old.model_copy(
                update={
                    "event_id": uuid4(),
                    "revision": old.revision + 1,
                    "retention_push_consent": True,
                }
            )
        )
        assert not await lab.touch.process_retention()
    finally:
        await lab.close()


async def test_active_specialist_question_has_priority_over_winback(tmp_path: Path) -> None:
    from app.mana_ai.domain.family_agents import AgentQuestionRequest
    from app.services.mana_chat_lab import LAB_CHILD

    lab, clock = await inactive_lab(tmp_path / "question")
    try:
        await lab.touch.request_question(
            AgentQuestionRequest(
                parent_id=LAB_PARENT,
                child_id=LAB_CHILD,
                agent_id="child-safety",
                request_id=uuid4(),
                information_key="school.routine",
                question="Как проходит учёба?",
                reason="Fictional check",
                source_revision="fictional-v1",
                observed_at=clock.now(),
                expires_at=clock.now() + timedelta(hours=1),
            )
        )
        assert not await lab.touch.process_retention()
        assert len((await lab.state()).history.messages) == 2
    finally:
        await lab.close()


async def test_retention_claim_expires_without_reclaiming_source_or_model(tmp_path: Path) -> None:
    from app.services.client_retention_store import SqliteClientRetentionStore

    lab, clock = await inactive_lab(tmp_path / "expired")
    try:
        assert isinstance(lab.store, SqliteClientRetentionStore)
        intent = await lab.store.claim_retention(clock.now())
        assert intent
        clock.value = intent.expires_at + timedelta(seconds=1)
        assert not await lab.touch.process_retention()
        assert len((await lab.state()).history.messages) == 2
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM retention_intents").fetchone()[0] == "unknown"
    finally:
        await lab.close()


async def test_specialist_need_arriving_during_retention_discards_late_text_with_cost(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt
    from app.mana_ai.domain.family_agents import AgentQuestionRequest
    from app.services.mana_chat_lab import LAB_CHILD

    lab, clock = await inactive_lab(tmp_path / "safety-race")
    original = lab.touch._model.respond

    async def pending(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        await lab.touch.request_question(
            AgentQuestionRequest(
                parent_id=LAB_PARENT,
                child_id=LAB_CHILD,
                agent_id="child-safety",
                request_id=uuid4(),
                information_key="safety.check",
                question="Ребёнок сейчас в безопасности?",
                reason="Fictional urgent need",
                source_revision="fictional-urgent-v1",
                observed_at=clock.now(),
                expires_at=clock.now() + timedelta(hours=1),
            )
        )
        return await original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(lab.touch._model, "respond", pending)
    try:
        assert await lab.touch.process_retention()
        state = await lab.state()
        assert len(state.history.messages) == 2
        assert state.history.quota.used_tokens == 150 and state.history.quota.reserved_tokens == 0
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM retention_intents").fetchone()[0] == "suppressed"
    finally:
        await lab.close()


async def test_simulation_retention_fixture_is_one_shot_and_uses_real_message_workflow(
    tmp_path: Path,
) -> None:
    lab, clock = await inactive_lab(tmp_path / "seed-existing")
    try:
        import pytest

        from app.mana_ai.application.chat_ports import ParentChatError

        with pytest.raises(ParentChatError, match="lab_retention_requires_empty_history"):
            await lab.prepare_retention_scenario()
    finally:
        await lab.close()
    lab = ChatLab(
        LabOptions(
            tmp_path / "seed-new",
            clock=clock,
            worker_enabled=False,
            native_sources=True,
            native_observations=True,
            source_reviews=True,
            reminders=True,
            retention=True,
        )
    )
    await lab.start()
    try:
        assert (await lab.prepare_retention_scenario())["status"] == "prepared"
        assert await lab.touch.process_retention()
        assert (await lab.prepare_retention_scenario())["status"] == "already_prepared"
        assert not await lab.touch.process_retention()
        assert len((await lab.state()).history.messages) == 3
    finally:
        await lab.close()


async def test_retention_respects_quiet_hours_before_any_claim(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    lab, clock = await inactive_lab(tmp_path / "quiet")
    try:
        clock.value = clock.value.replace(hour=18)  # 23:00 in verified recipient zone.
        assert not await lab.touch.process_retention()
        with lab.store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM retention_intents").fetchone()[0] == 0
        clock.value = datetime.combine(
            clock.value.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC
        ) + timedelta(hours=4)
        assert await lab.touch.process_retention()
        assert not await lab.touch.process_retention()
    finally:
        await lab.close()


async def test_retention_does_not_gain_inference_when_parent_quota_is_exhausted(
    tmp_path: Path,
) -> None:
    lab, _ = await inactive_lab(tmp_path / "quota")
    try:
        with lab.store._transaction() as db:
            day, _ = lab.store._period(lab.options.clock.now())
            db.execute(
                "INSERT OR REPLACE INTO parent_chat_quota(parent_id,day,used,attempts) "
                "VALUES(?,?,2000,0)",
                (LAB_PARENT, day),
            )
        assert await lab.touch.process_retention()
        assert not await lab.touch.process_retention()
        assert len((await lab.state()).history.messages) == 2
        stop = await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT, request_id=uuid4(), message="stop check-ins"
            )
        )
        assert stop.response and stop.response.answer == "I will stop initiating chat check-ins."
        assert (await lab.state()).history.quota.used_tokens == 2000
    finally:
        await lab.close()
