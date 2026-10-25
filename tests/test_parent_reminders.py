"""Actual single-chat/SQL assistant lifecycle; all families/providers/models are fictional."""

from datetime import UTC, timedelta
from pathlib import Path
from uuid import uuid4

from pytest import MonkeyPatch

from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.services.mana_chat_lab import LAB_PARENT, ChatLab, LabOptions
from app.services.parent_reminder_store import SqliteParentReminderStore
from tests.test_mana_chat_lab import Clock


async def setup(path: Path) -> tuple[ChatLab, Clock]:
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
        )
    )
    await lab.start()
    return lab, clock


async def propose(
    lab: ChatLab, message: str = "Напомни завтра в 9 купить тетради"
) -> ParentTouchMessageRequest:
    request = ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=message)
    admitted = await lab.touch.admit_message(request)
    assert admitted.phase == "awaiting_review"
    job = await lab.safety.process_one()
    assert job and job.status == "completed"
    assert await lab.touch.process_reviewed_message()
    result = await lab.touch.message_state(LAB_PARENT, request.request_id)
    assert result.phase == "completed", result
    return request


async def test_reminder_is_confirmed_in_chat_and_delivered_once_without_extra_inference(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "lab")
    try:
        assert isinstance(lab.store, SqliteParentReminderStore)
        await propose(lab)
        state = await lab.state()
        pending = state.history.active_confirmation
        assert pending and pending.kind == "approval"
        assert "Asia/Samarkand" in state.history.messages[-1].content
        assert state.history.reminders[0].status == "draft"
        used = state.history.quota.used_tokens
        safety_used = state.safety_budget.server_used_tokens
        confirm = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Да",
            reply_to_confirmation_id=pending.confirmation_id,
        )
        done = await lab.touch.admit_message(confirm)
        assert (
            done.phase == "completed" and done.response and "запланировано" in done.response.answer
        )
        state = await lab.state()
        assert state.history.active_confirmation is None
        assert state.history.reminders[0].status == "scheduled"
        assert state.history.quota.used_tokens == used
        assert state.safety_budget.server_used_tokens == safety_used
        due = pending.candidate.due_at
        assert due is not None
        clock.value = due.astimezone(UTC) + timedelta(seconds=1)
        assert await lab.touch.process_reminders()
        assert not await lab.touch.process_reminders()
        state = await lab.state()
        assert (
            len(state.history.messages) == 5
        )  # Two parent messages, their replies and one due reminder.
        assert state.history.messages[-1].content == "Напоминание: «купить тетради»."
        assert state.history.quota.used_tokens == 0  # Delivery falls on the next local quota day.
        with lab.store._connect() as db:
            assert db.execute("SELECT SUM(used) FROM parent_chat_quota").fetchone()[0] == used
        assert (await lab.touch.admit_message(confirm)).phase == "completed"
        assert len((await lab.state()).history.messages) == 5
        assert lab.touch.proactive and lab.touch.proactive._gateway is None
    finally:
        await lab.close()


async def confirm_and_due(lab: ChatLab, clock: Clock) -> None:
    await propose(lab)
    pending = (await lab.state()).history.active_confirmation
    assert pending and pending.candidate.due_at
    await lab.touch.admit_message(
        ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Да",
            reply_to_confirmation_id=pending.confirmation_id,
        )
    )
    clock.value = pending.candidate.due_at.astimezone(UTC) + timedelta(seconds=1)


async def test_date_clarification_and_cancellation_use_no_model_after_quota_exhaustion(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "dates")
    try:
        await propose(lab, "Напомни позже купить тетради")
        pending = (await lab.state()).history.active_confirmation
        assert pending and pending.kind == "details"
        with lab.store._transaction() as db:
            db.execute("UPDATE parent_chat_quota SET used=2000 WHERE parent_id=?", (LAB_PARENT,))
        response = await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT,
                request_id=uuid4(),
                message="завтра в 10:30",
                reply_to_confirmation_id=pending.confirmation_id,
            )
        )
        assert response.phase == "completed"
        state = await lab.state()
        replacement = state.history.active_confirmation
        assert replacement and replacement.confirmation_id != pending.confirmation_id
        assert replacement.candidate.due_at and replacement.candidate.due_at.hour == 10
        await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT,
                request_id=uuid4(),
                message="Да",
                reply_to_confirmation_id=replacement.confirmation_id,
            )
        )
        cancelled = await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT,
                request_id=uuid4(),
                message="отмени последнее напоминание",
            )
        )
        assert cancelled.response and "отменено" in cancelled.response.answer
        assert not (await lab.state()).history.reminders
        assert (await lab.state()).history.quota.used_tokens == 2000
        assert not await lab.touch.process_reminders()
    finally:
        await lab.close()


