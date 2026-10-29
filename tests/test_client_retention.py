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
                "VALUES(?,?,5000,0)",
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
        assert (await lab.state()).history.quota.used_tokens == 5000
    finally:
        await lab.close()


async def test_retention_resume_round_trips_mobile_chat_without_inference_or_source(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    import httpx

    from scripts.mana_chat_lab import create_app
    from tests.test_mana_chat_lab import BASE, PREFIX, session

    lab, _ = await inactive_lab(tmp_path / "resume-mobile")
    options = lab.options
    await lab.close()
    app = create_app(options=options)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client,
    ):
        runtime = app.state.chat_lab

        async def forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("Preference controls must not read a source or infer")

        monkeypatch.setattr(runtime.touch._model, "count_input", forbidden)
        monkeypatch.setattr(runtime.touch._model, "respond", forbidden)
        monkeypatch.setattr(runtime.touch._children, "read", forbidden)
        headers = await session(client)
        stopped = {
            "parent_id": LAB_PARENT,
            "request_id": str(uuid4()),
            "message": "stop check-ins",
        }
        resumed = {
            "parent_id": LAB_PARENT,
            "request_id": str(uuid4()),
            "message": "resume chat check-ins",
        }
        for body in (stopped, resumed):
            admitted = await client.post(
                PREFIX + "/parent-touch/messages", headers=headers, json=body
            )
            assert admitted.status_code == 202 and admitted.json()["phase"] == "completed"
            observed = await client.get(
                PREFIX + f"/parent-touch/messages/{body['request_id']}?parent_id={LAB_PARENT}"
            )
            assert observed.status_code == 200 and observed.json() == admitted.json()
        before = (await client.get(PREFIX + f"/parent-touch/chat?parent_id={LAB_PARENT}")).json()
        assert len(before["messages"]) == 6
        assert before["messages"][-1]["content"] == (
            "I can initiate chat check-ins again when your verified settings allow it."
        )
        # Replaying an old stop cannot overwrite the later parent choice.
        replay = await client.post(PREFIX + "/parent-touch/messages", headers=headers, json=stopped)
        assert replay.status_code == 202 and replay.json()["phase"] == "completed"
        assert (
            await client.get(PREFIX + f"/parent-touch/chat?parent_id={LAB_PARENT}")
        ).json() == before
        assert not await runtime.touch.process_retention()
        with runtime.store._connect() as db:
            assert not db.execute("SELECT 1 FROM retention_opt_outs").fetchone()
            assert not db.execute("SELECT 1 FROM retention_intents").fetchone()
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM retention_events WHERE kind='parent_resumed_check_ins'"
                ).fetchone()[0]
                == 1
            )


async def test_resume_changes_only_future_retention_preference_not_verified_consent(
    tmp_path: Path,
) -> None:
    lab, clock = await inactive_lab(tmp_path / "resume-consent", consent=False)
    try:
        for text in ("не пиши первым", "возобнови напоминания об этом чате"):
            result = await lab.touch.admit_message(
                ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=text)
            )
            assert result.phase == "completed"
        assert not await lab.touch.process_retention()
        clock.value += timedelta(days=15)
        assert lab.touch.proactive
        contact = await lab.store.contact_context(LAB_PARENT, clock.now() - timedelta(days=15))
        assert contact and not contact.retention_chat_consent
        current = contact.model_copy(
            update={
                "event_id": uuid4(),
                "revision": contact.revision + 1,
                "observed_at": clock.now(),
                "valid_until": clock.now() + timedelta(days=1),
            }
        )
        await lab.touch.proactive.register(current)
        assert not await lab.touch.process_retention()
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM retention_intents").fetchone()
        await lab.touch.proactive.register(
            current.model_copy(
                update={
                    "event_id": uuid4(),
                    "revision": current.revision + 1,
                    "retention_chat_consent": True,
                }
            )
        )
        assert await lab.touch.process_retention()
        assert not await lab.touch.process_retention()
        assert (await lab.state()).history.quota.used_tokens == 150
    finally:
        await lab.close()


async def test_replaying_old_resume_does_not_remove_newer_refusal(tmp_path: Path) -> None:
    lab, _ = await inactive_lab(tmp_path / "resume-replay")
    try:
        resume = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="bu chat haqida yana eslatib turing"
        )
        first = await lab.touch.admit_message(resume)
        assert first.response and first.response.answer.startswith("Sozlamalaringiz")
        stop = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="birinchi bo‘lib yozmang"
        )
        await lab.touch.admit_message(stop)
        assert await lab.touch.admit_message(resume) == first
        with lab.store._connect() as db:
            assert db.execute(
                "SELECT 1 FROM retention_opt_outs WHERE parent_id=?", (LAB_PARENT,)
            ).fetchone()
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM retention_events WHERE kind='parent_resumed_check_ins'"
                ).fetchone()[0]
                == 1
            )
        assert not await lab.touch.process_retention()
    finally:
        await lab.close()


