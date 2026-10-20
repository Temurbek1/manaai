import asyncio
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.domain.chat import ChatTokens, ParentChatRequest
from app.mana_ai.domain.child_safety import (
    ChildSafetyLimits,
    SafetyJob,
    SafetyStoredResult,
    SafetyTarget,
)
from app.mana_ai.domain.enums import AgeBand, AnalysisStatus, AnalysisVerdict, ManaAICapability
from app.mana_ai.domain.family_agents import ParentTouchDeliveryRequest, ParentTouchRequest
from app.mana_ai.domain.requests import (
    BehaviourAnomalyInput,
    BehaviourAnomalyRequest,
    SafetyMonitorInput,
    SafetyMonitorRequest,
)
from app.mana_ai.domain.responses import ManaAIAnalysisResult, SafetyMonitorDetails
from app.mana_ai.domain.signals import BatterySignal, SubjectContext
from app.services.child_safety_store import SqliteChildSafetyStore
from tests.test_family_agent_queue import intent
from tests.test_parent_chat import NOW, Children, message
from tests.test_parent_touch_api import TouchModel


def limits(**changes: int) -> ChildSafetyLimits:
    return ChildSafetyLimits.model_validate(
        {
            "server_daily_tokens": 2000,
            "parent_daily_tokens": 1000,
            "job_tokens": 500,
        }
        | changes
    )


async def store(path: Path, **changes: int) -> SqliteChildSafetyStore:
    repository = SqliteChildSafetyStore(
        path, limits=limits(**changes), daily_limit=2000, timezone="Asia/Tashkent"
    )
    await repository.initialize()
    return repository


def analysis(child: int = 124, *, percent: int = 75) -> SafetyMonitorRequest:
    return SafetyMonitorRequest(
        request_id="synthetic-input",
        occurred_at=NOW,
        locale="ru",
        data_minimized=True,
        subject=SubjectContext(
            subject_id=str(child), age_band=AgeBand.AGE_7_12, timezone="Asia/Tashkent"
        ),
        input=SafetyMonitorInput(
            battery=[BatterySignal(evidence_id="battery", observed_at=NOW, percent=percent)]
        ),
    )


def target(parent: str = "123") -> SafetyTarget:
    return SafetyTarget(
        parent_id=parent, child_id=int(parent) + 1, request_id=uuid4(), source_revision="v1"
    )


def result(request: SafetyMonitorRequest) -> SafetyStoredResult:
    return SafetyStoredResult(
        analysis=ManaAIAnalysisResult(
            request_id=request.request_id,
            processed_at=NOW,
            capability=ManaAICapability.SAFETY_MONITOR,
            status=AnalysisStatus.COMPLETED,
            verdict=AnalysisVerdict.INSUFFICIENT_DATA,
            summary="Synthetic historical result, not a current measurement.",
            details=SafetyMonitorDetails(parent_context="Synthetic", significant_event_count=0),
            findings=[],
            checks=[],
            data_quality_notes=[],
            proposed_actions=[],
            model_name="fake-model",
        )
    )


async def submitted(repository: SqliteChildSafetyStore, job: SafetyJob) -> None:
    await repository.authorize_children(job, (job.view.child_id or 124,), NOW)
    await repository.submit_safety(job, 300, NOW)


