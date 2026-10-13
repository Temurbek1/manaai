"""Bounded SQL discovery only: fake data, no source/model/production calls."""

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch
from sqlalchemy import event, update

from app.core.config import get_settings
from app.main import create_app
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.report_catalog import (
    REPORT_CATALOG_PAGE_SIZE,
    SavedReportCandidatePage,
    SavedReportCatalogQuery,
    catalog_cursor,
    catalog_position,
)
from app.mana_operation_ai.domain.chat import TopicCreate
from app.mana_operation_ai.domain.enums import AgentRunStatus, AgentStatus, TriggerType
from app.mana_operation_ai.domain.goals import GoalCreate
from app.mana_operation_ai.domain.models import AgentDefinition, AgentReport, AgentRun
from app.mana_operation_ai.infrastructure.agent_tool_schema import agent_function_tools
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import AgentReportRow
from app.mana_operation_ai.infrastructure.persistence.repository import (
    SqlAlchemyOperationRepository,
)
from tests.test_operation_agent_workspace import configure_workspace
from tests.test_operation_goals import seed

NOW = datetime(2026, 10, 14, 10, tzinfo=UTC)


def search(**updates: object) -> SavedReportCatalogQuery:
    return SavedReportCatalogQuery.model_validate(
        {
            "scope_id": "synthetic-goal",
            "product": "mana",
            "agent_ids": ("retention-agent",),
            "before": NOW,
            **updates,
        }
    )


async def catalog_agents(repository: SqlAlchemyOperationRepository) -> None:
    for agent_id in ("retention-agent", "growth-agent", "marketing-agent"):
        await repository.register_agent(
            AgentDefinition(
                agent_id=agent_id,
                display_name=agent_id,
                description="Synthetic catalog fixture",
                version="test",
                status=AgentStatus.ENABLED,
                capabilities=[],
                default_capability_key="retention.engagement.analyze",
                configuration_schema={},
                registered_at=NOW,
            )
        )


async def catalog_report(
    repository: SqlAlchemyOperationRepository,
    report_id: str,
    *,
    product: str = "mana",
    agent_id: str = "retention-agent",
    created_at: datetime = NOW - timedelta(seconds=1),
    text: str = "Synthetic saved report only",
    verified: bool = True,
    capability: str = "retention.engagement.analyze",
) -> AgentReport:
    run = AgentRun(
        run_id="run-" + report_id,
        agent_id=agent_id,
        capability_key=capability,
        correlation_id="synthetic-catalog",
        trigger=TriggerType.API,
        initiated_by="fixture",
        status=AgentRunStatus.COMPLETED,
        configuration_version=1,
        idempotency_key="catalog-" + report_id,
        started_at=created_at,
        updated_at=created_at,
        completed_at=created_at,
    )
    await repository.create_run(run)
    report = AgentReport(
        report_id=report_id,
        agent_id=agent_id,
        capability_key=capability,
        run_id=run.run_id,
        report_type="retention_engagement_analysis",
        period_start=created_at - timedelta(days=7),
        period_end=created_at,
        human_readable=text,
        structured={
            "product": product,
            "scope_verified": verified,
            "scope_basis": "approved_source_binding",
            "collected_at": created_at.isoformat(),
            "fresh_until": (created_at + timedelta(hours=6)).isoformat(),
            "refresh_status": "live",
        },
        data_quality_notes=["Synthetic fixture, not actual customer activity."],
        created_at=created_at,
    )
    await repository.save_report(report)
    return report


