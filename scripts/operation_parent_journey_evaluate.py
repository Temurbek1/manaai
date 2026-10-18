"""One new two-report parent-journey diagnostic; offline by default, <= $0.49.

No old diagnostic can be resumed. The actual native Goal/SQL/model adapters are
used with fictional saved reports only; no source or action executor is assembled.
Protocol completion is not a semantic grade, real MANA measurement or release.
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import cast
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
from scripts.operation_catalog_goal_evaluate import CatalogOnlyAdmin  # noqa: E402
from scripts.operation_workspace_evaluate import receipts  # noqa: E402

BUDGET = 490000
MAX_CALLS = 8
OUTPUT_TOKENS = 8192
OBSERVED = datetime(2026, 9, 29, tzinfo=UTC)
FUNNEL_ID = "synthetic-journey-parent-funnel"
RETENTION_ID = "synthetic-journey-parent-retention"
COHORT = "cohort-A-2026-09-14-20-parent-first-open"
OWNER = "parent-journey-quality"
COMMON = f"""SYNTHETIC ONLY. No actual MANA customers or production measurement.
Snapshot cutoff 2026-09-29T00:00:00Z; event timezone Asia/Tashkent.
The complete fictional cohort {COHORT} contains 900 distinct MANA parents whose
first app open was 2026-09-14 through 2026-09-20 inclusive in that timezone.
All first-seven-day and D1/D7 windows have matured by the cutoff. Cohort identity,
definition, deduplication and cutoff agree across the two named journey reports.
The SQL/report creation or collection date is not the event observation period.
"""
FUNNEL = (
    COMMON
    + """FIRST-SEVEN-DAY ORDERED PARENT FUNNEL.
Unique parents within [0h,168h) of first open, every later stage a subset of its
predecessor in this order: first open=900; registration completed=720;
child linked=360; first safety rule executed=270; successful first payment=135.
Payment status is confirmed by the FICTIONAL transaction ledger, not tariff labels.
No amounts, currency, refunds, subscription/renewal status or payment geography.
The first value action is an executed safety rule, not a screen view or button click.
A separate unlinked 100-parent profile prefix has 95 non-free tariff labels.
A separate child inventory has 1400 children. Neither replaces the cohort counts.
No individual dropout reasons, contacts, consents, experiments or actions executed.
"""
)
RETENTION = (
    COMMON
    + """COHORT RETURN OBSERVATIONS, NOT DAU/WAU.