async def test_stop_then_resume_during_inference_cannot_resurrect_priced_outreach(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt

    lab, _ = await inactive_lab(tmp_path / "resume-race")
    original = lab.touch._model.respond

    async def changed(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        for text in ("не пиши первым", "снова напоминай об этом чате"):
            result = await lab.touch.admit_message(
                ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=text)
            )
            assert result.phase == "completed"
        return await original(prompt, max_output_tokens=max_output_tokens)

    monkeypatch.setattr(lab.touch._model, "respond", changed)
    try:
        assert await lab.touch.process_retention()
        assert not await lab.touch.process_retention()
        state = await lab.state()
        assert len(state.history.messages) == 6  # Original pair plus two control pairs only.
        assert state.history.quota.used_tokens == 150
        assert state.history.quota.reserved_tokens == 0
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM retention_intents").fetchone()[0] == "suppressed"
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
    finally:
        await lab.close()


async def test_resume_retains_unknown_model_hold_over_restart_and_midnight(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt

    lab, clock = await inactive_lab(tmp_path / "resume-unknown")
    calls = 0

    async def lost(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        nonlocal calls
        calls += 1
        raise TimeoutError("fictional lost retention response")

    monkeypatch.setattr(lab.touch._model, "respond", lost)
    try:
        assert await lab.touch.process_retention()
        held = (await lab.state()).history.quota.reserved_tokens
        assert held > 0
        for text in ("stop check-ins", "start chat check-ins again"):
            result = await lab.touch.admit_message(
                ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=text)
            )
            assert result.phase == "completed"
        options = lab.options
        await lab.close()
        clock.value += timedelta(days=1)
        lab = ChatLab(options)
        await lab.start()
        assert not await lab.touch.process_retention()
        state = await lab.state()
        assert state.history.quota.blocked_by_unresolved_request
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM retention_intents").fetchone()[0] == "unknown"
            assert (
                db.execute(
                    "SELECT SUM(reserved) FROM parent_chat_turns WHERE status='unknown'"
                ).fetchone()[0]
                == held
            )
        assert calls == 1
    finally:
        await lab.close()


async def test_resume_never_restores_suppressed_push_or_answers_a_safety_question(
    tmp_path: Path,
) -> None:
    from app.mana_ai.domain.family_agents import AgentQuestionRequest
    from app.services.mana_chat_lab import LAB_CHILD

    lab, clock = await inactive_lab(tmp_path / "resume-priority")
    try:
        assert lab.touch.proactive
        contact = await lab.store.contact_context(LAB_PARENT, clock.now())
        assert contact
        await lab.touch.proactive.register(
            contact.model_copy(
                update={
                    "event_id": uuid4(),
                    "revision": contact.revision + 1,
                    "retention_push_consent": True,
                }
            )
        )
        lab.store._push_enabled = True  # SQL outbox only; the lab has no push gateway.
        assert await lab.touch.process_retention()
        await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT, request_id=uuid4(), message="stop check-ins"
            )
        )
        question = await lab.touch.request_question(
            AgentQuestionRequest(
                parent_id=LAB_PARENT,
                child_id=LAB_CHILD,
                agent_id="child-safety",
                request_id=uuid4(),
                information_key="safety.current_status",
                question="Ребёнок сейчас в безопасности?",
                reason="Fictional safety clarification",
                source_revision="fictional-v1",
                observed_at=clock.now(),
                expires_at=clock.now() + timedelta(hours=1),
            )
        )
        await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT,
                request_id=uuid4(),
                message="resume chat check-ins",
                reply_to_question_id=question.question.question_id,
            )
        )
        assert not await lab.touch.process_retention()
        with lab.store._connect() as db:
            assert db.execute("SELECT status FROM parent_push_outbox").fetchone()[0] == "suppressed"
            saved = db.execute(
                "SELECT status,answer_turn_id FROM family_questions WHERE question_id=?",
                (str(question.question.question_id),),
            ).fetchone()
            assert saved[0] == "queued" and saved[1] is None
    finally:
        await lab.close()


async def test_resume_observes_host_command_ceiling_without_losing_refusal(
    tmp_path: Path,
) -> None:
    import pytest

    from app.mana_ai.application.chat_ports import ParentChatError
    from app.services.client_retention_store import SqliteClientRetentionStore

    lab, clock = await inactive_lab(tmp_path / "resume-command-limit")
    try:
        assert isinstance(lab.store, SqliteClientRetentionStore)
        stop = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="stop check-ins"
        )
        await lab.touch.admit_message(stop)
        with lab.store._transaction() as db:
            for _ in range(lab.store._reminder_policy.parent_commands_per_24h):
                lab.store._assistant_event(
                    db, LAB_PARENT, None, "host_message_published", clock.now()
                )
        with pytest.raises(ParentChatError, match="assistant_command_limit_exceeded"):
            await lab.touch.admit_message(
                ParentTouchMessageRequest(
                    parent_id=LAB_PARENT, request_id=uuid4(), message="resume chat check-ins"
                )
            )
        assert (await lab.touch.admit_message(stop)).phase == "completed"
        with lab.store._connect() as db:
            assert db.execute("SELECT 1 FROM retention_opt_outs").fetchone()
            assert not db.execute(
                "SELECT 1 FROM retention_events WHERE kind='parent_resumed_check_ins'"
            ).fetchone()
    finally:
        await lab.close()
