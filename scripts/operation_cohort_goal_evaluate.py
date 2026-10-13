"""One independent synthetic historical Goal; at most six calls/$0.49, no sources."""

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
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
from app.mana_operation_ai.domain.goals import GoalAvailability, GoalCreate  # noqa: E402
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
from scripts.operation_workspace_evaluate import SavedOnlyAdmin, receipts  # noqa: E402

REPORT_ID = "synthetic-complete-parent-cohort"
BUDGET = 490000
MAX_STEPS = 6
OUTPUT_TOKENS = 8192
OBSERVED = datetime(2026, 9, 23, tzinfo=UTC)
REPORT = """SYNTHETIC EVALUATION ONLY. No real MANA customers or production measurement.
Observation cutoff: 2026-09-23T00:00:00Z. Timezone UTC. Counts are complete for the
fictional cohorts below, not the actual app population. No identities or child content.
Cohort A: 900 new registered MANA parents, registration dates 2026-09-01 to 2026-09-07.
Cohort B: 100 new registered MANA parents, registration dates 2026-08-25 to 2026-08-31.
All D1/D7 windows and each parent's first 14-day funnel window are fully observed.
D1 means any return in [24h,48h) after registration; D7 in [168h,192h), not lifetime return.
A: 540 D1 returns, 180 D7 returns. B: 60 D7 returns. Cohorts are different people.
Ordered same-cohort A funnel, deduplicated parent IDs within first 14 days: registration=900;
email verified=720; child linked=360; first core feature used=270; successful payment=135.
Every later stage is a subset of the earlier stage in the stated sequence; no join duplication.
The 135 successful payers are confirmed unique parents in this fictional transaction ledger.
Payment amounts, currency, subscriptions, renewals and refunds are not supplied.
Core feature usage means setting a child-safety rule. A core-feature view is not its execution.
A separate parent activity window has DAU=100, WAU=400; not cohort D7 membership.
A separate 10-row parent prefix has 7 non-free tariffs; not a verified payment sample.
Child inventory=4000, active children=2000; neither is a parent activity denominator.
Parent activity geography separately counts Tashkent=900, Samarkand=600; no order geography.
No randomized experiment, individual dropout reason or causal evidence is supplied.
No contacts, consents or action execution. Recommendations are hypotheses, not measured lift.
"""


def oracle() -> dict[str, object]:
    def percentage(numerator: int, denominator: int) -> str:
        return f"{float(Fraction(numerator, denominator) * 100):.2f}"

    return {
        "d1_a_pct": percentage(540, 900),
        "d7_a_pct": percentage(180, 900),
        "d7_b_pct": percentage(60, 100),
        "d7_delta_pp": "-40.00",
        "d7_relative_change_pct": "-66.67",
        "pooled_d7_pct": percentage(240, 1000),
        "unweighted_mean_is_wrong_pct": "40.00",
        "purchase_conversion_pct": percentage(135, 900),
        "funnel_transitions": [
            {
                "from": before,
                "to": after,
                "conversion_pct": percentage(after, before),
                "lost": before - after,
            }
            for before, after in [(900, 720), (720, 360), (360, 270), (270, 135)]
        ],
        "largest_absolute_loss": "verification to linking: 360 parents",
        "largest_relative_drop_tied": "verification to linking and core action to payment: 50%",
        "human_review_required": [
            "All numbers cited to the exact dated synthetic report, no actual MANA claims.",
            "DAU/WAU is not D7; parent, child and separate samples are not merged.",
            "Confirmed fictional payers differ from tariff labels; no revenue/subscriber claim.",
            "No geographic sales ranking, causal dropout explanation or measured business lift.",
            "Prioritized hypotheses and measurement plan without contacts or executed actions.",
            "Retain the full original Goal and independently review every success criterion.",
        ],
    }


def plan() -> dict[str, object]:
    return {
        "max_calls": MAX_STEPS,
        "budget_microusd": BUDGET,
        "model": "gpt-6.1-sol",
        "reasoning": "medium",
        "max_output_tokens": OUTPUT_TOKENS,
        "analysis_scope": "saved_snapshot",
        "source_attempts": 0,
        "production_changes": 0,
        "fixture": REPORT,
        "oracle": oracle(),
        "replay": False,
    }


