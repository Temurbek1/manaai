"""Explicit post-human native continuation; no domain write or source execution."""

import asyncio
from datetime import UTC, datetime

from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.chat_ports import (
    ChatError,
    ChatRepository,
    ChatTurnOutput,
    ContactContinuationModel,
    ContactLoopModel,
    SessionContextReader,
)
from app.mana_operation_ai.application.cost_control import CostBudgetExceeded
from app.mana_operation_ai.application.inference_errors import (
    InferenceProviderError,
    inference_failure_message,
)
from app.mana_operation_ai.application.workspace_retention_contacts import (
    WorkspaceRetentionContacts,
)
from app.mana_operation_ai.domain.chat import ChatTurn, MessageCreate
from app.mana_operation_ai.domain.contact_continuation import (
    BoundContactWindow,
    ContactContinueRequest,
    ContactPreparationResult,
    verify_window_request,
)
from app.mana_operation_ai.domain.contact_loop import (
    ContactLoopState,
    verify_loop_append,
    verify_loop_window,
)
from app.mana_operation_ai.domain.contact_preparation import (
    CONTACT_TOOL_LOOP_CONTRACT,
    ContactToolRequest,
    contact_selection_fingerprint,
)


class ContactResultContinuationService:
    def __init__(
        self,
        *,
        chats: ChatRepository,
        contacts: WorkspaceRetentionContacts,
        model: ContactContinuationModel,
        context: SessionContextReader,
        enabled: bool,
        loop_enabled: bool = False,
        loop_model: ContactLoopModel | None = None,
    ) -> None:
        self._chats, self._contacts, self._model = chats, contacts, model
        self._context, self._enabled = context, enabled
        self._loop_enabled, self._loop_model = loop_enabled, loop_model

    async def continue_with_result(
        self, actor: ActorContext, topic_id: str, turn_id: str, request: ContactContinueRequest
    ) -> ChatTurn:
        if not self._enabled or self._model is None:
            raise ChatError("Продолжение после инструмента отключено.", 503)
        await self._contacts._access(actor.actor_id, topic_id, turn_id)
        origin = await self._chats.turn(actor.actor_id, topic_id, turn_id)
        bound, selection = origin.contact_model_window, origin.contact_preparation
        if bound is None or selection is None:
            raise ChatError("Исходный вызов не сохранил протокол продолжения.", 409)
        if origin.contact_reply_turn_id:
            child = await self._chats.turn(actor.actor_id, topic_id, origin.contact_reply_turn_id)
            result = child.contact_result
            if result is None or (result.action_id, result.action_fingerprint, result.revision) != (
                request.action_id,
                request.action_fingerprint,
                request.revision,
            ):
                raise ChatError("Этот вызов уже продолжен с другим SQL-снимком.", 409)
            return child  # Observation only, including a lost response or unknown model receipt.
        root = origin
        if origin.contact_loop is not None:
            if not self._loop_enabled or self._loop_model is None:
                raise ChatError("Последовательные тестовые действия отключены.", 503)
            if not await self._contacts._contacts._execution_allowed():
                raise ChatError("Продолжение контактного цикла остановлено.", 423)
            root = await self._chats.turn(
                actor.actor_id, topic_id, origin.contact_loop.root_turn_id
            )
            if (
                root.contact_loop != ContactLoopState(root_turn_id=root.turn_id)
                or root.contact_tool_contract != CONTACT_TOOL_LOOP_CONTRACT
                or root.contact_model_window is None
                or (root.model_choice, root.reasoning, root.response_language)
                != (origin.model_choice, origin.reasoning, origin.response_language)
                or root.contact_model_window.window.context != bound.window.context
                or root.contact_model_window.window.instructions != bound.window.instructions
            ):
                raise ChatError("Исходные условия контактного цикла изменились.", 503)
        action = await self._contacts._bound(actor, topic_id, turn_id, request.action_id)
        if (action.fingerprint, action.revision) != (request.action_fingerprint, request.revision):
            raise ChatError("Состояние действия изменилось; обновите его перед продолжением.")
        if origin.contact_loop is not None and action.status == "proposed":
            raise ChatError(
                "Сначала завершите отдельное согласование подготовленного действия.", 409
            )
        if (action.message.template, action.request.parameters.account_ref) != (
            selection.template,
            self._contacts._account_refs[selection.recipient],
        ):
            raise ChatError("Результат не соответствует выбранным параметрам инструмента.")
        try:
            if origin.contact_loop is not None:
                verify_loop_window(
                    bound.window,
                    selection,
                    origin.contact_loop,
                    owner=actor.actor_id,
                    topic_id=topic_id,
                    turn_id=turn_id,
                    root_message=root.message,
                    response_language=origin.response_language,
                )
            else:
                verify_window_request(
                    bound.window,
                    selection,
                    topic_id=topic_id,
                    message=origin.message,
                    response_language=origin.response_language,
                )
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ChatError(
                "Сохранённое окно инструмента требует проверки. AI не вызван.", 503
            ) from None
        result = ContactPreparationResult(
            origin_turn_id=turn_id,
            selection_fingerprint=selection.selection_fingerprint,
            action_id=action.action_id,
            action_fingerprint=action.fingerprint,
            revision=action.revision,
            observed_at=datetime.now(UTC),
            template=selection.template,
            message=action.message,
            status=action.status,
            result_code=action.result_code,
        )
        child, admitted = await self._chats.reserve(
            actor.actor_id,
            topic_id,
            MessageCreate(
                request_id=request.request_id,
                message="Tayyorlash natijasini agent bilan davom ettiring."
                if origin.response_language == "uz"
                else "Продолжить с агентом по результату подготовки.",
                model_choice=origin.model_choice,
                reasoning=origin.reasoning,
                execution_mode="agent",
                response_language=origin.response_language,
            ),
            contact_result=result,
        )
        if not admitted:
            return child
        try:
            memory = await self._context.read(actor.actor_id, topic_id, before=child.created_at)
            child = child.model_copy(update={"status": "thinking", "session_memory": memory})
            if not await self._chats.update(child):
                return await self._chats.turn(actor.actor_id, topic_id, child.turn_id)
            async with asyncio.timeout(180):
                if origin.contact_loop is not None:
                    if self._loop_model is None or child.contact_loop is None:
                        raise ChatError("Цикл не сохранил новую SQL-привязку.", 503)
                    output = await self._loop_model.continue_contact_loop(
                        window=bound.window,
                        result=result,
                        call_sha256=selection.provider_call_sha256,
                        owner=actor.actor_id,
                        memory=child.session_memory,
                        loop=child.contact_loop,
                    )
                else:
                    output = await self._model.continue_contact(
                        window=bound.window,
                        result=result,
                        call_sha256=selection.provider_call_sha256,
                        owner=actor.actor_id,
                        memory=child.session_memory,
                    )
            next_request, next_window = None, None
            if output.contact_selection is not None and child.contact_loop is not None:
                next_request, next_window = self._next_request(
                    actor.actor_id, child, output, bound, root
                )
                if not await self._contacts._contacts._execution_allowed():
                    raise ChatError("Новый запрос цикла остановлен после ответа модели.", 423)
            if not output.answer.strip() or (
                next_request is None
                and (
                    output.next_action != "none"
                    or output.contact_selection is not None
                    or output.contact_model_window is not None
                    or output.contact_call_sha256 is not None
                )
            ):
                raise ChatError("Продолжение не может создавать новый запрос действия.", 502)
            child = child.model_copy(
                update={
                    "status": "completed",
                    "answer": output.answer[:16000],
                    "model": output.model,
                    "input_tokens": output.input_tokens,
                    "output_tokens": output.output_tokens,
                    "plan": output.plan[:3],
                    "next_action": "retention_contacts" if next_request else "none",
                    "contact_preparation": next_request,
                    "contact_model_window": next_window,
                }
            )
        except asyncio.CancelledError:
            await self._chats.update(
                child.model_copy(
                    update={
                        "status": "failed",
                        "answer": "Продолжение прервано. Автоматического повтора не будет.",
                    }
                )
            )
            raise
        except InferenceProviderError as exc:
            child = child.model_copy(
                update={"status": "failed", "answer": inference_failure_message(exc)}
            )
        except CostBudgetExceeded:
            child = child.model_copy(
                update={
                    "status": "failed",
                    "answer": "Лимит расходов не допускает продолжение. Повтор не запущен.",
                }
            )
        except Exception:
            child = child.model_copy(
                update={
                    "status": "failed",
                    "answer": "Продолжение не подтверждено. Автоматического повтора не будет.",
                }
            )
        await self._chats.update(child)
        return await self._chats.turn(actor.actor_id, topic_id, child.turn_id)

    @staticmethod
    def _next_request(
        owner: str,
        child: ChatTurn,
        output: ChatTurnOutput,
        original: BoundContactWindow,
        root: ChatTurn,
    ) -> tuple[ContactToolRequest, BoundContactWindow]:
        if (
            child.contact_loop is None
            or output.contact_selection is None
            or output.contact_call_sha256 is None
            or output.contact_model_window is None
            or output.next_action != "retention_contacts"
        ):
            raise ChatError("Продолжение не сохранило точный нативный вызов.", 502)
        request = ContactToolRequest(
            **output.contact_selection.model_dump(),
            contract=CONTACT_TOOL_LOOP_CONTRACT,
            provider_call_sha256=output.contact_call_sha256,
            selection_fingerprint=contact_selection_fingerprint(
                owner,
                child.topic_id,
                child.turn_id,
                output.contact_selection,
                output.contact_call_sha256,
                contract=CONTACT_TOOL_LOOP_CONTRACT,
            ),
        )
        verify_loop_append(
            original.window, output.contact_model_window, child.contact_loop, child.session_memory
        )
        verify_loop_window(
            output.contact_model_window,
            request,
            child.contact_loop,
            owner=owner,
            topic_id=child.topic_id,
            turn_id=child.turn_id,
            root_message=root.message,
            response_language=root.response_language,
        )
        return request, BoundContactWindow(
            protocol="contact-model-continuation-v2",
            selection_fingerprint=request.selection_fingerprint,
            window=output.contact_model_window,
        )
