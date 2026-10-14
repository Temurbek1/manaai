"""Full unchanged input and exact retained draft, never a paid model or live source."""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError
from pytest import MonkeyPatch
from sqlalchemy import update

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.goal_review import review_decision, review_input
from app.mana_operation_ai.application.model_continuation import public_goal
from app.mana_operation_ai.domain.goal_review import GoalReviewVerdictBody
from app.mana_operation_ai.domain.goals import GoalTask, OperationGoal
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import GoalRow
from tests.legacy_goal_contract import LegacyGoal
from tests.test_goal_continuation import context
from tests.test_inference_failures import wire
from tests.test_native_report_discovery import configure, new_goal
from tests.test_operation_api import headers
from tests.test_operation_goals import command
from tests.test_runtime_snapshots import evidence, native_goal

TEXT = "Full fictional parent report. No actual customer measurement. EXACT REVIEW FOOTER."


def reviewing() -> OperationGoal:
    goal = native_goal()
    goal.page_projection_enabled = goal.review_verdict_enabled = True
    goal.phase = "review"
    goal.plan = [
        GoalTask(title="Read the entire source", status="done"),
        GoalTask(title="Independently review all criteria", status="active"),
    ]
    goal.result = "Full synthetic analysis: parents, not children; no payment or causal proof."
    goal.evidence = [evidence(goal, TEXT)]
    return OperationGoal.model_validate(goal.model_dump())


def verdict(text: str, *, disposition: str = "accepted") -> GoalReviewVerdictBody:
    goal = OperationGoal.model_validate(json.loads(text)["goal"])
    descriptors = json.loads(review_input(text))["review_contract"]
    return GoalReviewVerdictBody.model_validate(
        {
            "input_sha256": descriptors["input_sha256"],
            "draft_sha256": descriptors["draft_sha256"],
            "checks": [
                {
                    "target": target,
                    "quote": getattr(goal.request, target),
                    "status": "passed",
                    "finding": "All criteria, dates and arithmetic checked.",
                }
                for target in ("objective", "success_criteria")
                if getattr(goal.request, target)
            ],
            "checked_plan_positions": list(range(len(goal.plan))),
            "conditions_checked": True,
            "evidence_checked": True,
            "evidence_ids": [item.report_id for item in goal.evidence],
            "disposition": disposition,
            "feedback": "Every original criterion checked; fictional scope only.",
        }
    )


@pytest.mark.parametrize("disposition", ["accepted", "revise", "waiting"])
def test_verdict_preserves_full_source_conditions_and_exact_draft(disposition: str) -> None:
    goal = reviewing()
    goal.request.objective = "Check every word: α\n  β 🧠, including the final clause."
    text = context(goal)
    sent = json.loads(review_input(text))
    assert sent["goal"] == json.loads(text)["goal"]
    assert sent["goal"]["evidence"][0]["summary"] == TEXT
    assert sent["goal"]["session_memory"]["user_context"]
    decision = review_decision(verdict(text, disposition=disposition), text)
    assert decision.draft == goal.result and decision.evidence_ids == ["exact-source"]
    assert [task.title for task in decision.plan] == [task.title for task in goal.plan]
    assert decision.requested_capability is None and decision.tool_call is None
    assert all(task.status == "done" for task in decision.plan) == (disposition == "accepted")


@pytest.mark.parametrize(
    "failure",
    [
        "input",
        "draft",
        "omit_objective",
        "omit_criterion",
        "not_checked",
        "conditions",
        "evidence",
        "plan",
        "citation",
        "duplicate_plan",
        "wrong_phase",
    ],
)
def test_verdict_cannot_silently_narrow_or_accept_an_unchecked_task(failure: str) -> None:
    goal = reviewing()
    text = context(goal)
    review = verdict(text)
    if failure in {"input", "draft"}:
        setattr(review, f"{failure}_sha256", "0" * 64)
    elif failure.startswith("omit"):
        review.checks[0 if failure == "omit_objective" else 1].quote = "Shortened user request"
    elif failure == "not_checked":
        review.checks[0].status = "not_checked"
    elif failure in {"conditions", "evidence"}:
        setattr(review, f"{failure}_checked", False)
    elif failure == "plan":
        review.checked_plan_positions = [0]
    elif failure == "duplicate_plan":
        review.checked_plan_positions = [0, 0]
    elif failure == "citation":
        review.evidence_ids = ["not-loaded"]
    else:
        goal.phase = "investigate"
        text = context(goal)
    with pytest.raises(ValueError):
        review_decision(review, text)


