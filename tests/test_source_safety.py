"""Actual SQL/application pipeline with fictional family/source/model only."""

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pytest import MonkeyPatch

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatError
from app.mana_ai.application.deterministic import analyze_deterministically
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.application.source_safety import SourceSafetyService
from app.mana_ai.domain.chat import ChatChild, ParentChildContext
from app.mana_ai.domain.child_safety import SafetyJobView, SafetyTarget
from app.mana_ai.domain.enums import FindingCategory
from app.mana_ai.domain.family_sources import (
    ChildBatteryFacts,
    FamilySourceLimits,
    FamilySourceTarget,
)
from app.mana_ai.domain.requests import ManaAIRequest, SafetyMonitorInput
from app.mana_ai.domain.signals import BatterySignal
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services.commercial_conversation_store import SqliteClosedCommercialConversationStore
from app.services.family_source_store import SqliteFamilySourceStore
from app.services.mana_chat_lab import LAB_CHILD, LAB_PARENT, ChatLab, LabOptions, LabProfiles
from app.services.source_safety_store import SqliteSourceSafetyStore


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 24, 9, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value


@pytest.fixture
async def lab(tmp_path: Path) -> AsyncIterator[tuple[ChatLab, Clock]]:
    clock = Clock()
    runtime = ChatLab(LabOptions(tmp_path / "lab", clock=clock, worker_enabled=False))
    await runtime.start()
    try:
        yield runtime, clock
    finally:
        await runtime.close()


def request() -> FamilySourceTarget:
    return FamilySourceTarget(parent_id=LAB_PARENT, child_id=LAB_CHILD, request_id=uuid4())


async def seed(runtime: ChatLab) -> None:
    result = await runtime.sources.read_child_battery(request())
    assert result.status == "completed"


async def test_source_change_reaches_single_parent_chat_before_first_parent_message(
    lab: tuple[ChatLab, Clock],
) -> None:
    runtime, _ = lab
    await seed(runtime)
    assert (await runtime.state()).history.messages == []
    prepared = await runtime.source_safety.process_one()
    assert prepared and prepared.phase == "prepared"
    work = await runtime.source_store.dispatch_work(LAB_PARENT, prepared.event_id)
    assert work.intent and work.intent.analysis.input.battery[0].online is None
    assert (await runtime.state()).safety_budget.server_used_tokens == 0
    admitted = await runtime.source_safety.process_one()
    assert admitted and admitted.phase == "admitted" and admitted.job_id
    assert (await runtime.state()).history.messages == []
    analysis = await runtime.safety.process_one()
    assert analysis and analysis.status == "completed"
    delivery = await runtime.store.next_delivery(runtime.options.clock.now())
    assert delivery
    response = await runtime.touch.deliver(delivery)
    assert "12%" in response.answer and "подключение неизвестно" in response.answer
    assert "2026-10-24" in response.answer
    state = await runtime.state()
    assert len(state.history.messages) == 1
    assert state.history.messages[0].role == "assistant"
    assert state.history.quota.used_tokens == 150
    assert state.safety_budget.server_used_tokens == 150
    await seed(runtime)  # New caller, same shared source snapshot.
    assert runtime.battery.calls == 1
    assert await runtime.source_safety.process_one() is None
    assert await runtime.safety.process_one() is None
    assert (await runtime.state()).history.messages == state.history.messages
    assert (await runtime.state()).safety_budget.server_used_tokens == 150


@pytest.mark.parametrize("online", [None, True, False])
def test_unknown_battery_connectivity_is_neither_online_nor_offline(online: bool | None) -> None:
    observed = datetime(2026, 10, 24, 9, tzinfo=UTC)
    data = SafetyMonitorInput(
        battery=[
            BatterySignal(evidence_id="battery", observed_at=observed, percent=12, online=online)
        ]
    )
    result = analyze_deterministically(data, evaluated_at=observed)
    offline = [item for item in result.findings if item.category == FindingCategory.DEVICE_OFFLINE]
    assert bool(offline) is (online is False)
    if online is None:
        assert any("does not establish connectivity" in note for note in result.data_quality_notes)


