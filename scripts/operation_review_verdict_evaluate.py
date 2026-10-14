"""Two fresh full-input review-stage checks; never full-workflow acceptance or a replay.

Offline by default. Explicit paid mode has one shared $0.49/two-call ledger,
handwritten synthetic artifacts, the unchanged catalog task and complete evidence.
No application factory, source executor, production connection or retry is created.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.mana_operation_ai.application.goal_ports import GoalModelResponseError  # noqa: E402
from app.mana_operation_ai.application.inference_errors import InferenceProviderError  # noqa: E402
from app.mana_operation_ai.application.runtime import SystemClock  # noqa: E402
from app.mana_operation_ai.domain.cost_control import CostLimits, ResourceUsage  # noqa: E402
from app.mana_operation_ai.domain.goals import (  # noqa: E402
    GoalEvidence,
    GoalTask,
    OperationGoal,
)
from app.mana_operation_ai.infrastructure.goal_model import OpenAIGoalModel  # noqa: E402
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import (  # noqa: E402
    SqlAlchemyCostLedger,
)
from app.mana_operation_ai.infrastructure.persistence.database import (
    OperationDatabase,  # noqa: E402
)
from scripts.operation_catalog_goal_evaluate import (  # noqa: E402
    BUDGET,
    OBSERVED,
    OUTPUT_TOKENS,
    REPORT,
    REPORT_ID,
    catalog_request,
)
from scripts.operation_workspace_evaluate import receipts  # noqa: E402

MAX_CALLS = 2
CORRECT_POOLED = "Объединённый D7: (200 + 100) / (800 + 200) = 30%."
INCORRECT_POOLED = "Объединённый D7: (25% + 50%) / 2 = 37,5%."
DRAFT = f"""# Исторический анализ синтетических когорт MANA

Источник [{REPORT_ID}], дата наблюдения 25.09.2026, UTC. Это вымышленные родители,
не реальные клиенты и не текущее состояние приложения. Полный исходный отчёт,
включая FINAL RETENTION OBSERVATIONS и EXACT CATALOG QUALITY FOOTER, приложен.
Когорта A: 800 зарегистрированных родителей 01–07.09.2026. B: 200 других родителей
25–31.08.2026. Все заданные окна D1/D7 и первые 14 дней воронки полностью наблюдены.
Единица расчёта — уникальный родитель; поздняя стадия входит в предыдущую.

## Воронка A и оплаты

| Переход | Родители | Конверсия | Абсолютные потери | Относительные потери |
| --- | --- | --- | --- | --- |
| Регистрация → email подтверждён | 800 → 680 | 680/800 = 85% | 120 | 15% |
| Подтверждение → ребёнок подключён | 680 → 340 | 340/680 = 50% | 340 | 50% |
| Подключение → правило безопасности выполнено | 340 → 272 | 272/340 = 80% | 68 | 20% |
| Выполнение → успешная оплата | 272 → 136 | 136/272 = 50% | 136 | 50% |

Общая конверсия в подтверждённую оплату: 136/800 = 17%. Это 136 уникальных
успешно оплативших родителей в вымышленном платёжном реестре, не тарифные метки.
Выручка, валюта, сумма, подписки, возвраты и продления неизвестны. Правило считается
использованным после выполнения; просмотр не является выполнением.
Наибольшая абсолютная потеря — подключение ребёнка: 340 родителей. По относительным
потерям подключение и оплата равны: 50%; оплата теряет 136, а не 340 родителей.
Это описательные барьеры в полной вымышленной воронке, не доказанные причины отказа.

## Возвращаемость

D1 — возврат через [24ч,48ч) от регистрации; D7 — через [168ч,192ч), не любой
пожизненный визит. Для A D1 = 520/800 = 65%; D7 = 200/800 = 25%. Для B
D7 = 100/200 = 50%. A относительно B: 25% − 50% = −25 п.п.;
(25% − 50%)/50% = −50% относительно. Снижение между разными когортами не является
индивидуальным изменением одного пользователя или эффектом конкретного релиза.
{CORRECT_POOLED}
Пересечение вернувшихся D1 и D7 не дано. Когортная возвращаемость не доказывает
сохранение платной подписки; D1 B отсутствует. DAU=150 и WAU=400 относятся к отдельному
окну активности, их отношение не D7. Выборка десяти родителей с девятью небесплатными
тарифами не подтверждает оплаты или долю платящих во всей базе. 5000 детей и 2500
активных детей не входят в родительский знаменатель. Активность по Ташкенту=1400 и
Самарканду=1100 не является географией заказов или рейтингом региональных продаж.

