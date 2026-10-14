"""A human review lane delegates to Retention; Goals retain read-only tools."""

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.chat_ports import ChatError, ChatRepository
from app.mana_operation_ai.application.retention.contact import RetentionContactService
from app.mana_operation_ai.application.retention.contact_ports import RetentionContactStore
from app.mana_operation_ai.domain.retention_contact import (
    RetentionContactAction,
    RetentionContactDecision,
    RetentionContactParameters,
    RetentionContactPrepare,
)
from app.mana_operation_ai.domain.workspace_retention_contacts import (
    SandboxRecipient,
    WorkspaceContactHistory,
    WorkspaceContactPage,
    WorkspaceContactPrepare,
    WorkspaceContactRecipient,
    WorkspaceContactReconcile,
    WorkspaceContactView,
)


class WorkspaceRetentionContacts:
    def __init__(
        self,
        *,
        chats: ChatRepository,
        contacts: RetentionContactService,
        store: RetentionContactStore,
        enabled: bool,
        allow_self_approval: bool,
        recipients: tuple[WorkspaceContactRecipient, WorkspaceContactRecipient],
        account_refs: dict[SandboxRecipient, str],
        peer_reviews_enabled: bool = False,
    ) -> None:
        if set(account_refs) != {item.key for item in recipients}:
            raise ValueError("Every fictional recipient requires an explicit server-owned binding")
        self._chats, self._contacts, self._store = chats, contacts, store
        self._enabled, self._allow_self_approval = enabled, allow_self_approval
        self._recipients, self._account_refs = recipients, dict(account_refs)
        self._peer_reviews_enabled = peer_reviews_enabled

    async def _access(self, owner: str, topic_id: str, turn_id: str) -> None:
        if not self._enabled:
            raise ChatError("Контактный sandbox в чате отключён.", 503)
        topic = await self._chats.topic(owner, topic_id)
        if topic.product != "mana" or topic.agent_id not in {
            "retention-agent",
            "operations-orchestrator",
        }:
            raise ChatError("Контактный sandbox доступен только в темах MANA Retention.", 403)
        turn = await self._chats.turn(owner, topic_id, turn_id)
        if (
            turn.execution_mode != "agent"
            or turn.status != "completed"
            or turn.next_action != "retention_contacts"
        ):
            raise ChatError("Это сообщение не запрашивало контактный sandbox.", 403)

    def view(
        self, action: RetentionContactAction, *, actor_id: str | None = None
    ) -> WorkspaceContactView:
        if action.turn_id is None:
            raise ChatError("Историческое действие не связано с этим сообщением.", 403)
        keys = [
            key
            for key, ref in self._account_refs.items()
            if ref == action.request.parameters.account_ref
        ]
        if len(keys) != 1:
            raise ChatError("Получатель не относится к контактному sandbox.", 403)
        return WorkspaceContactView(
            action_id=action.action_id,
            topic_id=action.topic_id,
            turn_id=action.turn_id,
            recipient=keys[0],
            message=action.message,
            fingerprint=action.fingerprint,
            expires_at=action.expires_at,
            status=action.status,
            revision=action.revision,
            result_code=action.result_code,
            policy_reasons=action.policy.reasons,
            self_approval_forbidden=(actor_id is None or actor_id == action.owner)
            and not self._allow_self_approval,
            decision_recorded=action.decision is not None,
        )

    async def page(self, owner: str, topic_id: str, turn_id: str) -> WorkspaceContactPage:
        await self._access(owner, topic_id, turn_id)
        actions = await self._store.list_for_turn(owner, topic_id, turn_id)
        turn = await self._chats.turn(owner, topic_id, turn_id)
        return WorkspaceContactPage(
            items=[self.view(item) for item in actions[:3]],
            recipients=self._recipients,
            more_omitted=len(actions) > 3,
            peer_reviews_enabled=self._peer_reviews_enabled,
            preparation_request=turn.contact_preparation,
        )

    async def history(
        self, owner: str, topic_id: str, *, before: datetime
    ) -> list[WorkspaceContactHistory]:
        if not self._enabled:
            return []
        topic = await self._chats.topic(owner, topic_id)
        if topic.product != "mana":
            return []
        return await self._store.history(owner, topic_id, before=before)

    async def prepare(
        self, actor: ActorContext, topic_id: str, turn_id: str, request: WorkspaceContactPrepare
    ) -> WorkspaceContactView:
        await self._access(actor.actor_id, topic_id, turn_id)
        turn = await self._chats.turn(actor.actor_id, topic_id, turn_id)
        selection = turn.contact_preparation
        if selection is not None:
            if (request.recipient, request.template, request.selection_fingerprint) != (
                selection.recipient,
                selection.template,
                selection.selection_fingerprint,
            ):
                raise ChatError("Подтверждение не соответствует выбранному агентом действию.", 409)
        elif request.selection_fingerprint is not None:
            raise ChatError("Это сообщение не содержит нативного выбора.", 409)
        recipient = next(item for item in self._recipients if item.key == request.recipient)
        action = await self._contacts.prepare(
            actor,
            topic_id,
            RetentionContactPrepare(
                request_id=uuid5(
                    NAMESPACE_URL, f"retention-chat:{topic_id}:{turn_id}:{request.request_id}"
                ),
                parameters=RetentionContactParameters(
                    account_ref=self._account_refs[recipient.key],
                    template=request.template,
                    language=recipient.language,
                ),
            ),
            turn_id=turn_id,
        )
        return self.view(action)

    async def _bound(
        self, actor: ActorContext, topic_id: str, turn_id: str, action_id: str
    ) -> RetentionContactAction:
        await self._access(actor.actor_id, topic_id, turn_id)
        action = await self._contacts.get(actor, action_id)
        if action.topic_id != topic_id or action.turn_id != turn_id:
            raise ChatError("Действие не найдено в этом сообщении.", 404)
        return action

    async def decide(
        self,
        actor: ActorContext,
        topic_id: str,
        turn_id: str,
        action_id: str,
        request: RetentionContactDecision,
    ) -> WorkspaceContactView:
        await self._bound(actor, topic_id, turn_id, action_id)
        return self.view(await self._contacts.decide(actor, action_id, request))

    async def reconcile(
        self,
        actor: ActorContext,
        topic_id: str,
        turn_id: str,
        action_id: str,
        request: WorkspaceContactReconcile,
    ) -> WorkspaceContactView:
        action = await self._bound(actor, topic_id, turn_id, action_id)
        if action.fingerprint != request.fingerprint:
            raise ChatError("Условия сохранённого действия изменились.")
        return self.view(await self._contacts.reconcile(actor, action_id))
