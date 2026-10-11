import hashlib
import json
import re
from typing import TypedDict

from openai import AsyncOpenAI
from openai.types.responses import FunctionToolParam
from pydantic import BaseModel, Field, JsonValue

from app.core.config import Settings
from app.mana_operation_ai.application.cost_control import CostLedger
from app.mana_operation_ai.application.goal_ports import GoalModelOutput, GoalModelResponseError
from app.mana_operation_ai.application.goal_service import GOAL_INSTRUCTIONS
from app.mana_operation_ai.domain.cost_control import (
    CostAttribution,
    LlmRateCard,
    ProductScope,
    ResourceUsage,
)
from app.mana_operation_ai.domain.goals import GoalDecision, GoalDecisionBody
from app.mana_operation_ai.infrastructure.agent_tool_schema import (
    agent_function_tools,
    parse_agent_function,
)
from app.mana_operation_ai.infrastructure.inference import (
    inference_rate_cards,
    selected_inference,
)


class ToolRequestOptions(TypedDict, total=False):
    tools: list[FunctionToolParam]
    parallel_tool_calls: bool


class GoalInputUsage(BaseModel):
    cached_tokens: int = Field(ge=0)
    # Optional in older Responses payloads; no cache write is reported there.
    cache_write_tokens: int = Field(default=0, ge=0)


class GoalProviderUsage(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    input_tokens_details: GoalInputUsage


class GoalUsageEnvelope(BaseModel):
    model: str
    service_tier: str | None
    status: str
    usage: GoalProviderUsage | None
    output: list[dict[str, JsonValue]] = Field(default_factory=list)


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
                        "schema": GoalDecisionBody.model_json_schema(),
                        "tools": agent_function_tools() if self._agent_mode(context) else [],
                    },
                    ensure_ascii=False,
                ).encode()
            )
            + 1024
        )

    def _agent_mode(self, context: str) -> bool:
        return (
            self._settings.operation_agent_workspace_enabled
            and json.loads(context).get("goal", {}).get("request", {}).get("execution_mode")
            == "agent"
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
        tool_options: ToolRequestOptions = (
            {"tools": agent_function_tools(), "parallel_tool_calls": False}
            if self._agent_mode(context) and goal.get("phase") != "review"
            else {}
        )
        raw = await self._client.responses.with_raw_response.parse(
            model=model_name,
            instructions=GOAL_INSTRUCTIONS,
            input=context,
            max_output_tokens=self._settings.operation_goals_max_output_tokens,
            reasoning={"effort": effort},
            text={"verbosity": "medium"},
            text_format=GoalDecisionBody,
            store=False,
            service_tier="default",
            safety_identifier=hashlib.sha256(owner.encode()).hexdigest(),
            **tool_options,
        )
        # Parsing an incomplete JSON body can fail inside the SDK before returning usage.
        # Account verified raw HTTP usage first, then validate the domain decision.
        envelope = GoalUsageEnvelope.model_validate(raw.http_response.json())
        # Unknown usage/model/tier retains the global and goal-local worst-case hold.
        if (
            re.fullmatch(re.escape(rates.model) + r"(?:-\d{4}-\d{2}-\d{2})?", envelope.model)
            is None
            or envelope.service_tier != "default"
            or envelope.usage is None
        ):
            raise RuntimeError("Goal response usage/pricing cannot be verified")
        usage = envelope.usage
        actual = ResourceUsage(
            llm_calls=1,
            provider_requests=1,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            response_bytes=len(raw.http_response.content),
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
        if envelope.status != "completed":
            raise GoalModelResponseError(
                "Ответ AI не завершён. Токены учтены; автоматического повтора нет.",
                actual.llm_microusd,
            )
        # A native call may accompany ordinary public commentary. Do not parse that
        # commentary as a structured final decision before handling the function call.
        calls = [item for item in envelope.output if item.get("type") == "function_call"]
        if calls:
            if not self._agent_mode(context) or goal.get("phase") == "review" or len(calls) != 1:
                raise GoalModelResponseError(
                    "AI запросил недопустимые инструменты. Ничего не выполнялось.",
                    actual.llm_microusd,
                )
            name, arguments = calls[0].get("name"), calls[0].get("arguments")
            if not isinstance(name, str) or not isinstance(arguments, str):
                raise GoalModelResponseError(
                    "Аргументы инструмента не прошли проверку. Ничего не выполнялось.",
                    actual.llm_microusd,
                )
            try:
                call = parse_agent_function(name, arguments)
            except ValueError:
                raise GoalModelResponseError(
                    "Аргументы инструмента не прошли проверку. Ничего не выполнялось.",
                    actual.llm_microusd,
                ) from None
            decision = GoalDecision(
                update="Запрошен инструмент анализа.",
                plan=goal.get("plan", []),
                draft=goal.get("result", ""),
                evidence_ids=[],
                disposition="continue",
                missing_information="",
                requested_capability=None,
                tool_call=call,
            )
        else:
            try:
                response = raw.parse()
                if response.output_parsed is None:
                    raise ValueError("Missing structured decision")
                decision = GoalDecision.model_validate(response.output_parsed.model_dump())
            except ValueError:
                raise GoalModelResponseError(
                    "Формат ответа AI не прошёл проверку. Расходы учтены; повтор не запущен.",
                    actual.llm_microusd,
                ) from None
        return GoalModelOutput(decision, envelope.model, actual.llm_microusd)

    async def close(self) -> None:
        await self._client.close()
