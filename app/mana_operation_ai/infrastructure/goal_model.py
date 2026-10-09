import hashlib
import json
import re

from openai import AsyncOpenAI

from app.core.config import Settings
from app.mana_operation_ai.application.cost_control import CostLedger
from app.mana_operation_ai.application.goal_ports import GoalModelOutput
from app.mana_operation_ai.application.goal_service import GOAL_INSTRUCTIONS
from app.mana_operation_ai.domain.cost_control import (
    CostAttribution,
    LlmRateCard,
    ProductScope,
    ResourceUsage,
)
from app.mana_operation_ai.domain.goals import GoalDecision
from app.mana_operation_ai.infrastructure.inference import (
    inference_rate_cards,
    selected_inference,
)


class OpenAIGoalModel:
    """Separate strong reasoning configuration, bounded structured calls, no SDK retries."""

    def __init__(self, settings: Settings, ledger: CostLedger) -> None:
        settings.require_operation_goals_rate_card()
        self._settings = settings
        self._ledger = ledger
        self._catalog = (
            inference_rate_cards(settings) if settings.operation_model_selection_enabled else {}
        )
        self._rates = LlmRateCard(
            model=settings.operation_goals_rate_model,
            input_usd_per_million=settings.operation_goals_input_usd_per_million,
            cached_input_usd_per_million=settings.operation_goals_cached_input_usd_per_million,
            cache_write_usd_per_million=settings.operation_goals_cache_write_usd_per_million,
            output_usd_per_million=settings.operation_goals_output_usd_per_million,
        )
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(), max_retries=0, timeout=120
        )

    def _input_bound(self, context: str) -> int:
        return (
            len(
                json.dumps(
                    {
                        "instructions": GOAL_INSTRUCTIONS,
                        "input": context,
                        "schema": GoalDecision.model_json_schema(),
                    },
                    ensure_ascii=False,
                ).encode()
            )
            + 1024
        )

    def reservation(self, context: str) -> int:
        if len(context.encode()) > self._settings.operation_goals_max_context_bytes:
            raise ValueError("Goals context exceeds its configured bound")
        plan = selected_inference(context, goal=True) if self._catalog else None
        rates = self._catalog[plan.model] if plan else self._rates
        return rates.reserve_microusd(
            input_tokens=self._input_bound(context),
            output_tokens=self._settings.operation_goals_max_output_tokens,
        )

    async def decide(self, *, context: str, owner: str) -> GoalModelOutput:
        amount = self.reservation(context)
        plan = selected_inference(context, goal=True) if self._catalog else None
        model_name = plan.model if plan else self._settings.operation_goals_model
        effort = plan.effort if plan else self._settings.operation_goals_reasoning_effort
        rates = self._catalog[plan.model] if plan else self._rates
        goal = json.loads(context)["goal"]
        reservation = await self._ledger.reserve(
            ResourceUsage(
                llm_calls=1,
                provider_requests=1,
                input_tokens=self._input_bound(context),
                output_tokens=self._settings.operation_goals_max_output_tokens,
                response_bytes=262_144,
                llm_microusd=amount,
            ),
            attribution=CostAttribution(
                product=ProductScope(goal["product"]),
                source="openai",
                agent_id=goal["agent_id"],
                capability_key="goals.analyze",
            ),
        )
        response = await self._client.responses.parse(
            model=model_name,
            instructions=GOAL_INSTRUCTIONS,
            input=context,
            max_output_tokens=self._settings.operation_goals_max_output_tokens,
            reasoning={"effort": effort},
            text={"verbosity": "medium"},
            text_format=GoalDecision,
            store=False,
            service_tier="default",
            safety_identifier=hashlib.sha256(owner.encode()).hexdigest(),
        )
        # Unknown usage/model/tier retains the global and goal-local worst-case hold.
        if (
            re.fullmatch(re.escape(rates.model) + r"(?:-\d{4}-\d{2}-\d{2})?", response.model)
            is None
            or response.service_tier != "default"
            or response.usage is None
        ):
            raise RuntimeError("Goal response usage/pricing cannot be verified")
        usage = response.usage
        actual = ResourceUsage(
            llm_calls=1,
            provider_requests=1,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            response_bytes=len(response.model_dump_json(warnings=False).encode()),
            llm_microusd=rates.actual_microusd(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cached_tokens=usage.input_tokens_details.cached_tokens,
                cache_write_tokens=getattr(usage.input_tokens_details, "cache_write_tokens", 0)
                or 0,
            ),
        )
        await self._ledger.settle(reservation.reservation_id, actual=actual)
        if actual.exceeds(reservation.usage):
            raise RuntimeError("Goal response exceeded its resource reservation")
        if response.status != "completed" or response.output_parsed is None:
            raise RuntimeError("Goal response did not complete")
        return GoalModelOutput(response.output_parsed, response.model, actual.llm_microusd)

    async def close(self) -> None:
        await self._client.close()
