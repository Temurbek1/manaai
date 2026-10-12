"""Known local paging mistakes may replan; provider I/O and policy never retry."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.domain.agent_tools import AgentToolCall
from app.mana_operation_ai.domain.chat import TopicCreate
from app.mana_operation_ai.domain.goals import GoalCreate, GoalDecision
from app.mana_operation_ai.domain.models import AgentReport
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from tests.test_goal_continuation import decision, raw_reply
from tests.test_operation_agent_workspace import ToolModel, configure_workspace
from tests.test_operation_goals import command, seed
from tests.test_saved_report_pages import REPORT_ID, TEXT, setup_goal


def tool_reply(name: str, arguments: dict[str, object]) -> SimpleNamespace:
    raw = raw_reply(decision())
    payload = raw.http_response.json()
    payload["output"][-1] = {
        "type": "function_call",
        "id": f"fc_{uuid4()}",
        "call_id": f"call_{uuid4()}",
        "name": name,
        "arguments": json.dumps(arguments),
    }
    return raw


def page_reply(offset: int, *, report_id: str = REPORT_ID) -> SimpleNamespace:
    return tool_reply("read_saved_report_page", {"report_id": report_id, "offset": offset})


def report_decision(*, review: bool = False) -> GoalDecision:
    return decision(review=review).model_copy(
        update={
            "draft": "Read the complete synthetic source including EXACT FOOTER; not payments.",
            "evidence_ids": [REPORT_ID],
        }
    )


@pytest.mark.parametrize("bad_offset", [5000, 32000])
async def test_local_page_mistake_replans_with_exact_receipt_and_review_after_sql_restart(
    monkeypatch: MonkeyPatch, tmp_path: Path, bad_offset: int
) -> None:
    configure_workspace(monkeypatch, tmp_path / "replan.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        created = await setup_goal(app)
        model = service._continuing_model
        assert isinstance(model, OpenAIGoalModel)
        parser = AsyncMock(
            side_effect=[
                page_reply(0),
                page_reply(bad_offset),
                page_reply(4000),
                page_reply(8000),
                raw_reply(report_decision()),
                raw_reply(report_decision()),
                raw_reply(report_decision(review=True)),
            ]
        )
        monkeypatch.setattr(model._client.responses.with_raw_response, "parse", parser)
        source = AsyncMock(side_effect=AssertionError("Replanning must not collect a source"))
        monkeypatch.setattr(service._admin, "run_now", source)
        assert await service.tick()
        before = await service.repository.get("alice", created.goal_id)
        assert await service.tick()
        reopened = SqlAlchemyGoalRepository(app.state.operation_database, service._clock)
        corrected = await reopened.get("alice", created.goal_id)
        assert corrected.status == "queued" and corrected.model_recoveries == 1
        assert corrected.evidence == before.evidence and corrected.request == created.request
        assert corrected.tools[-1].status == "denied"
        receipt = json.loads(corrected.tools[-1].result)
        assert receipt["expected_offset"] == 4000
        assert receipt["code"] in {"invalid_offset", "noncontiguous_page"}
        assert corrected.accounted_microusd == 2 * before.accounted_microusd
        service.repository = reopened
        for _ in range(5):
            assert await service.tick()
        saved = await reopened.get("alice", created.goal_id)
        assert saved.status == "completed" and saved.phase == "review"
        assert saved.model_recoveries == 1 and saved.steps_used == 7
        assert saved.evidence[0].summary == TEXT and not saved.evidence[0].shortened
        assert saved.request == created.request and not saved.read_attempted
        assert saved.approved_capability is None
        assert saved.accounted_microusd == 7 * before.accounted_microusd
        receipt_input = str(parser.call_args_list[2].kwargs["input"][-2])
        assert "function_call_output" in receipt_input
        assert ("noncontiguous_page" if bad_offset == 5000 else "invalid_offset") in receipt_input
        review_input = str(parser.call_args_list[-1].kwargs["input"])
        assert "EXACT FOOTER" in review_input and "test-encrypted-continuation" not in review_input
        source.assert_not_called()
        assert parser.call_count == 7 and not await service.tick()
    get_settings.cache_clear()


@pytest.mark.parametrize("middle", ["page", "format", "citation"])
async def test_local_replanning_shares_the_existing_two_recovery_cap(
    monkeypatch: MonkeyPatch, tmp_path: Path, middle: str
) -> None:
    configure_workspace(monkeypatch, tmp_path / "cap.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        created = await setup_goal(app)
        model = service._continuing_model
        assert isinstance(model, OpenAIGoalModel)
        second = page_reply(32000) if middle == "page" else raw_reply(report_decision())
        if middle == "format":
            second.parse = Mock(side_effect=ValueError("PRIVATE invalid schema"))
        parser = AsyncMock(side_effect=[page_reply(32000), second, page_reply(32000)])
        monkeypatch.setattr(model._client.responses.with_raw_response, "parse", parser)
        source = AsyncMock()
        monkeypatch.setattr(service._admin, "run_now", source)
        for count in (1, 2):
            assert await service.tick()
            saved = await service.repository.get("alice", created.goal_id)
            assert saved.status == "queued" and saved.model_recoveries == count
            assert not saved.evidence and saved.request == created.request
        assert await service.tick()
        saved = await service.repository.get("alice", created.goal_id)
        assert saved.status == "waiting" and saved.model_recoveries == 2
        assert saved.steps_used == 3 and saved.accounted_microusd > 0
        assert saved.request == created.request and not saved.read_attempted
        assert parser.call_count == 3 and not await service.tick()
        source.assert_not_called()
    get_settings.cache_clear()


@pytest.mark.parametrize("failure", ["foreign", "missing", "oversized", "sql", "unpriced", "cut"])
async def test_policy_capacity_and_unknown_io_still_stop_without_replanning(
    monkeypatch: MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    configure_workspace(monkeypatch, tmp_path / "stop.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        created = await setup_goal(app, text="r" * 32001 if failure == "oversized" else TEXT)
        model = service._continuing_model
        assert isinstance(model, OpenAIGoalModel)
        if failure == "foreign":
            await seed(service, product="360rec")
        report_id = {
            "foreign": "report-360rec",
            "missing": "missing",
        }.get(failure, REPORT_ID)
        raw = page_reply(32000, report_id=report_id)
        if failure in {"unpriced", "cut"}:
            payload = raw.http_response.json()
            payload["usage" if failure == "unpriced" else "status"] = (
                None if failure == "unpriced" else "incomplete"
            )
        parser = AsyncMock(return_value=raw)
        monkeypatch.setattr(model._client.responses.with_raw_response, "parse", parser)
        if failure == "sql":
            monkeypatch.setattr(
                service._admin, "get_report", AsyncMock(side_effect=TimeoutError("PRIVATE SQL"))
            )
        source = AsyncMock()
        monkeypatch.setattr(service._admin, "run_now", source)
        assert await service.tick()
        saved = await service.repository.get("alice", created.goal_id)
        assert saved.status == "waiting" and saved.model_recoveries == 0
        assert not saved.evidence and not saved.read_attempted
        assert saved.approved_capability is None and saved.request == created.request
        assert saved.accounted_microusd > 0 and saved.steps_used == 1
        assert "PRIVATE" not in saved.model_dump_json()
        assert parser.call_count == 1 and not await service.tick()
        source.assert_not_called()
    get_settings.cache_clear()


async def test_replanning_never_raises_step_or_cost_budget(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "limits.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        created = await setup_goal(app, max_steps=3)
        model = service._continuing_model
        assert isinstance(model, OpenAIGoalModel)
        parser = AsyncMock(side_effect=[page_reply(32000), page_reply(0), page_reply(32000)])
        monkeypatch.setattr(model._client.responses.with_raw_response, "parse", parser)
        for _ in range(3):
            assert await service.tick()
        before = await service.repository.get("alice", created.goal_id)
        assert before.status == "queued" and before.model_recoveries == 2
        assert await service.tick()
        stopped = await service.repository.get("alice", created.goal_id)
        assert stopped.status == "waiting" and stopped.steps_used == 3
        assert stopped.accounted_microusd == before.accounted_microusd
        assert stopped.request == created.request and parser.call_count == 3
        # A separate Goal retains its original monetary bound; excessive next-step
        # admission must stop before the adapter sends anything, even after correction.
        topic = await service._chats.create(
            "alice",
            TopicCreate(agent_id="operations-orchestrator", product="mana", title="Cost bound"),
        )
        another = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(), objective="Read saved text only.", execution_mode="agent"
            ),
        )
        parser.side_effect = None
        parser.return_value = page_reply(32000)
        assert await service.tick()
        before = await service.repository.get("alice", another.goal_id)
        assert before.status == "queued" and before.model_recoveries == 1
        monkeypatch.setattr(
            model,
            "continuation_reservation",
            Mock(return_value=another.request.budget_microusd + 1),
        )
        assert await service.tick()
        stopped = await service.repository.get("alice", another.goal_id)
        assert stopped.status == "waiting" and stopped.steps_used == 1
        assert stopped.request == another.request
        assert stopped.accounted_microusd == before.accounted_microusd
        assert parser.call_count == 4 and not await service.tick()
    get_settings.cache_clear()


@pytest.mark.parametrize("control", ["pause", "cancel"])
async def test_user_control_wins_a_local_replanning_race(
    monkeypatch: MonkeyPatch, tmp_path: Path, control: str
) -> None:
    configure_workspace(monkeypatch, tmp_path / "control.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        created = await setup_goal(app)
        original = await service._admin.get_report(REPORT_ID)
        assert isinstance(original, AgentReport)
        started, release = asyncio.Event(), asyncio.Event()

        async def local_read(report_id: str) -> AgentReport:
            assert report_id == REPORT_ID
            started.set()
            await release.wait()
            return original

        monkeypatch.setattr(service._admin, "get_report", local_read)
        model = service._continuing_model
        assert isinstance(model, OpenAIGoalModel)
        parser = AsyncMock(return_value=page_reply(32000))
        monkeypatch.setattr(model._client.responses.with_raw_response, "parse", parser)
        tick = asyncio.create_task(service.tick())
        await asyncio.wait_for(started.wait(), timeout=5)
        current = await service.repository.get("alice", created.goal_id)
        held = current.accounted_microusd
        await service.command("alice", created.goal_id, command(current, control))
        release.set()
        assert await tick
        saved = await service.repository.get("alice", created.goal_id)
        assert saved.status == ("paused" if control == "pause" else "cancelled")
        assert saved.model_recoveries == 0 and saved.tools[-1].status == "unknown"
        assert saved.accounted_microusd == held and saved.request == created.request
        assert parser.call_count == 1 and not await service.tick()
    get_settings.cache_clear()


@pytest.mark.parametrize("changed", ["text", "metadata", "shorter"])
async def test_changed_report_requires_explicit_model_selected_restart_not_mixed_pages(
    monkeypatch: MonkeyPatch, tmp_path: Path, changed: str
) -> None:
    configure_workspace(monkeypatch, tmp_path / "changed.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        created = await setup_goal(app)
        model = service._continuing_model
        assert isinstance(model, OpenAIGoalModel)
        parser = AsyncMock(side_effect=[page_reply(0)])
        monkeypatch.setattr(model._client.responses.with_raw_response, "parse", parser)
        assert await service.tick()
        before = await service.repository.get("alice", created.goal_id)
        original = await service._admin.get_report(REPORT_ID)
        assert original is not None
        replacement = original.model_copy(
            update={
                "human_readable": {
                    "text": TEXT + " NEW FIXTURE NOTE",
                    "shorter": "Replacement EXACT FOOTER",
                }.get(changed, TEXT),
                "data_quality_notes": ["Updated fixture limitation"],
            }
        )
        pages = [page_reply(offset) for offset in range(0, len(replacement.human_readable), 4000)]
        parser.side_effect = [
            page_reply(4000),
            *pages,
            raw_reply(report_decision()),
            raw_reply(report_decision()),
            raw_reply(report_decision(review=True)),
        ]
        monkeypatch.setattr(service._admin, "get_report", AsyncMock(return_value=replacement))
        assert await service.tick()
        rejected = await service.repository.get("alice", created.goal_id)
        assert rejected.status == "queued" and rejected.evidence == before.evidence
        receipt = json.loads(rejected.tools[-1].result)
        assert receipt["code"] == "report_changed" and receipt["expected_offset"] == 0
        for _ in range(len(pages) + 3):
            assert await service.tick()
        saved = await service.repository.get("alice", created.goal_id)
        assert (
            saved.status == "completed" and saved.evidence[0].summary == replacement.human_readable
        )
        assert saved.model_recoveries == 1 and saved.request == created.request
        assert saved.evidence[0].limitations == replacement.data_quality_notes
        assert not saved.read_attempted and not await service.tick()
    get_settings.cache_clear()


async def test_saved_task_offset_correction_never_turns_history_into_evidence(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "task.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED", "true")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        prior = await setup_goal(app)
        cancelled = await service.command("alice", prior.goal_id, command(prior, "cancel"))
        assert await service.repository.save(
            "alice", cancelled, cancelled.model_copy(update={"result": "Historical fixture only"})
        )
        created = await service.create(
            "alice",
            prior.topic_id,
            GoalCreate(
                request_id=uuid4(), objective="Read the prior task result.", execution_mode="agent"
            ),
        )
        model = service._continuing_model
        assert isinstance(model, OpenAIGoalModel)
        waiting = decision().model_copy(
            update={
                "draft": "Historical fixture only; no measurement evidence is loaded.",
                "evidence_ids": [],
                "disposition": "waiting",
                "missing_information": "Need report evidence.",
            }
        )
        parser = AsyncMock(
            side_effect=[
                tool_reply("read_saved_task", {"task_id": prior.goal_id, "offset": 1000}),
                tool_reply("read_saved_task", {"task_id": prior.goal_id, "offset": 0}),
                raw_reply(waiting),
            ]
        )
        monkeypatch.setattr(model._client.responses.with_raw_response, "parse", parser)
        assert await service.tick()
        rejected = await service.repository.get("alice", created.goal_id)
        assert rejected.status == "queued" and rejected.model_recoveries == 1
        assert json.loads(rejected.tools[-1].result)["expected_offset"] == 0
        assert await service.tick() and await service.tick()
        saved = await service.repository.get("alice", created.goal_id)
        assert saved.status == "waiting" and saved.evidence == []
        assert not saved.read_attempted and saved.approved_capability is None
        assert saved.tools[1].status == "completed"
        assert json.loads(saved.tools[1].result)["historical_context_only"] is True
        assert saved.request == created.request and not await service.tick()
    get_settings.cache_clear()


async def test_non_continuing_native_work_does_not_gain_automatic_correction(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "disabled.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_MODEL_CONTINUATION_ENABLED", "false")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        created = await setup_goal(app)
        assert service._continuing_model is None
        service._model = ToolModel(
            AgentToolCall(name="read_saved_report_page", report_id=REPORT_ID, offset=32000)
        )
        assert await service.tick() and await service.tick()
        saved = await service.repository.get("alice", created.goal_id)
        assert saved.status == "waiting" and saved.model_recoveries == 0
        assert saved.model_continuation is None and not saved.read_attempted
        assert saved.tools[-1].status == "denied" and not await service.tick()
    get_settings.cache_clear()
