"""One opt-in synthetic streamed request; never replay a Goal, source or old party."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput  # noqa: E402
from app.mana_operation_ai.application.inference_errors import InferenceProviderError  # noqa: E402
from app.mana_operation_ai.application.runtime import SystemClock  # noqa: E402
from app.mana_operation_ai.domain.cost_control import CostLimits, ResourceUsage  # noqa: E402
from app.mana_operation_ai.infrastructure.chat_model import OpenAIConversationModel  # noqa: E402
from app.mana_operation_ai.infrastructure.inference import inference_rate_cards  # noqa: E402
from app.mana_operation_ai.infrastructure.persistence.cost_ledger import (  # noqa: E402
    SqlAlchemyCostLedger,
)
from app.mana_operation_ai.infrastructure.persistence.database import (
    OperationDatabase,  # noqa: E402
)
from app.mana_operation_ai.infrastructure.persistence.models import CostReservationRow  # noqa: E402

MODEL = "gpt-6.1-sol"
CAP_MICROUSD = 50000
OUTPUT_TOKENS = 128


def plan() -> dict[str, str | int | bool]:
    return {
        "model": MODEL,
        "reasoning": "low",
        "max_calls": 1,
        "max_output_tokens": OUTPUT_TOKENS,
        "cap_microusd": CAP_MICROUSD,
        "stream": True,
        "source_attempts": 0,
        "production_changes": 0,
        "replay_or_retry": False,
    }


async def run(directory: Path) -> dict[str, object]:
    os.umask(0o077)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "plan.json").write_text(json.dumps(plan(), indent=2))
    # No application startup or deployment/source DB URL. This is a new local ledger.
    database = OperationDatabase(f"sqlite+aiosqlite:///{directory.resolve() / 'budget.db'}")
    await database.create_schema()
    limit = ResourceUsage(
        llm_calls=1,
        provider_requests=1,
        input_tokens=16384,
        output_tokens=OUTPUT_TOKENS,
        response_bytes=1048576,
        llm_microusd=CAP_MICROUSD,
    )
    ledger = SqlAlchemyCostLedger(
        database, clock=SystemClock(), limits=CostLimits(daily=limit, monthly=limit)
    )
    gateway: OpenAIConversationModel | None = None
    result: dict[str, object] = {"plan": plan(), "status": "failed", "phase": "configuration"}
    try:
        settings = get_settings()
        rate = inference_rate_cards(settings)[MODEL]
        settings = settings.model_copy(
            update={
                "operation_model_selection_enabled": False,
                "operation_chat_model": MODEL,
                "operation_chat_reasoning_effort": "low",
                "openai_max_output_tokens": OUTPUT_TOKENS,
                "operation_chat_rate_model": MODEL,
                "operation_chat_input_usd_per_million": rate.input_usd_per_million,
                "operation_chat_cached_input_usd_per_million": rate.cached_input_usd_per_million,
                "operation_chat_cache_write_usd_per_million": rate.cache_write_usd_per_million,
                "operation_chat_output_usd_per_million": rate.output_usd_per_million,
            }
        )
        gateway = OpenAIConversationModel(settings, ledger=ledger)
        if str(gateway._client.base_url).rstrip("/") != "https://api.openai.com/v1":
            raise ValueError("Only the configured official API endpoint is allowed")
        result["phase"] = "stream"
        context = json.dumps(
            {
                "topic": {"product": "mana", "agent_id": "retention-agent"},
                "message": "Synthetic transport check only. Answer OK. "
                "No sources, actions or goals.",
            }
        )
        final: ChatTurnOutput | None = None
        async for event in gateway.stream_reply(
            instructions="Return ChatReply with answer OK, empty plan and next_action none.",
            context=context,
            owner="isolated-synthetic-diagnostic",
        ):
            if isinstance(event, ChatTurnOutput):
                final = event
        if final is None or final.next_action != "none" or final.plan:
            raise ValueError("No valid synthetic final receipt")
        result.update(status="completed", phase="verified", model=final.model)
    except InferenceProviderError as exc:
        result.update(failure_kind=exc.kind, http_status=exc.http_status)
    except Exception:
        # No upstream exception, payload, user data or credential is recorded.
        result["failure_kind"] = "unclassified"
    finally:
        if gateway is not None:
            await gateway.close()
        async with database.session_factory() as session:
            rows = list((await session.scalars(select(CostReservationRow))).all())
        result["accounting"] = {
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
        (directory / "result.json").write_text(json.dumps(result, indent=2))
        await database.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-paid", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.confirm_paid:
        print(json.dumps(plan(), indent=2))
        return
    if args.output is None:
        parser.error("A fresh output directory is required; previous attempts cannot be resumed")
    print(json.dumps(asyncio.run(run(args.output)), indent=2))


if __name__ == "__main__":
    main()
