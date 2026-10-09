import hashlib
import json
import re

from openai import AsyncOpenAI

from app.core.config import Settings
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput
from app.mana_operation_ai.application.cost_control import CostLedger
from app.mana_operation_ai.domain.chat import ChatReply
from app.mana_operation_ai.domain.cost_control import (
    CostAttribution,
    CostReservation,
    LlmRateCard,
    ProductScope,
    ResourceUsage,
)
from app.mana_operation_ai.infrastructure.inference import (
    inference_rate_cards,
    selected_inference,
)


class OpenAIConversationModel:
    """One bounded Responses call per turn, isolated from the audio provider client."""

    def __init__(self, settings: Settings, *, ledger: CostLedger | None = None) -> None:
        # Revalidate explicit overrides even for Settings.model_copy(), which
        # bypasses Pydantic validators. No SDK client exists before this check.
        settings.require_operation_chat_rate_card()
        self._settings = settings
        self._model_name = settings.effective_operation_chat_model
        self._reasoning_effort = settings.effective_operation_chat_reasoning_effort
        self._ledger = ledger
        self._catalog = (
            inference_rate_cards(settings) if settings.operation_model_selection_enabled else {}
        )
        self._rates = LlmRateCard(
            model=settings.operation_chat_rate_model,
            input_usd_per_million=settings.operation_chat_input_usd_per_million,
            cached_input_usd_per_million=settings.operation_chat_cached_input_usd_per_million,
            cache_write_usd_per_million=settings.operation_chat_cache_write_usd_per_million,
            output_usd_per_million=settings.operation_chat_output_usd_per_million,
        )
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            max_retries=0,
            timeout=150 if settings.operation_model_selection_enabled else 45,
        )

    async def reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        model_name, effort, rates = self._model_name, self._reasoning_effort, self._rates
        output_limit = min(self._settings.openai_max_output_tokens, 2048)
        if self._settings.operation_model_selection_enabled:
            plan = selected_inference(context, goal=False)
            model_name, effort, rates = plan.model, plan.effort, self._catalog[plan.model]
            output_limit = self._settings.operation_chat_max_output_tokens
        reservation: CostReservation | None = None
        if self._ledger is not None:
            if model_name != rates.model:
                raise RuntimeError("Operational model and configured rate card do not match")
            # Text-only byte bound includes instructions and the structured-output
            # schema. It deliberately over-reserves instead of guessing a tokenizer
            # for a different model or adding an external token-counting request.
            input_bound = conversation_input_bound(instructions=instructions, context=context)
            if input_bound > self._settings.operation_chat_max_input_tokens:
                raise RuntimeError("Operational conversation context exceeds its token bound")
            reservation = await self._ledger.reserve(
                ResourceUsage(
                    llm_calls=1,
                    provider_requests=1,
                    input_tokens=input_bound,
                    output_tokens=output_limit,
                    response_bytes=262_144,
                    llm_microusd=rates.reserve_microusd(
                        input_tokens=input_bound,
                        output_tokens=output_limit,
                    ),
                ),
                attribution=_attribution(context),
            )
        # Exceptions, timeouts and cancellation deliberately retain the reservation.
        response = await self._client.responses.parse(
            model=model_name,
            instructions=instructions,
            input=context,
            max_output_tokens=output_limit,
            reasoning={"effort": effort},
            text={"verbosity": "medium" if self._catalog else self._settings.openai_verbosity},
            store=False,
            service_tier="default",
            safety_identifier=hashlib.sha256(owner.encode()).hexdigest(),
            text_format=ChatReply,
        )
        if reservation is not None and self._ledger is not None:
            if (
                re.fullmatch(re.escape(rates.model) + r"(?:-\d{4}-\d{2}-\d{2})?", response.model)
                is None
                or response.service_tier != "default"
                or response.usage is None
            ):
                raise RuntimeError("Operational response pricing or usage cannot be verified")
            cached = response.usage.input_tokens_details.cached_tokens
            cache_writes = (
                getattr(response.usage.input_tokens_details, "cache_write_tokens", 0) or 0
            )
            actual = ResourceUsage(
                llm_calls=1,
                provider_requests=1,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                # SDK parsed-response generic annotations can emit serialization
                # warnings containing answer/source text. This local size estimate
                # must not log it; model/tier/usage validation stays strict above.
                response_bytes=len(response.model_dump_json(warnings=False).encode()),
                llm_microusd=rates.actual_microusd(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cached_tokens=cached,
                    cache_write_tokens=cache_writes,
                ),
            )
            await self._ledger.settle(reservation.reservation_id, actual=actual)
            if actual.exceeds(reservation.usage):
                raise RuntimeError("Operational response exceeded its reserved resource bound")
        if response.status != "completed" or response.output_parsed is None:
            raise RuntimeError("Conversation response did not complete")
        return ChatTurnOutput(
            answer=response.output_parsed.answer,
            model=response.model,
            input_tokens=response.usage.input_tokens if response.usage else None,
            output_tokens=response.usage.output_tokens if response.usage else None,
            plan=response.output_parsed.plan,
            next_action=response.output_parsed.next_action,
        )

    async def close(self) -> None:
        await self._client.close()


def conversation_input_bound(*, instructions: str, context: str) -> int:
    """Shared conservative text/schema/protocol bound for admission and dry-run QA."""
    return (
        len(
            json.dumps(
                {
                    "instructions": instructions,
                    "input": context,
                    "schema": ChatReply.model_json_schema(),
                },
                ensure_ascii=False,
            ).encode()
        )
        + 1024
    )


def _attribution(context: str) -> CostAttribution:
    payload = json.loads(context)
    if not isinstance(payload, dict) or not isinstance(payload.get("topic"), dict):
        raise ValueError("Budgeted conversations require a typed topic context")
    topic = payload["topic"]
    return CostAttribution(
        product=ProductScope(topic["product"]),
        source="openai",
        agent_id=topic["agent_id"],
        capability_key="conversation.reply",
    )