def test_exact_quote_fragments_private_receipt_and_strict_schema() -> None:
    goal = reviewing()
    text = context(goal)
    review = verdict(text)
    first = review.checks[0]
    review.checks = [
        first.model_copy(update={"quote": first.quote[:12]}),
        first.model_copy(update={"quote": first.quote[12:]}),
        *review.checks[1:],
    ]
    assert review_decision(review, text).draft == goal.result
    goal.review_receipt = review
    assert public_goal(goal).review_receipt is None
    assert "draft" not in review.model_dump() and "plan" not in review.model_dump()
    for field in ("conditions_checked", "evidence_checked"):
        with pytest.raises(ValidationError):
            GoalReviewVerdictBody.model_validate(review.model_dump() | {field: 1})
    with pytest.raises(ValidationError):
        GoalReviewVerdictBody.model_validate(review.model_dump() | {"draft": "rewrite"})


def enable(monkeypatch: MonkeyPatch, path: Path) -> None:
    configure(monkeypatch, path)
    for name in (
        "SNAPSHOT_REPLACEMENT",
        "PAGE_PROJECTION",
        "REVIEW_VERDICTS",
        "MODEL_CONTINUATION",
    ):
        monkeypatch.setenv(f"OPERATION_WORKSPACE_{name}_ENABLED", "true")
    get_settings.cache_clear()