async def test_confirmation_is_parent_bound_stale_safe_and_requires_actual_yes(
    tmp_path: Path,
) -> None:
    import pytest

    from app.mana_ai.application.chat_ports import ParentChatError

    lab, _ = await setup(tmp_path / "binding")
    try:
        await propose(lab)
        pending = (await lab.state()).history.active_confirmation
        assert pending
        for parent, confirmation in (("900002", pending.confirmation_id), (LAB_PARENT, uuid4())):
            with pytest.raises(ParentChatError, match="assistant_confirmation_not_active"):
                await lab.touch.admit_message(
                    ParentTouchMessageRequest(
                        parent_id=parent,
                        request_id=uuid4(),
                        message="Да",
                        reply_to_confirmation_id=confirmation,
                    )
                )
        declined = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Нет",
            reply_to_confirmation_id=pending.confirmation_id,
        )
        assert (await lab.touch.admit_message(declined)).phase == "completed"
        assert not (await lab.state()).history.reminders
        assert (await lab.touch.admit_message(declined)).phase == "completed"
        with pytest.raises(ParentChatError, match="assistant_confirmation_not_active"):
            await lab.touch.admit_message(declined.model_copy(update={"request_id": uuid4()}))
    finally:
        await lab.close()


async def test_new_chat_during_profile_check_defers_publication_without_rereading(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from app.mana_ai.domain.chat import ParentChildContext

    lab, clock = await setup(tmp_path / "race")
    try:
        await confirm_and_due(lab, clock)
        assert lab.touch.reminders
        source = lab.touch.reminders._children.read
        calls = 0
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Как лучше обсудить уроки?"
        )

        async def racing(parent: str) -> ParentChildContext:
            nonlocal calls
            calls += 1
            context = await source(parent)
            await lab.touch.admit_message(request)
            return context

        monkeypatch.setattr(lab.touch.reminders._children, "read", racing)
        assert await lab.touch.process_reminders()
        state = await lab.state()
        assert state.history.reminders[0].status == "ready"
        assert state.history.messages[-1].role == "user"
        assert not await lab.touch.process_reminders()
        monkeypatch.setattr(lab.touch.reminders._children, "read", source)
        await lab.safety.process_one()
        assert await lab.touch.process_reviewed_message()
        assert await lab.touch.process_reminders()
        assert calls == 1
        assert (await lab.state()).history.messages[-1].content.startswith("Напоминание:")
        assert not await lab.touch.process_reminders()
    finally:
        await lab.close()