async def test_sql_catalog_keyset_ties_cutoff_product_aliases_and_new_insert(
    tmp_path: Path,
) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'catalog.db'}")
    await db.create_schema()
    repository = SqlAlchemyOperationRepository(db)
    try:
        await catalog_agents(repository)
        for index in range(23):
            await catalog_report(repository, f"candidate-{index:03}")
        await catalog_report(repository, "foreign-product", product="360rec")
        await catalog_report(repository, "foreign-agent", agent_id="growth-agent")
        await catalog_report(repository, "at-cutoff", created_at=NOW)
        query = search()
        first = await repository.page_report_candidates(query)
        assert len(first.reports) == REPORT_CATALOG_PAGE_SIZE
        assert [item.report_id for item in first.reports] == [
            f"candidate-{index:03}" for index in range(22, 12, -1)
        ]
        assert first.next_cursor is not None
        await catalog_report(repository, "new-after-cutoff", created_at=NOW + timedelta(seconds=1))
        second = await repository.page_report_candidates(query, cursor=first.next_cursor)
        assert second.next_cursor is not None
        third = await repository.page_report_candidates(query, cursor=second.next_cursor)
        all_ids = [item.report_id for page in (first, second, third) for item in page.reports]
        assert all_ids == [f"candidate-{index:03}" for index in range(22, -1, -1)]
        assert third.next_cursor is None
        assert await repository.page_report_candidates(query, cursor=first.next_cursor) == second
        await catalog_report(repository, "old-alias", agent_id="marketing-agent")
        aliases = await repository.page_report_candidates(
            search(agent_ids=("growth-agent", "marketing-agent"))
        )
        assert {item.report_id for item in aliases.reports} == {"foreign-agent", "old-alias"}
    finally:
        await db.dispose()


@pytest.mark.parametrize(
    "updates",
    [
        {"scope_id": "other-goal"},
        {"product": "360rec"},
        {"agent_ids": ("growth-agent",)},
        {"query": "other"},
        {"capability_key": "retention.parents.analyze"},
        {"before": NOW - timedelta(seconds=2)},
    ],
)
def test_cursor_cannot_switch_goal_product_agent_query_capability_or_cutoff(
    updates: dict[str, object],
) -> None:
    cursor = catalog_cursor(search(), report_id="anchor", created_at=NOW - timedelta(seconds=3))
    with pytest.raises(ChatError, match="Курсор"):
        catalog_position(search(**updates), cursor)


@pytest.mark.parametrize("cursor", ["", "!invalid", "{" + "secret" * 300, "текст"])
def test_malformed_cursor_is_controlled_and_never_echoed(cursor: str) -> None:
    with pytest.raises(ChatError) as failure:
        catalog_position(search(), cursor)
    assert failure.value.status == 422
    assert cursor not in str(failure.value) if cursor else True


def test_cursor_requires_aware_dates_closed_fields_and_normalizes_agent_order() -> None:
    query = search(agent_ids=("growth-agent", "retention-agent"))
    cursor = catalog_cursor(query, report_id="anchor", created_at=NOW - timedelta(seconds=1))
    same = search(agent_ids=("retention-agent", "growth-agent", "retention-agent"))
    assert catalog_position(same, cursor).report_id == "anchor"
    decoded = json.loads(base64.urlsafe_b64decode(cursor))
    decoded["permission"] = "not a grant"
    with pytest.raises(ChatError):
        catalog_position(query, base64.urlsafe_b64encode(json.dumps(decoded).encode()).decode())
    with pytest.raises(ValidationError):
        search(before=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        search(agent_ids=())
    with pytest.raises(ValidationError):
        search(query="x" * 121)


@pytest.mark.parametrize("version", [True, False, 1.0, "1", 2, None])
def test_cursor_version_is_exact_and_not_sdk_coerced(version: object) -> None:
    cursor = catalog_cursor(search(), report_id="anchor", created_at=NOW - timedelta(seconds=1))
    decoded = json.loads(base64.urlsafe_b64decode(cursor))
    decoded["version"] = version
    with pytest.raises(ChatError):
        catalog_position(search(), base64.urlsafe_b64encode(json.dumps(decoded).encode()).decode())


async def test_cursor_anchor_is_rechecked_and_sql_is_bounded_without_count(tmp_path: Path) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'anchors.db'}")
    await db.create_schema()
    repository = SqlAlchemyOperationRepository(db)
    statements: list[str] = []

    def capture(*args: object) -> None:
        statements.append(str(args[2]).lower())

    try:
        await catalog_agents(repository)
        for index in range(12):
            await catalog_report(repository, f"anchor-{index:03}")
        event.listen(db.engine.sync_engine, "before_cursor_execute", capture)
        first = await repository.page_report_candidates(search())
        assert first.next_cursor is not None
        assert len(statements) == 1 and "limit" in statements[0]
        assert "count(" not in statements[0] and "offset" in statements[0]  # SQLite emits OFFSET 0.
        statements.clear()
        second = await repository.page_report_candidates(search(), cursor=first.next_cursor)
        assert len(statements) == 2 and len(second.reports) == 2
        assert all("count(" not in statement for statement in statements)
        forged = catalog_cursor(
            search(), report_id="anchor-002", created_at=NOW - timedelta(seconds=4)
        )
        with pytest.raises(ChatError, match="Позиция"):
            await repository.page_report_candidates(search(), cursor=forged)
        async with db.session_factory.begin() as session:
            anchor = catalog_position(search(), first.next_cursor)
            await session.execute(
                update(AgentReportRow)
                .where(AgentReportRow.report_id == anchor.report_id)
                .values(created_at=NOW)
            )
        with pytest.raises(ChatError, match="Позиция"):
            await repository.page_report_candidates(search(), cursor=first.next_cursor)
    finally:
        event.remove(db.engine.sync_engine, "before_cursor_execute", capture)
        await db.dispose()