async def test_lost_admission_ack_reconciles_sql_without_another_write(
    lab: tuple[ChatLab, Clock],
    monkeypatch: MonkeyPatch,
) -> None:
    runtime, _ = lab
    await seed(runtime)
    await runtime.source_safety.process_one()
    original, calls = runtime.safety.admit, []

    async def lose(target: SafetyTarget, analysis: ManaAIRequest) -> SafetyJobView:
        calls.append(target.request_id)
        await original(target, analysis)
        raise TimeoutError("fake-lost-local-ack")

    monkeypatch.setattr(runtime.safety, "admit", lose)
    receipt = await runtime.source_safety.process_one()
    assert receipt and receipt.phase == "admitted" and len(calls) == 1
    assert await runtime.source_safety.observe(LAB_PARENT, receipt.event_id) == receipt
    assert await runtime.source_safety.process_one() is None
    assert len((await runtime.state()).assessments.assessments) == 1


async def test_cancelled_admission_preserves_unknown_then_observes_existing_sql_job(
    lab: tuple[ChatLab, Clock],
    monkeypatch: MonkeyPatch,
) -> None:
    runtime, _ = lab
    await seed(runtime)
    prepared = await runtime.source_safety.process_one()
    assert prepared
    original, calls = runtime.safety.admit, []

    async def cancel(target: SafetyTarget, analysis: ManaAIRequest) -> SafetyJobView:
        calls.append(target.request_id)
        await original(target, analysis)
        raise asyncio.CancelledError

    monkeypatch.setattr(runtime.safety, "admit", cancel)
    with pytest.raises(asyncio.CancelledError):
        await runtime.source_safety.process_one()
    work = await runtime.source_store.dispatch_work(LAB_PARENT, prepared.event_id)
    assert work.receipt.phase == "unknown"
    known = await runtime.source_safety.observe(LAB_PARENT, prepared.event_id)
    assert known.phase == "admitted" and known.job_id and len(calls) == 1
    assert runtime.battery.calls == 1
    assert (await runtime.state()).safety_budget.server_used_tokens == 0


async def test_prepared_restart_never_recaptures_ownership_or_source_context(
    lab: tuple[ChatLab, Clock],
    monkeypatch: MonkeyPatch,
) -> None:
    runtime, clock = lab
    await seed(runtime)
    prepared = await runtime.source_safety.process_one()
    assert prepared
    before = await runtime.source_store.dispatch_work(LAB_PARENT, prepared.event_id)
    await runtime.close()
    restored = ChatLab(LabOptions(runtime.options.directory, clock=clock, worker_enabled=False))
    await restored.start()
    try:

        class Forbidden:
            async def read(self, parent_id: str) -> ParentChildContext:
                raise AssertionError("Prepared intent cannot reread profiles")

        monkeypatch.setattr(restored.source_safety, "_children", Forbidden())
        admitted = await restored.source_safety.process_one()
        assert admitted and admitted.phase == "admitted"
        after = await restored.source_store.dispatch_work(LAB_PARENT, admitted.event_id)
        assert before.intent == after.intent
        assert restored.battery.calls == 0
    finally:
        await restored.close()


async def test_unresolved_preparation_never_reissues_profile_read(
    lab: tuple[ChatLab, Clock],
    monkeypatch: MonkeyPatch,
) -> None:
    runtime, _ = lab
    await seed(runtime)
    work = await runtime.source_store.claim_next_dispatch(runtime.options.clock.now())
    assert work and work.receipt.phase == "preparing"
    calls = []

    class Forbidden:
        async def read(self, parent_id: str) -> ParentChildContext:
            calls.append(parent_id)
            raise AssertionError("An already claimed read cannot be restarted")

    monkeypatch.setattr(runtime.source_safety, "_children", Forbidden())
    assert await runtime.source_safety.process_one() is None
    assert calls == []
    assert (
        await runtime.source_safety.observe(LAB_PARENT, work.event.event_id)
    ).phase == "preparing"