async def test_content_and_chat_revision_dedup_precede_any_new_admission(tmp_path: Path) -> None:
    repository = await store(tmp_path / "dedup.db")
    original, request = target(), analysis()
    first = await repository.admit_analysis(target=original, analysis=request, now=NOW)
    assert await repository.admit_analysis(target=original, analysis=request, now=NOW) == first
    changed_metadata = request.model_copy(
        update={
            "locale": "uz",
            "request_id": "new-nonce",
            "occurred_at": NOW + timedelta(minutes=1),
        }
    )
    duplicate = await repository.admit_analysis(
        target=original.model_copy(
            update={"request_id": uuid4(), "source_revision": "different-label"}
        ),
        analysis=changed_metadata,
        now=NOW,
    )
    assert duplicate == first
    represented_elsewhere = request.model_copy(
        update={
            "input": SafetyMonitorInput(
                battery=[
                    request.input.battery[0].model_copy(
                        update={"observed_at": NOW.astimezone(timezone(timedelta(hours=5)))}
                    )
                ]
            )
        }
    )
    assert (
        await repository.admit_analysis(target=target(), analysis=represented_elsewhere, now=NOW)
    ).job_id == first.job_id
    with pytest.raises(ParentChatError, match="request_id_conflict"):
        await repository.admit_analysis(target=original, analysis=analysis(percent=60), now=NOW)
    await repository.admit(message(text="New parent context"), NOW)
    # New parent text has its own outbox trigger; resending old signals is not
    # another data event and must not pay for the same full analysis again.
    assert (
        await repository.admit_analysis(target=target(), analysis=request, now=NOW)
    ).job_id == first.job_id
    newer = await repository.admit_analysis(target=target(), analysis=analysis(percent=60), now=NOW)
    assert newer.job_id != first.job_id and newer.parent_turn_cutoff > first.parent_turn_cutoff
    with pytest.raises(ParentChatError, match="not_found"):
        await repository.assessment("456", first.job_id)


async def test_global_budget_and_one_active_parent_are_atomic_between_workers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "race.db"
    first, second = (
        await store(path, server_daily_tokens=500, parent_daily_tokens=500),
        await store(path, server_daily_tokens=500, parent_daily_tokens=500),
    )
    for parent in ("123", "456"):
        await first.admit_analysis(
            target=target(parent), analysis=analysis(int(parent) + 1), now=NOW
        )
    outcomes = await asyncio.gather(first.claim_next(NOW), second.claim_next(NOW))
    jobs = [job for job in outcomes if job is not None]
    assert len(jobs) == 1
    job = jobs[0]
    assert job.reserved_tokens == 500 and job.claim_id
    budget = await second.safety_budget(job.view.parent_id, NOW)
    assert budget.server_reserved_tokens == 500 and budget.server_remaining_tokens == 0
    await submitted(first, job)
    await first.fail_safety(job, "synthetic_timeout", NOW)
    assert await second.claim_next(NOW) is None
    assert (await first.quota(job.view.parent_id, NOW)).used_tokens == 0


async def test_unknown_hold_survives_midnight_and_late_verified_receipt_cannot_publish(
    tmp_path: Path,
) -> None:
    path = tmp_path / "unknown.db"
    repository = await store(path)
    original = target()
    view = await repository.admit_analysis(target=original, analysis=analysis(), now=NOW)
    job = await repository.claim_next(NOW)
    assert job is not None
    await submitted(repository, job)
    await repository.fail_safety(job, "synthetic_timeout", NOW)
    next_day = NOW + timedelta(days=1)
    restarted = await store(path)
    budget = await restarted.safety_budget("123", next_day)
    assert budget.server_reserved_tokens == budget.parent_reserved_tokens == 300
    assert budget.parent_used_tokens == 0 and budget.parent_blocked_by_unknown
    assert await restarted.admit_analysis(
        target=original, analysis=analysis(), now=next_day
    ) == await restarted.assessment("123", view.job_id)
    assert await restarted.claim_next(next_day) is None
    assert not await restarted.record_usage(
        job, ChatTokens(input_tokens=100, output_tokens=50), "fake", next_day
    )
    known = await restarted.assessment("123", view.job_id)
    assert known.status == "failed" and known.usage and known.usage.total == 150
    assert known.error_code == "safety_late_receipt_discarded"
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT analysis FROM child_safety_jobs").fetchone()[0] is None
    assert (await restarted.safety_budget("123", next_day)).server_reserved_tokens == 0
    assert (await restarted.safety_budget("123", NOW)).server_used_tokens == 150
    with pytest.raises(ParentChatError, match="no_longer_claimed"):
        await restarted.finish_safety(job, result(analysis()), next_day)
    with pytest.raises(ParentChatError, match="already_settled"):
        await restarted.record_usage(
            job, ChatTokens(input_tokens=1, output_tokens=0), "fake", next_day
        )