async def test_literal_search_escapes_sql_wildcards_and_filters_capability(tmp_path: Path) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'literal.db'}")
    await db.create_schema()
    repository = SqlAlchemyOperationRepository(db)
    try:
        await catalog_agents(repository)
        await catalog_report(repository, "literal", text=r"Needle 50%_\\ value")
        await catalog_report(repository, "wildcard", text="Needle 50abcXYZ value")
        query = search(query=r"50%_\\")
        page = await repository.page_report_candidates(query)
        assert [item.report_id for item in page.reports] == ["literal"]
        assert not (
            await repository.page_report_candidates(
                search(query="50%_", capability_key="retention.parents.analyze")
            )
        ).reports
    finally:
        await db.dispose()


async def test_discovery_finds_deep_verified_report_without_evidence_or_source_dispatch(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "deep.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        await seed(service)
        topic = await service._chats.create(
            "alice", TopicCreate(agent_id="operations-orchestrator", product="mana", title="Search")
        )
        goal = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(request_id=uuid4(), objective="Find saved data", execution_mode="agent"),
        )
        for index in range(23):
            await catalog_report(
                service._admin.repository,
                f"deep-{index:03}",
                created_at=goal.created_at - timedelta(seconds=1),
                text="needle: synthetic minimized report",
                verified=index == 0,
            )
        source = AsyncMock()
        monkeypatch.setattr(service._admin, "run_now", source)
        baseline = goal.model_dump_json()
        first = json.loads(await service._tools.find_reports(goal, query="needle", cursor=None))
        assert first["saved_reports"] == [] and first["next_cursor"] is not None
        second = json.loads(
            await service._tools.find_reports(goal, query="needle", cursor=first["next_cursor"])
        )
        assert second["saved_reports"] == [] and second["next_cursor"] is not None
        third = json.loads(
            await service._tools.find_reports(goal, query="needle", cursor=second["next_cursor"])
        )
        assert [item["report_id"] for item in third["saved_reports"]] == ["deep-000"]
        assert third["next_cursor"] is None
        assert third["references_only"] and not third["loaded_into_evidence"]
        assert not third["permission_granted"] and "synthetic minimized report" not in json.dumps(
            third
        )
        assert goal.model_dump_json() == baseline
        source.assert_not_called()
        # Foundation is deliberately not advertised until checkpoint/tool compatibility exists.
        assert "find_saved_reports" not in {tool["name"] for tool in agent_function_tools()}
    get_settings.cache_clear()


