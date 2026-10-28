"""No transport retries; strict raw terminal usage before text validation."""

import asyncio
import json
from datetime import UTC
from typing import Any, cast

from openai import APIStatusError, AsyncOpenAI
from openai.types.responses import ResponseInputParam
from openai.types.responses.response_text_config_param import ResponseTextConfigParam
from pydantic import ValidationError

from app.core.config import Settings
from app.mana_ai.application.bound_reminder_review import (
    BOUND_REMINDER_PREPARE_ACK,
    bound_reminder_review_candidate,
    bound_reminder_review_schema,
    parse_bound_reminder_review,
)
from app.mana_ai.application.chat_ports import (
    ChatDecisionFailure,
    ChatModelReceipt,
    ChatModelRejected,
    ChatPrompt,
)
from app.mana_ai.application.compact_manager_decision import (
    compact_manager_decision_tools,
    parse_compact_manager_decision,
)
from app.mana_ai.application.input_presentation import without_schema_titles
from app.mana_ai.application.parent_languages import language_name, parent_language
from app.mana_ai.application.upsell_text import TARIFF_HANDOFF_PLACEHOLDER
from app.mana_ai.domain.chat import ChatTokens
from app.mana_ai.domain.client_upsell import UpsellChoice
from app.mana_ai.domain.compact_manager_decision import (
    COMPACT_MANAGER_DECISION_TOOL,
    CompactManagerInvocation,
)
from app.mana_ai.domain.family_agents import (
    ParentTouchCurrencyReply,
    ParentTouchEvidenceReply,
    ParentTouchModelReply,
    ParentTouchReminderReply,
    ParentTouchSlotReply,
    ParentTouchText,
    ParentTouchUpsellReply,
)
from app.mana_ai.domain.parent_touch_manager import (
    CHILD_REVIEW_TOOL,
    REMINDER_TOOL,
    UPSELL_TOOL,
    ParentTouchClarificationReply,
    ParentTouchManagerHandoff,
    ParentTouchManagerReply,
    ParentTouchTariffCall,
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
        result = self._base_text(prompt)
        if prompt.input_presentation == 1 and "format" in result:
            format_value = result["format"]
            if format_value["type"] == "json_schema":
                format_value["schema"] = without_schema_titles(format_value["schema"])
        return result

    def _base_text(self, prompt: ChatPrompt) -> ResponseTextConfigParam:
        if prompt.safety_parent_review or prompt.safety_source_review:
            raise ValueError("A parent-chat adapter cannot inherit a specialist review protocol")
        if prompt.bound_reminder_request is not None:
            scope = prompt.manager_scope
            if (
                scope is None
                or scope.stage != "reminder"
                or scope.compact_decision_protocol is not None
                or prompt.reminder_scope is None
                or prompt.notice is not None
                or prompt.question is not None
                or prompt.upsell_scope is not None
                or prompt.retention_scope is not None
            ):
                raise ValueError("A bound review requires its one owning reminder scope")
            return {
                "verbosity": self._verbosity,
                "format": {
                    "type": "json_schema",
                    "name": "parent_touch_bound_reminder_review",
                    "strict": True,
                    "schema": bound_reminder_review_schema(scope),
                },
            }
        if prompt.manager_scope and prompt.manager_scope.compact_decision_protocol in {1, 2}:
            if prompt.manager_scope.stage != "route":
                raise ValueError("A compact native decision belongs only to initial routing")
            return {"verbosity": self._verbosity}
        text: ResponseTextConfigParam = {"verbosity": self._verbosity}
        if prompt.manager_scope and prompt.manager_scope.stage == "route":
            if not prompt.structured_reply:
                raise ValueError("A manager decision requires its strict response contract")
            text["format"] = {
                "type": "json_schema",
                "name": "parent_touch_clarification_reply"
                if prompt.manager_scope.clarifications_enabled
                else "parent_touch_manager_reply",
                "strict": True,
                "schema": (
                    ParentTouchClarificationReply
                    if prompt.manager_scope.clarifications_enabled
                    else ParentTouchManagerReply
                ).model_json_schema(),
            }
            return text
        if prompt.slot_reply:
            if not prompt.structured_reply:
                raise ValueError("A publication slot requires a structured reply")
            schema = (
                ParentTouchCurrencyReply
                if prompt.upsell_scope and prompt.upsell_scope.protocol == "catalog-currency-v2"
                else ParentTouchUpsellReply
                if prompt.upsell_scope
                else ParentTouchReminderReply
                if prompt.reminder_scope
                else ParentTouchSlotReply
            ).model_json_schema()
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
                if prompt.reminder_scope is None and prompt.upsell_scope is None:
                    schema["properties"]["body"]["minLength"] = 1
            elif prompt.retention_scope is not None and prompt.question.scope == "parent":
                # This owning publication requires its question; ordinary child
                # questions may still be deferred with null under their old contract.
                schema["properties"]["question"] = {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 400,
                    "pattern": r"^[^?\u061f\uff1f]*[?\u061f\uff1f]$",
                    "description": schema["properties"]["question"].get(
                        "description", "The single admitted parent support question."
                    ),
                }
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

    @staticmethod
    def _manager_tools(prompt: ChatPrompt) -> dict[str, Any]:
        scope = prompt.manager_scope
        if scope is None or scope.stage != "route":
            return {}
        if scope.compact_decision_protocol in {1, 2}:
            return compact_manager_decision_tools(scope)
        descriptions = [
            (CHILD_REVIEW_TOOL, "Ask Child-Safety to analyse this parent's child request.")
        ]
        if scope.upsell_enabled:
            descriptions.append((UPSELL_TOOL, "Handle the parent's account or tariff question."))
        if scope.reminders_enabled:
            descriptions.append((REMINDER_TOOL, "Prepare the parent's requested reminder."))
        result: dict[str, Any] = {
            "tools": [
                {
                    "type": "function",
                    "name": name,
                    "description": description,
                    "strict": True,
                    "parameters": ParentTouchTariffCall.model_json_schema()
                    if name == UPSELL_TOOL and scope.tariff_handoff_enabled
                    else {
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                }
                for name, description in descriptions
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
        }
        if prompt.input_presentation == 1:
            for tool in result["tools"]:
                tool["parameters"] = without_schema_titles(tool["parameters"])
        return result

    def _manager_call_receipt(
        self, prompt: ChatPrompt, payload: dict[str, Any], usage: ChatTokens, output_cap: int
    ) -> ChatModelReceipt | None:
        scope = prompt.manager_scope
        if scope is None or scope.stage != "route":
            return None
        if scope.compact_decision_protocol in {1, 2}:
            return self._compact_manager_receipt(prompt, payload, usage, output_cap)
        output = payload.get("output")
        calls = (
            [
                item
                for item in output
                if isinstance(item, dict) and item.get("type") == "function_call"
            ]
            if isinstance(output, list)
            else []
        )
        if not calls:
            return None
        raw_model = payload.get("model")
        model = (
            raw_model if isinstance(raw_model, str) and 0 < len(raw_model) <= 128 else self._model
        )
        handoff = None
        try:
            if (
                len(calls) != 1
                or payload.get("status") != "completed"
                or not isinstance(raw_model, str)
                or not 0 < len(raw_model) <= 128
                or usage.output_tokens > output_cap
            ):
                raise ValueError("Invalid manager terminal decision")
            assert isinstance(output, list)
            if any(
                not isinstance(i, dict)
                or i.get("type") not in {"function_call", "message", "reasoning"}
                for i in output
            ):
                raise ValueError("Unexpected manager output")
            call = calls[0]
            targets = {CHILD_REVIEW_TOOL: "child_safety"}
            if scope.upsell_enabled:
                targets[UPSELL_TOOL] = "upsell"
            if scope.reminders_enabled:
                targets[REMINDER_TOOL] = "reminder"
            arguments = call.get("arguments")
            direct_tariff = call.get("name") == UPSELL_TOOL and scope.tariff_handoff_enabled
            if (
                call.get("name") not in targets
                or call.get("status") not in {None, "completed"}
                or not isinstance(arguments, str)
                or len(arguments) > (4096 if direct_tariff else 256)
            ):
                raise ValueError("Unadmitted manager call")
            enquiry = None
            if direct_tariff:
                enquiry = ParentTouchTariffCall.model_validate_json(arguments).enquiry
            elif json.loads(arguments) != {}:
                raise ValueError("Unadmitted manager arguments")
            handoff = ParentTouchManagerHandoff(
                target=targets[call["name"]], call_id=call.get("call_id"), tariff_enquiry=enquiry
            )
        except (ValueError, TypeError, ValidationError):
            pass
        return ChatModelReceipt(
            usage=usage,
            model=model,
            answer=TARIFF_HANDOFF_PLACEHOLDER
            if handoff is not None and handoff.tariff_enquiry is not None
            else None,
            completed=handoff is not None,
            failure_code=None if handoff else "reply_schema_invalid",
            manager_handoff=handoff,
        )

    def _compact_manager_receipt(
        self, prompt: ChatPrompt, payload: dict[str, Any], usage: ChatTokens, output_cap: int
    ) -> ChatModelReceipt:
        scope = prompt.manager_scope
        assert scope is not None
        raw_model = payload.get("model")
        valid_model = (
            isinstance(raw_model, str) and 0 < len(raw_model) <= 128 and raw_model.isascii()
        )
        model = raw_model if isinstance(raw_model, str) and valid_model else self._model
        invocation = None
        answer = None
        handoff = None
        question = None
        failure: ChatDecisionFailure = "reply_schema_invalid"
        try:
            output = payload.get("output")
            if (
                payload.get("status") != "completed"
                or not valid_model
                or usage.output_tokens > output_cap
                or not isinstance(output, list)
                or any(
                    not isinstance(item, dict)
                    or item.get("type") not in {"function_call", "reasoning", "message"}
                    for item in output
                )
            ):
                raise ValueError("Invalid compact manager terminal output")
            calls = [item for item in output if item.get("type") == "function_call"]
            if len(calls) != 1:
                raise ValueError("One paired native decision is required")
            call = calls[0]
            arguments = call.get("arguments")
            if (
                call.get("name") != COMPACT_MANAGER_DECISION_TOOL
                or call.get("status") not in {None, "completed"}
                or not isinstance(arguments, str)
                or len(arguments) > 32768
            ):
                raise ValueError("Unadmitted compact manager function")
            decision = parse_compact_manager_decision(json.loads(arguments), scope)
            for value in (
                decision.body,
                decision.question,
                decision.enquiry.parent_quote if decision.enquiry else None,
            ):
                if value is not None:
                    value.encode("utf-8")
            invocation = CompactManagerInvocation(call_id=call.get("call_id"), decision=decision)
            if decision.kind == "reply":
                if prompt.response_language and any(
                    detected is not None and detected != prompt.response_language
                    for detected in (
                        parent_language(decision.body or ""),
                        parent_language(decision.question or ""),
                    )
                ):
                    failure = "reply_language_mismatch"
                    raise ValueError("The native reply used another presentation language")
                question = decision.question
                answer = "\n\n".join(
                    part for part in ((decision.body or "").strip(), question) if part
                )
            else:
                handoff = ParentTouchManagerHandoff(
                    target=decision.kind,
                    call_id=invocation.call_id,
                    tariff_enquiry=decision.enquiry,
                )
                answer = TARIFF_HANDOFF_PLACEHOLDER if decision.enquiry is not None else None
        except (ValueError, TypeError, ValidationError, RecursionError):
            invocation = None
            answer = None
            handoff = None
            question = None
        return ChatModelReceipt(
            usage=usage,
            model=model,
            answer=answer,
            completed=invocation is not None,
            failure_code=None if invocation is not None else failure,
            manager_handoff=handoff,
            clarification_question=question,
            native_manager_invocation=invocation,
        )

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
            **self._manager_tools(prompt),
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
                **self._manager_tools(prompt),
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
        delegated = self._manager_call_receipt(prompt, payload, tokens, max_output_tokens)
        if delegated is not None:
            return delegated
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
        if prompt.bound_reminder_request is not None:
            return self._bound_reminder_receipt(
                prompt, tokens, model, answer if completed else None, failure_code
            )
        reminder_candidate = None
        reminder_question_text = None
        upsell_choice = None
        upsell_question_text = None
        clarification_question = None
        upsell_enquiry = None
        if completed and prompt.structured_reply:
            try:
                reply: ParentTouchText
                if prompt.manager_scope and prompt.manager_scope.stage == "route":
                    if prompt.manager_scope.clarifications_enabled:
                        reply = ParentTouchClarificationReply.model_validate_json(answer)
                        clarification_question = reply.question
                    else:
                        routed = ParentTouchManagerReply.model_validate_json(answer)
                        reply = ParentTouchText(body=routed.body, question=None)
                elif prompt.slot_reply:
                    reply = (
                        ParentTouchCurrencyReply
                        if prompt.upsell_scope
                        and prompt.upsell_scope.protocol == "catalog-currency-v2"
                        else ParentTouchUpsellReply
                        if prompt.upsell_scope
                        else ParentTouchReminderReply
                        if prompt.reminder_scope
                        else ParentTouchSlotReply
                    ).model_validate_json(answer)
                    if isinstance(reply, ParentTouchCurrencyReply) and reply.upsell is not None:
                        if reply.upsell.currency is None:
                            upsell_enquiry = reply.upsell
                            if reply.question is not None:
                                raise ValueError("A currency question cannot overlap another slot")
                        else:
                            upsell_choice = UpsellChoice.model_validate(reply.upsell.model_dump())
                            upsell_question_text = reply.question
                    if isinstance(reply, ParentTouchUpsellReply) and reply.upsell is not None:
                        upsell_choice = reply.upsell
                        upsell_question_text = reply.question
                    if isinstance(reply, ParentTouchReminderReply) and reply.reminder is not None:
                        reminder_candidate = reply.reminder
                        reminder_question_text = reply.question
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
                if prompt.retention_scope is not None and (
                    len(reply.body) > 700 or any(mark in reply.body for mark in ("?", "？", "؟"))
                ):
                    raise ValueError("A retention check-in cannot create an unmanaged question")
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
                if (upsell_choice is not None or upsell_enquiry is not None) and not answer:
                    answer = "Catalog enquiry awaiting host validation."
                if reminder_candidate is not None and not answer:
                    answer = "Reminder proposal awaiting host validation."
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
            reminder_candidate=reminder_candidate if completed else None,
            reminder_question_text=reminder_question_text if completed else None,
            upsell_choice=upsell_choice if completed else None,
            upsell_question_text=upsell_question_text if completed else None,
            clarification_question=clarification_question if completed else None,
            upsell_enquiry=upsell_enquiry if completed else None,
        )

    def _bound_reminder_receipt(
        self,
        prompt: ChatPrompt,
        tokens: ChatTokens,
        raw_model: object,
        text: str | None,
        failure: ChatDecisionFailure | None,
    ) -> ChatModelReceipt:
        decision = candidate = question = answer = None
        model = self._model
        try:
            if (
                not isinstance(raw_model, str)
                or not 0 < len(raw_model) <= 128
                or not raw_model.isascii()
                or not raw_model.isprintable()
                or any(c.isspace() for c in raw_model)
            ):
                raise ValueError("Invalid bound-review model label")
            model = raw_model
            if (
                text is None
                or prompt.manager_scope is None
                or prompt.bound_reminder_request is None
            ):
                raise ValueError("No complete bound review")
            decision = parse_bound_reminder_review(
                json.loads(text), prompt.bound_reminder_request, prompt.manager_scope
            )
            for part in (decision.body, decision.question):
                if part is not None:
                    part.encode("utf-8")
                    if (
                        prompt.response_language
                        and (detected := parent_language(part)) is not None
                        and detected != prompt.response_language
                    ):
                        failure = "reply_language_mismatch"
                        raise ValueError("The bound review used another parent language")
            candidate = bound_reminder_review_candidate(decision, prompt.bound_reminder_request)
            question = decision.question
            answer = (
                BOUND_REMINDER_PREPARE_ACK
                if candidate is not None
                else "\n\n".join(p for p in ((decision.body or "").strip(), question) if p)
            )
        except (ValueError, TypeError, RecursionError):
            decision = candidate = question = answer = None
            failure = failure or "reply_schema_invalid"
        return ChatModelReceipt(
            usage=tokens,
            model=model,
            answer=answer,
            completed=decision is not None,
            failure_code=None if decision is not None else failure,
            reminder_candidate=candidate,
            clarification_question=question,
            bound_reminder_decision=decision,
        )

    async def close(self) -> None:
        await self._client.close()
