"""Actual private SQL + SDK + source workflow, with fictional providers only."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx
import pytest

from app.mana_ai.application.child_safety import ChildSafetyService
from app.mana_ai.application.family_sources import FamilySourceService
from app.mana_ai.application.parent_touch import ParentTouchService
from app.mana_ai.application.source_tool_workflow import SourceToolWorkflow
from app.mana_ai.domain.chat import ParentChildContext
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.conversion import ConversionPolicy
from app.mana_ai.domain.conversion_accounts import ConversionAccountReadLimits
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest, ParentTouchReviewedTurn
from app.mana_ai.domain.family_sources import ChildBatteryFacts, FamilySourceLimits
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services.child_safety_prompts import ChildSafetyPromptBuilder
from app.services.child_source_model import OpenAIChildSourceModel
from app.services.reviewed_message_store import SqliteReviewedMessageStore
from app.services.source_safety_store import SqliteSourceSafetyStore
from app.services.source_tool_prompts import SourceToolPromptBuilder
from app.services.source_tool_safety_store import (
    SqliteClosedSourceToolSafetyStore,
    SqliteSourceToolSafetyStore,
)
from tests.test_child_source_model import NOW, Provider, message, model
from tests.test_parent_chat import Children, Model


class Clock:
    def __init__(self) -> None:
        self.value = NOW

    def now(self) -> datetime:
        return self.value


class Profiles(Children):
    def __init__(self) -> None:
        super().__init__()
        self.revoke_at: int | None = None

    async def read(self, parent_id: str) -> ParentChildContext:
        result = await super().read(parent_id)
        result = result.model_copy(update={"collected_at": NOW})
        return (
            result.model_copy(update={"children": []}) if self.revoke_at == self.calls else result
        )


class Battery:
    def __init__(self) -> None:
        self.calls = 0
        self.unknown = False

    async def read(self, child_id: int) -> ChildBatteryFacts:
        self.calls += 1
        if self.unknown:
            raise httpx.ReadTimeout("Synthetic source receipt lost")
        return ChildBatteryFacts(
            child_id=child_id,
            status="available",
            percent=12,
            observed_at=NOW - timedelta(seconds=2),
            source_updated_at=NOW - timedelta(seconds=1),
            collected_at=NOW,
            quality="dated",
        )


class NativeProvider(Provider):
    def __init__(self) -> None:
        super().__init__()
        self.lose_second = False
        self.invalid_choice = False
        self.direct_final = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        if not request.url.path.endswith("input_tokens") and (
            not data.get("tools") or self.direct_final
        ):
            self.body["output"] = [
                message(
                    json.dumps(
                        {
                            "analysis": None,
                            "followup_summary": "Нет нового измерения; уточнение не требуется.",
                            "question": None,
                        },
                        ensure_ascii=False,
                    )
                )
            ]
            return super().handle(request)
        if not request.url.path.endswith("input_tokens") and data.get("tool_choice") == "none":
            if self.lose_second:
                self.lost = True
            self.body["output"] = [
                message(
                    json.dumps(
                        {
                            "analysis": None,
                            "followup_summary": (
                                "По измерению от 2026-10-24 заряд 12%; онлайн неизвестен."
                            ),
                            "question": None,
                        },
                        ensure_ascii=False,
                    )
                )
            ]
        elif self.invalid_choice:
            self.body["output"][1]["arguments"] = '{"child_alias":"child-2"}'
        return super().handle(request)


@dataclass
class Runtime:
    adapter: OpenAIChildSourceModel
    store: SqliteSourceToolSafetyStore
    source_store: SqliteSourceSafetyStore
    touch: ParentTouchService
    touch_model: Model
    safety: ChildSafetyService
    provider: NativeProvider
    profiles: Profiles
    battery: Battery
    clock: Clock


async def setup(
    path: Path,
    *,
    native_model: str = "gpt-5.4-mini",
    effort: Literal["none", "low", "medium", "high", "xhigh"] = "none",
    output: int = 512,
    job_tokens: int = 2000,
) -> Runtime:
    clock, profiles, provider, battery = Clock(), Profiles(), NativeProvider(), Battery()
    limits = ChildSafetyLimits(
        server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=job_tokens
    )
    store = SqliteSourceToolSafetyStore(
        path / "family.sqlite3",
        native_model=native_model,
        native_reasoning_effort=effort,
        native_max_output_tokens=output,
        limits=limits,
        daily_limit=2000,
        timezone="Asia/Tashkent",
        conversion_policy=ConversionPolicy(),
        conversion_offers=(),
        account_read_limits=ConversionAccountReadLimits(),
    )
    await store.initialize()
    sources = SqliteSourceSafetyStore(
        path / "sources.sqlite3",
        binding="fake-native-source",
        limits=FamilySourceLimits(),
        policy=SourceSafetyPolicy(),
        enabled=False,
    )
    await sources.initialize()
    adapter = model(provider)
    adapter._model = native_model
    adapter._effort = effort
    workflow = SourceToolWorkflow(
        store=store,
        children=profiles,
        model=adapter,
        prompts=SourceToolPromptBuilder(),
        sources=FamilySourceService(sources, profiles, battery, clock=clock.now),
        clock=clock,
        limits=limits,
        max_output_tokens=output,
    )
    safety = ChildSafetyService(
        store=store,
        children=profiles,
        model=adapter,
        prompts=ChildSafetyPromptBuilder(),
        clock=clock,
        limits=limits,
        max_output_tokens=output,
        native_sources=workflow,
    )
    touch_model = Model()
    touch = ParentTouchService(
        store=store,
        children=profiles,
        model=touch_model,
        clock=clock.now,
        max_output_tokens=512,
        history_turn_limit=2,
        safety=safety,
        reviewed=store,
    )
    return Runtime(
        adapter, store, sources, touch, touch_model, safety, provider, profiles, battery, clock
    )


def request() -> ParentTouchMessageRequest:
    return ParentTouchMessageRequest(
        parent_id="123", request_id=uuid4(), message="Какой заряд у ребёнка?"
    )


async def test_selected_source_returns_to_same_review_and_single_parent_chat(
    tmp_path: Path,
) -> None:
    runtime = await setup(tmp_path)
    req = request()
    admitted = await runtime.touch.admit_message(req)
    assert admitted.phase == "awaiting_review"
    result = await runtime.safety.process_one()
    assert result and result.status == "completed" and result.usage and result.usage.total == 300
    assert runtime.battery.calls == 1
    assert await runtime.touch.process_reviewed_message()
    done = await runtime.touch.message_state("123", req.request_id)
    assert done.phase == "completed" and done.response
    assert (await runtime.safety.budget("123")).server_used_tokens == 300
    assert await runtime.safety.process_one() is None
    assert await runtime.touch.admit_message(req) == done
    assert runtime.battery.calls == 1
    assert len([p for p in runtime.provider.requests if "max_output_tokens" in p]) == 2
    assert len((await runtime.touch.history("123", before=None, limit=20)).messages) == 2
    speaker = runtime.touch_model.prompts[-1]
    assert speaker.required_observation_dates == ("2026-10-24",)
    observations = json.loads(speaker.messages[0][1])["specialist_guidance"]["source_observations"]
    assert observations[0]["percent"] == 12 and observations[0]["profile_position"] == 1
    assert "child_id" not in observations[0]
    with sqlite3.connect(tmp_path / "family.sqlite3") as sql:
        assert sql.execute("PRAGMA user_version").fetchone()[0] == 11
        assert sql.execute("SELECT COUNT(*) FROM source_tool_receipts").fetchone()[0] == 2
        assert sql.execute("SELECT phase FROM source_tool_jobs").fetchone()[0] == "final_metered"
    await runtime.adapter.close()


async def test_second_model_unknown_preserves_first_spend_and_remaining_hold_after_restart(
    tmp_path: Path,
) -> None:
    runtime = await setup(tmp_path)
    runtime.provider.lose_second = True
    req = request()
    await runtime.touch.admit_message(req)
    result = await runtime.safety.process_one()
    assert result and result.status == "unknown" and result.usage and result.usage.total == 150
    budget = await runtime.safety.budget("123")
    assert (
        budget.server_used_tokens,
        budget.server_reserved_tokens,
        budget.server_remaining_tokens,
    ) == (150, 1850, 0)
    count = len(runtime.provider.requests)
    runtime.clock.value += timedelta(days=1)
    assert await runtime.safety.process_one() is None
    assert len(runtime.provider.requests) == count and runtime.battery.calls == 1
    closed = SqliteClosedSourceToolSafetyStore(
        tmp_path / "family.sqlite3",
        history_only=True,
        daily_limit=2000,
        timezone="Asia/Tashkent",
    )
    await closed.initialize()
    restarted = await setup(tmp_path)
    restarted.clock.value = runtime.clock.value
    assert await restarted.safety.process_one() is None
    current = await restarted.safety.budget("123")
    assert current.server_reserved_tokens == 1850 and current.server_used_tokens == 0
    assert (await restarted.safety.assessment("123", result.job_id)).usage == result.usage
    assert restarted.provider.requests == [] and restarted.battery.calls == 0
    await runtime.adapter.close()
    await restarted.adapter.close()


async def test_next_native_review_uses_remaining_daily_allowance_and_same_source_cache(
    tmp_path: Path,
) -> None:
    runtime = await setup(tmp_path)
    for _ in range(2):
        await runtime.touch.admit_message(request())
        result = await runtime.safety.process_one()
        assert result and result.status == "completed"
        assert await runtime.touch.process_reviewed_message()
        runtime.provider.body["output"] = Provider().body["output"]
    budget = await runtime.safety.budget("123")
    assert budget.server_used_tokens == 600 and budget.server_daily_limit == 2000
    assert runtime.battery.calls == 1
    with sqlite3.connect(tmp_path / "family.sqlite3") as sql:
        assert [
            row[0] for row in sql.execute("SELECT cap FROM source_tool_jobs ORDER BY rowid")
        ] == [2000, 1700]
    await runtime.adapter.close()


async def test_native_model_can_finish_without_a_source_call(tmp_path: Path) -> None:
    runtime = await setup(tmp_path)
    runtime.provider.direct_final = True
    await runtime.touch.admit_message(request())
    result = await runtime.safety.process_one()
    assert result and result.status == "completed" and result.usage and result.usage.total == 150
    assert runtime.battery.calls == 0
    assert await runtime.touch.process_reviewed_message()
    assert runtime.touch_model.prompts[-1].required_observation_dates == ()
    await runtime.adapter.close()


async def test_queued_old_review_is_not_upgraded_by_private_v11_migration(tmp_path: Path) -> None:
    limits = ChildSafetyLimits(server_daily_tokens=2000, parent_daily_tokens=2000, job_tokens=2000)
    old = SqliteReviewedMessageStore(
        tmp_path / "family.sqlite3", limits=limits, daily_limit=2000, timezone="Asia/Tashkent"
    )
    await old.initialize()
    original = ParentTouchReviewedTurn(**request().model_dump())
    await old.admit_reviewed(original, NOW, allow_new=True)
    with sqlite3.connect(tmp_path / "family.sqlite3") as sql:
        frozen = sql.execute("SELECT context FROM child_safety_parent_events").fetchone()[0]
    runtime = await setup(tmp_path)
    result = await runtime.safety.process_one()
    assert result and result.status == "completed" and result.usage and result.usage.total == 150
    assert runtime.battery.calls == 0
    with sqlite3.connect(tmp_path / "family.sqlite3") as sql:
        assert sql.execute("SELECT context FROM child_safety_parent_events").fetchone()[0] == frozen
        assert sql.execute("SELECT COUNT(*) FROM source_tool_turns").fetchone()[0] == 0
        assert sql.execute("SELECT COUNT(*) FROM source_tool_jobs").fetchone()[0] == 0
    assert "tools" not in runtime.provider.requests[-1]
    await runtime.adapter.close()


async def test_queued_native_model_cannot_change_after_capture(tmp_path: Path) -> None:
    runtime = await setup(tmp_path)
    await runtime.touch.admit_message(request())
    changed = await setup(tmp_path, native_model="changed-model")
    result = await changed.safety.process_one()
    assert result and result.status == "failed" and result.usage is None
    assert not changed.provider.requests and changed.battery.calls == 0
    await runtime.adapter.close()
    await changed.adapter.close()


@pytest.mark.parametrize("failure", ["invalid_choice", "source_unknown", "revoked", "second_count"])
async def test_failed_continuations_do_not_reexecute_and_preserve_known_usage(
    tmp_path: Path, failure: str
) -> None:
    runtime = await setup(tmp_path)
    runtime.provider.invalid_choice = failure == "invalid_choice"
    runtime.battery.unknown = failure == "source_unknown"
    runtime.profiles.revoke_at = 3 if failure == "revoked" else None
    runtime.provider.count = 1900 if failure == "second_count" else 100
    req = request()
    await runtime.touch.admit_message(req)
    result = await runtime.safety.process_one()
    assert result and result.status == "failed" and result.usage and result.usage.total == 150
    budget = await runtime.safety.budget("123")
    assert budget.server_used_tokens == 150 and budget.server_reserved_tokens == 0
    assert runtime.battery.calls == (0 if failure == "invalid_choice" else 1)
    assert len([p for p in runtime.provider.requests if "max_output_tokens" in p]) == 1
    assert await runtime.safety.process_one() is None
    assert await runtime.touch.process_reviewed_message() is False
    state = await runtime.touch.message_state("123", req.request_id)
    assert state.phase == "failed"
    await runtime.adapter.close()