D1 is any parent return in [24h,48h) from first open; D7 is [168h,192h).
Current cohort A: D1 returned=540 of 900; D7 returned=270 of 900.
Previous comparable mature cohort B: first opens 2026-09-07 through 2026-09-13,
300 distinct different parents, D7 returned=180 of 300. Same return definition.
A and B are disjoint; pooled D7 includes all 1200 parents, not equal cohort weights.
For cohort A only, the same parent-key join to first-seven-day confirmed payments:
135 payers, of whom 80 returned on D7; 765 non-payers, of whom 190 returned on D7.
The strata are exhaustive/disjoint and sum to the 270 D7 returners of cohort A.
This is observational association: payment was not randomized; selection/confounding
are possible. It does not establish that payment causes retention or vice versa.
No D30, D1/D7 intersection, individual churn reason or measured intervention lift.
Parent activity geography: Tashkent=600, Samarkand=300; not order geography.
EXACT JOURNEY FOOTER: experiments are hypotheses; no contact, send or measured lift.
"""
)


def oracle() -> dict[str, object]:
    def pct(numerator: int, denominator: int) -> str:
        return f"{float(Fraction(numerator, denominator) * 100):.2f}"

    return {
        "d1_a_pct": pct(540, 900),
        "d7_a_pct": pct(270, 900),
        "d7_b_pct": pct(180, 300),
        "d7_delta_pp": "-30.00",
        "d7_relative_change_pct": "-50.00",
        "pooled_d7_pct": pct(450, 1200),
        "incorrect_equal_weight_d7_pct": "45.00",
        "payment_conversion_pct": pct(135, 900),
        "payer_d7_pct": pct(80, 135),
        "nonpayer_d7_pct": pct(190, 765),
        "payer_nonpayer_difference_pp": (
            f"{float((Fraction(80, 135) - Fraction(190, 765)) * 100):.2f}"
        ),
        "funnel_transitions": [
            {
                "from": before,
                "to": after,
                "conversion_pct": pct(after, before),
                "lost": before - after,
            }
            for before, after in [(900, 720), (720, 360), (360, 270), (270, 135)]
        ],
        "semantic_checks": [
            "Cite both complete saved reports and the exact historical cohort/cutoff.",
            "Largest absolute loss is registration to linking: 360 parents; two 50% barriers.",
            "Payment/retention association is not causal; strata sum to the same cohort.",
            "No actual MANA, child-denominator, tariff-payment or regional-sales substitution.",
            "No invented D30, revenue, churn causes, contacts or measured business lift.",
            "Two prioritized experiments need metric, denominator, guardrail and human review.",
            "Complete the original historical objective only after independent bound review.",
        ],
    }


def plan() -> dict[str, object]:
    return {
        "max_calls": MAX_CALLS,
        "budget_microusd": BUDGET,
        "model": "gpt-6.1-sol",
        "reasoning": "medium",
        "max_output_tokens": OUTPUT_TOKENS,
        "workspace_contract": "v14/v5",
        "compact_threshold": 24000,
        "analysis_scope": "saved_snapshot",
        "fixtures": {FUNNEL_ID: FUNNEL, RETENTION_ID: RETENTION},
        "saved_report_contract": "retention_engagement_analysis; fictional evidence only",
        "oracle_not_model_input": oracle(),
        "source_attempts": 0,
        "production_changes": 0,
        "replay": False,
    }


def request() -> GoalCreate:
    return GoalCreate(
        request_id=uuid4(),
        execution_mode="agent",
        analysis_scope="saved_snapshot",
        model_choice="gpt-6.1-sol",
        reasoning="medium",
        max_steps=MAX_CALLS,
        budget_microusd=BUDGET,
        objective="Найди и полностью проанализируй два сохранённых синтетических отчёта "
        "о пути родителей MANA: воронку от первого открытия до оплаты и удержание D1/D7. "
        "Определи основные потери, этап оплаты и связь оплаты с возвратом. Наша тестовая "
        "цель — предложить обоснованный план повышения удержания. Это полный исторический "
        "анализ предоставленной фикстуры на 29.09.2026, не текущих клиентов MANA.",
        success_criteria="Прочитай оба полных отчёта и проверь совместимость когорт/окон. "
        "Посчитай конверсии и абсолютные потери всех переходов, итоговую конверсию в оплату; "
        "D1 A, D7 A/B, изменение в п.п. и относительно, объединённый D7 с верным весом; "
        "D7 плативших и не плативших, разницу в п.п. Различай крупнейшую абсолютную потерю "
        "и равные относительные барьеры, связь и причинность. Дай два приоритетных "
        "эксперимента с метрикой, знаменателем, защитными метриками и планом проверки. "
        "Явно укажи неизвестные D30/выручку/причины, даты и обе ссылки на источники. "
        "Независимо проверь все исходные критерии до завершения.",
        constraints="Только сохранённые синтетические SQL-отчёты. Никаких внешних источников, "
        "контактов, изменений, действий или увеличения лимитов. Не сужай исходную цель, "
        "не выдавай вымысел за реальное положение MANA или гипотезы за измеренный эффект. "
        "Не смешивай MANA/360REC, родителей/детей, тарифы/оплаты, активность/географию продаж. "
        "Отвечай по-русски; рекомендации не являются разрешением на запуск экспериментов.",
    )


async def seed(repository: SqlAlchemyOperationRepository, clock: SystemClock) -> None:
    # Reuse the established admitted report contract, not an invented scope bit
    # on an unsupported Growth/provider payload. No production binding is implied.
    agent, capability = "retention-agent", "retention.engagement.analyze"
    created = clock.now() - timedelta(hours=1)
    await repository.register_agent(
        AgentDefinition(
            agent_id=agent,
            display_name="Synthetic journey fixture",
            description="Local only",
            version="fixture",
            status=AgentStatus.ENABLED,
            capabilities=[],
            default_capability_key=capability,
            configuration_schema={},
            registered_at=created,
        )
    )
    for report_id, text in [(FUNNEL_ID, FUNNEL), (RETENTION_ID, RETENTION)]:
        run = AgentRun(
            run_id="run-" + report_id,
            agent_id=agent,
            capability_key=capability,
            correlation_id="synthetic-parent-journey",
            trigger=TriggerType.API,
            initiated_by=OWNER,
            status=AgentRunStatus.COMPLETED,
            configuration_version=1,
            idempotency_key=report_id,
            started_at=created,
            updated_at=created,
            completed_at=created,
        )
        await repository.create_run(run)
        await repository.save_report(
            AgentReport(
                report_id=report_id,
                agent_id=agent,
                capability_key=capability,
                run_id=run.run_id,
                report_type="retention_engagement_analysis",
                period_start=datetime(2026, 9, 7, tzinfo=UTC),
                period_end=OBSERVED,
                created_at=created,
                human_readable=text,
                structured={
                    "product": "mana",
                    "scope_verified": True,
                    "scope_basis": "approved_source_binding",
                    "collected_at": OBSERVED.isoformat(),
                    "fresh_until": OBSERVED.isoformat(),
                    "refresh_status": "cached",
                },
                data_quality_notes=[
                    "Complete fictional cohorts only, not real MANA or causal evidence."
                ],
            )
        )


async def evaluate(directory: Path) -> dict[str, object]:
    os.umask(0o077)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "plan.json").write_text(json.dumps(plan(), ensure_ascii=False, indent=2))
    settings = get_settings().model_copy(
        update={
            "operation_agent_workspace_enabled": True,
            "operation_workspace_model_continuation_enabled": True,
            "operation_workspace_report_discovery_enabled": True,
            "operation_workspace_snapshot_replacement_enabled": True,
            "operation_workspace_page_projection_enabled": True,
            "operation_workspace_review_verdicts_enabled": True,
            "operation_goal_limit_extensions_enabled": True,
            "operation_model_selection_enabled": True,
            "operation_workspace_model_max_output_tokens": OUTPUT_TOKENS,
            "operation_workspace_compact_threshold": 24000,
        }
    )
    clock = SystemClock()
    database = OperationDatabase(f"sqlite+aiosqlite:///{directory.resolve() / 'workspace.db'}")
    model: OpenAIGoalModel | None = None
    result: dict[str, object] = {"semantic_review": "pending", "production_changes": 0}
    try:
        await database.create_schema()
        resources = ResourceUsage(
            llm_calls=MAX_CALLS,
            provider_requests=MAX_CALLS,
            input_tokens=1000000,
            output_tokens=MAX_CALLS * OUTPUT_TOKENS,
            response_bytes=MAX_CALLS * 262144,
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
            snapshot_replacement_enabled=True,
            page_projection_enabled=True,
            review_verdict_enabled=True,
        )
        reports = SqlAlchemyOperationRepository(database)
        await seed(reports, clock)
        fixture = CatalogOnlyAdmin(reports)
        model = OpenAIGoalModel(settings, ledger)
        if str(model._client.base_url).rstrip("/") != "https://api.openai.com/v1":
            raise ValueError("Unapproved inference endpoint")
        service = OperationGoalService(
            repository=goals,
            chats=chats,
            model=model,
            continuing_model=model,
            admin=cast(OperationAdminService, fixture),
            clock=clock,
            model_step_timeout_seconds=settings.operation_goals_model_step_timeout_seconds,
            report_discovery_enabled=True,
            snapshot_replacement_enabled=True,
            page_projection_enabled=True,
            review_verdict_enabled=True,
            session_context=OperationSessionContext(chats, goals),
            availability=GoalAvailability(
                enabled=True,
                model="gpt-6.1-sol",
                max_steps=MAX_CALLS,
                budget_microusd=BUDGET,
                read_capabilities=[],
                agent_workspace_enabled=True,
                model_selection_enabled=True,
                limit_extensions_enabled=True,
                extension_max_steps=MAX_CALLS,
                extension_budget_microusd=BUDGET,
            ),
        )
        topic = await chats.create(
            OWNER,
            TopicCreate(
                agent_id="operations-orchestrator", product="mana", title="Synthetic parent journey"
            ),
        )
        original = request()
        saved = await service.create(OWNER, topic.topic_id, original)
        for _ in range(MAX_CALLS + 1):
            await service.tick()
            saved = await goals.get(OWNER, saved.goal_id)
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
        before_replay = await receipts(database)
        replay = await service.create(OWNER, topic.topic_id, original)
        if replay.goal_id != saved.goal_id or await receipts(database) != before_replay:
            raise AssertionError("Exact observation replay changed Goal identity or accounting")
        result.update(
            goal=document,
            accounting=before_replay,
            source_attempts=fixture.source_attempts,
            original_request_retained=saved.request == original,
            exact_replay_observed=True,
            oracle_not_model_input=oracle(),
        )
    finally:
        (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        if model is not None:
            await model.close()
        await database.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-paid", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.confirm_paid:
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
        return
    if args.output is None:
        parser.error("A fresh directory is required; existing/lost attempts cannot resume")
    asyncio.run(evaluate(args.output))


if __name__ == "__main__":
    main()
