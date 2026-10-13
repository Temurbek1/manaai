import hashlib
import json
import re
from typing import TypedDict

from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from openai.types.responses import FunctionToolParam, ResponseIncludable, ResponseInputItemParam
from openai.types.responses.response_create_params import ContextManagement
from pydantic import BaseModel, Field, JsonValue, ValidationError

from app.core.config import Settings
from app.mana_operation_ai.application.cost_control import CostLedger
from app.mana_operation_ai.application.goal_ports import GoalModelOutput, GoalModelResponseError
from app.mana_operation_ai.application.goal_service import GOAL_INSTRUCTIONS
from app.mana_operation_ai.application.inference_errors import InferenceProviderError
from app.mana_operation_ai.domain.cost_control import (
    CostAttribution,
    LlmRateCard,
    ProductScope,
    ResourceUsage,
)
from app.mana_operation_ai.domain.goals import GoalDecision, GoalDecisionBody
from app.mana_operation_ai.domain.model_continuation import ModelContinuation
from app.mana_operation_ai.infrastructure.agent_tool_schema import (
    agent_function_tools,
    parse_agent_function,
)
from app.mana_operation_ai.infrastructure.decision_validation import (
    decision_issues,
    is_decision_validation,
)
from app.mana_operation_ai.infrastructure.goal_continuation import (
    PreparedContinuation,
    finish_continuation,
    prepare_continuation,
)
from app.mana_operation_ai.infrastructure.inference import (
    inference_rate_cards,
    selected_inference,
)
from app.mana_operation_ai.infrastructure.inference_errors import response_failure, sdk_failure
from app.mana_operation_ai.infrastructure.inference_usage import InferenceUsageEnvelope


class ToolRequestOptions(TypedDict, total=False):
    tools: list[FunctionToolParam]
    parallel_tool_calls: bool


class ContinuationRequestOptions(TypedDict, total=False):
    context_management: list[ContextManagement]
    include: list[ResponseIncludable]


