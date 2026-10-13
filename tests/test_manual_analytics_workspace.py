"""Manual source capabilities through actual bootstrap, SQL, HTTP and Goals."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pytest import MonkeyPatch
from sqlalchemy import select

import app.main as main_module
from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.chat_service import _verified_report_product
from app.mana_operation_ai.application.goal_ports import GoalModelOutput
from app.mana_operation_ai.application.goal_tools import GoalEvidenceTools
from app.mana_operation_ai.application.ports import ProviderPermanentError
from app.mana_operation_ai.application.retention.analytics_evidence import (
    ManualAnalyticsEvidenceHandler,
)
from app.mana_operation_ai.application.shared_data import SharedDataUnavailable
from app.mana_operation_ai.domain.agent_tools import AgentToolCall
from app.mana_operation_ai.domain.chat import MessageCreate, TopicCreate
from app.mana_operation_ai.domain.enums import TriggerType, UserRole
from app.mana_operation_ai.domain.first_party_analytics import (
    CHILD_TELEMETRY_CAPABILITY,
    PARENT_ACTIVITY_CAPABILITY,
    ChildTelemetryFacts,
    ParentAnalyticsFacts,
)
from app.mana_operation_ai.domain.goals import GoalCreate, GoalDecision, OperationGoal
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import CostReservationRow, GoalRow
from app.mana_operation_ai.infrastructure.retention import analytics_runtime
from tests.legacy_goal_contract import LegacyGoal
from tests.test_manual_analytics_sources import Token, firestore_payload, ga4_payload
from tests.test_operation_agent_workspace import ToolModel, configure_workspace
from tests.test_operation_api import headers
from tests.test_operation_chat import FakeConversation
from tests.test_operation_cost_ledger import Clock
from tests.test_operation_goals import command


def configure(monkeypatch: MonkeyPatch, tmp_path: Path) -> Clock:
    configure_workspace(monkeypatch, tmp_path / "manual-workspace.db")
    clock = Clock(datetime(2026, 10, 12, 10, tzinfo=UTC))
    monkeypatch.setattr(main_module, "SystemClock", lambda: clock)
    key = tmp_path / "fake-credential.json"
    key.write_text("{}")
    for name, value in {
        "OPERATION_PARENT_ANALYTICS_ENABLED": "true",
        "OPERATION_CHILD_TELEMETRY_ENABLED": "true",
        "OPERATION_PARENT_ANALYTICS_BINDING_REVISION": "owner-fixture-v1",
        "OPERATION_CHILD_TELEMETRY_BINDING_REVISION": "owner-fixture-v1",
        "GA4_PROPERTY_ID": "12345",
        "GA4_PARENT_STREAM_ID": "99",
        "GA4_PARENT_PROPERTY_TIMEZONE": "Etc/GMT-5",
        "GA4_SERVICE_ACCOUNT_FILE": str(key),
        "FIREBASE_PROJECT_ID": "fake-project",
        "FIREBASE_SERVICE_ACCOUNT_FILE": str(key),
        "OPERATION_PRODUCT_ACTIVITY_PROVIDER": "fake",
        "MANAKIDS_API_USERNAME": "",
        "MANAKIDS_API_PASSWORD": "",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        analytics_runtime, "GoogleServiceAccountTokenProvider", lambda *args, **kwargs: Token()
    )
    get_settings.cache_clear()
    return clock


def sources(
    app: FastAPI,
) -> tuple[
    ManualAnalyticsEvidenceHandler[ParentAnalyticsFacts],
    ManualAnalyticsEvidenceHandler[ChildTelemetryFacts],
]:
    # Tests deliberately inspect the assembled source boundary, not a replacement handler.
    registry = app.state.operation_agent_registry
    capabilities = registry.get("retention-agent").capabilities
    return (
        cast(
            ManualAnalyticsEvidenceHandler[ParentAnalyticsFacts],
            capabilities.get(PARENT_ACTIVITY_CAPABILITY),
        ),
        cast(
            ManualAnalyticsEvidenceHandler[ChildTelemetryFacts],
            capabilities.get(CHILD_TELEMETRY_CAPABILITY),
        ),
    )


class ManualAnalyticsModel(ToolModel):
    async def decide(self, *, context: str, owner: str) -> GoalModelOutput:
        goal = OperationGoal.model_validate(json.loads(context)["goal"])
        if goal.read_attempted and not goal.evidence:
            receipt = json.loads(goal.tools[-1].result)
            return GoalModelOutput(
                GoalDecision(
                    update="Читаю сохранённый результат подтверждённого сбора.",
                    plan=goal.plan,
                    draft=goal.result,
                    evidence_ids=[],
                    disposition="continue",
                    missing_information="",
                    requested_capability=None,
                    tool_call=AgentToolCall(
                        name="read_saved_report", report_id=receipt["report_id"]
                    ),
                ),
                "fake-strong",
                5000,
            )
        return await super().decide(context=context, owner=owner)


async def test_manual_capabilities_cache_restart_shared_roles_and_product_isolation(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    clock = configure(monkeypatch, tmp_path)
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=ga4_payload(request)
            if "analyticsdata" in request.url.host
            else firestore_payload(request, clock),
        )

    for restart in range(2):
        app = create_app()
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.MockTransport(handle)) as source_client,
        ):
            parent, child = sources(app)
            parent._source._http._client = source_client  # type: ignore[attr-defined]
            child._source._http._client = source_client  # type: ignore[attr-defined]
            # Bootstrap, registry polling and source health do not collect anything.
            assert await parent.health() == [] and await child.health() == []
            assert len(requests) == (0 if restart == 0 else 7)
            runner = app.state.operation_agent_service
            report_ids = []
            for key in [PARENT_ACTIVITY_CAPABILITY, CHILD_TELEMETRY_CAPABILITY]:
                result = await runner.run_now(
                    agent_id="retention-agent",
                    capability_key=key,
                    job_type="analysis",
                    trigger=TriggerType.USER,
                    actor_id=f"operator-{restart}",
                    actor_role=UserRole.OPERATOR,
                    idempotency_key=f"manual-{restart}-{key}",
                )
                assert result.report_id
                report_ids.append(result.report_id)
                assert (
                    await app.state.operation_repository.list_schedules("retention-agent", key)
                    == []
                )
                replay = await runner.run_now(
                    agent_id="retention-agent",
                    capability_key=key,
                    job_type="analysis",
                    trigger=TriggerType.USER,
                    actor_id="different-actor",
                    actor_role=UserRole.OPERATOR,
                    idempotency_key=f"manual-{restart}-{key}",
                )
                assert replay.run_id == result.run_id
            assert len(requests) == 7
            ledger = app.state.operation_cost_ledger
            assert (await ledger.periods())[0].usage.provider_requests == 7
            if restart == 0:
                clock.value += timedelta(hours=1)
                continue
            for report_id in report_ids:
                report = await app.state.operation_repository.get_report(report_id)
                assert report and report.structured["refresh_status"] == "cached"
                assert report.structured["collected_at"] == "2026-10-12T10:00:00Z"
                assert "PRIVATE" not in report.model_dump_json()
                assert _verified_report_product(report) == "mana"
                for field, value in [
                    ("population", "wrong_population"),
                    ("product_scope", "360rec"),
                    ("source", "other_source"),
                    ("collected_at", "not-a-date"),
                    ("unexpected_private_field", "PRIVATE"),
                ]:
                    invalid = report.model_copy(
                        update={"structured": {**report.structured, field: value}}
                    )
                    assert _verified_report_product(invalid) is None
                wrong_type = report.model_copy(
                    update={"report_type": "retention_engagement_analysis"}
                )
                assert _verified_report_product(wrong_type) is None
            chat = app.state.operation_chat_service
            model = FakeConversation()
            chat._model = model
            for agent in [
                "operations-orchestrator",
                "growth-agent",
                "retention-agent",
                "technical-agent",
            ]:
                for product in ["mana", "360rec"]:
                    topic = await chat.create(
                        "alice", TopicCreate(agent_id=agent, product=product, title="Data scope")
                    )
                    output = await chat.send(
                        "alice",
                        topic.topic_id,
                        MessageCreate(request_id=uuid4(), message="Какие данные подтверждены?"),
                    )
                    context = model.contexts[-1]
                    reports = cast(list[dict[str, Any]], context["saved_reports"])
                    if product == "mana":
                        assert len(reports) == 2 and len(output.sources) == 2
                        assert all(
                            item["scope_verified"] and item["product"] == "mana" for item in reports
                        )
                    else:
                        assert context["saved_reports"] == [] and output.sources == []
            assert len(requests) == 7
            with pytest.raises(ProviderPermanentError, match="manual"):
                await runner.run_now(
                    agent_id="retention-agent",
                    capability_key=PARENT_ACTIVITY_CAPABILITY,
                    job_type="analysis",
                    trigger=TriggerType.SCHEDULE,
                    actor_id="scheduler",
                    actor_role=UserRole.OPERATOR,
                    idempotency_key="must-not-schedule",
                )
            assert len(requests) == 7
            # A query-shape change cannot bypass the binding-wide source cooldown.
            child._cache_parameters["sample_limit"] = 10
            with pytest.raises(SharedDataUnavailable, match="cooldown"):
                await runner.run_now(
                    agent_id="retention-agent",
                    capability_key=CHILD_TELEMETRY_CAPABILITY,
                    job_type="analysis",
                    trigger=TriggerType.USER,
                    actor_id="operator",
                    actor_role=UserRole.OPERATOR,
                    idempotency_key="changed-shape",
                )
            assert len(requests) == 7


async def test_native_goal_read_approval_v9_restart_and_legacy_closed_projection(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure(monkeypatch, tmp_path)
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=ga4_payload(request))

    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.MockTransport(handle)) as source_client,
    ):
        parent, _ = sources(app)
        parent._source._http._client = source_client  # type: ignore[attr-defined]
        service = app.state.operation_goal_service
        service._model = ManualAnalyticsModel(
            AgentToolCall(name="request_source_read", capability=PARENT_ACTIVITY_CAPABILITY)
        )
        topic = await app.state.operation_chat_service.create(
            "alice", TopicCreate(agent_id="growth-agent", product="mana", title="Retention data")
        )
        goal = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(),
                objective="Изучи родительскую активность MANA, только чтение.",
                execution_mode="agent",
            ),
        )
        assert PARENT_ACTIVITY_CAPABILITY in service._allowed_reads(goal)
        assert await service.tick() and await service.tick()
        waiting = await service.repository.get("alice", goal.goal_id)
        assert (
            waiting.status == "waiting"
            and waiting.requested_capability == PARENT_ACTIVITY_CAPABILITY
        )
        assert requests == []
        async with app.state.operation_database.session_factory() as session:
            row = await session.scalar(select(GoalRow).where(GoalRow.goal_id == goal.goal_id))
            assert row and row.workspace_payload["version"] == 9
            legacy = LegacyGoal.model_validate(row.payload)
            assert legacy.status == "cancelled" and legacy.requested_capability is None
        service.repository = SqlAlchemyGoalRepository(app.state.operation_database, service._clock)
        approved = await service.command("alice", goal.goal_id, command(waiting, "approve_read"))
        assert approved.approved_capability == PARENT_ACTIVITY_CAPABILITY
        assert await service.tick()
        collected = await service.repository.get("alice", goal.goal_id)
        assert collected.read_attempted and len(requests) == 5 and not collected.evidence
        assert await service.tick()
        collected = await service.repository.get("alice", goal.goal_id)
        assert collected.evidence and len(requests) == 5
        assert collected.evidence[0].capability_key == PARENT_ACTIVITY_CAPABILITY
        assert service._allowed_reads(collected) == []
        tools = GoalEvidenceTools(service._admin, service._clock, service.repository)
        evidence = await tools.read(collected, collected.evidence[0].report_id)
        assert evidence.refresh_status == "live" and evidence.product == "mana"
        forbidden = collected.model_copy(update={"product": "360rec"})
        with pytest.raises(ChatError, match="области"):
            await tools.read(forbidden, evidence.report_id)
        with pytest.raises(ChatError):
            await service.command("bob", collected.goal_id, command(collected, "pause"))
        async with app.state.operation_database.session_factory() as session:
            row = await session.scalar(select(GoalRow).where(GoalRow.goal_id == goal.goal_id))
            assert row and row.workspace_payload["version"] == 9
            assert LegacyGoal.model_validate(row.payload).status == "cancelled"
        assert len(requests) == 5


async def test_disabled_manual_sources_are_not_advertised(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "disabled.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        assert PARENT_ACTIVITY_CAPABILITY not in service.availability.read_capabilities
        assert CHILD_TELEMETRY_CAPABILITY not in service.availability.read_capabilities
        keys = {
            item.key
            for item in app.state.operation_agent_registry.get(
                "retention-agent"
            ).definition.capabilities
        }
        assert PARENT_ACTIVITY_CAPABILITY not in keys and CHILD_TELEMETRY_CAPABILITY not in keys


@pytest.mark.parametrize("failure", ["timeout", "403"])
async def test_http_child_approval_failure_is_consumed_and_never_reissued_after_restart(
    monkeypatch: MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    configure(monkeypatch, tmp_path)
    requests: list[httpx.Request] = []
    goal_id = ""

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("PRIVATE upstream detail", request=request)
        return httpx.Response(403, json={"error": "PRIVATE upstream detail"})

    for restart in range(2):
        app = create_app()
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.MockTransport(handle)) as source_client,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client,
        ):
            _, child = sources(app)
            child._source._http._client = source_client  # type: ignore[attr-defined]
            service = app.state.operation_goal_service
            service._model = ToolModel(
                AgentToolCall(name="request_source_read", capability=CHILD_TELEMETRY_CAPABILITY)
            )
            base = "/api/v1/admin/operation/goals"
            if not restart:
                topic = await app.state.operation_chat_service.create(
                    "alice",
                    TopicCreate(
                        agent_id="operations-orchestrator", product="mana", title="Device quality"
                    ),
                )
                response = await client.post(
                    f"{base}/topics/{topic.topic_id}",
                    headers=headers("alice", "operator"),
                    json=GoalCreate(
                        request_id=uuid4(),
                        objective="Проверь качество телеметрии MANA, без родителей.",
                        execution_mode="agent",
                    ).model_dump(mode="json"),
                )
                assert response.status_code == 202, response.text
                goal_id = response.json()["goal_id"]
                assert await service.tick() and await service.tick()
                waiting = await service.repository.get("alice", goal_id)
                approval = command(waiting, "approve_read").model_dump(mode="json")
                for actor, role, status in [("alice", "viewer", 403), ("bob", "admin", 404)]:
                    denied = await client.post(
                        f"{base}/{goal_id}/commands", headers=headers(actor, role), json=approval
                    )
                    assert denied.status_code == status
                assert requests == []
                approved = await client.post(
                    f"{base}/{goal_id}/commands",
                    headers=headers("alice", "operator"),
                    json=approval,
                )
                assert approved.status_code == 200
                replay = await client.post(
                    f"{base}/{goal_id}/commands",
                    headers=headers("alice", "operator"),
                    json=approval,
                )
                assert replay.json()["revision"] == approved.json()["revision"]
                assert await service.tick()
            goal = await service.repository.get("alice", goal_id)
            assert goal.status == "waiting" and goal.read_attempted
            assert not goal.requested_capability and not goal.approved_capability
            assert goal.tools[-1].status == "unknown"
            assert service._allowed_reads(goal) == []
            assert not await service.tick()
            assert len(requests) == 1
            view = await client.get(f"{base}/{goal_id}", headers=headers("alice", "viewer"))
            assert view.status_code == 200 and "PRIVATE" not in view.text
            ledger = (await app.state.operation_cost_ledger.periods())[0]
            if failure == "timeout":
                async with app.state.operation_database.session_factory() as session:
                    reservations = list(await session.scalars(select(CostReservationRow)))
                source_holds = [
                    row
                    for row in reservations
                    if row.attribution.get("source") == "firestore_child_telemetry"
                ]
                assert len(source_holds) == 1 and source_holds[0].actual is None
            assert ledger.usage.document_reads == 100 and ledger.usage.provider_requests == 1
            with pytest.raises(SharedDataUnavailable):
                await app.state.operation_agent_service.run_now(
                    agent_id="retention-agent",
                    capability_key=CHILD_TELEMETRY_CAPABILITY,
                    job_type="analysis",
                    trigger=TriggerType.USER,
                    actor_id="another-operator",
                    actor_role=UserRole.OPERATOR,
                    idempotency_key=f"failure-cache-{restart}",
                )
            assert len(requests) == 1