async def test_verified_usage_is_retained_when_the_decision_is_invalid(tmp_path: Path) -> None:
    repository = await store(tmp_path / "invalid.db")
    view = await repository.admit_analysis(target=target(), analysis=analysis(), now=NOW)
    job = await repository.claim_next(NOW)
    assert job is not None
    with pytest.raises(ParentChatError, match="no_longer_claimed"):
        await repository.submit_safety(job, 300, NOW)  # No fresh child authorization yet.
    with pytest.raises(ParentChatError, match="not_authorized"):
        await repository.authorize_children(job, (999,), NOW)
    await submitted(repository, job)
    assert await repository.record_usage(
        job, ChatTokens(input_tokens=100, output_tokens=50), "fake", NOW
    )
    await repository.fail_safety(job, "safety_invalid_decision", NOW)
    state = await repository.assessment("123", view.job_id)
    assert state.status == "failed" and state.usage and state.usage.total == 150
    assert (await repository.safety_budget("123", NOW)).parent_used_tokens == 150
    assert (await repository.quota("123", NOW)).used_tokens == 0
    with sqlite3.connect(repository._path) as connection:
        assert connection.execute("SELECT analysis FROM child_safety_jobs").fetchone()[0] is None


async def test_abandoned_preparation_fails_without_source_or_model_replay(tmp_path: Path) -> None:
    repository = await store(tmp_path / "abandoned.db")
    original = target()
    first = await repository.admit_analysis(target=original, analysis=analysis(), now=NOW)
    job = await repository.claim_next(NOW)
    assert job
    later = NOW + timedelta(minutes=6)
    assert await repository.claim_next(later) is None
    recovered = await repository.assessment("123", first.job_id)
    assert recovered.status == "failed" and recovered.error_code == "safety_preparation_abandoned"
    assert (await repository.safety_budget("123", later)).server_reserved_tokens == 0
    assert (
        await repository.admit_analysis(
            target=original.model_copy(update={"request_id": uuid4()}),
            analysis=analysis(),
            now=later,
        )
    ).job_id == first.job_id
    with pytest.raises(ParentChatError, match="no_longer_claimed"):
        await repository.authorize_children(job, (124,), later)