## Приоритеты и проверяемые гипотезы

1. Сначала исследовать подключение ребёнка: самый большой абсолютный барьер.
   Гипотеза — понятный статус подключения и помощь на проблемном шаге уменьшат потери.
   Сейчас неизвестны причины, ошибки, время шага и отношение родителей к интерфейсу.
   Исследовать их по разрешённым агрегатам/добровольной обратной связи, не утверждать причину.
2. Затем проверить первую полезную работу правила и возвращаемость после неё.
   Гипотеза — понятное объяснение полученной пользы улучшит D7. Нужна наблюдаемая
   связь действий и когорт; из этих агрегатов не следует, кто из 272 вернулся.
3. Оплата имеет такой же относительный барьер, но меньшие абсолютные потери.
   Гипотеза — ясное описание предложения снизит потери. Не назначать скидки без
   экономики, согласований и данных; нет цены, платёжных ошибок и причин отказа.

## План измерения

До эксперимента закрепить родительскую единицу, последовательность стадий, уникальные
идентификаторы и UTC-окна. В сравнимых зрелых когортах измерять конверсию каждого
перехода, общую подтверждённую оплату, D1/D7 по указанным определениям и абсолютные
потери. Для общего D7 складывать вернувшихся и размеры когорт, не усреднять проценты.
Гипотезы проверять отдельно с заранее заданной метрикой и рандомизированными группами,
если это согласовано; заранее определить объём, длительность, эффект и интервалы
неопределённости, наблюдать завершённые окна. Нельзя вычислить интервал, мощность,
объём или измеренный lift из отсутствующих экспериментальных данных.
Контролировать ошибки подключения, платёжные ошибки, отмены/возвраты и жалобы,
когда соответствующие источники появятся. Учитывать приватность и контактные согласия.
Сейчас это план проверки, не запущенный эксперимент. Никаких уведомлений, контактов,
скидок, внешних чтений или изменений не было. MANA отделена от 360REC, родители —
от детей. Нет причинных доказательств и измеренного улучшения бизнеса."""


@dataclass(frozen=True)
class ReviewCase:
    case_id: str
    draft: str
    expected_verdict: str


def cases() -> list[ReviewCase]:
    return [
        ReviewCase("complete_correct", DRAFT, "accepted"),
        ReviewCase(
            "incorrect_pooled_d7", DRAFT.replace(CORRECT_POOLED, INCORRECT_POOLED), "revise"
        ),
    ]


def reviewing_goal(case: ReviewCase) -> OperationGoal:
    now = SystemClock().now()
    return OperationGoal(
        goal_id=str(uuid4()),
        topic_id=str(uuid4()),
        agent_id="operations-orchestrator",
        product="mana",
        request=catalog_request(),
        status="running",
        phase="review",
        created_at=now,
        updated_at=now,
        limit_tracking=True,
        report_discovery_enabled=True,
        snapshot_replacement_enabled=True,
        page_projection_enabled=True,
        review_verdict_enabled=True,
        result=case.draft,
        plan=[
            GoalTask(title=title, status="done" if position < 5 else "active")
            for position, title in enumerate(
                [
                    "Find and read the complete dated synthetic report",
                    "Calculate all four funnel transitions and payment conversion",
                    "Calculate D1/D7 and weighted cohort comparisons",
                    "Separate populations and evidence limitations",
                    "Prioritize hypotheses and define a measurement plan",
                    "Independently review every original criterion",
                ]
            )
        ],
        evidence=[
            GoalEvidence(
                report_id=REPORT_ID,
                capability_key="retention.engagement.analyze",
                product="mana",
                collected_at=OBSERVED,
                fresh_until=None,
                refresh_status="stale",
                summary=REPORT,
                limitations=[
                    "Handwritten synthetic review-stage fixture; no real customer data.",
                    "Supplied complete text, not proof of model-driven discovery or analysis.",
                    "No causal effects, actual business lift, contacts or actions.",
                ],
            )
        ],
    )


def context(goal: OperationGoal) -> str:
    return json.dumps(
        {
            "goal": goal.model_dump(
                mode="json",
                exclude={"lease_until", "events", "model_continuation", "review_receipt"},
            ),
            "evaluation_time": SystemClock().now().isoformat(),
            "allowed_read_capabilities": [],
            "completion_scope": "analysis_only_not_business_outcome",
        },
        ensure_ascii=False,
    )


def plan() -> dict[str, object]:
    return {
        "stage_only": True,
        "full_workflow_acceptance": False,
        "max_calls": MAX_CALLS,
        "shared_budget_microusd": BUDGET,
        "model": "gpt-6.1-sol",
        "reasoning": "medium",
        "max_output_tokens": OUTPUT_TOKENS,
        "workspace_contract": "v14/v5",
        "fixture_characters": len(REPORT),
        "fixture_sha256": hashlib.sha256(REPORT.encode()).hexdigest(),
        "case_ids": [case.case_id for case in cases()],
        "expected_verdicts_not_model_input": [case.expected_verdict for case in cases()],
        "artifact_origin": "handwritten synthetic stage fixtures, not old model results",
        "source_attempts": 0,
        "production_changes": 0,
        "replay": False,
        "semantic_review": "pending",
    }


async def evaluate(directory: Path) -> dict[str, object]:
    os.umask(0o077)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "plan.json").write_text(json.dumps(plan(), ensure_ascii=False, indent=2))
    settings = get_settings().model_copy(
        update={
            "operation_agent_workspace_enabled": True,
            "operation_workspace_report_discovery_enabled": True,
            "operation_workspace_snapshot_replacement_enabled": True,
            "operation_workspace_page_projection_enabled": True,
            "operation_workspace_review_verdicts_enabled": True,
            "operation_workspace_model_continuation_enabled": True,
            "operation_model_selection_enabled": True,
            "operation_goal_limit_extensions_enabled": True,
            "operation_workspace_model_max_output_tokens": OUTPUT_TOKENS,
        }
    )
    database = OperationDatabase(f"sqlite+aiosqlite:///{directory.resolve() / 'receipts.db'}")
    await database.create_schema()
    resources = ResourceUsage(
        llm_calls=MAX_CALLS,
        provider_requests=MAX_CALLS,
        input_tokens=200000,
        output_tokens=MAX_CALLS * OUTPUT_TOKENS,
        response_bytes=MAX_CALLS * 262144,
        llm_microusd=BUDGET,
    )
    ledger = SqlAlchemyCostLedger(
        database, clock=SystemClock(), limits=CostLimits(daily=resources, monthly=resources)
    )
    model = OpenAIGoalModel(settings, ledger)
    outputs: list[dict[str, object]] = []
    result: dict[str, object] = {**plan(), "cases": outputs}
    try:
        if str(model._client.base_url).rstrip("/") != "https://api.openai.com/v1":
            raise ValueError("Unapproved inference endpoint")
        for case in cases():
            goal = reviewing_goal(case)
            if goal.result != case.draft:
                raise ValueError("The input fixture must retain the complete exact artifact")
            frozen = context(goal)
            (directory / f"{case.case_id}-input.json").write_text(frozen)
            item: dict[str, object] = {"case_id": case.case_id, "goal_id": goal.goal_id}
            outputs.append(item)
            try:
                reservation = model.continuation_reservation(
                    context=frozen, owner="review-quality", state=None
                )
                item["reservation_microusd"] = reservation
                async with asyncio.timeout(settings.operation_goals_model_step_timeout_seconds):
                    output = await model.continue_decide(
                        context=frozen, owner="review-quality", state=None
                    )
                if output.review is None or output.decision.draft != case.draft:
                    raise ValueError("Review did not retain the exact artifact and verdict")
                item.update(
                    review=output.review.model_dump(mode="json"),
                    draft_sha256=hashlib.sha256(output.decision.draft.encode()).hexdigest(),
                    actual_microusd=output.actual_microusd,
                    mechanical_expected_verdict=output.review.disposition == case.expected_verdict,
                )
            except GoalModelResponseError as exc:
                item.update(
                    status="output_failure",
                    actual_microusd=exc.actual_microusd,
                    completion_facts=exc.completion_feedback,
                    validation_facts=exc.validation_feedback,
                )
            except InferenceProviderError as exc:
                item.update(status="provider_failure", failure=exc.kind)
            except (TimeoutError, ValueError, RuntimeError) as exc:
                # No raw provider/validation body is included in evidence or console output.
                item.update(status="stopped", error_type=type(exc).__name__)
            accounting = await receipts(database)
            result["receipts"] = accounting
            (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps({"case_id": case.case_id, "receipts": accounting}), flush=True)
            if accounting["unknown_hold_microusd"]:
                break
        return result
    finally:
        await model.close()
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-paid", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.confirm_paid:
        print(json.dumps(plan(), ensure_ascii=False, indent=2))
        return
    if args.output is None:
        parser.error("A new exclusive directory is required; stopped attempts are never resumed")
    asyncio.run(evaluate(args.output))


if __name__ == "__main__":
    main()
