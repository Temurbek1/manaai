"""Native saved-only inspection has no external-source claim, refresh or retry fallback."""

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.source_tool_ports import SourceModelReceipt, SourceToolPrompt
from app.mana_ai.application.source_tool_workflow import SourceToolWorkflow
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest
from app.mana_ai.domain.family_sources import (
    FamilySourceLimits,
    FamilySourceTarget,
    ObservedSourceKey,
)
from app.mana_ai.domain.saved_observations import (
    SavedObservationLimits,
    SavedObservationReceipt,
    SavedObservationTarget,
)
from app.mana_ai.domain.source_tools import SavedObservationCall, SourceToolChild, SourceToolScope
from app.services.child_source_model import OpenAIChildSourceModel
from app.services.lab_workspace import workspace_options
from app.services.mana_chat_lab import LAB_CHILD, LAB_PARENT, ChatLab
from app.services.saved_observation_reader import SqliteSavedObservationReader
from app.services.saved_observation_safety_store import (
    SqliteClosedSavedObservationSafetyStore,
    SqliteSavedObservationSafetyStore,
)
from app.services.source_review_cache import SqliteSourceReviewCache
from tests.test_mana_chat_lab import Clock


def snapshot(path: Path) -> dict[str, list[tuple[Any, ...]]]:
    with sqlite3.connect(path) as db:
        return {
            name: db.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
            for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


async def setup(
    path: Path,
    *,
    enabled: bool = True,
    followups: bool = False,
    limits: SavedObservationLimits | None = None,
) -> tuple[ChatLab, Clock]:
    clock = Clock()
    clock.value = Clock.value
    lab = ChatLab(
        replace(
            workspace_options(path, clock=clock, worker_enabled=False),
            tariff_handoff=True,
            compact_inputs=True,
            compact_publication=True,
            compact_manager=True,
            saved_observations=enabled,
            tariff_followups=followups,
            saved_observation_limits=limits or SavedObservationLimits(),
        )
    )
    await lab.start()
    return lab, clock


def reader(lab: ChatLab, *, age: int = 21600) -> SqliteSavedObservationReader:
    return SqliteSavedObservationReader(
        lab.source_store._path.absolute(),
        binding=lab.source_store._binding,
        limits=lab.source_store._limits,
        allowed_sources=(
            "firebase.child_battery.v1",
            "manakids.child_app_usage.v1",
            "firebase.child_location.v1",
            "manakids.family_day_app_usage.v1",
        ),
        maximum_age_seconds=age,
    )


def target(source: ObservedSourceKey = "firebase.child_battery.v1") -> SavedObservationTarget:
    return SavedObservationTarget(
        parent_id=LAB_PARENT, child_id=LAB_CHILD, request_id=uuid4(), source=source
    )


async def seed(lab: ChatLab, source: Any = "firebase.child_battery.v1") -> None:
    assert isinstance(lab.source_store, SqliteSourceReviewCache)
    lab.source_store._dispatch_enabled = False
    result = await lab.sources.read(
        FamilySourceTarget(
            parent_id=LAB_PARENT, child_id=LAB_CHILD, request_id=uuid4(), source=source
        )
    )
    lab.source_store._dispatch_enabled = True
    assert result.status == "completed"


async def flow(
    lab: ChatLab, message: str = "Покажи сохранённый заряд ребёнка"
) -> ParentTouchMessageRequest:
    request = ParentTouchMessageRequest(parent_id=LAB_PARENT, request_id=uuid4(), message=message)
    await lab.touch.admit_message(request)
    assert await lab.touch.process_reviewed_message()
    result = await lab.safety.process_one()
    assert result and result.status == "completed", result
    assert await lab.touch.process_reviewed_message()
    state = await lab.touch.message_state(LAB_PARENT, request.request_id)
    assert state.phase == "completed" and state.response
    return request


@pytest.mark.parametrize("followups", [False, True])
async def test_full_saved_loop_preserves_pairing_restart_and_closed_reader(
    tmp_path: Path, followups: bool
) -> None:
    path = tmp_path / str(followups)
    lab, clock = await setup(path, followups=followups)
    assert isinstance(lab.store, SqliteSavedObservationSafetyStore)
    calls: list[dict[str, Any]] = []
    model = lab._models[1]
    assert isinstance(model, OpenAIChildSourceModel)

    async def observe(request: httpx.Request) -> None:
        calls.append(json.loads(request.content))

    model._client._client.event_hooks["request"].append(observe)
    try:
        await seed(lab)
        before = snapshot(lab.source_store._path)
        request = await flow(lab)
        assert lab.battery.calls == 1
        assert snapshot(lab.source_store._path) == before
        assert [t["name"] for t in calls[0]["tools"]] == [
            "read_child_observation",
            "inspect_saved_child_observation",
        ]
        assert calls[-1]["tools"] == [] and calls[-1]["tool_choice"] == "none"
        tool = next(i for i in calls[-1]["input"] if i.get("type") == "function_call")
        result = next(i for i in calls[-1]["input"] if i.get("type") == "function_call_output")
        assert (
            tool["name"] == "inspect_saved_child_observation"
            and tool["call_id"] == result["call_id"]
        )
        projected = json.loads(result["output"])
        assert projected["saved_observation"]["provider_refreshed"] is False
        assert not any(
            k in json.dumps(projected)
            for k in ("parent_id", "child_id", "fingerprint", "snapshot_id")
        )
        state = await lab.state()
        assert state.history.quota.used_tokens == state.safety_budget.server_used_tokens == 300
        assert (
            state.history.quota.reserved_tokens == state.safety_budget.server_reserved_tokens == 0
        )
        assert len(state.history.messages) == 2
        with lab.store._connect() as db:
            row = db.execute(
                "SELECT prepared,continuation,target,source_result,phase FROM source_tool_jobs"
            ).fetchone()
            assert json.loads(row[0])["scope"]["protocol"] == 4
            assert json.loads(row[1])["version"] == 4
            assert (
                json.loads(row[2])["operation"]
                == json.loads(row[3])["operation"]
                == "saved_observation_inspection"
            )
            assert row[4] == "final_metered"
            assert db.execute(
                "SELECT COUNT(*),MIN(status) FROM saved_observation_inspections"
            ).fetchone()[:] == (1, "completed")
        family_before = snapshot(lab.store._path)
        original = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert await lab.touch.admit_message(request) == original
        assert await lab.safety.process_one() is None
        assert snapshot(lab.store._path) == family_before
        await lab.close()
        lab, _ = await setup(path, followups=followups)
        assert await lab.touch.admit_message(request) == original
        assert lab.battery.calls == 0 and snapshot(lab.source_store._path) == before
        assert snapshot(lab.store._path) == family_before
        if not followups:
            closed = SqliteClosedSavedObservationSafetyStore(
                lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
            )
            await closed.initialize()
            assert (
                await closed.touch_history(LAB_PARENT, before=None, limit=20, now=clock.now())
            ).messages == state.history.messages
            assert snapshot(lab.store._path) == family_before
    finally:
        await lab.close()


@pytest.mark.parametrize(
    "source",
    ["firebase.child_battery.v1", "manakids.child_app_usage.v1", "firebase.child_location.v1"],
)
async def test_each_saved_source_is_positive_readonly_and_retains_exact_facts(
    tmp_path: Path, source: Any
) -> None:
    lab, clock = await setup(tmp_path / source.replace(".", "_"))
    try:
        await seed(lab, source)
        before = snapshot(lab.source_store._path)
        receipt = await reader(lab).inspect(target(source), clock.now())
        assert receipt.status == "completed" and receipt.facts
        assert receipt.facts.child_id == LAB_CHILD
        assert receipt.fingerprint == receipt.facts.fingerprint()
        assert receipt.provenance().provider_refreshed is False
        assert snapshot(lab.source_store._path) == before
    finally:
        await lab.close()


@pytest.mark.parametrize(
    "case", ["missing", "stale", "unresolved", "stopped", "foreign", "fingerprint", "future"]
)
async def test_missing_stale_or_invalid_sources_cannot_refresh_or_substitute_evidence(
    tmp_path: Path, case: str
) -> None:
    lab, clock = await setup(tmp_path / case)
    try:
        if case != "missing":
            await seed(lab)
        if case == "stale":
            clock.value += timedelta(hours=6, seconds=1)
        elif case == "unresolved":
            clock.value += timedelta(hours=6)
            await lab.source_store.claim(
                FamilySourceTarget(parent_id=LAB_PARENT, child_id=LAB_CHILD, request_id=uuid4()),
                clock.now(),
            )
        elif case == "stopped":
            with lab.source_store._connection() as db:
                db.execute("UPDATE source_policy SET blocked=1")
        elif case in {"fingerprint", "future"}:
            with lab.source_store._connection() as db:
                db.execute(
                    "UPDATE source_snapshots SET fingerprint=?", ("f" * 64,)
                ) if case == "fingerprint" else db.execute(
                    "UPDATE source_heads SET checked_at=?",
                    ((clock.now() + timedelta(days=1)).isoformat(),),
                )
        request = (
            target().model_copy(update={"parent_id": "123"}) if case == "foreign" else target()
        )
        before = snapshot(lab.source_store._path)
        if case in {"fingerprint", "future"}:
            with pytest.raises(ParentChatError):
                await reader(lab).inspect(request, clock.now())
        else:
            result = await reader(lab).inspect(request, clock.now())
            assert result.status == "unavailable" and result.facts is None
        assert snapshot(lab.source_store._path) == before
        assert lab.battery.calls == (0 if case == "missing" else 1)
    finally:
        await lab.close()


async def test_original_consumed_external_read_limit_is_not_reset_by_saved_inspection(
    tmp_path: Path,
) -> None:
    lab, clock = await setup(tmp_path / "consumed")
    try:
        # A separately constructed source ledger with its original immutable 1/2
        # allowance, not a reset/new ledger standing in for a consumed source.
        from app.mana_ai.domain.source_reviews import SourceReviewPolicy
        from app.mana_ai.domain.source_safety import SourceSafetyPolicy
        from app.services.location_comparison_cache import SqliteLocationComparisonCache

        limits = FamilySourceLimits(requests_per_24h=1, document_units_per_24h=2)
        source = SqliteLocationComparisonCache(
            tmp_path / "consumed-source.sqlite3",
            binding="original-test-binding",
            limits=limits,
            policy=SourceSafetyPolicy(),
            review_policy=SourceReviewPolicy(),
            location_enabled=True,
        )
        await source.initialize()
        request = FamilySourceTarget(parent_id=LAB_PARENT, child_id=LAB_CHILD, request_id=uuid4())
        await source.claim(request, clock.now())
        await source.complete(request, await lab.battery.read(LAB_CHILD), clock.now())
        before = snapshot(source._path)
        inspector = SqliteSavedObservationReader(
            source._path.absolute(),
            binding="original-test-binding",
            limits=limits,
            allowed_sources=("firebase.child_battery.v1",),
        )
        assert (await inspector.inspect(target(), clock.now())).status == "completed"
        assert snapshot(source._path) == before
        with pytest.raises(ParentChatError, match="family_source_request_limit"):
            await source.claim(
                FamilySourceTarget(parent_id=LAB_PARENT, child_id=LAB_CHILD, request_id=uuid4()),
                clock.now(),
            )
        assert snapshot(source._path) == before
    finally:
        await lab.close()


async def test_old_protocol3_turn_never_gains_saved_tool_after_setting_enable(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(tmp_path / "old")
    assert isinstance(lab.store, SqliteSavedObservationSafetyStore)
    store = lab.store
    try:
        store._saved_observations_enabled = False
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Какой заряд ребёнка?"
        )
        await lab.touch.admit_message(request)
        with store._connect() as db:
            old_profile = db.execute("SELECT profile FROM source_tool_turns").fetchone()[0]
            assert db.execute("SELECT COUNT(*) FROM saved_observation_turns").fetchone()[0] == 0
        store._saved_observations_enabled = True
        assert await lab.touch.process_reviewed_message()
        job = await lab.safety.process_one()
        assert job and job.status == "completed"
        assert await lab.touch.process_reviewed_message()
        with store._connect() as db:
            assert db.execute("SELECT profile FROM source_tool_turns").fetchone()[0] == old_profile
            prepared = json.loads(db.execute("SELECT prepared FROM source_tool_jobs").fetchone()[0])
            assert prepared["scope"]["protocol"] == 3
            assert "saved_observations_enabled" not in prepared["scope"]
            assert (
                db.execute("SELECT COUNT(*) FROM saved_observation_inspections").fetchone()[0] == 0
            )
        assert lab.battery.calls == 1
    finally:
        await lab.close()


async def test_saved_query_day_minimizes_family_page_and_keeps_exact_day(tmp_path: Path) -> None:
    from app.mana_ai.domain.family_day_usage import DayUsageTarget

    lab, clock = await setup(tmp_path / "day")
    try:
        assert lab.day_usage
        assert isinstance(lab.source_store, SqliteSourceReviewCache)
        lab.source_store._dispatch_enabled = False
        day = clock.now().date() - timedelta(days=1)
        result = await lab.day_usage.read_for_analysis(
            DayUsageTarget(
                parent_id=LAB_PARENT, child_id=LAB_CHILD, request_id=uuid4(), requested_day=day
            ),
            None,
        )
        assert result.status == "completed"
        before = snapshot(lab.source_store._path)
        saved = await reader(lab).inspect(
            SavedObservationTarget(
                parent_id=LAB_PARENT,
                child_id=LAB_CHILD,
                request_id=uuid4(),
                source="manakids.family_day_app_usage.v1",
                requested_day=day,
            ),
            clock.now(),
        )
        assert saved.status == "completed" and saved.facts and saved.facts.child_id == LAB_CHILD
        assert saved.requested_day == day
        assert snapshot(lab.source_store._path) == before
    finally:
        await lab.close()


@pytest.mark.parametrize("when", ["before_first", "after_first", "after_second"])
async def test_native_disable_fences_selected_saved_work_and_retains_verified_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    lab, _ = await setup(tmp_path / when)
    assert isinstance(lab.store, SqliteSavedObservationSafetyStore)
    store = lab.store
    model = lab._models[1]
    assert isinstance(model, OpenAIChildSourceModel)
    try:
        await seed(lab)
        source_before = snapshot(lab.source_store._path)
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Проверь сохранённый заряд ребёнка"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        original_count, original_respond = model.count_source_input, model.respond_source
        calls = 0
        if when == "before_first":

            async def count(prompt: SourceToolPrompt) -> int:
                size = await original_count(prompt)
                store._saved_observations_enabled = False
                return size

            monkeypatch.setattr(model, "count_source_input", count)
        else:

            async def respond(
                prompt: SourceToolPrompt, *, max_output_tokens: int
            ) -> SourceModelReceipt:
                nonlocal calls
                result = await original_respond(prompt, max_output_tokens=max_output_tokens)
                calls += 1
                if (calls == 1 and when == "after_first") or (
                    calls == 2 and when == "after_second"
                ):
                    store._saved_observations_enabled = False
                return result

            monkeypatch.setattr(model, "respond_source", respond)
        result = await lab.safety.process_one()
        assert result and result.status == "failed"
        state = await lab.state()
        assert (
            state.safety_budget.server_used_tokens
            == {"before_first": 0, "after_first": 150, "after_second": 300}[when]
        )
        assert state.safety_budget.server_reserved_tokens == 0
        assert len(state.history.messages) == 1 and state.history.messages[0].role == "user"
        assert snapshot(lab.source_store._path) == source_before
        with store._connect() as db:
            assert db.execute("SELECT COUNT(*) FROM saved_observation_inspections").fetchone()[
                0
            ] == (1 if when == "after_second" else 0)
    finally:
        await lab.close()


async def test_unknown_second_model_retains_hold_original_pairing_and_exact_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, clock = await setup(tmp_path / "unknown")
    model = lab._models[1]
    assert isinstance(model, OpenAIChildSourceModel)
    try:
        await seed(lab)
        source_before = snapshot(lab.source_store._path)
        original = model.respond_source

        async def respond(
            prompt: SourceToolPrompt, *, max_output_tokens: int
        ) -> SourceModelReceipt:
            if prompt.continuation:
                raise asyncio.CancelledError()
            return await original(prompt, max_output_tokens=max_output_tokens)

        monkeypatch.setattr(model, "respond_source", respond)
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Какой сохранённый заряд ребёнка?"
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        with pytest.raises(asyncio.CancelledError):
            await lab.safety.process_one()
        state = await lab.state()
        assert (
            state.safety_budget.server_used_tokens == 150
            and state.safety_budget.server_reserved_tokens > 0
        )
        assert snapshot(lab.source_store._path) == source_before
        with lab.store._connect() as db:
            assert (
                db.execute("SELECT phase FROM source_tool_jobs").fetchone()[0] == "second_submitted"
            )
            assert (
                db.execute("SELECT status FROM saved_observation_inspections").fetchone()[0]
                == "completed"
            )
        before = snapshot(lab.store._path)
        closed = SqliteClosedSavedObservationSafetyStore(
            lab.store._path, history_only=True, daily_limit=2000, timezone="Asia/Samarkand"
        )
        await closed.initialize()
        budget = await lab.store.safety_budget(LAB_PARENT, clock.now() + timedelta(days=1))
        assert budget.server_reserved_tokens == state.safety_budget.server_reserved_tokens
        assert snapshot(lab.store._path) == before
        original_state = await lab.touch.message_state(LAB_PARENT, request.request_id)
        assert await lab.touch.admit_message(request) == original_state
        assert snapshot(lab.source_store._path) == source_before
    finally:
        await lab.close()


async def test_unavailable_saved_context_finishes_without_live_fallback(tmp_path: Path) -> None:
    lab, _ = await setup(tmp_path / "no-snapshot")
    try:
        before = snapshot(lab.source_store._path)
        await flow(lab)
        assert lab.battery.calls == lab.location.calls == lab.app_usage.calls == 0
        assert snapshot(lab.source_store._path) == before
        with lab.store._connect() as db:
            result = SavedObservationReceipt.model_validate_json(
                db.execute("SELECT source_result FROM source_tool_jobs").fetchone()[0]
            )
            assert result.status == "unavailable" and result.reason == "saved_observation_missing"
            assert (
                db.execute("SELECT COUNT(*) FROM saved_observation_inspections").fetchone()[0] == 1
            )
    finally:
        await lab.close()


async def test_separate_sql_ceiling_is_durable_and_does_not_change_source_allowance(
    tmp_path: Path,
) -> None:
    lab, _ = await setup(
        tmp_path / "sql-limit",
        limits=SavedObservationLimits(global_inspections_per_24h=1, parent_inspections_per_24h=1),
    )
    assert isinstance(lab.store, SqliteSavedObservationSafetyStore)
    store = lab.store
    try:
        await seed(lab)
        before = snapshot(lab.source_store._path)
        await flow(lab)
        request = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Ещё раз проверь сохранённый заряд ребёнка",
        )
        await lab.touch.admit_message(request)
        assert await lab.touch.process_reviewed_message()
        result = await lab.safety.process_one()
        assert result and result.status == "failed"
        assert snapshot(lab.source_store._path) == before
        with store._connect() as db:
            assert (
                db.execute("SELECT COUNT(*) FROM saved_observation_inspections").fetchone()[0] == 1
            )
        family = snapshot(store._path)
        store._saved_observation_limits = SavedObservationLimits()
        with pytest.raises(ValueError, match="cannot reset"):
            await store.initialize()
        assert snapshot(store._path) == family
    finally:
        await lab.close()


