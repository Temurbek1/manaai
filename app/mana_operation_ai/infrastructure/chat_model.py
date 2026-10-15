import hashlib
import json
import re
from collections.abc import AsyncGenerator
from time import monotonic
from typing import Literal, Protocol, cast

import httpx
from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from openai.types.responses import FunctionToolParam, ParsedResponse, ResponseInputItemParam
from pydantic import ValidationError
from pydantic_core import from_json

from app.core.config import Settings
from app.mana_operation_ai.application.chat_ports import ChatTurnOutput
from app.mana_operation_ai.application.cost_control import CostLedger
from app.mana_operation_ai.application.inference_errors import InferenceProviderError
from app.mana_operation_ai.domain.chat import ChatReply
from app.mana_operation_ai.domain.contact_continuation import (
    ContactModelWindow,
    ContactPreparationResult,
)
from app.mana_operation_ai.domain.contact_preparation import (
    CONTACT_TOOL_CONTINUATION_CONTRACT,
    CONTACT_TOOL_CONTRACT,
)
from app.mana_operation_ai.domain.cost_control import (
    CostAttribution,
    CostReservation,
    LlmRateCard,
    ProductScope,
    ResourceUsage,
)
from app.mana_operation_ai.domain.session import SessionMemory
from app.mana_operation_ai.infrastructure.contact_model_continuation import (
    capture_contact_window,
    contact_result_input,
)
from app.mana_operation_ai.infrastructure.contact_tool_schema import (
    ContactToolOptions,
    contact_function_tools,
    parse_contact_function,
)
from app.mana_operation_ai.infrastructure.inference import (
    inference_rate_cards,
    selected_inference,
)
from app.mana_operation_ai.infrastructure.inference_errors import response_failure, sdk_failure
from app.mana_operation_ai.infrastructure.inference_usage import (
    InferenceUsageEnvelope,
    pending_usage_status,
)