async def test_question_and_safety_result_commit_together_then_parent_touch_owns_the_conversation(
    tmp_path: Path,
) -> None:
    repository = await store(tmp_path / "loop.db")
    view = await repository.admit_analysis(target=target(), analysis=analysis(), now=NOW)
    job = await repository.claim_next(NOW)
    assert job
    await submitted(repository, job)
    await repository.record_usage(job, ChatTokens(input_tokens=100, output_tokens=50), "fake", NOW)
    completed = await repository.finish_safety(job, result(analysis()), NOW, question=intent())
    assert completed.status == "completed" and completed.result and completed.result.question_id
    assert (await repository.history("123", before=None, limit=30, now=NOW)).messages == []
    model, children = TouchModel(), Children()
    touch = ParentTouchService(
        store=repository,
        model=model,
        children=children,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    question = await touch.send_touch(
        ParentTouchRequest.model_validate(message(text="Salom").model_dump())
    )
    assert (
        question.asked_question
        and question.asked_question.question_id == completed.result.question_id
    )
    event = await repository.materialize_parent_event(NOW)
    assert event and event.kind == "parent_message" and event.parent_turn_cutoff == 1
    assert await repository.materialize_parent_event(NOW) is None
    followup = await repository.claim_next(NOW)
    assert followup and followup.view.job_id == event.job_id
    assert [m.content for m in followup.context.messages] == ["Salom"]
    assert followup.context.saved_assessment_ids == [view.job_id]
    await touch.send_touch(
        ParentTouchRequest(
            parent_id="123",
            request_id=uuid4(),
            message="Soat to'qqizda",
            reply_to_question_id=question.asked_question.question_id,
        )
    )
    assert (await repository.questions("123")).questions[0].status == "answered"
    assert followup.context.messages[0].content == "Salom"  # Frozen before the new answer.
    assert (await repository.safety_budget("123", NOW)).parent_used_tokens == 150
    assert (await repository.quota("123", NOW)).used_tokens == 300


async def test_outbox_replays_get_and_assistant_deliveries_never_trigger_more_safety_jobs(
    tmp_path: Path,
) -> None:
    repository, model, children = await store(tmp_path / "events.db"), TouchModel(), Children()
    touch = ParentTouchService(
        store=repository,
        model=model,
        children=children,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    original = message(text="Здравствуйте")
    await touch.send(original)
    await touch.send(original)
    await repository.enqueue(intent(), NOW)
    await touch.deliver(ParentTouchDeliveryRequest(parent_id="123", request_id=uuid4()))
    await touch.history("123", before=None, limit=30)
    await touch.read_touch_history("123", before=None, limit=30)
    event = await repository.materialize_parent_event(NOW)
    assert event and event.parent_turn_cutoff == 1
    assert await repository.materialize_parent_event(NOW) is None


async def test_ambiguous_protective_input_round_trips_its_actual_capability(tmp_path: Path) -> None:
    repository = await store(tmp_path / "contract.db")
    base = analysis()
    request = BehaviourAnomalyRequest(
        **base.model_dump(exclude={"input"}),
        input=BehaviourAnomalyInput(battery=base.input.battery),
    )
    await repository.admit_analysis(target=target(), analysis=request, now=NOW)
    job = await repository.claim_next(NOW)
    assert job and isinstance(job.analysis, BehaviourAnomalyRequest)
    assert job.analysis.input.capability == ManaAICapability.BEHAVIOUR_ANOMALY


async def test_result_queue_failure_rolls_back_result_not_earlier_verified_cost(
    tmp_path: Path,
) -> None:
    repository = await store(tmp_path / "rollback.db")
    view = await repository.admit_analysis(target=target(), analysis=analysis(), now=NOW)
    job = await repository.claim_next(NOW)
    assert job
    await submitted(repository, job)
    await repository.record_usage(job, ChatTokens(input_tokens=100, output_tokens=50), "fake", NOW)
    transaction = repository._transaction

    @contextmanager
    def fail_commit() -> Iterator[sqlite3.Connection]:
        with transaction() as connection:
            yield connection
            raise sqlite3.OperationalError("Synthetic failing commit")

    repository._transaction = fail_commit  # type: ignore[method-assign]
    with pytest.raises(sqlite3.OperationalError):
        await repository.finish_safety(job, result(analysis()), NOW, question=intent())
    repository._transaction = transaction  # type: ignore[method-assign]
    assert (await repository.assessment("123", view.job_id)).status == "metered"
    assert not (await repository.questions("123")).questions
    assert (await repository.safety_budget("123", NOW)).parent_used_tokens == 150


def test_explicit_budgets_and_typed_family_targets_are_required() -> None:
    for raw in (
        {},
        {"server_daily_tokens": 300, "parent_daily_tokens": 200, "job_tokens": 201},
        {"server_daily_tokens": True, "parent_daily_tokens": 100, "job_tokens": 64},
    ):
        with pytest.raises(ValidationError):
            ChildSafetyLimits.model_validate(raw)
    with pytest.raises(ValidationError):
        SafetyTarget(parent_id="0123", child_id=124, request_id=uuid4(), source_revision="v1")


async def test_overspent_verified_receipt_is_never_overwritten_or_released(tmp_path: Path) -> None:
    repository = await store(tmp_path / "overspend.db")
    view = await repository.admit_analysis(target=target(), analysis=analysis(), now=NOW)
    job = await repository.claim_next(NOW)
    assert job
    await submitted(repository, job)
    assert not await repository.record_usage(
        job, ChatTokens(input_tokens=300, output_tokens=50), "fake", NOW
    )
    state = await repository.assessment("123", view.job_id)
    assert state.status == "unknown" and state.error_code == "safety_usage_exceeded_hold"
    assert state.usage and state.usage.total == 350
    with pytest.raises(ParentChatError, match="already_settled"):
        await repository.record_usage(job, ChatTokens(input_tokens=1, output_tokens=0), "fake", NOW)
    await repository.fail_safety(job, "ignored", NOW)
    budget = await repository.safety_budget("123", NOW)
    assert budget.server_used_tokens == 350 and budget.parent_blocked_by_unknown
    assert await repository.claim_next(NOW) is None


async def test_only_classified_preinference_rejection_can_release_a_submitted_hold(
    tmp_path: Path,
) -> None:
    repository = await store(tmp_path / "reject.db")
    original = target()
    view = await repository.admit_analysis(target=original, analysis=analysis(), now=NOW)
    job = await repository.claim_next(NOW)
    assert job
    await submitted(repository, job)
    with pytest.raises(ParentChatError, match="not_classified"):
        await repository.fail_safety(
            job, "arbitrary_provider_error", NOW, definite_model_rejection=True
        )
    assert (await repository.safety_budget("123", NOW)).server_reserved_tokens == 300
    await repository.fail_safety(job, "model_request_rejected", NOW, definite_model_rejection=True)
    state = await repository.assessment("123", view.job_id)
    assert state.status == "failed" and state.usage is None
    assert (await repository.safety_budget("123", NOW)).server_reserved_tokens == 0
    assert (
        await repository.admit_analysis(target=original, analysis=analysis(), now=NOW)
    ).status == "failed"
    assert await repository.claim_next(NOW) is None


async def test_metered_result_processing_remains_single_flight_without_holding_cost_twice(
    tmp_path: Path,
) -> None:
    repository = await store(tmp_path / "metered.db")
    await repository.admit_analysis(target=target(), analysis=analysis(), now=NOW)
    await repository.admit_analysis(target=target(), analysis=analysis(percent=60), now=NOW)
    job = await repository.claim_next(NOW)
    assert job
    await submitted(repository, job)
    await repository.record_usage(job, ChatTokens(input_tokens=100, output_tokens=50), "fake", NOW)
    assert await repository.claim_next(NOW) is None
    budget = await repository.safety_budget("123", NOW)
    assert budget.server_used_tokens == 150 and budget.server_reserved_tokens == 0
    await repository.fail_safety(job, "safety_invalid_decision", NOW)
    assert await repository.claim_next(NOW) is not None


async def test_queue_capacity_and_expiry_never_repeat_input_work(
    tmp_path: Path,
) -> None:
    repository = await store(
        tmp_path / "capacity.db", max_pending_jobs=1, max_parent_pending_jobs=1
    )
    original = target()
    first = await repository.admit_analysis(target=original, analysis=analysis(), now=NOW)
    with pytest.raises(ParentChatError, match="queue_full"):
        await repository.admit_analysis(target=target(), analysis=analysis(percent=60), now=NOW)
    assert await repository.claim_next(NOW + timedelta(hours=2)) is None
    assert (await repository.assessment("123", first.job_id)).error_code == "safety_queue_expired"
    duplicate = await repository.admit_analysis(
        target=original.model_copy(update={"request_id": uuid4()}),
        analysis=analysis(),
        now=NOW + timedelta(hours=2),
    )
    assert duplicate.job_id == first.job_id and duplicate.status == "failed"
    assert (await repository.safety_budget("123", NOW)).server_used_tokens == 0


async def test_queue_owns_no_new_action_when_the_question_child_is_foreign(tmp_path: Path) -> None:
    repository = await store(tmp_path / "foreign.db")
    view = await repository.admit_analysis(target=target(), analysis=analysis(), now=NOW)
    job = await repository.claim_next(NOW)
    assert job
    await submitted(repository, job)
    await repository.record_usage(job, ChatTokens(input_tokens=100, output_tokens=50), "fake", NOW)
    with pytest.raises(ParentChatError, match="scope_mismatch"):
        await repository.finish_safety(job, result(analysis()), NOW, question=intent(child=999))
    assert not (await repository.questions("123")).questions
    assert (await repository.assessment("123", view.job_id)).status == "metered"


async def test_v3_upgrade_keeps_history_unknown_holds_and_does_not_recapture_old_chat(
    tmp_path: Path,
) -> None:
    from tests.test_family_agent_queue import store as family_store

    path = tmp_path / "upgrade.db"
    old, model, children = await family_store(path), TouchModel(), Children()
    service = ParentTouchService(
        store=old,
        children=children,
        model=model,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    original = message()
    expected = await service.send(original)
    model.error = TimeoutError("Synthetic lost receipt")
    with pytest.raises(ParentChatError):
        await service.send(message(text="New parent message"))
    before = await old.history("123", before=None, limit=30, now=NOW)
    upgraded = await store(path)
    assert await upgraded.history("123", before=None, limit=30, now=NOW) == before
    assert (await upgraded.admit(original, NOW)).result == expected
    assert await upgraded.materialize_parent_event(NOW) is None
    assert before.quota.blocked_by_unresolved_request
    assert (await upgraded.safety_budget("123", NOW)).server_reserved_tokens == 0
    with pytest.raises(RuntimeError, match="dedicated database"):
        await old.initialize()


async def test_parent_event_admission_is_atomic_with_the_parent_message(tmp_path: Path) -> None:
    repository = await store(tmp_path / "atomic.db")
    original_hook = repository._on_admitted

    def broken_hook(
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        now: datetime,
    ) -> None:
        original_hook(connection, request, turn_id, now)
        raise sqlite3.OperationalError("Synthetic admission rollback")

    repository._on_admitted = broken_hook  # type: ignore[method-assign]
    with pytest.raises(sqlite3.OperationalError):
        await repository.admit(message(), NOW)
    repository._on_admitted = original_hook  # type: ignore[method-assign]
    assert not (await repository.history("123", before=None, limit=30, now=NOW)).messages
    assert await repository.materialize_parent_event(NOW) is None


async def test_attempt_ceiling_is_separate_from_token_usage_and_resets_only_by_day(
    tmp_path: Path,
) -> None:
    repository = await store(
        tmp_path / "attempts.db", parent_daily_attempts=1, max_queue_age_seconds=86_400
    )
    await repository.admit_analysis(target=target(), analysis=analysis(), now=NOW)
    second = await repository.admit_analysis(
        target=target(), analysis=analysis(percent=60), now=NOW
    )
    job = await repository.claim_next(NOW)
    assert job
    await repository.fail_safety(job, "safety_source_unavailable", NOW)
    assert await repository.claim_next(NOW) is None
    assert (await repository.safety_budget("123", NOW)).parent_used_tokens == 0
    next_day = NOW + timedelta(hours=8)  # After the Asia/Tashkent date boundary.
    resumed = await repository.claim_next(next_day)
    assert resumed and resumed.view.job_id == second.job_id


async def test_completed_result_must_belong_to_the_exact_original_request(tmp_path: Path) -> None:
    repository = await store(tmp_path / "result-owner.db")
    view = await repository.admit_analysis(target=target(), analysis=analysis(), now=NOW)
    job = await repository.claim_next(NOW)
    assert job
    await submitted(repository, job)
    await repository.record_usage(job, ChatTokens(input_tokens=100, output_tokens=50), "fake", NOW)
    foreign = result(analysis().model_copy(update={"request_id": "another-request"}))
    with pytest.raises(ParentChatError, match="result_mismatch"):
        await repository.finish_safety(job, foreign, NOW)
    assert (await repository.assessment("123", view.job_id)).result is None
    assert (await repository.safety_budget("123", NOW)).parent_used_tokens == 150


async def test_dated_metadata_survives_raw_input_cleanup_and_future_signals_are_denied(
    tmp_path: Path,
) -> None:
    repository = await store(tmp_path / "dates.db")
    request = analysis()
    old_signal = request.input.battery[0].model_copy(
        update={"observed_at": NOW - timedelta(days=2)}
    )
    dated = request.model_copy(update={"input": SafetyMonitorInput(battery=[old_signal])})
    view = await repository.admit_analysis(target=target(), analysis=dated, now=NOW)
    job = await repository.claim_next(NOW)
    assert job
    await submitted(repository, job)
    await repository.record_usage(job, ChatTokens(input_tokens=100, output_tokens=50), "fake", NOW)
    done = await repository.finish_safety(job, result(dated), NOW)
    assert done.job_id == view.job_id and done.evaluated_at == NOW
    assert done.signal_first_observed_at == done.signal_last_observed_at == NOW - timedelta(days=2)
    future = old_signal.model_copy(update={"observed_at": NOW + timedelta(days=1)})
    with pytest.raises(ParentChatError, match="observation_in_future"):
        await repository.admit_analysis(
            target=target(),
            analysis=request.model_copy(update={"input": SafetyMonitorInput(battery=[future])}),
            now=NOW,
        )


async def test_new_chat_context_includes_assistant_only_questions_without_reanalyzing_old_data(
    tmp_path: Path,
) -> None:
    repository, model, children = await store(tmp_path / "full-chat.db"), TouchModel(), Children()
    touch = ParentTouchService(
        store=repository,
        model=model,
        children=children,
        clock=lambda: NOW,
        max_output_tokens=512,
        history_turn_limit=2,
    )
    await touch.send(message(text="Здравствуйте"))
    await repository.enqueue(intent(), NOW)
    delivery = await touch.deliver(ParentTouchDeliveryRequest(parent_id="123", request_id=uuid4()))
    pending = await repository.admit_analysis(target=target(), analysis=analysis(), now=NOW)
    job = await repository.claim_next(NOW)
    assert job and job.view.job_id == pending.job_id
    assert job.context.chat_turn_cutoff > job.view.parent_turn_cutoff
    assert job.context.messages[-1].role == "assistant"
    assert job.context.messages[-1].content == delivery.answer
    assert not any(not m.content for m in job.context.messages)
    # Frozen historical results load only exact same-family references.
    assert await repository.saved_assessments(job) == []


async def test_exhausted_prefix_cannot_starve_an_eligible_family(tmp_path: Path) -> None:
    repository = await store(tmp_path / "dispatch-fairness.db", parent_daily_attempts=1)
    for parent in ("123", "456", "789"):
        for percent in range(20):
            await repository.admit_analysis(
                target=target(parent), analysis=analysis(int(parent) + 1, percent=percent), now=NOW
            )
    last = await repository.admit_analysis(target=target("999"), analysis=analysis(1000), now=NOW)
    for _ in range(3):
        job = await repository.claim_next(NOW)
        assert job
        await repository.fail_safety(job, "safety_source_unavailable", NOW)
    eligible = await repository.claim_next(NOW)
    assert eligible and eligible.view.job_id == last.job_id


async def test_full_parent_queues_cannot_starve_a_later_parent_message(tmp_path: Path) -> None:
    repository = await store(tmp_path / "outbox-fairness.db", max_parent_pending_jobs=1)
    for parent in ("123", "456", "789"):
        await repository.admit_analysis(
            target=target(parent), analysis=analysis(int(parent) + 1), now=NOW
        )
        for _ in range(17):
            turn = await repository.admit(message(parent), NOW)
            await repository.fail(turn, code="synthetic_failed_parent_reply")
    await repository.admit(message("999"), NOW)
    eligible = await repository.materialize_parent_event(NOW)
    assert eligible and eligible.parent_id == "999"
