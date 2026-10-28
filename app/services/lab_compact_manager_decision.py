"""Model-free lab pairing for the same captured native manager lifecycle."""

from dataclasses import replace
from typing import Protocol
from uuid import uuid4

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatPrompt, ParentChatModel
from app.mana_ai.domain.compact_manager_decision import (
    CompactManagerDecision,
    CompactManagerInvocation,
)


class _LabModel(ParentChatModel, Protocol):
    async def close(self) -> None: ...


class LabCompactManagerModel:
    def __init__(self, model: _LabModel) -> None:
        self._model = model

    async def count_input(self, prompt: ChatPrompt) -> int:
        return await self._model.count_input(prompt)

    async def respond(self, prompt: ChatPrompt, *, max_output_tokens: int) -> ChatModelReceipt:
        receipt = await self._model.respond(prompt, max_output_tokens=max_output_tokens)
        scope = prompt.manager_scope
        if scope is None or scope.compact_decision_protocol not in {1, 2} or not receipt.completed:
            return receipt
        handoff = receipt.manager_handoff
        if handoff is not None:
            decision = CompactManagerDecision(
                kind=handoff.target, body=None, question=None, enquiry=handoff.tariff_enquiry
            )
            call_id = handoff.call_id
        else:
            question = receipt.clarification_question
            body = receipt.answer or ""
            if question:
                if not body.endswith(question):
                    return replace(receipt, completed=False, answer=None)
                body = body[: -len(question)].strip()
            decision = CompactManagerDecision(
                kind="reply", body=body, question=question, enquiry=None
            )
            call_id = "lab_call_" + uuid4().hex
        return replace(
            receipt,
            native_manager_invocation=CompactManagerInvocation(call_id=call_id, decision=decision),
        )

    async def close(self) -> None:
        await self._model.close()
