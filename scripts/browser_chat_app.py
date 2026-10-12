"""Local browser audit factory. Never contacts a model provider."""

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI
from pydantic import JsonValue
from sqlalchemy import select

from app.core.config import get_settings
from app.main import create_app as create_real_app
from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput
from app.mana_operation_ai.application.goal_ports import GoalModelOutput
from app.mana_operation_ai.application.goal_service import GoalWorker
from app.mana_operation_ai.application.retention.constants import PARENTS_CAPABILITY_KEY
from app.mana_operation_ai.application.runtime import SystemClock
from app.mana_operation_ai.domain.agent_tools import AgentToolCall
from app.mana_operation_ai.domain.chat import ChatTopic, ChatTurn
from app.mana_operation_ai.domain.enums import AgentRunStatus, TriggerType, UserRole
from app.mana_operation_ai.domain.goals import GoalCreate, GoalDecision, GoalTask, OperationGoal
from app.mana_operation_ai.domain.model_continuation import ModelContinuation
from app.mana_operation_ai.domain.models import AgentReport, AgentRun
from app.mana_operation_ai.infrastructure.agent_tool_schema import agent_function_tools
from app.mana_operation_ai.infrastructure.goal_continuation import (
    finish_continuation,
    prepare_continuation,
)
from app.mana_operation_ai.infrastructure.persistence.chat_repository import _storage
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import (
    AdminUserRow,
    ChatTopicRow,
    ChatTurnRow,
    GoalRow,
)
from app.mana_operation_ai.infrastructure.retention.parents import FakeParentSummaryAdapter

LONG_TOPIC = "00000000-0000-4000-8000-000000000110"
LONG_CONSTRAINT = "Не смешивай родителей и детей; не запускай повторный сбор данных."
ARCHIVE_TOPIC = "00000000-0000-4000-8000-000000000105"
ARCHIVE_CONSTRAINT = "Не контактируй с родителями; бюджет $5; только родительские когорты."


