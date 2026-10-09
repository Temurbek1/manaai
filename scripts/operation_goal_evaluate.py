"""Opt-in, one synthetic Goals workflow with a persistent <$0.50 shared ledger."""

import argparse
import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.mana_operation_ai.application.admin_service import OperationAdminService  # noqa: E402
from app.mana_operation_ai.application.goal_service import OperationGoalService  # noqa: E402
from app.mana_operation_ai.application.runtime import SystemClock  # noqa: E402
from app.mana_operation_ai.domain.chat import TopicCreate  # noqa: E402
from app.mana_operation_ai.domain.cost_control import CostLimits, ResourceUsage  # noqa: E402
from app.mana_operation_ai.domain.goals import GoalAvailability, GoalCreate  # noqa: E402
from app.mana_operation_ai.domain.models import AgentReport  # noqa: E402
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


class SyntheticControls:
    async def get_control(self, key: str, *, default: bool = False) -> bool:
        return default


class SyntheticAdmin:
    repository = SyntheticControls()

    def __init__(self, clock: SystemClock) -> None:
        now = clock.now()
        self.report = AgentReport(
            report_id="synthetic-mana-goal-evidence",
            agent_id="retention-agent",
            capability_key="retention.engagement.analyze",
            run_id="synthetic-run",
            report_type="retention_engagement_analysis",
            period_start=now - timedelta(days=7),
            period_end=now,
            created_at=now,
            structured={
                "product": "mana",
                "scope_verified": True,
                "scope_basis": "approved_source_binding",
                "collected_at": (now - timedelta(minutes=10)).isoformat(),
                "fresh_until": (now + timedelta(hours=5)).isoformat(),
                "refresh_status": "cached",
            },
            human_readable="SYNTHETIC EVALUATION ONLY. Parent cohort: 100 new MANA parents. "
            "60 returned on D1, 35 returned on D7. Previous comparable parent cohort: 100, "
            "30 returned on D7. Both D7 windows are complete; these are different cohorts, "
            "not individual before/after tracking or causal evidence. Child aggregates: "
            "200 children, 80 active; not parent activity or contactable audiences. "
            "A bounded separate sample has 30 non-free tariffs; not verified payments. "
            "Purchase events, revenue, payment status and ordered registration funnels "
            "are missing. "
            "No verified reason for churn. No phone/email/child content is supplied.",
            data_quality_notes=[
                "Synthetic facts, no real customers; cohort/funnel availability "
                "not established in production."
            ],
        )

    async def list_reports(
        self, *, agent_id: str | None, capability_key: str | None, limit: int, offset: int
    ) -> tuple[list[AgentReport], int]:
        return ([self.report], 1) if agent_id == "retention-agent" else ([], 0)

    async def run_now(self, **kwargs: object) -> None:
        raise AssertionError("The synthetic workflow must never read a product source")


async def evaluate(directory: Path) -> None:
    # Refuse existing output rather than silently rerunning a paid party/unknown call.
    directory.mkdir(parents=True, exist_ok=False)
    settings = get_settings()
    clock = SystemClock()
    database = OperationDatabase(f"sqlite+aiosqlite:///{directory.resolve() / 'budget.db'}")
    await database.create_schema()
    usage = ResourceUsage(
        llm_calls=3,
        provider_requests=3,
        input_tokens=250_000,
        output_tokens=3 * settings.operation_goals_max_output_tokens,
        response_bytes=786_432,
        llm_microusd=490_000,
    )
    ledger = SqlAlchemyCostLedger(
        database, clock=clock, limits=CostLimits(daily=usage, monthly=usage)
    )
    model = OpenAIGoalModel(settings, ledger)
    chats = SqlAlchemyChatRepository(database, hourly_limit=3, daily_limit=3)
    await chats.initialize()
    service = OperationGoalService(
        repository=SqlAlchemyGoalRepository(database, clock),
        chats=chats,
        model=model,
        admin=cast(OperationAdminService, SyntheticAdmin(clock)),
        clock=clock,
        availability=GoalAvailability(
            enabled=True,
            model=settings.operation_goals_model,
            max_steps=6,
            budget_microusd=490_000,
            read_capabilities=[],
        ),
        max_context_bytes=settings.operation_goals_max_context_bytes,
    )
    try:
        topic = await chats.create(
            "synthetic-goal-evaluation",
            TopicCreate(
                agent_id="operations-orchestrator", product="mana", title="Synthetic retention goal"
            ),
        )
        goal = await service.create(
            "synthetic-goal-evaluation",
            topic.topic_id,
            GoalCreate(
                request_id=uuid4(),
                budget_microusd=490_000,
                objective="Проанализируй положение пользователей MANA для увеличения удержания: "
                "что известно об активности, возвращаемости, отпадании и оплатах. "
                "Используй только данные в сводке, подготовь полезный анализ "
                "доступной части и рекомендации. "
                "Не связывайся с клиентами и не читай новые источники.",
                success_criteria="Посчитать D1/D7 родителей и изменение D7 в процентных пунктах. "
                "Не смешивать родителей и детей, не считать тариф оплатой, не выдумывать "
                "воронку, причины оттока или эффект. Явно обозначить недоступные метрики "
                "и дать приоритеты/план измерения. Анализ имеющихся фактов можно завершить "
                "без оплаты/воронки, если ограничения указаны; это не полное исследование бизнеса.",
            ),
        )
        for index in range(3):
            await service.tick()
            goal = await service.repository.get("synthetic-goal-evaluation", goal.goal_id)
            (directory / f"step-{index + 1}.json").write_text(
                goal.model_dump_json(indent=2), encoding="utf-8"
            )
            if goal.status in ("waiting", "completed", "cancelled", "paused"):
                break
        periods = [period.model_dump(mode="json") for period in await ledger.periods()]
        result = {
            "model": settings.operation_goals_model,
            "reasoning": settings.operation_goals_reasoning_effort,
            "status": goal.status,
            "steps": goal.steps_used,
            "budget_cap_microusd": 490_000,
            "accounting": periods,
            "manual_quality_review_required": True,
            "limitations": "One synthetic workflow, no production/user-source access; "
            "not broad quality acceptance.",
        }
        (directory / "results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False))
    finally:
        await model.close()
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-paid", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.confirm_paid:
        parser.error("Explicit --confirm-paid is required; at most three calls, $0.49 ledger cap")
    asyncio.run(evaluate(args.output))


if __name__ == "__main__":
    main()