@pytest.mark.parametrize("case", ["undated", "stale"])
async def test_undated_or_stale_source_changes_do_not_start_analysis(
    lab: tuple[ChatLab, Clock],
    case: str,
) -> None:
    runtime, clock = lab
    if case == "undated":
        runtime.battery._fixture = runtime.battery._fixture.model_copy(
            update={"observed_at": None, "quality": "unknown_measurement_time"}
        )
    await seed(runtime)
    if case == "stale":
        clock.value += timedelta(hours=7)
    skipped = await runtime.source_safety.process_one()
    assert skipped and skipped.phase == "skipped" and skipped.reason == case
    assert (await runtime.state()).assessments.assessments == []
    assert (await runtime.state()).history.messages == []


async def test_prepared_work_expires_without_an_admission_or_model_call(
    lab: tuple[ChatLab, Clock],
) -> None:
    runtime, clock = lab
    await seed(runtime)
    prepared = await runtime.source_safety.process_one()
    assert prepared and prepared.phase == "prepared"
    clock.value += timedelta(hours=7)
    skipped = await runtime.source_safety.process_one()
    assert skipped and skipped.phase == "skipped" and skipped.reason == "stale"
    assert (await runtime.state()).assessments.assessments == []


async def test_actual_safety_inference_rechecks_revoked_ownership(
    lab: tuple[ChatLab, Clock],
    monkeypatch: MonkeyPatch,
) -> None:
    runtime, clock = lab
    await seed(runtime)
    await runtime.source_safety.process_one()
    admitted = await runtime.source_safety.process_one()
    assert admitted and admitted.phase == "admitted"

    class Revoked:
        async def read(self, parent_id: str) -> ParentChildContext:
            return ParentChildContext(
                parent_id=parent_id,
                children=[ChatChild(child_id=LAB_CHILD, age=8, connected=False)],
                collected_at=clock.now(),
                limitations=[],
            )

    monkeypatch.setattr(runtime.safety, "_children", Revoked())
    failed = await runtime.safety.process_one()
    assert failed and failed.status == "failed" and failed.usage is None
    assert (await runtime.state()).safety_budget.server_used_tokens == 0
    assert (await runtime.state()).history.messages == []


async def test_server_rewrite_without_new_measurement_is_not_another_analysis(
    lab: tuple[ChatLab, Clock],
    tmp_path: Path,
) -> None:
    runtime, clock = lab
    policy = SourceSafetyPolicy()
    store = SqliteSourceSafetyStore(
        tmp_path / "short.sqlite3",
        binding="fake-short-source",
        enabled=True,
        limits=FamilySourceLimits(minimum_interval_seconds=300),
        policy=policy,
    )
    await store.initialize()
    profiles = LabProfiles(clock)
    sources = FamilySourceService(store, profiles, runtime.battery, clock=clock.now)
    bridge = SourceSafetyService(store, runtime.safety, profiles, policy=policy, clock=clock.now)
    await sources.read_child_battery(request())
    await bridge.process_one()
    assert (await bridge.process_one()).phase == "admitted"  # type: ignore[union-attr]
    clock.value += timedelta(minutes=5)
    runtime.battery._fixture = runtime.battery._fixture.model_copy(
        update={"source_updated_at": clock.now() - timedelta(seconds=1)}
    )
    await sources.read_child_battery(request())
    duplicate = await bridge.process_one()
    assert duplicate and duplicate.phase == "skipped" and duplicate.reason == "duplicate"
    assert len((await runtime.state()).assessments.assessments) == 1


