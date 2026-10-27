"""Native source transport only; never source dispatch, policy or budget authority."""

import asyncio
import hashlib
import json
from typing import cast

from openai import APIStatusError
from openai.types.responses import ResponseInputParam, ToolParam
from openai.types.responses.response_text_config_param import ResponseTextConfigParam
from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ChatModelRejected
from app.mana_ai.application.input_presentation import without_schema_titles
from app.mana_ai.application.source_tool_ports import SourceModelReceipt, SourceToolPrompt
from app.mana_ai.domain.chat import ChatTokens
from app.mana_ai.domain.family_day_usage import DayUsageReceipt
from app.mana_ai.domain.source_tools import (
    BatterySourceCall,
    DatedObservationCall,
    EncryptedSourceReasoning,
    ObservationSourceCall,
    SourceToolContinuation,
    SourceToolModelProfile,
    SourceToolScope,
    source_call_alias,
    source_call_day,
    source_call_key,
)
from app.services.chat_usage_receipt import terminal_chat_usage
from app.services.child_safety_model import OpenAIChildSafetyModel


class OpenAIChildSourceModel(OpenAIChildSafetyModel):
    @property
    def source_profile(self) -> SourceToolModelProfile:
        return SourceToolModelProfile(
            model_name=self._model,
            reasoning_effort=self._effort,
            verbosity=self._verbosity,
            wall_timeout_seconds=self._wall_timeout,
        )

    @property
    def model_name(self) -> str:
        return self._model

    def source_input_digest(self, prompt: SourceToolPrompt) -> str:
        return self._digest(prompt)

    def _tools(self, prompt: SourceToolPrompt) -> list[ToolParam]:
        if not prompt.scope.children:
            return []
        if prompt.scope.protocol in {2, 3}:
            return [
                {
                    "type": "function",
                    "name": "read_child_observation",
                    "strict": True,
                    "description": (
                        "Read own-child battery or a partial app-counter page; "
                        "dates/period may be unknown."
                        + (
                            " The captured location kind returns minimized dated point metadata, "
                            "not coordinates, an address or current presence."
                            if prompt.scope.location_enabled
                            else ""
                        )
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "child_alias": {
                                "type": "string",
                                "enum": [c.alias for c in prompt.scope.children],
                            },
                            "kind": {
                                "type": "string",
                                "enum": ["battery", "app_usage"]
                                + (["app_usage_day"] if prompt.scope.protocol == 3 else [])
                                + (["location"] if prompt.scope.location_enabled else []),
                            },
                            **(
                                {
                                    "calendar_day": {
                                        "type": ["string", "null"],
                                        "pattern": r"^\d{4}-\d{2}-\d{2}$",
                                        "description": (
                                            "Completed query day, last 31 days; null for other "
                                            "kinds. Not a verified measurement period."
                                        ),
                                    }
                                }
                                if prompt.scope.protocol == 3
                                else {}
                            ),
                        },
                        "required": ["child_alias", "kind"]
                        + (["calendar_day"] if prompt.scope.protocol == 3 else []),
                        "additionalProperties": False,
                    },
                }
            ]
        return [
            {
                "type": "function",
                "name": "read_child_battery",
                "description": (
                    "Read one authorized child's battery facts through the shared bounded cache. "
                    "Measurement time can be unknown; a write or profile is not online status. "
                    "This grants no messaging, controls, payments or additional queries."
                ),
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "child_alias": {
                            "type": "string",
                            "enum": [child.alias for child in prompt.scope.children],
                        }
                    },
                    "required": ["child_alias"],
                    "additionalProperties": False,
                },
            }
        ]

    def _native_text(self, prompt: SourceToolPrompt) -> ResponseTextConfigParam:
        result = self._text(prompt.input)
        if prompt.scope.input_presentation == 1:
            format_value = result["format"]
            if format_value["type"] != "json_schema":
                raise ValueError("Native input presentation requires the exact strict schema")
            format_value["schema"] = without_schema_titles(format_value["schema"])
        return result

    def _digest(self, prompt: SourceToolPrompt) -> str:
        payload = {
            "version": 1,
            "scope": prompt.scope.model_dump(mode="json"),
            "instructions": prompt.input.instructions,
            "input": self._input(prompt.input),
            "minimum_output_tokens": prompt.input.minimum_output_tokens,
            "text": self._native_text(prompt),
            "tools": self._tools(prompt),
            "model": self._model,
            "reasoning_effort": self._effort,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _request_tools(self, prompt: SourceToolPrompt) -> list[ToolParam]:
        # V3 keeps the original advertised schema in its immutable input digest,
        # but its final-only request has no callable tools. V1/v2 remain exact.
        if prompt.continuation is not None and (
            prompt.scope.protocol == 3 or prompt.scope.input_presentation == 1
        ):
            return []
        return self._tools(prompt)

    def _source_input(self, prompt: SourceToolPrompt) -> ResponseInputParam:
        SourceToolScope.model_validate(prompt.scope.model_dump())
        self._native_text(prompt)  # Refuse a Parent-Touch publication protocol before HTTP.
        if (prompt.continuation is None) != (prompt.source_result is None):
            raise ValueError("A native source result requires its original call")
        result = list(self._input(prompt.input))
        if prompt.continuation is None:
            return result
        continuation = SourceToolContinuation.model_validate(prompt.continuation.model_dump())
        if continuation.input_digest != self._digest(prompt):
            raise ValueError("Native source input changed")
        call = continuation.call
        prompt.scope.validate_call(call)
        alias = source_call_alias(call)
        child = next((child for child in prompt.scope.children if child.alias == alias), None)
        receipt = prompt.source_result
        assert receipt is not None
        # Revalidate, even if a caller used model_copy/model_construct internally.
        receipt = type(receipt).model_validate(receipt.model_dump())
        if (
            child is None
            or receipt.parent_id != prompt.scope.parent_id
            or receipt.child_id != child.child_id
            or receipt.request_id != prompt.scope.request_id_for(call)
            or receipt.status
            not in (
                {"completed", "unavailable"}
                if isinstance(receipt, DayUsageReceipt)
                else {"completed"}
            )
            or (receipt.facts is None and not isinstance(receipt, DayUsageReceipt))
            or receipt.source != source_call_key(call)
            or continuation.version != prompt.scope.protocol
            or (
                isinstance(receipt, DayUsageReceipt)
                and receipt.requested_day != source_call_day(call)
            )
        ):
            raise ValueError("An exact completed own-child source result is required")
        items: list[dict[str, object]] = []
        for item in continuation.items:
            value = item.model_dump(mode="json")
            if isinstance(item, EncryptedSourceReasoning):
                value["summary"] = []  # No raw or summarized reasoning is retained.
            items.append(value)
        tool_result: dict[str, object] = {
            "child_alias": alias,
            "source": receipt.source,
            "cache_hit": receipt.cache_hit,
            "facts": receipt.facts.model_dump(
                mode="json", exclude={"child_id", "position_fingerprint"}
            )
            if receipt.facts is not None
            else None,
            "qualification": "Observations only; unknown measurement time stays unknown.",
        }
        if isinstance(receipt, DayUsageReceipt):
            tool_result.update(
                query_calendar_day=receipt.requested_day.isoformat(),
                child_returned=receipt.child_returned,
                status=receipt.status,
                qualification=(
                    "API-filter label only; incomplete counters, unknown measurement "
                    "period/timezone; absent row is not zero use."
                ),
            )
        items.append(
            {
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": json.dumps(tool_result, ensure_ascii=False, separators=(",", ":")),
            }
        )
        return cast(ResponseInputParam, result + items)

    async def count_source_input(self, prompt: SourceToolPrompt) -> int:
        source_input = self._source_input(prompt)
        async with asyncio.timeout(self._wall_timeout):
            raw = await self._client.responses.input_tokens.with_raw_response.count(
                model=self._model,
                instructions=prompt.input.instructions,
                input=source_input,
                reasoning={"effort": self._effort},
                text=self._native_text(prompt),
                tools=self._request_tools(prompt),
                tool_choice="none" if prompt.continuation or not prompt.scope.children else "auto",
                parallel_tool_calls=False,
                truncation="disabled",
            )
        payload = raw.http_response.json()
        count = payload.get("input_tokens") if isinstance(payload, dict) else None
        if type(count) is not int or not 0 <= count <= 2**31 - 1:
            raise ValueError("Invalid native source token count")
        return count

    async def respond_source(
        self, prompt: SourceToolPrompt, *, max_output_tokens: int
    ) -> SourceModelReceipt:
        if type(max_output_tokens) is not int or not 32 <= max_output_tokens <= 4096:
            raise ValueError("Invalid native source output ceiling")
        source_input = self._source_input(prompt)
        try:
            async with asyncio.timeout(self._wall_timeout):
                raw = await self._client.responses.with_raw_response.create(
                    model=self._model,
                    instructions=prompt.input.instructions,
                    input=source_input,
                    reasoning={"effort": self._effort},
                    text=self._native_text(prompt),
                    tools=self._request_tools(prompt),
                    tool_choice="none"
                    if prompt.continuation or not prompt.scope.children
                    else "auto",
                    parallel_tool_calls=False,
                    include=["reasoning.encrypted_content"],
                    truncation="disabled",
                    max_output_tokens=max_output_tokens,
                    store=False,
                    service_tier="default",
                )
        except APIStatusError as error:
            if error.status_code in {400, 401, 403, 404, 413, 422}:
                raise ChatModelRejected from None
            raise
        payload = raw.http_response.json()
        usage = terminal_chat_usage(payload)
        assert isinstance(payload, dict)
        model = payload.get("model")
        valid_model = isinstance(model, str) and 0 < len(model) <= 128
        recorded_model = model if isinstance(model, str) and valid_model else self._model
        invalid = SourceModelReceipt(
            usage=usage,
            model=recorded_model,
            completed=False,
            failure_code="source_model_output_invalid",
        )
        # From here every invalid native choice still returns raw verified usage.
        try:
            output = payload.get("output")
            if (
                payload["status"] != "completed"
                or not valid_model
                or usage.output_tokens > max_output_tokens
                or not isinstance(output, list)
                or not 1 <= len(output) <= 16
                or any(not isinstance(item, dict) for item in output)
            ):
                return invalid
            assert isinstance(model, str)
            calls = [item for item in output if item.get("type") == "function_call"]
            if calls:
                if prompt.continuation is not None or len(calls) != 1:
                    return invalid
                return self._native_choice(prompt, output, usage=usage, model=model)
            texts: list[str] = []
            for item in output:
                if item.get("type") == "reasoning":
                    continue
                if item.get("type") != "message" or item.get("role") != "assistant":
                    return invalid
                if not isinstance(item.get("content"), list):
                    return invalid
                for part in item["content"]:
                    if (
                        not isinstance(part, dict)
                        or part.get("type") != "output_text"
                        or not isinstance(part.get("text"), str)
                    ):
                        return invalid
                    texts.append(part["text"])
            answer = "\n".join(texts).strip()
            if not 0 < len(answer) <= 32000:
                return invalid
            return SourceModelReceipt(usage=usage, model=model, completed=True, answer=answer)
        except (TypeError, ValueError, KeyError, ValidationError):
            return invalid

    def _native_choice(
        self,
        prompt: SourceToolPrompt,
        output: list[dict[str, object]],
        *,
        usage: ChatTokens,
        model: str,
    ) -> SourceModelReceipt:
        items: list[
            BatterySourceCall
            | ObservationSourceCall
            | DatedObservationCall
            | EncryptedSourceReasoning
        ] = []
        for item in output:
            kind = item.get("type")
            if kind == "message" and item.get("role") == "assistant":
                continue  # Native calls take priority; never retain accompanying prose.
            if item.get("status") not in {None, "completed"}:
                raise ValueError("A provisional item cannot authorize a source call")
            if kind == "function_call":
                call = (
                    BatterySourceCall
                    if prompt.scope.protocol == 1
                    else DatedObservationCall
                    if prompt.scope.protocol == 3
                    else ObservationSourceCall
                ).model_validate({key: value for key, value in item.items() if key != "status"})
                prompt.scope.validate_call(call)
                items.append(call)
            elif kind == "reasoning" and item.get("summary", []) == []:
                items.append(
                    EncryptedSourceReasoning.model_validate(
                        {
                            key: value
                            for key, value in item.items()
                            if key not in {"status", "summary"}
                        }
                    )
                )
            else:
                raise ValueError("Unsupported native source output")
        continuation = SourceToolContinuation(
            version=prompt.scope.protocol, input_digest=self._digest(prompt), items=tuple(items)
        )
        return SourceModelReceipt(
            usage=usage, model=model, completed=True, continuation=continuation
        )
