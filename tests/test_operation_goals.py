import asyncio
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.goal_ports import GoalModelOutput
from app.mana_operation_ai.application.goal_service import GoalWorker, OperationGoalService
from app.mana_operation_ai.domain.chat import TopicCreate
from app.mana_operation_ai.domain.enums import (
    AdminUserStatus,
    AgentRunStatus,
    TriggerType,
    UserRole,
)
from app.mana_operation_ai.domain.goals import (
    GoalCommand,
    GoalCreate,
    GoalDecision,
    GoalTask,
    OperationGoal,
)
from app.mana_operation_ai.domain.models import AgentReport, AgentRun, AgentRunResult
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from tests.test_operation_api import configure_operation_env, headers
from tests.test_operation_chat import BASE as CHAT
from tests.test_operation_cost_ledger import Clock

BASE = "/api/v1/admin/operation/goals"


class GoalFake:
    def __init__(self) -> None:
        self.contexts: list[dict[str, object]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.fail = False
        self.bad_citation = False
        self.revise = False
        self.ask_read = False

    def reservation(self, context: str) -> int:
        return 20_000

    async def decide(self, *, context: str, owner: str) -> GoalModelOutput:
        payload = json.loads(context)
        self.contexts.append(payload)
        self.started.set()
        await self.release.wait()
        if self.fail:
            raise RuntimeError("PRIVATE upstream secret")
        goal = OperationGoal.model_validate(payload["goal"])
        decision = GoalDecision(
            update=f"Шаг {goal.phase}",
            plan=[
                GoalTask(
                    title="Проверить удержание",
                    status="done" if goal.phase == "review" else "active",
                )
            ],
            draft="Факты и ограничения проверены; report-mana. Рост удержания не подтверждён.",
            evidence_ids=["fabricated"]
            if self.bad_citation
            else [item.report_id for item in goal.evidence],
            disposition="waiting"
            if self.ask_read
            else "revise"
            if self.revise and goal.phase == "review"
            else "accepted"
            if goal.phase == "review"
            else "continue",
            missing_information="Нужна свежая вовлечённость." if self.ask_read else "",
            requested_capability="retention.engagement.analyze" if self.ask_read else None,
        )
        return GoalModelOutput(decision, "fake-strong", 5_000)


async def seed(
    service: OperationGoalService,
    *,
    product: str = "mana",
    stale: bool = False,
    future: bool = False,
    shortened: bool = False,
) -> None:
    now = service._clock.now()
    await service._admin.repository.create_run(
        AgentRun(
            run_id=f"synthetic-run-{product}",
            agent_id="retention-agent",
            capability_key="retention.engagement.analyze",
            correlation_id="synthetic-goal",
            trigger=TriggerType.API,
            initiated_by="fixture",
            status=AgentRunStatus.COMPLETED,
            configuration_version=1,
            idempotency_key=f"synthetic-run-{product}",
            started_at=now,
            updated_at=now,
            completed_at=now,
        )
    )
    await service._admin.repository.save_report(
        AgentReport(
            report_id=f"report-{product}",
            run_id=f"synthetic-run-{product}",
            agent_id="retention-agent",
            capability_key="retention.engagement.analyze",
            report_type="retention_engagement_analysis",
            created_at=now,
            period_start=now - timedelta(days=7),
            period_end=now,
            human_readable="x" * 5100
            if shortened
            else "Дети: 100 активных. Платежи недоступны. Причины оттока не установлены.",
            structured={
                "product": product,
                "scope_verified": True,
                "scope_basis": "approved_source_binding",
                "collected_at": (
                    now + timedelta(days=1) if future else now - timedelta(hours=7 if stale else 1)
                ).isoformat(),
                "fresh_until": (now + timedelta(hours=-1 if stale else 5)).isoformat(),
                "refresh_status": "live",
            },
            data_quality_notes=[],
        )
    )


async def new_goal(
    service: OperationGoalService,
    *,
    owner: str = "alice",
    product: str = "mana",
    max_steps: int = 6,
    budget: int = 500_000,
) -> OperationGoal:
    topic = await service._chats.create(
        owner, TopicCreate(agent_id="operations-orchestrator", product=product, title="Удержание")
    )
    return await service.create(
        owner,
        topic.topic_id,
        GoalCreate(
            request_id=uuid4(),
            objective="Проанализируй текущее положение пользователей и подготовь план удержания.",
            max_steps=max_steps,
            budget_microusd=budget,
        ),
    )


def command(goal: OperationGoal, action: str, message: str = "") -> GoalCommand:
    return GoalCommand(
        request_id=uuid4(), command=action, expected_revision=goal.revision, message=message
    )


async def test_goal_api_private_idempotent_rbac_and_durable_restart(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "goals.db")
    saved: OperationGoal | None = None
    for restart in (False, True):
        app = create_app()
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
        ):
            service: OperationGoalService = app.state.operation_goal_service
            fake = GoalFake()
            service._model = fake
            if not restart:
                topic = (
                    await client.post(
                        f"{CHAT}/topics",
                        headers=headers("alice", "admin"),
                        json={
                            "agent_id": "operations-orchestrator",
                            "product": "mana",
                            "title": "Цель",
                        },
                    )
                ).json()
                path = f"{BASE}/topics/{topic['topic_id']}"
                payload = {
                    "request_id": str(uuid4()),
                    "objective": "Проанализируй текущее удержание пользователей.",
                }
                assert (
                    await client.post(path, headers=headers("alice", "viewer"), json=payload)
                ).status_code == 403
                response = await client.post(path, headers=headers("alice", "admin"), json=payload)
                assert response.status_code == 202
                saved = OperationGoal.model_validate(response.json())
                replay = await client.post(path, headers=headers("alice", "admin"), json=payload)
                assert replay.json() == response.json()
                assert (
                    await client.post(
                        path,
                        headers=headers("alice", "admin"),
                        json={**payload, "objective": "Другое описание цели полностью."},
                    )
                ).status_code == 409
                assert fake.contexts == []
                assert (
                    await client.get(f"{BASE}/{saved.goal_id}", headers=headers("bob", "admin"))
                ).status_code == 404
                assert (
                    await client.post(
                        f"{BASE}/{saved.goal_id}/commands",
                        headers=headers("bob", "admin"),
                        json=command(saved, "cancel").model_dump(mode="json"),
                    )
                ).status_code == 404
                await seed(service)
                await seed(service, product="360rec")
                assert await service.tick()
                saved = await service.repository.get("alice", saved.goal_id)
                assert saved.phase == "investigate" and saved.steps_used == 1
            else:
                assert saved
                restored = await service.repository.get("alice", saved.goal_id)
                assert restored.request == saved.request and restored.plan == saved.plan
                await service.tick()
                await service.tick()
                result = await service.repository.get("alice", saved.goal_id)
                assert result.status == "completed" and result.steps_used == 3
                assert result.accounted_microusd == 15_000
                assert [item.report_id for item in result.evidence] == ["report-mana"]
                assert all("report-360rec" not in json.dumps(context) for context in fake.contexts)
                assert result.events[-1].kind == "result"
                assert not await service.tick()
                assert (
                    await client.get(
                        "/api/v1/admin/operation/runs", headers=headers("alice", "admin")
                    )
                ).json()["total"] == 2
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "stale",
        "citation",
        "exception",
        "budget",
        "steps",
        "kill",
        "future",
        "shortened",
        "revoked",
    ],
)
async def test_goal_cannot_fake_completion_or_auto_retry(
    monkeypatch: MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "failure.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service: OperationGoalService = app.state.operation_goal_service
        fake = GoalFake()
        fake.bad_citation = failure == "citation"
        fake.fail = failure == "exception"
        fake.revise = failure == "steps"
        if failure == "budget":
            monkeypatch.setattr(fake, "reservation", lambda context: 60_000)
        service._model = fake
        if failure != "missing":
            await seed(
                service,
                stale=failure == "stale",
                future=failure == "future",
                shortened=failure == "shortened",
            )
        if failure == "kill":
            await service._admin.repository.set_control(
                key="global_kill_switch",
                enabled=True,
                updated_at=service._clock.now(),
                updated_by="fixture",
            )
        goal = await new_goal(
            service,
            max_steps=3 if failure == "steps" else 6,
            budget=50_000 if failure == "budget" else 500_000,
        )
        if failure == "revoked":
            auth = AsyncMock()
            auth.get_user.return_value = SimpleNamespace(
                status=AdminUserStatus.DISABLED, role=UserRole.ADMIN
            )
            service._auth = auth
        for _ in range(8):
            await service.tick()
        result = await service.repository.get("alice", goal.goal_id)
        assert result.status == "waiting" and result.waiting_reason
        assert "PRIVATE" not in result.model_dump_json()
        calls = len(fake.contexts)
        assert not await service.tick()
        assert len(fake.contexts) == calls
        if failure == "exception":
            assert result.accounted_microusd == 20_000
        if failure in ("kill", "revoked"):
            assert calls == 0
    get_settings.cache_clear()


async def test_goal_pause_wins_inflight_and_controls_are_idempotent(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "pause.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service: OperationGoalService = app.state.operation_goal_service
        fake = GoalFake()
        fake.release.clear()
        service._model = fake
        goal = await new_goal(service)
        ticking = asyncio.create_task(service.tick())
        await fake.started.wait()
        goal = await service.repository.get("alice", goal.goal_id)
        pause = command(goal, "pause")
        paused = await service.command("alice", goal.goal_id, pause)
        assert (await service.command("alice", goal.goal_id, pause)).status == "paused"
        with pytest.raises(Exception, match="заканчивается"):
            await service.command("alice", goal.goal_id, command(paused, "resume"))
        fake.release.set()
        await ticking
        paused = await service.repository.get("alice", goal.goal_id)
        assert paused.status == "paused" and paused.result == "" and paused.lease_until is None
        assert paused.steps_used == 1 and paused.accounted_microusd == 20_000
        with pytest.raises(Exception, match="изменилось"):
            await service.command("alice", goal.goal_id, command(goal, "cancel"))
        resumed = await service.command(
            "alice",
            goal.goal_id,
            command(paused, "steer", "Не используй данные детей как данные родителей."),
        )
        assert resumed.status == "queued" and resumed.instructions
        await service.tick()
        assert fake.contexts[-1]["goal"]["instructions"] == resumed.instructions  # type: ignore[index]
        current = await service.repository.get("alice", goal.goal_id)
        cancelled = await service.command("alice", goal.goal_id, command(current, "cancel"))
        assert cancelled.status == "cancelled"
        assert not await service.tick()
    get_settings.cache_clear()


async def test_goal_sql_claim_singleflight_and_unknown_restart_recovery(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "claim.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service: OperationGoalService = app.state.operation_goal_service
        clock = Clock()
        repos = [SqlAlchemyGoalRepository(app.state.operation_database, clock) for _ in range(4)]
        service.repository = repos[0]
        goal = await new_goal(service)
        claims = await asyncio.gather(*[repos[i % 4].claim() for i in range(20)])
        assert sum(item is not None for item in claims) == 1
        claimed = next(item for item in claims if item is not None)[1]
        held = claimed.model_copy(update={"steps_used": 1, "accounted_microusd": 20_000})
        assert await repos[0].save("alice", claimed, held)
        clock.value += timedelta(minutes=6)
        assert await repos[1].claim() is None
        recovered = await repos[1].get("alice", goal.goal_id)
        assert recovered.status == "waiting" and recovered.accounted_microusd == 20_000
        assert not await repos[0].save(
            "alice", claimed, claimed.model_copy(update={"status": "completed"})
        )
        assert await repos[2].claim() is None
    get_settings.cache_clear()


@pytest.mark.parametrize("product", ["mana", "360rec"])
async def test_goal_read_requires_verified_binding_and_one_separate_confirmation(
    monkeypatch: MonkeyPatch, tmp_path: Path, product: str
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "read.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service: OperationGoalService = app.state.operation_goal_service
        fake = GoalFake()
        fake.ask_read = True
        service._model = fake
        service.availability.read_capabilities = ["retention.engagement.analyze"]
        service.availability.read_product = "mana"
        run = AsyncMock(
            return_value=AgentRunResult(run_id="fake-read", status=AgentRunStatus.COMPLETED)
        )
        monkeypatch.setattr(service._admin, "run_now", run)
        goal = await new_goal(service, product=product)
        await service.tick()
        goal = await service.repository.get("alice", goal.goal_id)
        assert goal.status == "waiting" and run.call_count == 0
        assert bool(goal.requested_capability) is (product == "mana")
        if product == "mana":
            approval = command(goal, "approve_read")
            await service.command("alice", goal.goal_id, approval)
            await service.tick()
            await service.command("alice", goal.goal_id, approval)
            await service.tick()
            goal = await service.repository.get("alice", goal.goal_id)
            assert run.call_count == 1 and goal.read_attempted and not goal.requested_capability
            assert fake.contexts[-1]["allowed_read_capabilities"] == []
    get_settings.cache_clear()


async def test_goal_worker_runs_without_browser_and_stops_cleanly(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "worker.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service: OperationGoalService = app.state.operation_goal_service
        fake = GoalFake()
        service._model = fake
        await seed(service)
        goal = await new_goal(service)
        worker = GoalWorker(service, poll_seconds=0.01)
        worker.start()
        try:
            async with asyncio.timeout(5):
                while (await service.repository.get("alice", goal.goal_id)).status != "completed":
                    await asyncio.sleep(0.01)
        finally:
            await worker.stop()
        assert len(fake.contexts) == 3
    get_settings.cache_clear()


@pytest.mark.parametrize("paused", [False, True])
async def test_goal_read_failure_or_pause_never_replays_source(
    monkeypatch: MonkeyPatch, tmp_path: Path, paused: bool
) -> None:
    configure_operation_env(monkeypatch, tmp_path / "read-failure.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service: OperationGoalService = app.state.operation_goal_service
        fake = GoalFake()
        fake.ask_read = True
        service._model = fake
        service.availability.read_product = "mana"
        service.availability.read_capabilities = ["retention.engagement.analyze"]
        read = AsyncMock(
            return_value=AgentRunResult(run_id="failed-read", status=AgentRunStatus.FAILED)
        )
        monkeypatch.setattr(service._admin, "run_now", read)
        goal = await new_goal(service)
        await service.tick()
        goal = await service.repository.get("alice", goal.goal_id)
        await service.command("alice", goal.goal_id, command(goal, "approve_read"))
        if paused:
            save = service.repository.save

            async def pause_after_reservation(
                owner: str, before: OperationGoal, after: OperationGoal
            ) -> bool:
                result = await save(owner, before, after)
                if result and after.read_attempted and after.status == "running":
                    current = await service.repository.get(owner, after.goal_id)
                    await service.command(owner, after.goal_id, command(current, "pause"))
                return result

            monkeypatch.setattr(service.repository, "save", pause_after_reservation)
        await service.tick()
        result = await service.repository.get("alice", goal.goal_id)
        assert result.status == ("paused" if paused else "waiting")
        assert result.read_attempted and result.approved_capability is None
        assert read.call_count == (0 if paused else 1)
        for _ in range(5):
            assert not await service.tick()
        assert len(fake.contexts) == 1
    get_settings.cache_clear()