async def test_cancel_during_check_and_late_auth_error_close_source_without_contact(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from app.mana_ai.application.chat_ports import ParentChatError

    lab, clock = await setup(tmp_path / "cancel-race")
    try:
        await confirm_and_due(lab, clock)
        assert lab.touch.reminders

        async def cancelled(parent: str) -> object:
            await lab.touch.admit_message(
                ParentTouchMessageRequest(
                    parent_id=parent,
                    request_id=uuid4(),
                    message="отмени последнее напоминание",
                )
            )
            raise ParentChatError("child_source_auth_denied", 503)

        monkeypatch.setattr(lab.touch.reminders._children, "read", cancelled)
        assert await lab.touch.process_reminders()
        assert not await lab.touch.process_reminders()
        state = await lab.state()
        assert not state.history.reminders
        assert state.history.messages[-1].content == "Напоминание отменено."
        with lab.store._connect() as db:
            assert db.execute("SELECT backend_blocked FROM assistant_policy").fetchone()[0]
            assert (
                db.execute("SELECT status FROM assistant_deliveries").fetchone()[0] == "cancelled"
            )
    finally:
        await lab.close()


async def test_lost_ownership_reply_stays_unknown_across_restart_without_read_retry(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    lab, clock = await setup(tmp_path / "lost")
    try:
        await confirm_and_due(lab, clock)
        assert lab.touch.reminders
        calls = 0

        async def lost(parent: str) -> object:
            nonlocal calls
            calls += 1
            raise TimeoutError("fictional transport lost")

        monkeypatch.setattr(lab.touch.reminders._children, "read", lost)
        assert await lab.touch.process_reminders()
        assert not await lab.touch.process_reminders()
        assert calls == 1
        assert (await lab.state()).history.reminders[0].status == "unknown"
        await lab.close()
        lab = ChatLab(lab.options)
        await lab.start()
        assert not await lab.touch.process_reminders()
        assert (await lab.state()).history.reminders[0].status == "unknown"
        assert len((await lab.state()).history.messages) == 4
    finally:
        await lab.close()


async def test_delivery_claim_is_single_and_unacknowledged_lease_never_retries(
    tmp_path: Path,
) -> None:
    import asyncio

    lab, clock = await setup(tmp_path / "claim")
    try:
        await confirm_and_due(lab, clock)
        assert isinstance(lab.store, SqliteParentReminderStore)
        claims = await asyncio.gather(
            lab.store.claim_due_reminder(clock.now()), lab.store.claim_due_reminder(clock.now())
        )
        assert sum(c is not None for c in claims) == 1
        claim = next(c for c in claims if c)
        clock.value = claim.lease_expires_at + timedelta(seconds=1)
        assert await lab.store.claim_due_reminder(clock.now()) is None
        await lab.store.finish_due_reminder(
            claim, clock.now(), verified_parent=True, context_at=clock.now()
        )
        assert (await lab.state()).history.reminders[0].status == "unknown"
        assert len((await lab.state()).history.messages) == 4
    finally:
        await lab.close()


async def test_assistant_push_has_separate_consent_and_quiet_hour_claim(tmp_path: Path) -> None:
    from datetime import datetime

    from app.mana_ai.domain.proactive_parent import ParentContactContext

    lab, clock = await setup(tmp_path / "assistant-push")
    try:
        await confirm_and_due(lab, clock)
        assert isinstance(lab.store, SqliteParentReminderStore)
        lab.store._push_enabled = True  # Claims only; the lab still has no gateway.
        assert lab.touch.proactive
        contact = ParentContactContext(
            parent_id=LAB_PARENT,
            event_id=uuid4(),
            revision=int(clock.now().timestamp() * 1000000),
            observed_at=clock.now(),
            valid_until=clock.now() + timedelta(days=1),
            language="ru",
            timezone="Asia/Kabul",
            safety_chat_consent=True,
            safety_push_consent=True,
            marketing_push_consent=True,
            assistant_push_consent=True,
        )
        await lab.touch.proactive.register(contact)
        assert await lab.touch.process_reminders()
        with lab.store._connect() as db:
            row = db.execute("SELECT purpose,status,claimed_at FROM parent_push_outbox").fetchone()
            assert tuple(row) == ("assistant", "queued", None)
        assert await lab.store.claim_push(clock.now()) is None
        clock.value = datetime.combine(
            clock.now().date(), datetime.min.time(), tzinfo=UTC
        ) + timedelta(hours=4, minutes=30)
        assert await lab.store.claim_push(clock.now()) is not None
        assert await lab.store.claim_push(clock.now()) is None
        assert lab.touch.proactive._gateway is None
    finally:
        await lab.close()


async def test_safety_or_marketing_consent_cannot_authorize_assistant_push(tmp_path: Path) -> None:
    from app.mana_ai.domain.proactive_parent import ParentContactContext

    lab, clock = await setup(tmp_path / "no-push")
    try:
        await confirm_and_due(lab, clock)
        assert isinstance(lab.store, SqliteParentReminderStore)
        lab.store._push_enabled = True
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
            )
        )
        assert await lab.touch.process_reminders()
        with lab.store._connect() as db:
            assert not db.execute("SELECT 1 FROM parent_push_outbox").fetchone()
        assert (await lab.state()).history.messages[-1].content.startswith("Напоминание:")
    finally:
        await lab.close()


async def test_unknown_speaker_cost_is_not_reset_by_host_controls_or_midnight(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt

    lab, clock = await setup(tmp_path / "unknown-model")
    try:

        async def lost(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
            raise TimeoutError("fictional unknown model receipt")

        monkeypatch.setattr(lab.touch._model, "respond", lost)
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Напомни завтра купить тетради"
        )
        await lab.touch.admit_message(request)
        await lab.safety.process_one()
        assert await lab.touch.process_reviewed_message()
        before = (await lab.state()).history.quota
        assert before.reserved_tokens > 0
        control = await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT, request_id=uuid4(), message="мои напоминания"
            )
        )
        assert control.phase == "completed"
        clock.value += timedelta(days=1)
        state = await lab.state()
        assert state.history.quota.blocked_by_unresolved_request
        with lab.store._connect() as db:
            assert (
                db.execute("SELECT SUM(reserved) FROM parent_chat_turns").fetchone()[0]
                == before.reserved_tokens
            )
        assert not state.history.reminders
        assert len(state.history.messages) == 3  # Lost parent request plus host request/reply.
    finally:
        await lab.close()
