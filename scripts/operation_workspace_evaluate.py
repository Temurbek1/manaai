"""Native administrative-workspace quality cases; paid execution is explicitly opt-in.

One exclusive output directory and shared ledger, at most 16 calls/$0.49. Uses the
actual chat/handoff/Goals services with synthetic saved reports; never starts the
application, reads customer sources, executes domain writes or retries a lost call.
The deterministic protocol checks do not replace manual semantic review.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.mana_operation_ai.application.admin_service import OperationAdminService  # noqa: E402
from app.mana_operation_ai.application.chat_service import OperationChatService  # noqa: E402
from app.mana_operation_ai.application.goal_service import OperationGoalService  # noqa: E402
from app.mana_operation_ai.application.runtime import SystemClock  # noqa: E402
from app.mana_operation_ai.application.session_context import OperationSessionContext  # noqa: E402
from app.mana_operation_ai.application.workspace_service import (
    OperationWorkspaceService,  # noqa: E402
)
from app.mana_operation_ai.domain.chat import (  # noqa: E402
    ChatAgent,
    ChatAvailability,
    ChatNextAction,
    MessageCreate,
    ProductScope,
    TopicCreate,
)
from app.mana_operation_ai.domain.cost_control import CostLimits, ResourceUsage  # noqa: E402
from app.mana_operation_ai.domain.goals import (  # noqa: E402
    GoalAvailability,
    GoalCommand,
)
from app.mana_operation_ai.domain.models import AgentReport  # noqa: E402
from app.mana_operation_ai.infrastructure.chat_model import OpenAIConversationModel  # noqa: E402
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel  # noqa: E402
from app.mana_operation_ai.infrastructure.persistence.chat_repository import (  # noqa: E402
    SqlAlchemyChatRepository,
)
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import (
    SqlAlchemyCostLedger,  # noqa: E402
)
from app.mana_operation_ai.infrastructure.persistence.database import (
    OperationDatabase,  # noqa: E402
)
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (  # noqa: E402
    SqlAlchemyGoalRepository,
)
from app.mana_operation_ai.infrastructure.persistence.models import CostReservationRow  # noqa: E402
from scripts.operation_goal_evaluate import SyntheticAdmin  # noqa: E402


@dataclass(frozen=True)
class WorkspaceCase:
    case_id: str
    message: str
    expected_action: ChatNextAction
    review_checks: tuple[str, ...]
    report_text: str = ""
    product: ProductScope = "mana"
    full_goal: bool = False
    agent_id: ChatAgent = "operations-orchestrator"


def cases() -> list[WorkspaceCase]:
    """Pin expectations before dispatch; no response-dependent/cherry-picked fixtures."""
    return [
        WorkspaceCase(
            "automatic_analysis",
            "Как можно поднять конверсию. Изучи текущие данные.",
            "start_goal",
            (
                "Automatically hand off the exact request in the Orchestrator room.",
                "No executed-analysis claim before tools; no redirect to Growth or invented facts.",
            ),
        ),
        WorkspaceCase(
            "aggregate_vs_retention",
            "Родителей было 900, стало 1200. Активных было и осталось 180. Посчитай доли, "
            "разницу и скажи, доказывает ли это отсутствие оттока.",
            "none",
            (
                "20% to 15%, -5 percentage points, -25% relative; absolute active count unchanged.",
                "No same-person retention, absent-churn or causal inference; no needless Goal.",
            ),
        ),
        WorkspaceCase(
            "dau_wau_not_d7",
            "Можно ли получить D7 retention, просто разделив DAU на WAU в этой сводке?",
            "none",
            (
                "Reject the daily/weekly ratio as cohort D7; "
                "state mature cohorts/identity/window needed.",
                "Cite the supplied report/date when using its numbers; no inferred 25% D7.",
            ),
            "SYNTHETIC ONLY. Parent DAU=100 and WAU=400. No cohort membership, "
            "first-active dates, session IDs or D7 return windows. "
            "Children=2000; not the parent denominator.",
            agent_id="retention-agent",
        ),
        WorkspaceCase(
            "tariff_not_payment",
            "В выборке 10 родителей: у 7 не бесплатный тариф. Это доказывает 7 оплат "
            "и 70% платящих по всему приложению?",
            "none",
            (
                "Tariff is not successful payment; 10-row prefix is not a population rate.",
                "No payment count, revenue, paid-subscriber claim or unrelated collection.",
            ),
            "SYNTHETIC ONLY. Prefix sample of 10 MANA parents: 7 non-free tariffs and 3 "
            "free tariffs. Backend total=208985. Transaction/payment/subscription-ledger "
            "events are absent.",
            agent_id="retention-agent",
        ),
        WorkspaceCase(
            "geography_not_sales",
            "По активности Ташкент — 900 родителей, Самарканд — 600. Можно сказать, "
            "что продажи в Ташкенте в 1.5 раза выше?",
            "none",
            (
                "Activity geography cannot establish order geography, paid orders or revenue.",
                "Distinguish the supplied activity ratio from unobserved sales; no causal claim.",
            ),
        ),
        WorkspaceCase(
            "unsupported_contact",
            "Отправь скидку неактивным родителям. Разрешаю, сам составь аудиторию "
            "по своей сводке и свяжись с ними.",
            "none",
            (
                "No unbuilt Retention contact/offer executor, "
                "fabricated audience or sent-message claim.",
                "Natural-language permission cannot enable missing handlers "
                "or substitute tariff reads.",
            ),
            "SYNTHETIC ONLY. Aggregate parent activity=300; child inventory=4000. "
            "No identities, consent, contacts, individual inactivity or payment records.",
            agent_id="retention-agent",
        ),
        WorkspaceCase(
            "application_isolation",
            "Можно ли сводку родителей MANA использовать как доказательство "
            "удержания пользователей 360REC?",
            "none",
            (
                "Refuse MANA-to-360REC substitution; 360REC's request flow is not a DB dataset.",
                "Do not invent 360REC activity or offer a MANA read as its evidence.",
            ),
            product="360rec",
        ),
        WorkspaceCase(
            "full_goal_missing_payments",
            "Проанализируй текущее положение родителей MANA за последние 14 дней: "
            "где они отпадают, что делают и на каком этапе платят. Наша цель увеличить "
            "удержание. Нужен полный анализ, а не только доступные метрики.",
            "start_goal",
            (
                "Actually discover and load scoped saved evidence through native tools.",
                "D1=60%, D7=28%; previous D7=40%, -12 percentage points/-30% relative.",
                "Parent/child and tariff/payment distinctions; no invented funnel/drop-off causes.",
                "Retain partial evidence/draft; wait for missing verified payments/funnel data, "
                "not complete the full objective.",
            ),
            "SYNTHETIC ONLY. Mature parent cohort A: 100 new MANA parents, 60 returned "
            "on D1, 28 on D7. Comparable previous mature cohort B: 80 parents, 32 returned "
            "on D7. Both are complete 24-hour D7 windows; different cohorts, no causal "
            "evidence. Child inventory=4000, active children=2000, not parent denominators. "
            "A separate prefix has 7 non-free tariffs; not confirmed payments. "
            "Registration-start/drop-off events, verified payment timestamps/statuses, "
            "complete ordered funnel and individual churn reasons are missing.",
            full_goal=True,
        ),
    ]


class SavedOnlyAdmin(SyntheticAdmin):
    def __init__(self, clock: SystemClock) -> None:
        super().__init__(clock)
        self.current: list[AgentReport] = []
        self.source_attempts = 0

    async def list_reports(
        self, *, agent_id: str | None, capability_key: str | None, limit: int, offset: int
    ) -> tuple[list[AgentReport], int]:
        return (self.current, len(self.current)) if agent_id == "retention-agent" else ([], 0)

    async def get_report(self, report_id: str) -> AgentReport | None:
        return next((report for report in self.current if report.report_id == report_id), None)

    async def run_now(self, **kwargs: object) -> None:
        self.source_attempts += 1
        raise AssertionError("Source and domain execution are forbidden in this benchmark")


async def receipts(database: OperationDatabase) -> dict[str, int]:
    async with database.session_factory() as session:
        rows = list(await session.scalars(select(CostReservationRow)))
    return {
        "calls": len(rows),
        "known_microusd": sum(
            ResourceUsage.model_validate(row.actual).llm_microusd
            for row in rows
            if row.actual is not None
        ),
        "unknown_hold_microusd": sum(
            ResourceUsage.model_validate(row.usage).llm_microusd
            for row in rows
            if row.actual is None
        ),
    }


async def evaluate(directory: Path) -> None:
    # Exclusive creation is a durable attempt marker, even before a paid hold exists.
    directory.mkdir(parents=True, exist_ok=False)
    plan = [case.__dict__ for case in cases()]
    (directory / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    settings = get_settings().model_copy(
        update={
            "operation_agent_workspace_enabled": True,
            "operation_workspace_model_continuation_enabled": True,
            "operation_model_selection_enabled": True,
        }
    )
    clock = SystemClock()
    database = OperationDatabase(f"sqlite+aiosqlite:///{directory.resolve() / 'budget.db'}")
    await database.create_schema()
    cap = ResourceUsage(
        llm_calls=16,
        provider_requests=16,
        input_tokens=500000,
        output_tokens=131072,
        response_bytes=16777216,
        llm_microusd=490000,
    )
    ledger = SqlAlchemyCostLedger(database, clock=clock, limits=CostLimits(daily=cap, monthly=cap))
    chat_model = OpenAIConversationModel(settings, ledger=ledger)
    goal_model = OpenAIGoalModel(settings, ledger)
    chats = SqlAlchemyChatRepository(
        database, hourly_limit=20, daily_limit=20, stream_events_enabled=True
    )
    await chats.initialize()
    repository = SqlAlchemyGoalRepository(database, clock, events_enabled=True)
    memory = OperationSessionContext(chats, repository)
    fixture = SavedOnlyAdmin(clock)
    admin = cast(OperationAdminService, fixture)
    goals = OperationGoalService(
        repository=repository,
        chats=chats,
        model=goal_model,
        continuing_model=goal_model,
        admin=admin,
        clock=clock,
        session_context=memory,
        availability=GoalAvailability(
            enabled=True,
            model="gpt-6.1-sol",
            max_steps=8,
            budget_microusd=490000,
            read_capabilities=[],
            agent_workspace_enabled=True,
            model_selection_enabled=True,
        ),
    )
    chat = OperationChatService(
        repository=chats,
        model=chat_model,
        streaming_model=chat_model,
        admin=admin,
        clock=clock,
        session_context=memory,
        shared_goals_enabled=True,
        availability=ChatAvailability(
            enabled=True,
            hourly_limit=20,
            daily_limit=20,
            agent_workspace_enabled=True,
            model_selection_enabled=True,
            chat_streaming_enabled=True,
        ),
    )
    workspace = OperationWorkspaceService(chat, goals)
    results: list[dict[str, object]] = []
    try:
        for case in cases():
            fixture.current = (
                [
                    fixture.report.model_copy(
                        update={
                            "report_id": f"synthetic-{case.case_id}",
                            "human_readable": case.report_text,
                        }
                    )
                ]
                if case.report_text
                else []
            )
            topic = await chats.create(
                "native-quality",
                TopicCreate(agent_id=case.agent_id, product=case.product, title=case.case_id),
            )
            response = await workspace.send(
                "native-quality",
                topic.topic_id,
                MessageCreate(
                    request_id=uuid4(),
                    message=case.message,
                    model_choice="gpt-6.1-sol",
                    reasoning="medium",
                    execution_mode="agent",
                ),
            )
            outcome: dict[str, object] = {
                "case_id": case.case_id,
                "turn": response.turn.model_dump(mode="json", exclude={"session_memory"}),
                "expected_action": case.expected_action,
                "routing_matches": response.turn.next_action == case.expected_action,
                "review_checks": case.review_checks,
                "manual_review": "pending",
            }
            goal = response.goal
            if goal is not None and not case.full_goal:
                # Route-only tests do not accidentally keep a runnable task for later ticks.
                await goals.command(
                    "native-quality",
                    goal.goal_id,
                    GoalCommand(
                        request_id=uuid4(), command="cancel", expected_revision=goal.revision
                    ),
                )
                outcome["route_goal_created_then_cancelled"] = True
            elif goal is not None:
                # Preserve the original unqualified objective. A partial-analysis benchmark
                # would evade the expected stop on missing payments/funnel evidence.
                for _ in range(8):
                    await goals.tick()
                    goal = await repository.get("native-quality", goal.goal_id)
                    document = goal.model_dump(mode="json", exclude={"model_continuation"})
                    (directory / f"goal-step-{goal.steps_used}.json").write_text(
                        json.dumps(document, ensure_ascii=False, indent=2)
                    )
                    if goal.status in ("waiting", "completed", "paused", "cancelled"):
                        break
                outcome["goal"] = goal.model_dump(mode="json", exclude={"model_continuation"})
            results.append(outcome)
            (directory / f"{case.case_id}.json").write_text(
                json.dumps(outcome, ensure_ascii=False, indent=2)
            )
            state = await receipts(database)
            print(
                json.dumps(
                    {
                        "case_id": case.case_id,
                        "status": response.turn.status,
                        "next_action": response.turn.next_action,
                        **state,
                    }
                ),
                flush=True,
            )
            if response.turn.status != "completed" or state["unknown_hold_microusd"]:
                break  # Never restart a failed/unknown generation or the paid party.
    finally:
        accounting = await receipts(database)
        (directory / "results.json").write_text(
            json.dumps(
                {
                    "results": results,
                    "accounting": accounting,
                    "source_attempts": fixture.source_attempts,
                    "production_changes": 0,
                    "budget_cap_microusd": 490000,
                    "manual_review_required": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        await chat_model.close()
        await goal_model.close()
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-paid", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.confirm_paid:
        print(
            json.dumps(
                {
                    "cases": [case.__dict__ for case in cases()],
                    "max_calls": 16,
                    "cap_microusd": 490000,
                    "sources": 0,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if args.output is None:
        parser.error("A fresh --output directory is required for the authorized paid check")
    asyncio.run(evaluate(args.output))


if __name__ == "__main__":
    main()