class BrowserConversationFake:
    async def stream_reply(
        self, *, instructions: str, context: str, owner: str
    ) -> AsyncGenerator[str | ChatTurnOutput, None]:
        if json.loads(context)["message"] == "Проверь поток ответа без новой цели":
            yield "Тестовый поток: начало 🧒"
            await asyncio.sleep(4)
            yield "Тестовый поток: начало 🧒 и продолжение"
            await asyncio.sleep(2)
            yield ChatTurnOutput(
                "Тестовый поток завершён и проверен.", "browser-fake", 10, 20, next_action="none"
            )
            return
        output = await self.reply(instructions=instructions, context=context, owner=owner)
        yield output.answer
        yield output

    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        payload = json.loads(context)
        message = str(payload.get("message", ""))
        agent_mode = "start_goal" in payload.get("allowed_next_actions", [])
        if message == "Продолжи анализ с условиями из первой архивной задачи":
            memory = payload.get("session_memory")
            assert memory and any(
                item["text"] == ARCHIVE_CONSTRAINT for item in memory["user_context"]
            )
            assert memory["older_checkpoints_omitted"] == 102
            return ChatTurnOutput(
                "Исходные условия переданы в рабочую цель.",
                "browser-fake",
                10,
                20,
                next_action="start_goal",
            )
        if message == "Проверь первое условие длинной темы":
            memory = payload.get("session_memory")
            assert memory and memory["user_context"][0]["text"] == LONG_CONSTRAINT
            assert payload["older_turns_omitted"] == 104
            return ChatTurnOutput(
                "Первое условие сохранено полностью: " + LONG_CONSTRAINT,
                "browser-fake",
                10,
                20,
                next_action="none",
            )
        if message == "Покажи предложения экспериментов":
            assert "approvals" in payload["allowed_next_actions"]
            return ChatTurnOutput(
                "Показываю sandbox-предложения для согласования.",
                "browser-fake",
                10,
                10,
                next_action="approvals",
            )
        if message == "Что получилось после согласования эксперимента?":
            memory = payload.get("session_memory")
            assert memory and memory["actions"][0]["verification_status"] == "verified"
            assert memory["actions"][0]["business_outcome"] == "not_measured"
            return ChatTurnOutput(
                "Sandbox-черновик создан и проверен. Конверсия не измерена.",
                "browser-fake",
                10,
                10,
                next_action="none",
            )
        if message == "Объясни второй вывод завершённого анализа":
            memory = payload.get("session_memory")
            assert memory and memory["checkpoints"][0]["status"] == "completed"
            assert "Тестовый анализ" in memory["checkpoints"][0]["result"]
            assert memory["checkpoints"][0]["sources"][0]["report_id"] == "browser-workspace-report"
            assert any("Последние 7 дней" in item["text"] for item in memory["user_context"])
            return ChatTurnOutput(
                "Продолжаю по сохранённому анализу: период — последние 7 дней. "
                "Повторный сбор данных не запускался.",
                "browser-fake",
                10,
                20,
                next_action="none",
            )
        return ChatTurnOutput(
            "Это тестовый ответ. Сначала уточним цель, затем проверим сохранённые отчёты. "
            "Изменения не выполнялись. Привязка данных к приложению не подтверждена.",
            "browser-fake",
            10,
            20,
            next_action=(
                "start_goal"
                if agent_mode
                else "mana_parents"
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

    def continuation_reservation(
        self, *, context: str, owner: str, state: ModelContinuation | None
    ) -> int:
        prepare_continuation(
            context=context,
            owner=owner,
            state=state,
            model="browser-goal-fake",
            maximum_bytes=192000,
        )
        return 20_000

    async def continue_decide(
        self, *, context: str, owner: str, state: ModelContinuation | None
    ) -> GoalModelOutput:
        prepared = prepare_continuation(
            context=context,
            owner=owner,
            state=state,
            model="browser-goal-fake",
            maximum_bytes=192000,
        )
        if prepared.goal.phase == "review":
            assert len(prepared.items) == 1
        output = await self.decide(context=context, owner=owner)
        items: list[dict[str, JsonValue]] = [
            {
                "type": "compaction",
                "id": f"browser-cmp-{prepared.goal.steps_used}",
                "encrypted_content": "test-browser-private-continuation",
            }
        ]
        call = output.decision.tool_call
        if call:
            schema = next(item for item in agent_function_tools() if item["name"] == call.name)
            parameters = schema["parameters"]
            assert parameters is not None
            properties = parameters["properties"]
            assert isinstance(properties, dict)
            arguments = {key: call.model_dump()[key] for key in properties}
            items.append(
                {
                    "type": "function_call",
                    "id": f"browser-fc-{prepared.goal.steps_used}",
                    "call_id": f"browser-call-{prepared.goal.steps_used}",
                    "name": call.name,
                    "arguments": json.dumps(arguments),
                }
            )
        else:
            items.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "id": f"browser-msg-{prepared.goal.steps_used}",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": output.decision.model_dump_json(exclude={"tool_call"}),
                            "annotations": [],
                        }
                    ],
                }
            )
        output.continuation = finish_continuation(
            prepared, items, model="browser-goal-fake", call=call, maximum_bytes=192000
        )
        return output

    async def decide(self, *, context: str, owner: str) -> GoalModelOutput:
        goal = json.loads(context)["goal"]
        agent_mode = goal["request"].get("execution_mode") == "agent"
        waiting = goal["phase"] == "investigate" and not goal["instructions"]
        recall = "Прошлая рабочая цель" in goal["request"]["objective"]
        archive = "первой архивной задачи" in goal["request"]["objective"]
        paged = "Прочитай полный сохранённый отчёт вместе с концом" in goal["request"]["objective"]
        if archive:
            assert any(
                item["text"] == ARCHIVE_CONSTRAINT
                for item in goal["session_memory"]["user_context"]
            )
        if recall:
            waiting = False
        if paged:
            waiting = False
        tool = None
        if paged:
            if not goal["tools"]:
                tool = AgentToolCall(name="inspect_sources")
            else:
                item = goal["evidence"][0] if goal["evidence"] else None
                progress = item.get("report_read_progress") if item else None
                if progress is None or progress["next_offset"] < progress["total_characters"]:
                    tool = AgentToolCall(
                        name="read_saved_report_page",
                        report_id="browser-paged-report",
                        offset=progress["next_offset"] if progress else 0,
                    )
                elif goal["phase"] == "review":
                    assert item is not None and item["summary"].endswith("EXACT PAGED FOOTER")
                    assert not item["shortened"]
        elif recall and not goal["tools"]:
            tool = AgentToolCall(name="find_saved_tasks", query="", cursor=None)
        elif recall and len(goal["tools"]) == 1:
            tool = AgentToolCall(
                name="read_saved_task",
                task_id=goal["session_memory"]["checkpoints"][0]["goal_id"],
                offset=0,
            )
        elif recall and len(goal["tools"]) == 2:
            tool = AgentToolCall(name="read_saved_report", report_id="browser-workspace-report")
        elif agent_mode and not goal["tools"]:
            tool = AgentToolCall(name="inspect_sources")
        elif agent_mode and len(goal["tools"]) == 1:
            tool = AgentToolCall(name="read_saved_report", report_id="browser-workspace-report")
        elif agent_mode and waiting:
            tool = AgentToolCall(
                name="ask_user",
                question="Уточните период анализа",
                options=["Последние 7 дней", "Последние 30 дней"],
            )
        return GoalModelOutput(
            GoalDecision(
                update="Проверяю источники и ограничения",
                plan=[
                    GoalTask(
                        title="Проверить удержание по данным MANA",
                        status="done" if goal["phase"] == "review" else "active",
                    )
                ],
                draft=(
                    "Исходные условия из первой задачи сохранены. " + ARCHIVE_CONSTRAINT + " "
                    if archive
                    else ""
                )
                + ("EXACT PAGED FOOTER проверен. " if paged else "")
                + "Тестовый анализ. Есть исторические агрегаты, но платежи и отток "
                "по единой когорте не подтверждены. Данные пользователей не изменялись.",
                evidence_ids=[item["report_id"] for item in goal["evidence"]],
                disposition="waiting"
                if waiting and not agent_mode
                else "accepted"
                if goal["phase"] == "review"
                else "continue",
                missing_information="Уточните период анализа" if waiting else "",
                requested_capability=None,
                tool_call=tool,
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
            if settings.operation_workspace_chat_streaming_enabled:
                application.state.operation_chat_service._streaming_model = (
                    BrowserConversationFake()
                )
            application.state.operation_goal_service._model = BrowserGoalFake()
            if settings.operation_workspace_model_continuation_enabled:
                application.state.operation_goal_service._continuing_model = BrowserGoalFake()
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
            if settings.operation_agent_workspace_enabled:
                database = application.state.operation_database
                topic = ChatTopic(
                    topic_id=LONG_TOPIC,
                    agent_id="operations-orchestrator",
                    product="mana",
                    title="Длинная история",
                    created_at=observed,
                    updated_at=observed,
                )
                async with database.session_factory() as session, session.begin():
                    owner = await session.scalar(
                        select(AdminUserRow.user_id).where(AdminUserRow.telegram_id == 976835256)
                    )
                    assert owner is not None
                    if await session.get(ChatTopicRow, LONG_TOPIC) is None:
                        session.add(
                            ChatTopicRow(
                                topic_id=LONG_TOPIC,
                                owner=owner,
                                updated_at=observed,
                                payload=topic.model_dump(mode="json"),
                            )
                        )
                        await session.flush()
                        for index in range(110):
                            turn = ChatTurn(
                                turn_id=str(uuid4()),
                                topic_id=LONG_TOPIC,
                                request_id=uuid4(),
                                message=LONG_CONSTRAINT
                                if index == 0
                                else "Продолжай с исходными условиями.",
                                answer=f"Исторический ответ {index + 1}",
                                status="completed",
                                created_at=observed + timedelta(seconds=index),
                            )
                            session.add(
                                ChatTurnRow(
                                    turn_id=turn.turn_id,
                                    topic_id=LONG_TOPIC,
                                    owner=owner,
                                    request_id=str(turn.request_id),
                                    status=turn.status,
                                    created_at=turn.created_at,
                                    **_storage(turn),
                                )
                            )
                    if await session.get(ChatTopicRow, ARCHIVE_TOPIC) is None:
                        archive_topic = topic.model_copy(
                            update={"topic_id": ARCHIVE_TOPIC, "title": "Архив условий"}
                        )
                        session.add(
                            ChatTopicRow(
                                topic_id=ARCHIVE_TOPIC,
                                owner=owner,
                                updated_at=observed,
                                payload=archive_topic.model_dump(mode="json"),
                            )
                        )
                        await session.flush()
                        for index in range(105):
                            at = observed + timedelta(seconds=index)
                            goal = OperationGoal(
                                goal_id=str(uuid4()),
                                topic_id=ARCHIVE_TOPIC,
                                agent_id="operations-orchestrator",
                                product="mana",
                                status="completed",
                                request=GoalCreate(
                                    request_id=uuid4(),
                                    objective="Архивная тестовая задача.",
                                    constraints=ARCHIVE_CONSTRAINT if index == 0 else "",
                                ),
                                created_at=at,
                                updated_at=at,
                                result="Архивный тестовый результат.",
                            )
                            session.add(
                                GoalRow(
                                    goal_id=goal.goal_id,
                                    topic_id=ARCHIVE_TOPIC,
                                    owner=owner,
                                    request_id=str(goal.request.request_id),
                                    **SqlAlchemyGoalRepository._storage(goal),
                                )
                            )
                admin = application.state.operation_admin_service
                configuration = await repository.latest_configuration(
                    "growth-agent", "growth.funnel.analyze"
                )
                assert configuration is not None
                await admin.create_configuration(
                    agent_id="growth-agent",
                    capability_key="growth.funnel.analyze",
                    values={**configuration.values, "experiment_mode": "sandbox"},
                    actor=ActorContext("browser-fixture", UserRole.ADMIN),
                )
                await admin.run_now(
                    agent_id="growth-agent",
                    capability_key="growth.funnel.analyze",
                    job_type="analysis",
                    correlation_id="browser-experiment",
                    idempotency_key="browser-experiment",
                    actor=ActorContext("browser-fixture", UserRole.ADMIN),
                )
                await repository.create_run(
                    AgentRun(
                        run_id="browser-workspace-run",
                        agent_id="retention-agent",
                        capability_key="retention.engagement.analyze",
                        correlation_id="browser-workspace",
                        trigger=TriggerType.API,
                        initiated_by="browser-fixture",
                        status=AgentRunStatus.COMPLETED,
                        configuration_version=1,
                        idempotency_key="browser-workspace",
                        started_at=now,
                        updated_at=now,
                        completed_at=now,
                    )
                )
                await repository.save_report(
                    AgentReport(
                        report_id="browser-workspace-report",
                        run_id="browser-workspace-run",
                        agent_id="retention-agent",
                        capability_key="retention.engagement.analyze",
                        report_type="retention_engagement_analysis",
                        created_at=now,
                        period_start=now - timedelta(days=7),
                        period_end=now,
                        human_readable=(
                            "Synthetic parents-only activity summary. Not production data."
                        ),
                        structured={
                            "product": "mana",
                            "scope_verified": True,
                            "scope_basis": "approved_source_binding",
                            "collected_at": now.isoformat(),
                            "fresh_until": (now + timedelta(hours=6)).isoformat(),
                            "refresh_status": "live",
                        },
                        data_quality_notes=["Browser fixture only; no Firebase/GA4 reads."],
                    )
                )
                base_run = await repository.get_run("browser-workspace-run")
                base_report = await repository.get_report("browser-workspace-report")
                assert base_run is not None and base_report is not None
                await repository.create_run(
                    base_run.model_copy(
                        update={
                            "run_id": "browser-paged-run",
                            "idempotency_key": "browser-paged-run",
                        }
                    )
                )
                await repository.save_report(
                    base_report.model_copy(
                        update={
                            "report_id": "browser-paged-report",
                            "run_id": "browser-paged-run",
                            "human_readable": "Synthetic minimized report. "
                            + "р" * 8100
                            + " EXACT PAGED FOOTER",
                        }
                    )
                )
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
