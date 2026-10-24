"""No transport retries; strict raw terminal usage before text validation."""

import asyncio
from datetime import UTC
from typing import cast

from openai import APIStatusError, AsyncOpenAI
from openai.types.responses import ResponseInputParam
from openai.types.responses.response_text_config_param import ResponseTextConfigParam
from pydantic import ValidationError

from app.core.config import Settings
from app.mana_ai.application.chat_ports import (
    ChatDecisionFailure,
    ChatModelReceipt,
    ChatModelRejected,
    ChatPrompt,
)
from app.mana_ai.application.parent_languages import language_name, parent_language
from app.mana_ai.domain.family_agents import (
    ParentTouchEvidenceReply,
    ParentTouchModelReply,
    ParentTouchSlotReply,
    ParentTouchText,
)
from app.services.chat_usage_receipt import terminal_chat_usage


class OpenAIParentChatModel:
    def __init__(self, settings: Settings, *, client: AsyncOpenAI | None = None) -> None:
        self._wall_timeout = min(settings.openai_timeout_seconds, 120) + 10
        self._client = client or AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            max_retries=0,
            timeout=min(settings.openai_timeout_seconds, 120),
        )
        self._model = settings.openai_model
        self._effort = settings.openai_reasoning_effort
        self._verbosity = settings.openai_verbosity

    @staticmethod
    def _input(prompt: ChatPrompt) -> ResponseInputParam:
        return cast(
            ResponseInputParam,
            [{"role": role, "content": content} for role, content in prompt.messages],
        )

    def _text(self, prompt: ChatPrompt) -> ResponseTextConfigParam:
        if prompt.safety_parent_review or prompt.safety_source_review:
            raise ValueError("A parent-chat adapter cannot inherit a specialist review protocol")
        text: ResponseTextConfigParam = {"verbosity": self._verbosity}
        if prompt.slot_reply:
            if not prompt.structured_reply:
                raise ValueError("A publication slot requires a structured reply")
            schema = ParentTouchSlotReply.model_json_schema()
            if prompt.response_language:
                language = language_name(prompt.response_language)
                schema["properties"]["body"]["description"] = (
                    f"Statements in {language}, no questions."
                )
                schema["properties"]["question"]["description"] = (
                    f"Translate the admitted need into {language}; do not copy its source language."
                )
            if prompt.question is None:
                schema["properties"]["question"] = {"type": "null"}
                schema["properties"]["body"]["minLength"] = 1
            schema["properties"]["notice_communicated"] = (
                {"type": "boolean", "enum": [False]}
                if prompt.notice is None
                else {"type": "boolean", "enum": [True]}
                if prompt.notice.kind == "urgent"
                else {"type": "boolean"}
            )
            text["format"] = {
                "type": "json_schema",
                "name": "parent_touch_slot_reply",
                "strict": True,
                "schema": schema,
            }
            return text
        if prompt.structured_reply:
            schema = (
                ParentTouchEvidenceReply if prompt.evidence_reply else ParentTouchModelReply
            ).model_json_schema()
            properties = schema["properties"]
            if prompt.question is None:
                properties["question"] = {"type": "null"}
                properties["question_id"] = {"type": "null"}
            else:
                properties["question_id"] = {
                    "anyOf": [
                        {"type": "null"},
                        {"type": "string", "enum": [str(prompt.question.question_id)]},
                    ]
                }
            if prompt.evidence_reply:
                permitted = (
                    {"type": "string", "enum": [str(prompt.notice.notice_id)]}
                    if prompt.notice
                    else {"type": "null"}
                )
                properties["notice_id"] = (
                    permitted
                    if prompt.notice is None or prompt.notice.kind == "urgent"
                    else {"anyOf": [{"type": "null"}, permitted]}
                )
            text["format"] = {
                "type": "json_schema",
                "name": "parent_touch_reply",
                "strict": True,
                "schema": schema,
            }
        return text

    async def count_input(self, prompt: ChatPrompt) -> int:
        async with asyncio.timeout(self._wall_timeout):
            return await self._count_input(prompt)

    async def _count_input(self, prompt: ChatPrompt) -> int:
        raw = await self._client.responses.input_tokens.with_raw_response.count(
            model=self._model,
            instructions=prompt.instructions,
            input=self._input(prompt),
            reasoning={"effort": self._effort},
            text=self._text(prompt),
            truncation="disabled",
        )
        payload = raw.http_response.json()
        count = payload.get("input_tokens") if isinstance(payload, dict) else None
        if type(count) is not int or count < 0:
            raise ValueError("Invalid parent chat token count")
        return count

    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        async with asyncio.timeout(self._wall_timeout):
            return await self._respond(prompt, max_output_tokens=max_output_tokens)

    async def _respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        try:
            raw = await self._client.responses.with_raw_response.create(
                model=self._model,
                instructions=prompt.instructions,
                input=self._input(prompt),
                reasoning={"effort": self._effort},
                text=self._text(prompt),
                truncation="disabled",
                max_output_tokens=max_output_tokens,
                store=False,
                service_tier="default",
            )
        except APIStatusError as exc:
            if exc.status_code in {400, 401, 403, 404, 413, 422}:
                raise ChatModelRejected from None
            raise
        payload = raw.http_response.json()
        tokens = terminal_chat_usage(payload)
        assert isinstance(payload, dict)
        model = payload.get("model")
        valid_model = isinstance(model, str) and 0 < len(model) <= 128
        # From this point invalid text/schema still returns the verified usage.
        text: list[str] = []
        output = payload.get("output")
        valid_output = isinstance(output, list)
        for item in output if isinstance(output, list) else []:
            if not isinstance(item, dict):
                valid_output = False
                continue
            if item.get("type") == "reasoning":
                continue
            if item.get("type") != "message" or item.get("role") != "assistant":
                valid_output = False
                continue
            content = item.get("content")
            if not isinstance(content, list):
                valid_output = False
                continue
            for part in content:
                if not isinstance(part, dict):
                    valid_output = False
                    continue
                value = (
                    part.get("text")
                    if part.get("type") == "output_text"
                    else (part.get("refusal") if part.get("type") == "refusal" else None)
                )
                if isinstance(value, str):
                    text.append(value)
                else:
                    valid_output = False
        answer = "\n".join(text).strip()
        completed = (
            payload["status"] == "completed"
            and valid_model
            and valid_output
            and 0 < len(answer) <= 32_000
            and tokens.output_tokens <= max_output_tokens
        )
        question_id = None
        notice_id = None
        failure_code: ChatDecisionFailure | None = None if completed else "provider_output_invalid"
        if completed and prompt.structured_reply:
            try:
                reply: ParentTouchText
                if prompt.slot_reply:
                    reply = ParentTouchSlotReply.model_validate_json(answer)
                    if reply.question is not None:
                        if prompt.question is None:
                            raise ValueError("No admitted question slot")
                        question_id = prompt.question.question_id
                    if reply.notice_communicated:
                        if prompt.notice is None:
                            raise ValueError("No admitted notice slot")
                        report = prompt.notice.assessment
                        dates = {
                            instant.astimezone(UTC).date().isoformat()
                            for instant in (
                                report.signal_first_observed_at,
                                report.signal_last_observed_at,
                            )
                            if instant is not None
                        }
                        if any(date not in reply.body for date in dates):
                            raise ValueError("A delivered finding must retain its observation date")
                        notice_id = prompt.notice.notice_id
                    elif prompt.notice and prompt.notice.kind == "urgent":
                        raise ValueError("The urgent notice slot must be communicated")
                else:
                    reply = (
                        ParentTouchEvidenceReply if prompt.evidence_reply else ParentTouchModelReply
                    ).model_validate_json(answer)
                    question_id = reply.question_id
                if prompt.response_language and any(
                    detected is not None and detected != prompt.response_language
                    for detected in (
                        parent_language(reply.body),
                        parent_language(reply.question or ""),
                    )
                ):
                    failure_code = "reply_language_mismatch"
                    raise ValueError("The speaker used another presentation language")
                if any(date not in reply.body for date in prompt.required_observation_dates):
                    raise ValueError("A source-backed reply must preserve its observation date")
                if isinstance(reply, ParentTouchEvidenceReply):
                    notice_id = reply.notice_id
                    if notice_id is not None and (
                        prompt.notice is None or notice_id != prompt.notice.notice_id
                    ):
                        raise ValueError("Unadmitted notice identity")
                    if prompt.notice and prompt.notice.kind == "urgent" and notice_id is None:
                        raise ValueError("An urgent notice must be communicated")
                if question_id is not None and (
                    prompt.question is None or question_id != prompt.question.question_id
                ):
                    raise ValueError("The reply selected an unadmitted question")
                answer = "\n\n".join(part for part in (reply.body.strip(), reply.question) if part)
            except (ValueError, ValidationError):
                completed = False
                failure_code = failure_code or "reply_schema_invalid"
        return ChatModelReceipt(
            usage=tokens,
            model=model if isinstance(model, str) and valid_model else self._model,
            answer=answer if completed else None,
            completed=completed,
            question_id=question_id if completed else None,
            notice_id=notice_id if completed else None,
            failure_code=failure_code,
        )

    async def close(self) -> None:
        await self._client.close()
