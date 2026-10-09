"""Local browser audit factory. Never contacts a model provider."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI

from app.core.config import get_settings
from app.main import create_app as create_real_app
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput
from app.mana_operation_ai.application.goal_ports import GoalModelOutput
from app.mana_operation_ai.application.goal_service import GoalWorker
from app.mana_operation_ai.application.retention.constants import PARENTS_CAPABILITY_KEY
from app.mana_operation_ai.application.runtime import SystemClock
from app.mana_operation_ai.domain.enums import AgentRunStatus, TriggerType
from app.mana_operation_ai.domain.goals import GoalDecision, GoalTask
from app.mana_operation_ai.domain.models import AgentReport, AgentRun
from app.mana_operation_ai.infrastructure.retention.parents import FakeParentSummaryAdapter


class BrowserConversationFake:
    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        message = str(json.loads(context).get("message", ""))
        return ChatTurnOutput(
            "Это тестовый ответ. Сначала уточним цель, затем проверим сохранённые отчёты. "
            "Изменения не выполнялись. Привязка данных к приложению не подтверждена.",
            "browser-fake",
            10,
            20,
            next_action=(
                "mana_parents"
                if "Проверь родителей MANA" in message
                else "approvals"
                if "Покажи предложения" in message
                else "analyze"
                if "Собери свежие данные" in message
                else "none"
            ),
        )


class BrowserGoalFake:
    def reservation(self, context: str) -> int:
        return 20_000

    async def decide(self, *, context: str, owner: str) -> GoalModelOutput:
        goal = json.loads(context)["goal"]
        waiting = goal["phase"] == "investigate" and not goal["instructions"]
        return GoalModelOutput(
            GoalDecision(
                update="Проверяю источники и ограничения",
                plan=[
                    GoalTask(
                        title="Проверить удержание по данным MANA",
                        status="done" if goal["phase"] == "review" else "active",
                    )
                ],
                draft="Тестовый анализ. Есть исторические агрегаты, но платежи и отток "
                "по единой когорте не подтверждены. Данные пользователей не изменялись.",
                evidence_ids=[item["report_id"] for item in goal["evidence"]],
                disposition="waiting"
                if waiting
                else "accepted"
                if goal["phase"] == "review"
                else "continue",
                missing_information="Уточните период анализа" if waiting else "",
                requested_capability=None,
            ),
            "browser-goal-fake",
            5000,
        )


def create_app() -> FastAPI:
    settings = get_settings()
    if (
        settings.app_env != "local"
        or settings.operation_ads_provider != "fake_meta"
        or settings.operation_product_activity_provider != "fake"
        or settings.operation_scheduler_enabled
        or settings.audio_moderation_enabled
        or settings.manakids_parent_source_enabled
        or settings.openai_api_key.get_secret_value() != "test-openai-key"
    ):
        raise RuntimeError("Browser harness requires isolated fake settings")
    app = create_real_app()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def fake_lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with original_lifespan(application):
            application.state.operation_chat_service._model = BrowserConversationFake()
            application.state.operation_goal_service._model = BrowserGoalFake()
            goal_worker = GoalWorker(application.state.operation_goal_service, poll_seconds=0.1)
            goal_worker.start()
            application.state.operation_chat_service.availability.parent_summary_enabled = True
            retention = application.state.operation_agent_registry.get("retention-agent")
            retention.capabilities.get(PARENTS_CAPABILITY_KEY)._source = FakeParentSummaryAdapter(
                SystemClock()
            )
            now = SystemClock().now()
            observed = now - timedelta(hours=8)
            repository = application.state.operation_repository
            await repository.create_run(
                AgentRun(
                    run_id="browser-historical-parent-run",
                    agent_id="retention-agent",
                    capability_key=PARENTS_CAPABILITY_KEY,
                    correlation_id="browser-historical-parent",
                    trigger=TriggerType.API,
                    initiated_by="browser-fixture",
                    status=AgentRunStatus.COMPLETED,
                    configuration_version=1,
                    idempotency_key="browser-historical-parent",
                    started_at=observed,
                    updated_at=observed,
                    completed_at=observed,
                )
            )
            if await repository.get_report("browser-historical-parent-report") is None:
                await repository.save_report(
                    AgentReport(
                        report_id="browser-historical-parent-report",
                        run_id="browser-historical-parent-run",
                        agent_id="retention-agent",
                        capability_key=PARENTS_CAPABILITY_KEY,
                        report_type="mana_parent_summary",
                        period_start=observed,
                        period_end=observed,
                        created_at=now,
                        structured={
                            "product": "mana",
                            "scope_verified": True,
                            "scope_basis": "owner_confirmed_parent_api",
                            "collected_at": observed.isoformat(),
                            "fresh_until": (observed + timedelta(hours=6)).isoformat(),
                            "refresh_status": "cached",
                        },
                        human_readable="Synthetic historical prefix: 2 parents, 1 child link.",
                        data_quality_notes=["Browser fixture only; not real parents/payments."],
                    )
                )
            try:
                yield
            finally:
                await goal_worker.stop()

    app.router.lifespan_context = fake_lifespan
    return app
