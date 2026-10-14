"""One independent native catalog/analysis diagnostic; offline by default, <= $0.49."""

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import NoReturn, cast
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.mana_operation_ai.application.admin_service import OperationAdminService  # noqa: E402
from app.mana_operation_ai.application.goal_service import OperationGoalService  # noqa: E402
from app.mana_operation_ai.application.runtime import SystemClock  # noqa: E402
from app.mana_operation_ai.application.session_context import OperationSessionContext  # noqa: E402
from app.mana_operation_ai.domain.chat import TopicCreate  # noqa: E402
from app.mana_operation_ai.domain.cost_control import CostLimits, ResourceUsage  # noqa: E402
from app.mana_operation_ai.domain.enums import (  # noqa: E402
    AgentRunStatus,
    AgentStatus,
    TriggerType,
)
from app.mana_operation_ai.domain.goals import GoalAvailability, GoalCreate  # noqa: E402
from app.mana_operation_ai.domain.models import AgentDefinition, AgentReport, AgentRun  # noqa: E402
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel  # noqa: E402
from app.mana_operation_ai.infrastructure.persistence.chat_repository import (  # noqa: E402
    SqlAlchemyChatRepository,
)
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import (  # noqa: E402
    SqlAlchemyCostLedger,
)
from app.mana_operation_ai.infrastructure.persistence.database import (
    OperationDatabase,  # noqa: E402
)
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (  # noqa: E402
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.repository import (  # noqa: E402
    SqlAlchemyOperationRepository,
)
from scripts.operation_workspace_evaluate import receipts  # noqa: E402

BUDGET = 490000
MAX_STEPS = 12
OUTPUT_TOKENS = 8192
REPORT_ID = "catalog-parent-cohort"
OBSERVED = datetime(2026, 9, 25, tzinfo=UTC)
HEADER = """SYNTHETIC DIAGNOSTIC ONLY. No real MANA customer or production measurement.
Observation cutoff: 2026-09-25T00:00:00Z, UTC. Complete fictional parent cohorts only.
Cohort A: 800 registered MANA parents, registrations 2026-09-01 through 2026-09-07.
Cohort B: 200 distinct parents, registrations 2026-08-25 through 2026-08-31.
All D1/D7 and each parent's first 14-day funnel windows are fully observed.
D1 is a return in [24h,48h) since registration; D7 is [168h,192h), not lifetime return.
Same-cohort A ordered funnel, deduplicated parents, each stage a subset of its predecessor:
registration=800; email verified=680; child linked=340; first safety rule executed=272;
successful payment=136. Payers are unique confirmed parents in this FICTIONAL ledger.
Payment amounts, currency, subscriptions, renewals/refunds are absent. Views are not execution.
Separate activity window: DAU=150, WAU=400; not cohort membership or D7.
Separate ten-parent prefix: nine non-free tariffs; not confirmed payments or a population rate.
Child inventory=5000, active children=2500; neither is a parent retention denominator.
Parent activity geography: Tashkent=1400, Samarkand=1100; not payment-confirmed order geography.
No randomized experiment, individual churn cause, contacts, consents or executed action.
The retention counts and final caveats are in the last portion of this complete saved text.
"""
FOOTER = """FINAL RETENTION OBSERVATIONS. A: 520 D1 returns and 200 D7 returns.
B: 100 D7 returns. A/B cohorts are different people, not individual before/after tracking.
The correct pooled denominator comprises both full cohorts, not an average of percentages.
Do not infer the intersection of D1 and D7 parents: it was not observed.
Neither activity geography, tariffs nor child counts establish purchases, causes or sales.
EXACT CATALOG QUALITY FOOTER: recommendations are hypotheses, no measured business lift.
"""
REPORT = (
    HEADER
    + (
        "Supplemental fixture note: no identities, external sources, causal evidence or actions.\n"
        * 65
    )
    + FOOTER
)


class CatalogOnlyAdmin:
    """Actual saved SQL port only; no owning-domain/source executor is assembled."""

    def __init__(self, repository: SqlAlchemyOperationRepository) -> None:
        self.repository = repository
        self.source_attempts = 0

    def agent_identifiers(self, agent_id: str) -> set[str]:
        return {"growth-agent", "marketing-agent"} if agent_id == "growth-agent" else {agent_id}

    async def get_report(self, report_id: str) -> AgentReport | None:
        return await self.repository.get_report(report_id)

    async def run_now(self, **kwargs: object) -> NoReturn:
        self.source_attempts += 1
        raise AssertionError(
            "External sources and actions are forbidden in this isolated diagnostic"
        )


def oracle() -> dict[str, object]:
    def percentage(numerator: int, denominator: int) -> str:
        return f"{float(Fraction(numerator, denominator) * 100):.2f}"

    return {
        "d1_a_pct": percentage(520, 800),
        "d7_a_pct": percentage(200, 800),
        "d7_b_pct": percentage(100, 200),
        "d7_delta_pp": "-25.00",
        "d7_relative_change_pct": "-50.00",
        "pooled_d7_pct": percentage(300, 1000),
        "unweighted_mean_and_dau_wau_are_wrong_pct": "37.50",
        "purchase_conversion_pct": percentage(136, 800),
        "funnel_transitions": [
            {
                "from": before,
                "to": after,
                "conversion_pct": percentage(after, before),
                "lost": before - after,
            }
            for before, after in [(800, 680), (680, 340), (340, 272), (272, 136)]
        ],
        "largest_absolute_loss": "verification to linking: 340 parents",
        "largest_relative_loss_tied": "verification to linking and core action to payment: 50%",
        "semantic_review_required": True,
    }


def plan(
    *,
    project_pages: bool = False,
    review_verdicts: bool = False,
    compact_threshold: int | None = None,
) -> dict[str, object]:
    if review_verdicts and not project_pages:
        raise ValueError("Verdict diagnostics require the captured paged-catalog contract")
    if compact_threshold is not None and (
        type(compact_threshold) is not int or compact_threshold not in {8000, 24000}
    ):
        raise ValueError("Only the two explicit existing compaction profiles are supported")
    return {
        "max_calls": MAX_STEPS,
        "budget_microusd": BUDGET,
        "model": "gpt-6.1-sol",
        "reasoning": "medium",
        "max_output_tokens": OUTPUT_TOKENS,
        "requested_compact_threshold": compact_threshold,
        "analysis_scope": "saved_snapshot",
        "workspace_contract": "v14/v5"
        if review_verdicts
        else "v13/v4"
        if project_pages
        else "v11/v2",
        "source_attempts": 0,
        "production_changes": 0,
        "replay": False,
        "dataset": "23 newer invalid-binding candidates and one full dated parent-cohort report",
        "fixture": REPORT,
        "oracle_not_model_input": oracle(),
    }


async def seed(repository: SqlAlchemyOperationRepository, clock: SystemClock) -> None:
    now = clock.now()
    await repository.register_agent(
        AgentDefinition(
            agent_id="retention-agent",
            display_name="Synthetic Retention",
            description="Local fixture",
            version="fixture",
            status=AgentStatus.ENABLED,
            capabilities=[],
            default_capability_key="retention.engagement.analyze",
            configuration_schema={},
            registered_at=now,
        )
    )
    for index in range(24):
        target = index == 0
        identifier = REPORT_ID if target else f"z-catalog-invalid-{index:03}"
        created_at = now - timedelta(hours=2 if target else 1)
        run = AgentRun(
            run_id="run-" + identifier,
            agent_id="retention-agent",
            capability_key="retention.engagement.analyze",
            correlation_id="isolated-catalog-eval",
            trigger=TriggerType.API,
            initiated_by="synthetic-evaluator",
            status=AgentRunStatus.COMPLETED,
            configuration_version=1,
            idempotency_key=identifier,
            started_at=created_at,
            updated_at=created_at,
            completed_at=created_at,
        )
        await repository.create_run(run)
        await repository.save_report(
            AgentReport(
                report_id=identifier,
                agent_id=run.agent_id,
                capability_key=run.capability_key,
                run_id=run.run_id,
                report_type="retention_engagement_analysis",
                period_start=datetime(2026, 8, 25, tzinfo=UTC),
                period_end=OBSERVED,
                created_at=created_at,
                human_readable=REPORT if target else "Invalid binding fixture only.",
                structured={
                    "product": "mana",
                    "scope_verified": target,
                    "scope_basis": "approved_source_binding",
                    "collected_at": OBSERVED.isoformat(),
                    "fresh_until": OBSERVED.isoformat(),
                    "refresh_status": "cached",
                },
                data_quality_notes=[
                    "Complete fictional parent cohorts only; no real clients or causal proof."
                ],
            )
        )


def catalog_request() -> GoalCreate:
    """The unchanged full task shared by complete-loop and review-stage diagnostics."""
    return GoalCreate(
        request_id=uuid4(),
        execution_mode="agent",
        analysis_scope="saved_snapshot",
        model_choice="gpt-6.1-sol",
        reasoning="medium",
        max_steps=MAX_STEPS,
        budget_microusd=BUDGET,
        objective="Найди в сохранённом каталоге полный исторический СИНТЕТИЧЕСКИЙ отчёт "
        "о родительских когортах MANA на 25.09.2026 и полностью проанализируй его: "
        "воронка, места потерь, подтверждённые в фикстуре оплаты, D1/D7 и приоритеты "
        "увеличения удержания. Это полный анализ вымышленных когорт, не текущих клиентов MANA.",
        success_criteria="Все четыре перехода воронки: конверсия и абсолютные потери; общая "
        "конверсия в подтверждённую оплату. D1 A, D7 A/B, изменение в п.п. и относительно, "
        "взвешенный объединённый D7. Различай абсолютные и относительные барьеры. "
        "Не заменяй когорты DAU/WAU или средним процентов, оплаты — тарифами, родителей — "
        "детьми, географию заказов — активностью. Прочитай весь отчёт, включая хвост, "
        "и независимо проверь все критерии. Дай гипотезы, приоритеты и план измерения.",
        constraints="Только сохранённая синтетическая SQL-фикстура. "
        "Не читай внешние источники, "
        "не изменяй данные/production, не связывайся с пользователями и не увеличивай лимиты. "
        "Не сужай запрос и не выдавай вымышленные числа за реальное положение клиентов. "
        "Нет причинных доказательств или измеренного роста. "
        "MANA/360REC и родители/дети раздельно.",
    )


async def evaluate(
    directory: Path,
    *,
    project_pages: bool = False,
    review_verdicts: bool = False,
    compact_threshold: int | None = None,
) -> dict[str, object]:
    diagnostic_plan = plan(
        project_pages=project_pages,
        review_verdicts=review_verdicts,
        compact_threshold=compact_threshold,
    )
    os.umask(0o077)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "plan.json").write_text(json.dumps(diagnostic_plan, ensure_ascii=False, indent=2))
    settings = get_settings().model_copy(
        update={
            "operation_agent_workspace_enabled": True,
            "operation_workspace_report_discovery_enabled": True,
            "operation_workspace_snapshot_replacement_enabled": project_pages,
            "operation_workspace_page_projection_enabled": project_pages,
            "operation_workspace_review_verdicts_enabled": review_verdicts,
            "operation_workspace_model_continuation_enabled": True,
            "operation_model_selection_enabled": True,
            "operation_goal_limit_extensions_enabled": True,
            "operation_workspace_model_max_output_tokens": OUTPUT_TOKENS,
            **(
                {"operation_workspace_compact_threshold": compact_threshold}
                if compact_threshold is not None
                else {}
            ),
        }
    )
    (directory / "runtime-configuration.json").write_text(
        json.dumps(
            {
                "model_request_timeout_seconds": settings.operation_goals_request_timeout_seconds,
                "model_step_timeout_seconds": settings.operation_goals_model_step_timeout_seconds,
                "sdk_max_retries": 0,
                "compact_threshold": settings.operation_workspace_compact_threshold,
                "model_window_bytes": settings.operation_workspace_model_window_bytes,
                "goal_context_bytes": settings.operation_goals_max_context_bytes,
            },
            indent=2,
        )
    )
    clock = SystemClock()
    database = OperationDatabase(f"sqlite+aiosqlite:///{directory.resolve() / 'workspace.db'}")
    await database.create_schema()
    resources = ResourceUsage(
        llm_calls=MAX_STEPS,
        provider_requests=MAX_STEPS,
        input_tokens=1000000,
        output_tokens=MAX_STEPS * OUTPUT_TOKENS,
        response_bytes=MAX_STEPS * 262144,
        llm_microusd=BUDGET,
    )
    ledger = SqlAlchemyCostLedger(
        database, clock=clock, limits=CostLimits(daily=resources, monthly=resources)
    )
    chats = SqlAlchemyChatRepository(
        database, hourly_limit=10, daily_limit=10, stream_events_enabled=True
    )
    await chats.initialize()
    goals = SqlAlchemyGoalRepository(
        database,
        clock,
        events_enabled=True,
        limit_extensions_enabled=True,
        report_discovery_enabled=True,
        snapshot_replacement_enabled=project_pages,
        page_projection_enabled=project_pages,
        review_verdict_enabled=review_verdicts,
    )
    reports = SqlAlchemyOperationRepository(database)
    await seed(reports, clock)
    fixture = CatalogOnlyAdmin(reports)
    model = OpenAIGoalModel(settings, ledger)
    service = OperationGoalService(
        repository=goals,
        chats=chats,
        model=model,
        continuing_model=model,
        admin=cast(OperationAdminService, fixture),
        clock=clock,
        model_step_timeout_seconds=settings.operation_goals_model_step_timeout_seconds,
        report_discovery_enabled=True,
        snapshot_replacement_enabled=project_pages,
        page_projection_enabled=project_pages,
        review_verdict_enabled=review_verdicts,
        session_context=OperationSessionContext(chats, goals),
        availability=GoalAvailability(
            enabled=True,
            model="gpt-6.1-sol",
            max_steps=MAX_STEPS,
            budget_microusd=BUDGET,
            read_capabilities=[],
            agent_workspace_enabled=True,
            model_selection_enabled=True,
            limit_extensions_enabled=True,
            extension_max_steps=120,
            extension_budget_microusd=BUDGET,
        ),
    )
    result: dict[str, object] = {"semantic_review": "pending", "production_changes": 0}
    try:
        if str(model._client.base_url).rstrip("/") != "https://api.openai.com/v1":
            raise ValueError("Unapproved inference endpoint")
        topic = await chats.create(
            "catalog-quality",
            TopicCreate(
                agent_id="operations-orchestrator",
                product="mana",
                title="Independent synthetic catalog and cohort analysis",
            ),
        )
        request = catalog_request()
        saved = await service.create("catalog-quality", topic.topic_id, request)
        (directory / "goal-id.json").write_text(
            json.dumps({"goal_id": saved.goal_id, "topic_id": topic.topic_id})
        )
        document: dict[str, object] = {}
        for _ in range(MAX_STEPS + 1):
            await service.tick()
            saved = await goals.get("catalog-quality", saved.goal_id)
            accounting = await receipts(database)
            document = saved.model_dump(
                mode="json", exclude={"model_continuation", "session_memory"}
            )
            (directory / f"step-{saved.steps_used}.json").write_text(
                json.dumps(document, ensure_ascii=False, indent=2)
            )
            print(
                json.dumps(
                    {
                        "status": saved.status,
                        "phase": saved.phase,
                        "steps": saved.steps_used,
                        **accounting,
                    }
                ),
                flush=True,
            )
            if saved.status not in {"queued", "running"} or accounting["unknown_hold_microusd"]:
                break
        result.update(
            goal=document,
            accounting=await receipts(database),
            source_attempts=fixture.source_attempts,
            original_request_retained=saved.request == request,
            oracle_not_model_input=oracle(),
        )
    finally:
        (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        await model.close()
        await database.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-paid", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--project-saved-pages", action="store_true")
    parser.add_argument("--review-verdicts", action="store_true")
    parser.add_argument("--compact-threshold", type=int, choices=(8000, 24000))
    args = parser.parse_args()
    if not args.confirm_paid:
        print(
            json.dumps(
                plan(
                    project_pages=args.project_saved_pages,
                    review_verdicts=args.review_verdicts,
                    compact_threshold=args.compact_threshold,
                ),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if args.output is None:
        parser.error("A fresh directory is required; no existing/lost attempt can be resumed")
    asyncio.run(
        evaluate(
            args.output,
            project_pages=args.project_saved_pages,
            review_verdicts=args.review_verdicts,
            compact_threshold=args.compact_threshold,
        )
    )


if __name__ == "__main__":
    main()