async def test_source_v1_migration_never_captures_old_events_or_loses_read_holds(
    tmp_path: Path,
) -> None:
    clock = Clock()
    path = tmp_path / "old.sqlite3"
    binding, limits = "fake-versioned-binding", FamilySourceLimits()
    old = SqliteFamilySourceStore(path, binding=binding, limits=limits)
    await old.initialize()
    completed, pending = request(), request().model_copy(update={"child_id": 900003})
    await old.claim(completed, clock.now())
    earlier = await old.complete(
        completed,
        ChildBatteryFacts(
            child_id=LAB_CHILD,
            status="available",
            percent=12,
            quality="dated",
            observed_at=clock.now() - timedelta(seconds=30),
            source_updated_at=clock.now() - timedelta(seconds=30),
            collected_at=clock.now(),
        ),
        clock.now(),
    )
    await old.claim(pending, clock.now())
    before = await old.observation(pending)
    upgraded = SqliteSourceSafetyStore(
        path, binding=binding, limits=limits, policy=SourceSafetyPolicy(), enabled=True
    )
    await upgraded.initialize()
    assert await upgraded.observation(pending) == before
    assert await upgraded.observation(completed) == earlier
    assert len(await upgraded.changes(LAB_PARENT)) == 1
    assert await upgraded.claim_next_dispatch(clock.now()) is None
    payload = path.read_bytes()
    with pytest.raises(ValueError, match="dedicated"):
        await old.initialize()
    assert path.read_bytes() == payload


async def test_mutated_intent_fails_before_specialist_dispatch(lab: tuple[ChatLab, Clock]) -> None:
    runtime, _ = lab
    await seed(runtime)
    prepared = await runtime.source_safety.process_one()
    assert prepared
    with sqlite3.connect(runtime.options.directory / "sources.sqlite3") as connection:
        raw = json.loads(
            connection.execute("SELECT intent FROM source_safety_dispatches").fetchone()[0]
        )
        raw["analysis"]["input"]["battery"][0]["online"] = True
        connection.execute("UPDATE source_safety_dispatches SET intent=?", (json.dumps(raw),))
    with pytest.raises(ParentChatError, match="source_safety_intent_changed"):
        await runtime.source_safety.process_one()
    assert (await runtime.state()).assessments.assessments == []


async def test_dispatch_observation_cannot_read_another_family(lab: tuple[ChatLab, Clock]) -> None:
    runtime, _ = lab
    await seed(runtime)
    prepared = await runtime.source_safety.process_one()
    assert prepared
    with pytest.raises(ParentChatError, match="source_safety_dispatch_not_found"):
        await runtime.source_safety.observe("900009", prepared.event_id)


async def test_absent_uncertain_admission_never_retries_the_local_write(
    lab: tuple[ChatLab, Clock],
    monkeypatch: MonkeyPatch,
) -> None:
    runtime, _ = lab
    await seed(runtime)
    prepared = await runtime.source_safety.process_one()
    assert prepared
    calls = []

    async def lose(target: SafetyTarget, analysis: ManaAIRequest) -> SafetyJobView:
        calls.append(target.request_id)
        raise TimeoutError("fake-local-admission-outcome-unknown")

    monkeypatch.setattr(runtime.safety, "admit", lose)
    unknown = await runtime.source_safety.process_one()
    assert unknown and unknown.phase == "unknown"
    assert await runtime.source_safety.process_one() is None
    assert await runtime.source_safety.observe(LAB_PARENT, prepared.event_id) == unknown
    assert len(calls) == 1 and (await runtime.state()).assessments.assessments == []


async def test_disabled_source_change_never_acquires_analysis_authority_later(
    lab: tuple[ChatLab, Clock],
    tmp_path: Path,
) -> None:
    runtime, clock = lab
    policy, limits = SourceSafetyPolicy(), FamilySourceLimits()
    path = tmp_path / "disabled.sqlite3"
    disabled = SqliteSourceSafetyStore(
        path, binding="fake-disabled-source", limits=limits, policy=policy, enabled=False
    )
    await disabled.initialize()
    source = FamilySourceService(disabled, LabProfiles(clock), runtime.battery, clock=clock.now)
    await source.read_child_battery(request())
    assert await disabled.claim_next_dispatch(clock.now()) is None
    enabled = SqliteSourceSafetyStore(
        path, binding="fake-disabled-source", limits=limits, policy=policy, enabled=True
    )
    await enabled.initialize()
    bridge = SourceSafetyService(
        enabled, runtime.safety, LabProfiles(clock), policy=policy, clock=clock.now
    )
    skipped = await bridge.process_one()
    assert skipped and skipped.phase == "skipped" and skipped.reason == "not_admitted"
    assert (await runtime.state()).assessments.assessments == []