@pytest.mark.parametrize("failure", [None, "bad_hash", "missing_coverage", "incomplete", "pending"])
async def test_sdk_reviews_full_input_without_reprinting_or_extra_call(
    monkeypatch: MonkeyPatch, tmp_path: Path, failure: str | None
) -> None:
    enable(monkeypatch, tmp_path / "sdk.db")
    requests: list[dict[str, Any]] = []
    original = context(reviewing())

    def transport(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["text"]["format"]["name"] == "GoalReviewVerdictBody"
        assert "tools" not in payload and payload["store"] is False
        assert payload["reasoning"] == {"effort": "medium"}
        assert payload["max_output_tokens"] == 8192
        sent = json.loads(payload["input"][-1]["content"])
        assert sent["goal"] == json.loads(original)["goal"]
        assert (
            sent["review_contract"]["input_sha256"] == hashlib.sha256(original.encode()).hexdigest()
        )
        review = verdict(original)
        if failure == "bad_hash":
            review.draft_sha256 = "0" * 64
        if failure == "missing_coverage":
            review.checks = review.checks[:1]
        body = wire("gpt-6.1-sol", "goal")
        body["output"][0]["content"][0]["text"] = review.model_dump_json()
        if failure == "incomplete":
            body.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        if failure == "pending":
            body["status"] = "in_progress"
        return httpx.Response(200, json=body)

    async def forbidden(*args: object, **kwargs: object) -> httpx.Response:
        raise AssertionError("A test attempted the real network")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    app = create_app()
    async with app.router.lifespan_context(app):
        gateway = app.state.operation_goal_service._continuing_model
        assert isinstance(gateway, OpenAIGoalModel)
        await gateway._client.close()
        gateway._client = AsyncOpenAI(
            api_key="fixture",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )
        if failure is not None:
            with pytest.raises(RuntimeError):
                await gateway.continue_decide(context=original, owner="alice", state=None)
        else:
            result = await gateway.continue_decide(context=original, owner="alice", state=None)
            assert result.review is not None and result.decision.draft == reviewing().result
            assert result.decision.disposition == "accepted"
            assert (
                result.continuation is not None
                and result.continuation.protocol == "goal-model-continuation-v5"
            )
        assert len(requests) == 1 and gateway._client.max_retries == 0
        periods = await app.state.operation_cost_ledger.periods()
        if failure == "pending":
            assert all(period.usage.llm_microusd > 681 for period in periods)
        else:
            assert all(period.usage.llm_microusd == 681 for period in periods)


async def test_capture_replay_restart_and_runtime_disable(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    enable(monkeypatch, tmp_path / "capture.db")
    monkeypatch.setenv("OPERATION_WORKSPACE_REVIEW_VERDICTS_ENABLED", "false")
    get_settings.cache_clear()
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        old = await new_goal(service)
        topic = await service._chats.topic("alice", old.topic_id)
        service.repository._review_verdict_enabled = True
        replay = await service.repository.create("alice", topic, old.request)
        assert not replay.review_verdict_enabled
        await service.repository.save("alice", old, old.model_copy(update={"status": "cancelled"}))
        service._review_verdict_enabled = True
        new = await new_goal(service)
        assert new.review_verdict_enabled
        storage = service.repository._storage(new)
        assert (
            storage["workspace_payload"] is not None
            and storage["workspace_payload"]["version"] == 14
        )
        assert "review_verdict_enabled" not in storage["payload"]
        assert "review_receipt" not in storage["payload"]
        assert LegacyGoal.model_validate(storage["payload"]).status == "cancelled"
        restored = await SqlAlchemyGoalRepository(app.state.operation_database, service._clock).get(
            "alice", new.goal_id
        )
        assert restored.request == new.request and restored.review_verdict_enabled
        with pytest.raises(ChatError):
            await service.repository.save(
                "alice", restored, restored.model_copy(update={"review_verdict_enabled": False})
            )
        service._review_verdict_enabled = False
        model = AsyncMock()
        service._model = service._continuing_model = model
        assert await service.tick()
        stopped = await service.repository.get("alice", new.goal_id)
        assert stopped.status == "waiting" and stopped.steps_used == 0
        model.continue_decide.assert_not_awaited()


@pytest.mark.parametrize("tamper", ["version", "flag", "false_old_field"])
async def test_v14_cannot_masquerade_as_old_contract(
    monkeypatch: MonkeyPatch, tmp_path: Path, tamper: str
) -> None:
    enable(monkeypatch, tmp_path / "tamper.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        saved = await new_goal(service)
        payload = service.repository._storage(saved)["workspace_payload"]
        assert payload is not None
        if tamper == "version":
            payload["version"] = 13
        elif tamper == "flag":
            payload["goal"]["review_verdict_enabled"] = False
        else:
            payload["version"] = 13
            payload["goal"]["review_verdict_enabled"] = False
            payload["goal"]["review_receipt"] = None
        async with app.state.operation_database.session_factory() as session, session.begin():
            await session.execute(
                update(GoalRow)
                .where(GoalRow.goal_id == saved.goal_id)
                .values(workspace_payload=payload)
            )
        with pytest.raises(ChatError):
            await service.repository.get("alice", saved.goal_id)


@pytest.mark.parametrize("disposition", ["accepted", "revise", "waiting", "pause"])
async def test_service_persists_verdict_or_fences_it_without_rewriting_draft(
    monkeypatch: MonkeyPatch, tmp_path: Path, disposition: str
) -> None:
    enable(monkeypatch, tmp_path / "service.db")
    started, release = asyncio.Event(), asyncio.Event()
    if disposition != "pause":
        release.set()
    requests: list[str] = []

    async def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        sent = json.loads(json.loads(request.content)["input"][-1]["content"])
        sent.pop("review_contract")
        original = json.dumps(sent, ensure_ascii=False)
        reviewed = verdict(
            original, disposition="accepted" if disposition == "pause" else disposition
        )
        if disposition != "accepted" and disposition != "pause":
            reviewed.checks[-1].status = "failed" if disposition == "revise" else "not_checked"
            reviewed.feedback = "Preserve all criteria; correct the remaining evidence limitations."
        body = wire("gpt-6.1-sol", "goal")
        body["output"][0]["content"][0]["text"] = reviewed.model_dump_json()
        started.set()
        await release.wait()
        return httpx.Response(200, json=body)

    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        saved = await new_goal(service)
        fixture = reviewing()
        snapshot = saved.model_copy(
            update={
                "phase": "review",
                "result": fixture.result,
                "plan": fixture.plan,
                "evidence": fixture.evidence,
            }
        )
        assert await service.repository.save("alice", saved, snapshot)
        gateway = service._continuing_model
        assert isinstance(gateway, OpenAIGoalModel)
        await gateway._client.close()
        gateway._client = AsyncOpenAI(
            api_key="fixture",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )
        source = AsyncMock()
        monkeypatch.setattr(service._admin, "run_now", source)
        if disposition == "pause":
            work = asyncio.create_task(service.tick())
            await asyncio.wait_for(started.wait(), 2)
            pending = await service.repository.get("alice", saved.goal_id)
            assert pending.unsettled_microusd > 0
            await service.command("alice", saved.goal_id, command(pending, "pause"))
            release.set()
            assert await work
        else:
            assert await service.tick()
        restored = await SqlAlchemyGoalRepository(app.state.operation_database, service._clock).get(
            "alice", saved.goal_id
        )
        assert restored.result == fixture.result and restored.request == saved.request
        assert restored.accounted_microusd == 681 and restored.unsettled_microusd == 0
        assert not restored.read_attempted and requests == ["/v1/responses"]
        source.assert_not_awaited()
        if disposition == "pause":
            assert restored.status == "paused" and restored.review_receipt is None
        else:
            assert restored.review_receipt is not None
            assert (
                restored.review_receipt.draft_sha256
                == hashlib.sha256(fixture.result.encode()).hexdigest()
            )
            assert (
                restored.status
                == {"accepted": "completed", "revise": "queued", "waiting": "waiting"}[disposition]
            )
            if disposition == "revise":
                assert restored.phase == "investigate"
                next_input = json.loads(service._context(restored))
                assert "review_receipt" not in next_input["goal"]
                assert (
                    next_input["review_feedback"]["historical_model_opinion_not_evidence"] is True
                )
                assert next_input["review_feedback"]["feedback"] == restored.review_receipt.feedback
            else:
                assert "review_feedback" not in json.loads(service._context(restored))
        assert public_goal(restored).review_receipt is None
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/api/v1/admin/operation/goals/{saved.goal_id}",
                headers=headers("alice", "operator"),
            )
            assert response.status_code == 200 and response.json()["review_receipt"] is None