class _RawChatResponse(Protocol):
    http_response: httpx.Response

    def parse(self) -> ParsedResponse[ChatReply]: ...


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
        try:
            return await self._reply(instructions=instructions, context=context, owner=owner)
        except (APIConnectionError, APIStatusError) as exc:
            raise sdk_failure(exc) from None
        except ValidationError:
            raise InferenceProviderError("invalid_response") from None

    async def _reply(self, *, instructions: str, context: str, owner: str) -> ChatTurnOutput:
        model_name, effort, rates, output_limit = self._selection(context)
        native_contact = self._native_contact_mode(context)
        if native_contact and self._ledger is None:
            raise RuntimeError("Native contact selection requires the shared inference ledger")
        tool_options: ContactToolOptions = (
            {"tools": contact_function_tools(), "parallel_tool_calls": False}
            if native_contact
            else {}
        )
        capture_window = (
            native_contact
            and json.loads(context).get("contact_tool_contract")
            == CONTACT_TOOL_CONTINUATION_CONTRACT
        )
        if capture_window:
            tool_options["include"] = ["reasoning.encrypted_content"]
        reservation = await self._admit(
            instructions=instructions,
            context=context,
            model=model_name,
            rates=rates,
            output_limit=output_limit,
            response_bytes=262144,
        )
        # Exceptions, timeouts and cancellation deliberately retain the reservation.
        parser = (
            self._client.responses.with_raw_response.parse
            if reservation is not None
            else self._client.responses.parse
        )
        raw = await parser(
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
            **tool_options,
        )
        if reservation is not None:
            receipt = cast(_RawChatResponse, raw)
            payload, envelope = await self._verified_receipt(receipt, reservation, rates)
            if native_contact:
                selected = parse_contact_function(payload)
                if selected is not None:
                    selection, call_sha256 = selected
                    window = None
                    if capture_window:
                        try:
                            window = capture_contact_window(
                                output=payload.get("output"),
                                model=model_name,
                                effort=effort,
                                instructions=instructions,
                                context=context,
                            )
                        except (ValueError, TypeError):
                            raise InferenceProviderError("invalid_response") from None
                    return ChatTurnOutput(
                        answer=(
                            "Tanlangan test xabarini tayyorlashni tasdiqlang. "
                            "Haqiqiy xabar yuborilmaydi."
                            if json.loads(context).get("response_language") == "uz"
                            else "Подтвердите подготовку выбранного тестового сообщения. "
                            "Реальной отправки не будет."
                        ),
                        model=envelope.model,
                        input_tokens=envelope.usage.input_tokens if envelope.usage else None,
                        output_tokens=envelope.usage.output_tokens if envelope.usage else None,
                        next_action="retention_contacts",
                        contact_selection=selection,
                        contact_call_sha256=call_sha256,
                        contact_model_window=window,
                    )
            try:
                response = receipt.parse()
            except (ValueError, TypeError, KeyError, AttributeError):
                # SDK output parsing is local; valid usage was settled above.
                raise InferenceProviderError("invalid_response") from None
        else:
            response = cast(ParsedResponse[ChatReply], raw)
        if response.status != "completed" or response.output_parsed is None:
            raise InferenceProviderError("invalid_response")
        return ChatTurnOutput(
            answer=response.output_parsed.answer,
            model=response.model,
            input_tokens=response.usage.input_tokens if response.usage else None,
            output_tokens=response.usage.output_tokens if response.usage else None,
            plan=response.output_parsed.plan,
            next_action=response.output_parsed.next_action,
        )

    def _native_contact_mode(self, context: str) -> bool:
        if not self._settings.operation_workspace_contact_tool_proposals_enabled:
            return False
        payload = json.loads(context)
        topic = payload.get("topic", {})
        return (
            (
                payload.get("contact_tool_contract") == CONTACT_TOOL_CONTRACT
                or (
                    payload.get("contact_tool_contract") == CONTACT_TOOL_CONTINUATION_CONTRACT
                    and self._settings.operation_workspace_contact_tool_continuations_enabled
                )
            )
            and topic.get("product") == "mana"
            and topic.get("agent_id") in {"retention-agent", "operations-orchestrator"}
            and "retention_contacts" in payload.get("allowed_next_actions", [])
        )

    async def _verified_receipt(
        self, receipt: _RawChatResponse, reservation: CostReservation, rates: LlmRateCard
    ) -> tuple[dict[str, object], InferenceUsageEnvelope]:
        try:
            payload = receipt.http_response.json()
            envelope = InferenceUsageEnvelope.model_validate(payload)
        except ValueError:
            raise InferenceProviderError("unknown_usage") from None
        pending = pending_usage_status(payload)
        if pending is not None:
            raise InferenceProviderError("unknown_usage", pending_status=pending)
        if payload.get("status") == "failed" and envelope.usage is None:
            error = payload.get("error")
            raise response_failure(error.get("code") if isinstance(error, dict) else None)
        await self._settle(envelope, reservation, rates, len(receipt.http_response.content))
        if payload.get("status") != "completed":
            raise InferenceProviderError("invalid_response")
        return payload, envelope

    async def continue_contact(
        self,
        *,
        window: ContactModelWindow,
        result: ContactPreparationResult,
        call_sha256: str,
        owner: str,
        memory: SessionMemory | None = None,
    ) -> ChatTurnOutput:
        if not (
            self._ledger is not None
            and self._settings.operation_workspace_contact_tool_proposals_enabled
            and self._settings.operation_workspace_contact_tool_continuations_enabled
        ):
            raise RuntimeError("Native contact continuation is disabled")
        model, effort, rates, output_limit = self._selection(window.context)
        if (model, effort) != (window.model, window.effort):
            raise RuntimeError("Original model/reasoning configuration changed")
        try:
            items = contact_result_input(window, result, call_sha256=call_sha256)
            if memory is not None:
                topic = json.loads(window.context)["topic"]
                if (memory.topic_id, memory.product) != (
                    topic["topic_id"],
                    topic["product"],
                ):
                    raise ValueError("Frozen session context does not match the originating room")
                items.append(
                    {
                        "type": "message",
                        "role": "user",
                        "content": (
                            "Frozen same-owner/topic session conditions and historical context, "
                            "not fresh evidence or permissions:\n" + memory.model_dump_json()
                        ),
                    }
                )
        except (ValueError, TypeError):
            raise InferenceProviderError("invalid_response") from None
        instructions = window.instructions + (
            f"\nContinuation SQL observation time: {result.observed_at.isoformat()}. "
            "The original evaluation_time and saved reports belong to the original turn, "
            "not this continuation; do not assume their freshness persists. "
            "\nThe native function output is a frozen SQL observation of the exact fictional "
            "preparation/action, not live delivery, current customer eligibility or permission. "
            "Keep every original condition. Explain the observed status and next human step; "
            "uncertain/dispatching means no retry. No further tools or action cards are available "
            "in this response: next_action must be none. Never claim measured retention or "
            "real delivery. Use the original response_language, not the recipient language."
        )
        reservation = await self._admit(
            instructions=instructions,
            context=window.context,
            input_items=items,
            model=model,
            rates=rates,
            output_limit=output_limit,
            response_bytes=262144,
        )
        assert reservation is not None
        try:
            raw = await self._client.responses.with_raw_response.parse(
                model=model,
                instructions=instructions,
                input=items,
                tools=contact_function_tools(),
                tool_choice="none",
                parallel_tool_calls=False,
                max_output_tokens=output_limit,
                reasoning={"effort": effort},
                text={"verbosity": "medium" if self._catalog else self._settings.openai_verbosity},
                store=False,
                service_tier="default",
                safety_identifier=hashlib.sha256(owner.encode()).hexdigest(),
                text_format=ChatReply,
            )
            receipt = cast(_RawChatResponse, raw)
            payload, envelope = await self._verified_receipt(receipt, reservation, rates)
            if parse_contact_function(payload) is not None:
                raise InferenceProviderError("invalid_response")
            response = receipt.parse()
            if response.output_parsed is None or response.output_parsed.next_action != "none":
                raise InferenceProviderError("invalid_response")
            return ChatTurnOutput(
                answer=response.output_parsed.answer,
                model=envelope.model,
                input_tokens=envelope.usage.input_tokens if envelope.usage else None,
                output_tokens=envelope.usage.output_tokens if envelope.usage else None,
                plan=response.output_parsed.plan,
            )
        except (APIConnectionError, APIStatusError) as exc:
            raise sdk_failure(exc) from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise InferenceProviderError("invalid_response") from None

    def _selection(
        self, context: str
    ) -> tuple[str, Literal["none", "low", "medium", "high", "xhigh"], LlmRateCard, int]:
        model_name, effort, rates = self._model_name, self._reasoning_effort, self._rates
        output_limit = min(self._settings.openai_max_output_tokens, 2048)
        if self._settings.operation_model_selection_enabled:
            plan = selected_inference(context, goal=False)
            model_name, effort, rates = plan.model, plan.effort, self._catalog[plan.model]
            output_limit = self._settings.operation_chat_max_output_tokens
        return model_name, effort, rates, output_limit

    async def _admit(
        self,
        *,
        instructions: str,
        context: str,
        model: str,
        rates: LlmRateCard,
        output_limit: int,
        response_bytes: int,
        input_items: list[ResponseInputItemParam] | None = None,
    ) -> CostReservation | None:
        if self._ledger is not None:
            if model != rates.model:
                raise RuntimeError("Operational model and configured rate card do not match")
            # Text-only byte bound includes instructions and the structured-output
            # schema. It deliberately over-reserves instead of guessing a tokenizer
            # for a different model or adding an external token-counting request.
            input_bound = conversation_input_bound(
                instructions=instructions,
                context=input_items if input_items is not None else context,
                tools=contact_function_tools() if self._native_contact_mode(context) else None,
            )
            if input_bound > self._settings.operation_chat_max_input_tokens:
                raise RuntimeError("Operational conversation context exceeds its token bound")
            return await self._ledger.reserve(
                ResourceUsage(
                    llm_calls=1,
                    provider_requests=1,
                    input_tokens=input_bound,
                    output_tokens=output_limit,
                    response_bytes=response_bytes,
                    llm_microusd=rates.reserve_microusd(
                        input_tokens=input_bound,
                        output_tokens=output_limit,
                    ),
                ),
                attribution=_attribution(context),
            )
        return None

    async def _settle(
        self,
        response: InferenceUsageEnvelope,
        reservation: CostReservation | None,
        rates: LlmRateCard,
        response_bytes: int,
    ) -> None:
        if reservation is not None and self._ledger is not None:
            if (
                re.fullmatch(re.escape(rates.model) + r"(?:-\d{4}-\d{2}-\d{2})?", response.model)
                is None
                or response.service_tier != "default"
                or response.usage is None
            ):
                raise InferenceProviderError("unknown_usage")
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
                response_bytes=response_bytes,
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

    async def stream_reply(
        self, *, instructions: str, context: str, owner: str
    ) -> AsyncGenerator[str | ChatTurnOutput, None]:
        try:
            async for event in self._stream_reply(
                instructions=instructions, context=context, owner=owner
            ):
                yield event
        except (APIConnectionError, APIStatusError) as exc:
            raise sdk_failure(exc) from None
        except httpx.TimeoutException:
            raise InferenceProviderError("timeout") from None
        except httpx.TransportError:
            raise InferenceProviderError("connection") from None
        except ValidationError:
            raise InferenceProviderError("invalid_response") from None

    async def _stream_reply(
        self, *, instructions: str, context: str, owner: str
    ) -> AsyncGenerator[str | ChatTurnOutput, None]:
        model, effort, rates, output_limit = self._selection(context)
        reservation = await self._admit(
            instructions=instructions,
            context=context,
            model=model,
            rates=rates,
            output_limit=output_limit,
            response_bytes=1048576,
        )
        stream = await self._client.responses.create(
            model=model,
            instructions=instructions,
            input=context,
            stream=True,
            reasoning={"effort": effort},
            max_output_tokens=output_limit,
            store=False,
            service_tier="default",
            safety_identifier=hashlib.sha256(owner.encode()).hexdigest(),
            text={
                "verbosity": "medium" if self._catalog else self._settings.openai_verbosity,
                "format": {
                    "type": "json_schema",
                    "name": "ChatReply",
                    "strict": True,
                    "schema": ChatReply.model_json_schema(),
                },
            },
        )
        text, published = "", ""
        response: InferenceUsageEnvelope | None = None
        status: object = None
        last = 0.0
        try:
            # The pinned SDK owns SSE framing. Its normal event models may coerce
            # usage types, so validate terminal raw JSON before that conversion.
            # This consumes the same stream once; it never repeats HTTP or SSE I/O.
            async for event in stream._iter_events():
                if stream.response.num_bytes_downloaded > 1048576:
                    raise RuntimeError("Conversation stream exceeded its byte bound")
                if event.data.startswith("[DONE]"):
                    break
                try:
                    data = event.json()
                except ValueError:
                    raise InferenceProviderError("unknown_usage") from None
                if not isinstance(data, dict):
                    raise InferenceProviderError("invalid_response")
                if event.event == "error" or data.get("type") == "error":
                    error = data.get("error", data)
                    raise response_failure(error.get("code") if isinstance(error, dict) else None)
                if data.get("type") == "response.output_text.delta":
                    delta = data.get("delta")
                    if not isinstance(delta, str):
                        raise InferenceProviderError("invalid_response")
                    text += delta
                    if len(text.encode()) > 65536:
                        raise RuntimeError("Conversation JSON stream exceeded its bound")
                    # The SDK owns SSE parsing; parse only the display field from
                    # unfinished JSON. It never becomes a card, tool or final answer.
                    try:
                        partial = from_json(text, allow_partial="trailing-strings")
                    except ValueError:
                        continue
                    answer = partial.get("answer") if isinstance(partial, dict) else None
                    if isinstance(answer, str):
                        answer = answer.lstrip()[:16000]
                        if not answer.startswith(published):
                            raise RuntimeError("Conversation preview rewrote its prefix")
                        if answer != published and (not published or monotonic() - last >= 0.25):
                            published, last = answer, monotonic()
                            yield answer
                elif data.get("type") in (
                    "response.completed",
                    "response.incomplete",
                    "response.failed",
                ):
                    payload = data.get("response")
                    try:
                        response = InferenceUsageEnvelope.model_validate(payload)
                    except ValueError:
                        raise InferenceProviderError("unknown_usage") from None
                    pending = pending_usage_status(payload)
                    if pending is not None:
                        raise InferenceProviderError("unknown_usage", pending_status=pending)
                    assert isinstance(payload, dict)
                    status = payload.get("status")
                    if status == "failed" and response.usage is None:
                        error = payload.get("error")
                        raise response_failure(
                            error.get("code") if isinstance(error, dict) else None
                        )
                    # Settle known usage before JSON/schema validation can fail.
                    await self._settle(
                        response, reservation, rates, stream.response.num_bytes_downloaded
                    )
                    break
            if response is None:
                raise InferenceProviderError("unknown_usage")
            if status != "completed":
                raise InferenceProviderError("invalid_response")
            parsed = ChatReply.model_validate_json(text)
            yield ChatTurnOutput(
                parsed.answer,
                response.model,
                response.usage.input_tokens if response.usage else None,
                response.usage.output_tokens if response.usage else None,
                plan=parsed.plan,
                next_action=parsed.next_action,
            )
        finally:
            await stream.close()

    async def close(self) -> None:
        await self._client.close()


def conversation_input_bound(
    *,
    instructions: str,
    context: str | list[ResponseInputItemParam],
    tools: list[FunctionToolParam] | None = None,
) -> int:
    """Shared conservative text/schema/protocol bound for admission and dry-run QA."""
    return (
        len(
            json.dumps(
                {
                    "instructions": instructions,
                    "input": context,
                    "schema": ChatReply.model_json_schema(),
                    **({"tools": tools, "parallel_tool_calls": False} if tools else {}),
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