async def test_lost_sql_inspection_result_is_not_reissued_by_a_new_parent_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, _ = await setup(tmp_path / "lost-sql")
    workflow = lab.safety._native_sources
    assert isinstance(workflow, SourceToolWorkflow) and workflow._saved_observations
    inspector = workflow._saved_observations
    calls = 0
    original = inspector.inspect

    async def lost(request: SavedObservationTarget) -> SavedObservationReceipt:
        nonlocal calls
        calls += 1
        await original(request)
        raise asyncio.CancelledError()

    monkeypatch.setattr(inspector, "inspect", lost)
    try:
        await seed(lab)
        before = snapshot(lab.source_store._path)
        first = ParentTouchMessageRequest(
            parent_id=LAB_PARENT, request_id=uuid4(), message="Покажи сохранённый заряд ребёнка"
        )
        await lab.touch.admit_message(first)
        await lab.touch.process_reviewed_message()
        with pytest.raises(asyncio.CancelledError):
            await lab.safety.process_one()
        await lab.touch.process_reviewed_message()
        second = ParentTouchMessageRequest(
            parent_id=LAB_PARENT,
            request_id=uuid4(),
            message="Проверь ещё сохранённый заряд ребёнка",
        )
        await lab.touch.admit_message(second)
        await lab.touch.process_reviewed_message()
        result = await lab.safety.process_one()
        assert result and result.status == "failed" and calls == 1
        assert snapshot(lab.source_store._path) == before
        with lab.store._connect() as db:
            assert db.execute(
                "SELECT COUNT(*),MIN(status) FROM saved_observation_inspections"
            ).fetchone()[:] == (1, "claimed")
    finally:
        await lab.close()


def test_saved_call_requires_explicit_protocol4_scope() -> None:
    call = SavedObservationCall(
        id="fc",
        call_id="call",
        arguments=json.dumps({"child_alias": "child-1", "kind": "battery", "calendar_day": None}),
    )
    old = SourceToolScope(
        parent_id=LAB_PARENT,
        invocation_id=uuid4(),
        children=(SourceToolChild(alias="child-1", child_id=LAB_CHILD),),
        protocol=3,
        calendar_today=Clock.value.date(),
    )
    with pytest.raises(ValueError, match="not captured"):
        old.validate_call(call)
    scope = old.model_copy(update={"protocol": 4, "saved_observations_enabled": True})
    scope.validate_call(call)
    with pytest.raises(ValidationError):
        SourceToolScope.model_validate(scope.model_dump() | {"saved_observations_enabled": None})