class GoalOutputEnvelope(BaseModel):
    status: str
    output: list[dict[str, JsonValue]] = Field(default_factory=list)
    incomplete_details: dict[str, JsonValue] | None = None


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

    def _input_bound(self, context: str, items: list[ResponseInputItemParam] | None = None) -> int:
        return (
            len(
                json.dumps(
                    {
                        "instructions": GOAL_INSTRUCTIONS,
                        "input": items if items is not None else context,
                        "schema": GoalDecisionBody.model_json_schema(),
                        "tools": self._function_tools(context) if self._agent_mode(context) else [],
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

    def _report_discovery_mode(self, context: str) -> bool:
        return (
            self._settings.operation_workspace_report_discovery_enabled
            and self._agent_mode(context)
            and json.loads(context).get("goal", {}).get("report_discovery_enabled") is True
        )

    def _function_tools(self, context: str) -> list[FunctionToolParam]:
        return agent_function_tools(report_discovery_enabled=self._report_discovery_mode(context))

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
        try:
            return await self._decide(context=context, owner=owner)
        except (APIConnectionError, APIStatusError) as exc:
            raise sdk_failure(exc) from None

    def _prepare(
        self, context: str, owner: str, state: ModelContinuation | None
    ) -> PreparedContinuation:
        if (
            not self._agent_mode(context)
            or not self._settings.operation_workspace_model_continuation_enabled
        ):
            raise ValueError("Native model continuation is disabled")
        # Preserve the same current-snapshot bound before handling a separate private window.
        self.reservation(context)
        plan = selected_inference(context, goal=True) if self._catalog else None
        return prepare_continuation(
            context=context,
            owner=owner,
            state=state,
            model=plan.model if plan else self._settings.operation_goals_model,
            maximum_bytes=self._settings.operation_workspace_model_window_bytes,
        )

    def continuation_reservation(
        self, *, context: str, owner: str, state: ModelContinuation | None
    ) -> int:
        prepared = self._prepare(context, owner, state)
        plan = selected_inference(context, goal=True) if self._catalog else None
        rates = self._catalog[plan.model] if plan else self._rates
        return rates.reserve_microusd(
            input_tokens=self._input_bound(context, prepared.items),
            output_tokens=self._settings.operation_workspace_model_max_output_tokens,
        )

    async def continue_decide(
        self, *, context: str, owner: str, state: ModelContinuation | None
    ) -> GoalModelOutput:
        prepared = self._prepare(context, owner, state)
        try:
            return await self._decide(context=context, owner=owner, prepared=prepared)
        except (APIConnectionError, APIStatusError) as exc:
            raise sdk_failure(exc) from None

    async def _decide(
        self, *, context: str, owner: str, prepared: PreparedContinuation | None = None
    ) -> GoalModelOutput:
        plan = selected_inference(context, goal=True) if self._catalog else None
        model_name = plan.model if plan else self._settings.operation_goals_model
        effort = plan.effort if plan else self._settings.operation_goals_reasoning_effort
        rates = self._catalog[plan.model] if plan else self._rates
        output_bound = (
            self._settings.operation_workspace_model_max_output_tokens
            if prepared
            else self._settings.operation_goals_max_output_tokens
        )
        input_bound = self._input_bound(context, prepared.items if prepared else None)
        amount = (
            rates.reserve_microusd(
                input_tokens=input_bound,
                output_tokens=output_bound,
            )
            if prepared
            else self.reservation(context)
        )
        goal = json.loads(context)["goal"]
        reservation = await self._ledger.reserve(
            ResourceUsage(
                llm_calls=1,
                provider_requests=1,
                input_tokens=input_bound,
                output_tokens=output_bound,
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
            {"tools": self._function_tools(context), "parallel_tool_calls": False}
            if self._agent_mode(context) and goal.get("phase") != "review"
            else {}
        )
        continuation_options: ContinuationRequestOptions = (
            {
                "context_management": [
                    {
                        "type": "compaction",
                        "compact_threshold": self._settings.operation_workspace_compact_threshold,
                    }
                ],
                "include": ["reasoning.encrypted_content"],
            }
            if prepared
            else {}
        )
        raw = await self._client.responses.with_raw_response.parse(
            model=model_name,
            instructions=GOAL_INSTRUCTIONS,
            input=prepared.items if prepared else context,
            max_output_tokens=output_bound,
            reasoning={"effort": effort},
            text={"verbosity": "medium"},
            text_format=GoalDecisionBody,
            store=False,
            service_tier="default",
            safety_identifier=hashlib.sha256(owner.encode()).hexdigest(),
            **tool_options,
            **continuation_options,
        )
        # Parsing an incomplete JSON body can fail inside the SDK before returning usage.
        # Account verified raw HTTP usage first, then validate the domain decision.
        try:
            payload = raw.http_response.json()
            envelope = InferenceUsageEnvelope.model_validate(payload)
        except ValueError:
            raise InferenceProviderError("unknown_usage") from None
        if payload.get("status") == "failed" and envelope.usage is None:
            error = payload.get("error")
            raise response_failure(error.get("code") if isinstance(error, dict) else None)
        # Unknown usage/model/tier retains the global and goal-local worst-case hold.
        if (
            re.fullmatch(re.escape(rates.model) + r"(?:-\d{4}-\d{2}-\d{2})?", envelope.model)
            is None
            or envelope.service_tier != "default"
            or envelope.usage is None
        ):
            raise InferenceProviderError("unknown_usage")
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
        try:
            content = GoalOutputEnvelope.model_validate(payload)
        except ValueError:
            raise GoalModelResponseError(
                "Структура AI-ответа не прошла проверку. Расходы учтены; повтор не запущен.",
                actual.llm_microusd,
            ) from None
        if content.status != "completed":
            reason = (content.incomplete_details or {}).get("reason")
            raise GoalModelResponseError(
                "Ответ AI не завершён. Токены учтены; автоматического повтора нет.",
                actual.llm_microusd,
                provider_status=content.status
                if content.status in {"failed", "incomplete", "cancelled", "queued", "in_progress"}
                else None,
                incomplete_reason=reason
                if isinstance(reason, str) and reason in {"max_output_tokens", "content_filter"}
                else None,
            )
        # A native call may accompany ordinary public commentary. Do not parse that
        # commentary as a structured final decision before handling the function call.
        calls = [item for item in content.output if item.get("type") == "function_call"]
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
                call = parse_agent_function(
                    name, arguments, report_discovery_enabled=self._report_discovery_mode(context)
                )
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
            except ValidationError as exc:
                raise GoalModelResponseError(
                    "Формат ответа AI не прошёл проверку. Расходы учтены; повтор не запущен.",
                    actual.llm_microusd,
                    output_failure="invalid_decision" if is_decision_validation(exc) else None,
                    validation_issues=decision_issues(exc),
                ) from None
            except (ValueError, TypeError, KeyError, AttributeError):
                raise GoalModelResponseError(
                    "Формат ответа AI не прошёл проверку. Расходы учтены; повтор не запущен.",
                    actual.llm_microusd,
                    output_failure="invalid_decision",
                ) from None
        continuation = None
        if prepared:
            try:
                continuation = finish_continuation(
                    prepared,
                    content.output,
                    model=model_name,
                    call=decision.tool_call,
                    maximum_bytes=self._settings.operation_workspace_model_window_bytes,
                )
            except ValueError:
                raise GoalModelResponseError(
                    "Контекст продолжения не прошёл проверку. Расходы учтены; повтор не запущен.",
                    actual.llm_microusd,
                ) from None
        return GoalModelOutput(decision, envelope.model, actual.llm_microusd, continuation)

    async def close(self) -> None:
        await self._client.close()