async def test_preparation_cancel_fence_discards_late_intent_but_retains_history(
    lab: tuple[ChatLab, Clock],
) -> None:
    runtime, clock = lab
    await seed(runtime)
    prepared = await runtime.source_safety.process_one()
    assert prepared and prepared.phase == "prepared"
    unknown = await runtime.source_store.finish_dispatch(
        prepared.event_id, clock.now(), reason="preparation_unknown", unknown=True
    )
    assert await runtime.source_safety.observe(LAB_PARENT, prepared.event_id) == unknown
    assert (await runtime.source_store.dispatch_work(LAB_PARENT, prepared.event_id)).intent
    assert await runtime.source_safety.process_one() is None
    assert (await runtime.state()).assessments.assessments == []


async def test_current_closed_readers_preserve_unknown_model_hold_and_nullable_input(
    lab: tuple[ChatLab, Clock],
    monkeypatch: MonkeyPatch,
) -> None:
    runtime, clock = lab
    await seed(runtime)
    await runtime.source_safety.process_one()
    admitted = await runtime.source_safety.process_one()
    assert admitted
    calls = []

    async def lost(prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        calls.append(max_output_tokens)
        raise TimeoutError("fake-lost-submitted-model-receipt")

    monkeypatch.setattr(runtime.safety._model, "respond", lost)
    failed = await runtime.safety.process_one()
    assert failed and failed.status == "unknown"
    before = await runtime.safety.budget(LAB_PARENT)
    assert before.server_reserved_tokens > 0 and before.server_used_tokens == 0
    closed = SqliteClosedCommercialConversationStore(
        runtime.options.directory / "family.sqlite3",
        history_only=True,
        timezone="Asia/Samarkand",
        daily_limit=2000,
    )
    await closed.initialize()
    clock.value += timedelta(days=3)
    assert (
        await closed.history(LAB_PARENT, before=None, limit=100, now=clock.now())
    ).messages == []
    source_closed = SqliteSourceSafetyStore(
        runtime.options.directory / "sources.sqlite3",
        binding="fake-lab-mana-battery-v1",
        limits=FamilySourceLimits(),
        policy=SourceSafetyPolicy(timezone="Asia/Samarkand"),
        enabled=False,
    )
    await source_closed.initialize()
    assert await source_closed.claim_next_dispatch(clock.now()) is None
    retained = await source_closed.dispatch_work(LAB_PARENT, admitted.event_id)
    assert retained.intent and retained.intent.analysis.input.battery[0].online is None
    assert retained.receipt == admitted
    assert (
        await runtime.safety.budget(LAB_PARENT)
    ).server_reserved_tokens == before.server_reserved_tokens
    assert await runtime.safety.process_one() is None and len(calls) == 1


async def test_source_change_and_consumer_admission_are_one_atomic_commit(
    lab: tuple[ChatLab, Clock],
    monkeypatch: MonkeyPatch,
) -> None:
    runtime, _ = lab

    def broken(connection: sqlite3.Connection, event: object) -> None:
        raise RuntimeError("fake-failed-consumer-admission-write")

    monkeypatch.setattr(runtime.source_store, "_source_changed", broken)
    result = await runtime.sources.read_child_battery(request())
    assert result.status == "unknown" and result.document_units_reserved == 2
    assert await runtime.source_store.changes(LAB_PARENT) == []
    with sqlite3.connect(runtime.options.directory / "sources.sqlite3") as connection:
        for table in ("source_snapshots", "source_heads", "source_safety_admissions"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert (await runtime.state()).assessments.assessments == []
    assert runtime.battery.calls == 1