async def test_application_scope_literal_query_and_snapshot_cutoff_are_rechecked(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    configure_workspace(monkeypatch, tmp_path / "scopes.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        await seed(service)
        for agent_id, product, expected in [
            ("operations-orchestrator", "mana", ["matching"]),
            ("growth-agent", "mana", []),
            ("operations-orchestrator", "360rec", ["other-app"]),
        ]:
            topic = await service._chats.create(
                "alice", TopicCreate(agent_id=agent_id, product=product, title="Scope")
            )
            goal = await service.create(
                "alice",
                topic.topic_id,
                GoalCreate(request_id=uuid4(), objective="Find saved data", execution_mode="agent"),
            )
            if expected == ["matching"]:
                for report_id, app_product, text in [
                    ("matching", "mana", "Exact needle"),
                    ("wrong-case", "mana", "EXACT needle"),
                    ("other-app", "360rec", "Exact needle"),
                ]:
                    await catalog_report(
                        service._admin.repository,
                        report_id,
                        product=app_product,
                        text=text,
                        created_at=goal.created_at - timedelta(seconds=1),
                    )
                await catalog_report(
                    service._admin.repository,
                    "future",
                    created_at=goal.created_at + timedelta(days=1),
                    text="Exact needle",
                )
            value = json.loads(await service._tools.find_reports(goal, query="Exact", cursor=None))
            assert [item["report_id"] for item in value["saved_reports"]] == expected
            assert "EXACT needle" not in json.dumps(value)
    get_settings.cache_clear()


async def test_catalog_rejects_inconsistent_sql_payload_with_controlled_error(
    tmp_path: Path,
) -> None:
    db = OperationDatabase(f"sqlite+aiosqlite:///{tmp_path / 'integrity.db'}")
    await db.create_schema()
    repository = SqlAlchemyOperationRepository(db)
    try:
        await catalog_agents(repository)
        report = await catalog_report(repository, "inconsistent")
        async with db.session_factory.begin() as session:
            await session.execute(
                update(AgentReportRow)
                .where(AgentReportRow.report_id == report.report_id)
                .values(payload={**report.model_dump(mode="json"), "agent_id": "growth-agent"})
            )
        with pytest.raises(ChatError, match="целостности") as failure:
            await repository.page_report_candidates(search())
        assert failure.value.status == 503
    finally:
        await db.dispose()


@pytest.mark.parametrize("kind", ["oversized", "wrong_anchor", "wrong_scope", "discussion"])
async def test_application_port_does_not_trust_adapter_page_or_cursor(
    monkeypatch: MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    configure_workspace(monkeypatch, tmp_path / f"port-{kind}.db")
    app = create_app()
    async with app.router.lifespan_context(app):
        service = app.state.operation_goal_service
        await seed(service)
        topic = await service._chats.create(
            "alice", TopicCreate(agent_id="operations-orchestrator", product="mana", title="Port")
        )
        goal = await service.create(
            "alice",
            topic.topic_id,
            GoalCreate(request_id=uuid4(), objective="Find saved data", execution_mode="agent"),
        )
        report = await service._admin.get_report("report-mana")
        assert report is not None
        query = search(
            scope_id=goal.goal_id,
            before=goal.created_at,
            agent_ids=("growth-agent", "marketing-agent", "retention-agent"),
        )
        page = SavedReportCandidatePage((report,), None)
        if kind == "oversized":
            page = SavedReportCandidatePage((report,) * 11, None)
        elif kind in {"wrong_anchor", "wrong_scope"}:
            page = SavedReportCandidatePage(
                (report,),
                catalog_cursor(
                    query if kind == "wrong_anchor" else search(),
                    report_id="other-anchor" if kind == "wrong_anchor" else report.report_id,
                    created_at=report.created_at,
                ),
            )
        else:
            goal = goal.model_copy(
                update={"request": goal.request.model_copy(update={"execution_mode": "discussion"})}
            )
        adapter = AsyncMock(return_value=page)
        monkeypatch.setattr(service._admin.repository, "page_report_candidates", adapter)
        with pytest.raises(ChatError):
            await service._tools.find_reports(goal, query="", cursor=None)
        if kind == "discussion":
            adapter.assert_not_called()
    get_settings.cache_clear()
