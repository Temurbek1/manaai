"""Explicit post-human native continuation; no domain write or source execution."""

import asyncio
from datetime import UTC, datetime

from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.chat_ports import (
    ChatError,
    ChatRepository,
    ContactContinuationModel,
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
    ContactContinueRequest,
    ContactPreparationResult,
    verify_window_request,
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
    ) -> None:
        self._chats, self._contacts, self._model = chats, contacts, model
        self._context, self._enabled = context, enabled

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
        action = await self._contacts._bound(actor, topic_id, turn_id, request.action_id)
        if (action.fingerprint, action.revision) != (request.action_fingerprint, request.revision):
            raise ChatError("Состояние действия изменилось; обновите его перед продолжением.")
        if (action.message.template, action.request.parameters.account_ref) != (
            selection.template,
            self._contacts._account_refs[selection.recipient],
        ):
            raise ChatError("Результат не соответствует выбранным параметрам инструмента.")
        try:
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
                output = await self._model.continue_contact(
                    window=bound.window,
                    result=result,
                    call_sha256=selection.provider_call_sha256,
                    owner=actor.actor_id,
                    memory=child.session_memory,
                )
            if (
                not output.answer.strip()
                or output.next_action != "none"
                or output.contact_selection is not None
                or output.contact_model_window is not None
                or output.contact_call_sha256 is not None
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
