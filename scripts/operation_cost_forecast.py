"""Offline cost projection: no .env, service credentials, app startup or provider I/O."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mana_operation_ai.application.cost_forecast import ForecastWorkload, forecast  # noqa: E402
from app.mana_operation_ai.domain.cost_control import LlmRateCard  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products", type=int, default=2)
    parser.add_argument("--reads-per-day", type=int, default=50_000)
    parser.add_argument("--bytes-per-document", type=int, default=5120)
    parser.add_argument("--chat-calls-per-day", type=int, default=20)
    parser.add_argument("--analyses-per-product-refresh", type=int, default=4)
    parser.add_argument("--complex-calls-per-day", type=int, default=1)
    parser.add_argument("--chat-output-tokens", type=int, default=2000)
    parser.add_argument("--ordinary-rate-card", help="Explicit LlmRateCard JSON; no runtime change")
    parser.add_argument("--goals-per-day", type=int, default=0)
    parser.add_argument("--goal-steps-per-goal", type=int, default=6)
    parser.add_argument("--goal-input-tokens-per-step", type=int, default=8000)
    parser.add_argument("--goal-output-tokens-per-step", type=int, default=4096)
    parser.add_argument("--goal-budget-microusd", type=int, default=500_000)
    parser.add_argument(
        "--goal-rate-card", help="Explicit Goals LlmRateCard JSON; no runtime change"
    )
    args = parser.parse_args(argv)
    try:
        workload = ForecastWorkload(
            products=args.products,
            firestore_reads_per_day=args.reads_per_day,
            average_response_bytes_per_document=args.bytes_per_document,
            chat_calls_per_day=args.chat_calls_per_day,
            analyses_per_product_refresh=args.analyses_per_product_refresh,
            complex_calls_per_day=args.complex_calls_per_day,
            chat_output_tokens=args.chat_output_tokens,
            goals_per_day=args.goals_per_day,
            goal_steps_per_goal=args.goal_steps_per_goal,
            goal_input_tokens_per_step=args.goal_input_tokens_per_step,
            goal_output_tokens_per_step=args.goal_output_tokens_per_step,
            goal_budget_microusd=args.goal_budget_microusd,
        )
        rate_card = (
            LlmRateCard.model_validate_json(args.ordinary_rate_card)
            if args.ordinary_rate_card is not None
            else None
        )
        goal_rate_card = (
            LlmRateCard.model_validate_json(args.goal_rate_card)
            if args.goal_rate_card is not None
            else None
        )
    except ValidationError:
        parser.error("Forecast assumptions or rate card are invalid")
    result = forecast(workload, ordinary_rate_card=rate_card, goal_rate_card=goal_rate_card)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
