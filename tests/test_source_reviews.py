"""Coalesced source snapshots use the real family queue and fictional providers/model."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from pytest import MonkeyPatch

from app.mana_ai.application.source_reviews import SourceReviewService
from app.mana_ai.domain.family_sources import FamilySourceTarget
from app.services.mana_chat_lab import LAB_CHILD, LAB_PARENT, ChatLab, LabOptions
from app.services.source_review_cache import SqliteSourceReviewCache
from app.services.source_review_safety_store import SqliteSourceReviewSafetyStore
from tests.test_mana_chat_lab import Clock


async def setup(path: Path) -> tuple[ChatLab, Clock, SourceReviewService]:
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
        )
    )
    await lab.start()
    assert isinstance(lab.source_store, SqliteSourceReviewCache)
    assert isinstance(lab.store, SqliteSourceReviewSafetyStore)
    service = SourceReviewService(
        lab.source_store,
        lab.store,
        lab.safety._children,
        clock=clock.now,
        available=lambda: lab.safety.worker_available,
    )
    return lab, clock, service


async def read_pair(lab: ChatLab) -> None:
    for source in ("firebase.child_battery.v1", "manakids.child_app_usage.v1"):
        receipt = await lab.sources.read(
            FamilySourceTarget(
                parent_id=LAB_PARENT,
                child_id=LAB_CHILD,
                request_id=uuid4(),
                source=source,
            )
        )
        assert receipt.status == "completed"


async def test_two_source_changes_become_one_metered_review_and_one_parent_notice(
    tmp_path: Path,
) -> None:
    lab, clock, service = await setup(tmp_path / "lab")
    try:
        await read_pair(lab)
        assert await service.process_one() is None
        clock.value += timedelta(seconds=4)
        prepared = await service.process_one()
        assert prepared and prepared.phase == "prepared" and len(prepared.bundle.snapshots) == 2
        admitted = await service.process_one()
        assert admitted and admitted.phase == "admitted"
        job = await lab.safety.process_one()
        assert job and job.status == "completed", job
        assert job.kind == "source_review" and job.result and job.result.source_review_notify
        assert job.signal_first_observed_at is None and job.signal_last_observed_at is None
        request = await lab.store.next_delivery(clock.now())
        assert request is not None
        answer = await lab.touch.deliver(request)
        assert "не экранное время за день" in answer.answer
        state = await lab.state()
        assert len(state.history.messages) == 1 and state.history.messages[0].role == "assistant"
        assert state.safety_budget.server_used_tokens == 150
        assert lab.battery.calls == lab.app_usage.calls == 1
        assert await service.process_one() is None
        assert await lab.safety.process_one() is None
    finally:
        await lab.close()


async def test_native_chat_source_read_does_not_trigger_a_second_background_analysis(
    tmp_path: Path,
) -> None:
    from app.mana_ai.domain.family_agents import ParentTouchMessageRequest

    lab, clock, service = await setup(tmp_path / "native")
    try:
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="В каких приложениях ребёнок проводит время?",
        )
        await lab.touch.admit_message(request)
        job = await lab.safety.process_one()
        assert job and job.status == "completed" and job.usage and job.usage.total == 300
        await lab.touch.process_reviewed_message()
        clock.value += timedelta(seconds=4)
        assert await service.process_one() is None
        assert await lab.safety.process_one() is None
        with lab.source_store._connection() as db:
            assert db.execute("SELECT phase FROM review_events").fetchall()[0][0] == "native"
            assert db.execute("SELECT COUNT(*) FROM review_owners").fetchone()[0] == 1
        assert lab.app_usage.calls == 1 and lab.battery.calls == 0
        assert (await lab.state()).safety_budget.server_used_tokens == 300
    finally:
        await lab.close()


async def test_recollecting_unchanged_facts_cannot_create_another_review(tmp_path: Path) -> None:
    lab, clock, service = await setup(tmp_path / "same-facts")
    try:
        await read_pair(lab)
        clock.value += timedelta(seconds=4)
        prepared = await service.process_one()
        assert prepared and prepared.phase == "prepared"
        admitted = await service.process_one()
        assert admitted and admitted.phase == "admitted"
        job = await lab.safety.process_one()
        assert job and job.status == "completed"
        clock.value += timedelta(hours=6)
        await read_pair(lab)
        clock.value += timedelta(seconds=4)
        assert await service.process_one() is None
        assert await lab.safety.process_one() is None
        assert lab.battery.calls == lab.app_usage.calls == 2
        assert (await lab.state()).safety_budget.server_used_tokens == 150
    finally:
        await lab.close()


async def test_unknown_model_receipt_keeps_hold_and_original_job_across_restart(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    import httpx

    path = tmp_path / "unknown"
    lab, clock, service = await setup(path)
    try:
        await read_pair(lab)
        clock.value += timedelta(seconds=4)
        await service.process_one()
        await service.process_one()

        async def lost(*args: object, **kwargs: object) -> object:
            raise httpx.ReadTimeout("Synthetic model receipt lost")

        monkeypatch.setattr(lab.safety._model, "respond", lost)
        job = await lab.safety.process_one()
        assert job and job.status == "unknown"
        budget = await lab.safety.budget(LAB_PARENT)
        assert budget.server_reserved_tokens > 0 and budget.server_used_tokens == 0
        held = budget.server_reserved_tokens
    finally:
        await lab.close()
    restarted = ChatLab(
        LabOptions(
            path,
            clock=clock,
            worker_enabled=False,
            native_sources=True,
            native_observations=True,
            source_reviews=True,
        )
    )
    await restarted.start()
    try:
        assert (await restarted.safety.budget(LAB_PARENT)).server_reserved_tokens == held
        clock.value += timedelta(days=1)
        assert (await restarted.safety.budget(LAB_PARENT)).server_reserved_tokens == held
        assert await restarted.safety.process_one() is None
        assert restarted.app_usage.calls == restarted.battery.calls == 0
        assert (await restarted.state()).history.messages == []
    finally:
        await restarted.close()


async def test_ownership_revocation_after_capture_prevents_analysis_and_contact(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from app.mana_ai.domain.chat import ParentChildContext

    lab, clock, service = await setup(tmp_path / "revoked")
    try:
        await read_pair(lab)
        clock.value += timedelta(seconds=4)

        async def revoked(parent_id: str) -> ParentChildContext:
            return ParentChildContext(
                parent_id=parent_id, children=[], collected_at=clock.now(), limitations=[]
            )

        monkeypatch.setattr(service._children, "read", revoked)
        result = await service.process_one()
        assert result and result.phase == "skipped" and result.reason == "ownership_or_age_unknown"
        assert await lab.safety.process_one() is None
        assert (await lab.state()).safety_budget.server_used_tokens == 0
    finally:
        await lab.close()


async def test_native_cache_hit_consumes_a_queued_same_snapshot_before_background_capture(
    tmp_path: Path,
) -> None:
    from app.mana_ai.domain.family_agents import ParentTouchMessageRequest

    lab, clock, service = await setup(tmp_path / "cached-native")
    try:
        receipt = await lab.sources.read(
            FamilySourceTarget(
                parent_id=LAB_PARENT,
                child_id=LAB_CHILD,
                request_id=uuid4(),
                source="manakids.child_app_usage.v1",
            )
        )
        assert receipt.status == "completed"
        await lab.touch.admit_message(
            ParentTouchMessageRequest(
                parent_id=LAB_PARENT,
                request_id=uuid4(),
                message="В каких приложениях ребёнок проводит время?",
            )
        )
        job = await lab.safety.process_one()
        assert job and job.status == "completed"
        clock.value += timedelta(seconds=4)
        assert await service.process_one() is None and lab.app_usage.calls == 1
        assert (await lab.state()).safety_budget.server_used_tokens == 300
    finally:
        await lab.close()


async def test_invalid_source_decision_is_metered_and_never_retried(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt
    from app.mana_ai.domain.chat import ChatTokens

    lab, clock, service = await setup(tmp_path / "invalid")
    try:
        await read_pair(lab)
        clock.value += timedelta(seconds=4)
        await service.process_one()
        await service.process_one()

        async def invalid(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
            return ChatModelReceipt(
                usage=ChatTokens(input_tokens=100, output_tokens=50),
                model="fake-invalid-decision",
                answer="{}",
                completed=True,
            )

        monkeypatch.setattr(lab.safety._model, "respond", invalid)
        job = await lab.safety.process_one()
        assert job and job.status == "failed" and job.error_code == "safety_invalid_decision"
        budget = await lab.safety.budget(LAB_PARENT)
        assert budget.server_used_tokens == 150 and budget.server_reserved_tokens == 0
        assert await service.process_one() is None and await lab.safety.process_one() is None
        assert (await lab.state()).history.messages == []
    finally:
        await lab.close()


async def test_lost_committed_review_admission_ack_is_reconciled_without_reissue(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from datetime import datetime

    from app.mana_ai.domain.child_safety import SafetyJobView
    from app.mana_ai.domain.source_reviews import SourceReviewWork

    lab, clock, service = await setup(tmp_path / "lost-ack")
    try:
        assert isinstance(lab.store, SqliteSourceReviewSafetyStore)
        await read_pair(lab)
        clock.value += timedelta(seconds=4)
        await service.process_one()
        original = lab.store.admit_source_review
        calls = 0

        async def lose(work: SourceReviewWork, now: datetime, *, allow_new: bool) -> SafetyJobView:
            nonlocal calls
            calls += 1
            await original(work, now, allow_new=allow_new)
            raise RuntimeError("Synthetic committed admission acknowledgement loss")

        monkeypatch.setattr(lab.store, "admit_source_review", lose)
        result = await service.process_one()
        assert result and result.phase == "admitted"
        assert await service.process_one() is None and calls == 1
        job = await lab.safety.process_one()
        assert job and job.status == "completed"
    finally:
        await lab.close()


async def test_ordinary_source_push_waits_for_quiet_hours_before_claim(
    tmp_path: Path,
) -> None:
    from datetime import UTC, datetime

    from app.mana_ai.domain.proactive_parent import ParentContactContext

    clock = Clock()
    clock.value = datetime(2026, 10, 24, 3, 59, tzinfo=UTC)  # 08:59 in verified recipient zone.
    lab = ChatLab(
        LabOptions(
            tmp_path / "quiet",
            clock=clock,
            worker_enabled=False,
            native_sources=True,
            native_observations=True,
            source_reviews=True,
        )
    )
    await lab.start()
    try:
        assert isinstance(lab.source_store, SqliteSourceReviewCache)
        assert isinstance(lab.store, SqliteSourceReviewSafetyStore)
        lab.store._push_enabled = True  # No gateway exists; claims alone are observed.
        assert lab.touch.proactive is not None
        await lab.touch.proactive.register(
            ParentContactContext(
                parent_id=LAB_PARENT,
                event_id=uuid4(),
                revision=int(clock.now().timestamp() * 1000000) + 1,
                observed_at=clock.now(),
                valid_until=clock.now() + timedelta(days=1),
                language="ru",
                timezone="Asia/Samarkand",
                safety_chat_consent=True,
                safety_push_consent=True,
                marketing_push_consent=False,
            )
        )
        service = SourceReviewService(
            lab.source_store,
            lab.store,
            lab.safety._children,
            clock=clock.now,
            available=lambda: True,
        )
        await read_pair(lab)
        clock.value += timedelta(seconds=4)
        await service.process_one()
        await service.process_one()
        job = await lab.safety.process_one()
        assert job and job.status == "completed"
        delivery = await lab.store.next_delivery(clock.now())
        assert delivery is not None
        await lab.touch.deliver(delivery)
        assert await lab.store.claim_push(clock.now()) is None
        with lab.store._connect() as db:
            push = db.execute("SELECT status,claimed_at FROM parent_push_outbox").fetchone()
            assert tuple(push) == ("queued", None)
        clock.value = datetime(2026, 10, 24, 4, tzinfo=UTC)
        assert await lab.store.claim_push(clock.now()) is not None
        assert lab.touch.proactive._gateway is None
    finally:
        await lab.close()


async def test_lost_preparation_claim_expires_to_unknown_without_repeating_profile_read(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    lab, clock, service = await setup(tmp_path / "lost-preparation")
    try:
        assert isinstance(lab.source_store, SqliteSourceReviewCache)
        await read_pair(lab)
        clock.value += timedelta(seconds=4)
        work = await lab.source_store.claim_next_review(clock.now())
        assert work and work.phase == "preparing"
        clock.value += timedelta(seconds=181)

        async def forbidden(parent_id: str) -> object:
            raise AssertionError("An uncertain ownership read must never be redispatched")

        monkeypatch.setattr(service._children, "read", forbidden)
        assert await service.process_one() is None
        records = await lab.source_store.reviews(LAB_PARENT)
        assert records[0].phase == "unknown" and records[0].reason == "preparation_unknown"
        assert await lab.safety.process_one() is None
        assert (await lab.state()).safety_budget.server_used_tokens == 0
    finally:
        await lab.close()