async def evaluate(directory: Path) -> dict[str, object]:
    os.umask(0o077)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "plan.json").write_text(json.dumps(plan(), ensure_ascii=False, indent=2))
    settings = get_settings().model_copy(
        update={
            "operation_agent_workspace_enabled": True,
            "operation_workspace_model_continuation_enabled": True,
            "operation_model_selection_enabled": True,
            "operation_goal_limit_extensions_enabled": True,
            "operation_workspace_model_max_output_tokens": OUTPUT_TOKENS,
        }
    )
    clock = SystemClock()
    database = OperationDatabase(f"sqlite+aiosqlite:///{directory.resolve() / 'workspace.db'}")
    await database.create_schema()
    resources = ResourceUsage(
        llm_calls=MAX_STEPS,
        provider_requests=MAX_STEPS,
        input_tokens=500000,
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
    repository = SqlAlchemyGoalRepository(
        database, clock, events_enabled=True, limit_extensions_enabled=True
    )
    fixture = SavedOnlyAdmin(clock)
    fixture.current = [
        fixture.report.model_copy(
            update={
                "report_id": REPORT_ID,
                "human_readable": REPORT,
                "period_start": datetime(2026, 8, 25, tzinfo=UTC),
                "period_end": OBSERVED,
                "structured": {
                    "product": "mana",
                    "scope_verified": True,
                    "scope_basis": "approved_source_binding",
                    "collected_at": OBSERVED.isoformat(),
                    "fresh_until": OBSERVED.isoformat(),
                    "refresh_status": "cached",
                },
                "data_quality_notes": [
                    "Synthetic, complete fictional cohorts only; "
                    "not real MANA measurements or causal evidence."
                ],
            }
        )
    ]
    model = OpenAIGoalModel(settings, ledger)
    service = OperationGoalService(
        repository=repository,
        chats=chats,
        model=model,
        continuing_model=model,
        admin=cast(OperationAdminService, fixture),
        clock=clock,
        session_context=OperationSessionContext(chats, repository),
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
            "cohort-quality",
            TopicCreate(
                agent_id="operations-orchestrator",
                product="mana",
                title="Synthetic complete cohort analysis",
            ),
        )
        request = GoalCreate(
            request_id=uuid4(),
            execution_mode="agent",
            analysis_scope="saved_snapshot",
            model_choice="gpt-6.1-sol",
            reasoning="medium",
            max_steps=MAX_STEPS,
            budget_microusd=BUDGET,
            objective=f"Полностью проанализируй исторический СИНТЕТИЧЕСКИЙ отчёт {REPORT_ID}: "
            "воронку родителей MANA, места потерь, подтверждённые в фикстуре оплаты и D1/D7. "
            "Наша тестовая цель — предложить обоснованные гипотезы увеличения удержания. "
            "Это полный анализ предоставленной вымышленной выборки, не текущих клиентов MANA.",
            success_criteria="Все переходы воронки: конверсия и абсолютные потери; "
            "общая конверсия в оплату; "
            "D1 A, D7 A/B, изменение в п.п. и относительно, объединённый D7 с верным весом. "
            "Различай крупнейшую абсолютную потерю и одинаковые относительные барьеры. "
            "Объясни почему DAU/WAU, детские числа, тарифная выборка и география не заменяют "
            "нужные метрики. Дай приоритеты, гипотезы и план измерения без причинных утверждений. "
            "Прочитай весь датированный отчёт и независимо проверь все критерии до завершения.",
            constraints="Только этот сохранённый синтетический отчёт; никаких внешних чтений, "
            "контактов, действий, изменения данных, реальных продаж или измеренного роста. "
            "Не сужай исходный запрос, не выдавай фикстуру за реальных пользователей, "
            "не смешивай родителей/детей/MANA/360REC. Никаких новых grants или увеличения бюджета.",
        )
        saved = await service.create("cohort-quality", topic.topic_id, request)
        (directory / "goal-id.json").write_text(
            json.dumps({"goal_id": saved.goal_id, "topic_id": topic.topic_id})
        )
        for _ in range(MAX_STEPS + 1):
            await service.tick()
            saved = await repository.get("cohort-quality", saved.goal_id)
            state = await receipts(database)
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
                        **state,
                    }
                ),
                flush=True,
            )
            if saved.status not in {"queued", "running"} or state["unknown_hold_microusd"]:
                break
        result.update(
            goal=document,
            source_attempts=fixture.source_attempts,
            accounting=await receipts(database),
            original_request_retained=saved.request == request,
            oracle=oracle(),
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
    args = parser.parse_args()
    if not args.confirm_paid:
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
        return
    if args.output is None:
        parser.error("A fresh directory is required; existing or lost attempts cannot be resumed")
    asyncio.run(evaluate(args.output))


if __name__ == "__main__":
    main()
