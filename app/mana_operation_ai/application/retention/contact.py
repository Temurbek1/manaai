"""Private approved sandbox contact; intent precedes dispatch, replay observes SQL only."""

from datetime import timedelta

from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.chat_ports import ChatError, ChatRepository
from app.mana_operation_ai.application.contact_review_ports import RetentionContactReviewAccess
from app.mana_operation_ai.application.ports import Clock, IdGenerator
from app.mana_operation_ai.application.retention.contact_policy import (
    contact_fingerprint,
    evaluate_contact,
)
from app.mana_operation_ai.application.retention.contact_ports import (
    RetentionContactControls,
    RetentionContactExecutor,
    RetentionContactStore,
)
from app.mana_operation_ai.application.retention.contact_templates import (
    contact_dispatch_fingerprint,
    contact_message,
)
from app.mana_operation_ai.domain.enums import UserRole
from app.mana_operation_ai.domain.manual_action_controls import (
    RETENTION_CONTACT_CONTROL_KEY,
    ManualActionControlDefinition,
)
from app.mana_operation_ai.domain.retention_contact import (
    ContactStatus,
    RetentionContactAction,
    RetentionContactDecision,
    RetentionContactDelivery,
    RetentionContactEvent,
    RetentionContactPrepare,
    RetentionContactTarget,
    contact_proposal_fingerprint,
)


class RetentionContactService:
    def __init__(
        self,
        *,
        store: RetentionContactStore,
        executor: RetentionContactExecutor,
        chats: ChatRepository,
        clock: Clock,
        ids: IdGenerator,
        enabled: bool,
        allow_self_approval: bool,
        controls: RetentionContactControls,
        global_kill_switch_default: bool,
        review_access: RetentionContactReviewAccess | None = None,
    ) -> None:
        if executor.provider_name != "fake_retention_contact":
            raise ValueError("Only the explicitly fictional contact executor is supported")
        self._store, self._executor, self._chats = store, executor, chats
        self._clock, self._ids = clock, ids
        self._enabled, self._allow_self_approval = enabled, allow_self_approval
        self._controls, self._global_kill_default = controls, global_kill_switch_default
        self._review_access = review_access

    def control_definition(self) -> ManualActionControlDefinition | None:
        return ManualActionControlDefinition() if self._enabled else None

    async def _execution_allowed(self) -> bool:
        for key, default in [
            ("global_kill_switch", self._global_kill_default),
            ("agent_kill_switch:retention-agent", False),
            (f"capability_kill_switch:retention-agent:{RETENTION_CONTACT_CONTROL_KEY}", False),
        ]:
            if await self._controls.get_control(key, default=default):
                return False
        return True

    async def _access(self, actor: ActorContext, topic_id: str) -> None:
        await self._topic_access(actor.actor_id, topic_id)

    async def _topic_access(self, owner: str, topic_id: str) -> None:
        if not self._enabled:
            raise ChatError("Контактный sandbox Retention отключён.", 503)
        topic = await self._chats.topic(owner, topic_id)
        if topic.product != "mana" or topic.agent_id not in {
            "retention-agent",
            "operations-orchestrator",
        }:
            raise ChatError("Для этой темы контактные действия не подключены.", 403)

    async def prepare(
        self,
        actor: ActorContext,
        topic_id: str,
        request: RetentionContactPrepare,
        *,
        turn_id: str | None = None,
    ) -> RetentionContactAction:
        await self._access(actor, topic_id)
        if actor.role not in {UserRole.OPERATOR, UserRole.APPROVER, UserRole.ADMIN}:
            raise ChatError("Нужны права оператора.", 403)
        existing = await self._store.by_request(actor.actor_id, str(request.request_id))
        if existing is not None:
            if (
                existing.topic_id != topic_id
                or existing.request != request
                or existing.turn_id != turn_id
            ):
                raise ChatError("Этот запрос уже связан с другим предложением.")
            return existing
        if not await self._execution_allowed():
            raise ChatError("Контактные действия Retention остановлены.", 423)
        target = await self._target(request.parameters.account_ref)
        policy = evaluate_contact(request.parameters, target, now=self._clock.now())
        if not await self._execution_allowed():
            policy.eligible_for_review = False
            policy.reasons.append("kill_switch_active")
        now = self._clock.now()
        target_hash = contact_fingerprint(target)
        action_id = self._ids.new()
        expires = min(now + timedelta(hours=1), target.consent_expires_at)
        # A refused proposal is an audit artifact, never an executable expired grant.
        if expires <= now:
            expires = now + timedelta(seconds=1)
        message = contact_message(request.parameters)
        fingerprint = contact_proposal_fingerprint(
            action_id=action_id,
            owner=actor.actor_id,
            topic_id=topic_id,
            request=request,
            message=message,
            target_sha256=target_hash,
            policy=policy,
            prepared_at=now,
            expires_at=expires,
            turn_id=turn_id,
        )
        return await self._store.create(
            RetentionContactAction(
                version=2 if turn_id is not None else 1,
                action_id=action_id,
                owner=actor.actor_id,
                topic_id=topic_id,
                turn_id=turn_id,
                request=request,
                message=message,
                fingerprint=fingerprint,
                target_sha256=target_hash,
                policy=policy,
                prepared_at=now,
                expires_at=expires,
                status="proposed" if policy.eligible_for_review else "refused",
                result_code="awaiting_human_decision"
                if policy.eligible_for_review
                else "policy_denied",
            )
        )

    async def get(self, actor: ActorContext, action_id: str) -> RetentionContactAction:
        if not self._enabled:
            raise ChatError("Контактный sandbox Retention отключён.", 503)
        try:
            action = await self._store.get(actor.actor_id, action_id)
        except ChatError as exc:
            if exc.status != 404 or self._review_access is None:
                raise
            owner = await self._review_access.owner_for_review(
                actor, action_id, now=self._clock.now()
            )
            if owner is None:
                raise ChatError("Действие не найдено.", 404) from None
            action = await self._store.get(owner, action_id)
            if not await self._review_access.allowed(actor, action, now=self._clock.now()):
                raise ChatError("Доступ к согласованию отозван или истёк.", 403) from None
        # Validate the original owner's topic; this does not share its transcript.
        await self._topic_access(action.owner, action.topic_id)
        return action

    async def decide(
        self,
        actor: ActorContext,
        action_id: str,
        decision: RetentionContactDecision,
    ) -> RetentionContactAction:
        action = await self.get(actor, action_id)
        if actor.role not in {UserRole.APPROVER, UserRole.ADMIN}:
            raise ChatError("Нужны права согласования.", 403)
        if action.decision is not None:
            if action.decision != decision or action.decided_by != actor.actor_id:
                raise ChatError("Решение уже сохранено. Повторное выполнение запрещено.")
            return action
        if action.status != "proposed" or decision.fingerprint != action.fingerprint:
            raise ChatError("Предложение изменилось или недоступно для согласования.")
        if decision.approve and actor.actor_id == action.owner and not self._allow_self_approval:
            raise ChatError("Согласование собственного предложения отключено.", 403)
        if self._clock.now() >= action.expires_at:
            return await self._finish(action, "refused", "proposal_expired")
        updated = RetentionContactAction.model_validate(
            {
                **action.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
                "decided_by": actor.actor_id,
                "revision": action.revision + 1,
                "status": "dispatching" if decision.approve else "rejected",
                "result_code": "intent_admitted" if decision.approve else "human_rejected",
            }
        )
        if not await self._store.transition(action, updated, self._event(updated)):
            return await self._store.get(action.owner, action_id)
        if not decision.approve:
            return updated
        if not await self._execution_allowed():
            return await self._finish(updated, "refused", "fresh_state_denied")
        # Durable recipient reservation and the exact human intent already exist.
        try:
            current = await self._target(action.request.parameters.account_ref)
        except Exception:
            return await self._finish(updated, "refused", "fresh_state_unavailable")
        if (
            self._clock.now() >= action.expires_at
            or not await self._execution_allowed()
            or (
                actor.actor_id != action.owner
                and (
                    self._review_access is None
                    or not await self._review_access.allowed(actor, action, now=self._clock.now())
                )
            )
            or contact_fingerprint(current) != action.target_sha256
            or not evaluate_contact(
                action.request.parameters,
                current,
                now=self._clock.now(),
            ).eligible_for_review
        ):
            return await self._finish(updated, "refused", "fresh_state_denied")
        try:
            await self._executor.send(
                action_id=action_id,
                parameters=action.request.parameters,
                message=action.message,
                expected_target_sha256=action.target_sha256,
                valid_until=action.expires_at,
            )
        except Exception:
            # A lost response can be verified by its exact receipt, never by resending.
            return await self._verify(updated)
        return await self._verify(updated)

    async def reconcile(self, actor: ActorContext, action_id: str) -> RetentionContactAction:
        action = await self.get(actor, action_id)
        if actor.role not in {UserRole.APPROVER, UserRole.ADMIN}:
            raise ChatError("Нужны права согласования.", 403)
        if action.status not in {"dispatching", "uncertain"}:
            return action
        return await self._verify(action)

    async def _verify(self, action: RetentionContactAction) -> RetentionContactAction:
        try:
            receipt = await self._executor.receipt(action.action_id)
            if receipt is not None:
                receipt = RetentionContactDelivery.model_validate(receipt.model_dump(mode="json"))
            matched = bool(
                receipt is not None
                and receipt.action_id == action.action_id
                and receipt.parameters_sha256
                == contact_dispatch_fingerprint(action.request.parameters, action.message)
                and action.prepared_at <= receipt.accepted_at <= self._clock.now()
                and receipt.accepted_at < action.expires_at
            )
        except Exception:
            receipt, matched = None, False
        if matched:
            return await self._finish(action, "verified", "sandbox_acceptance_verified", receipt)
        if action.status == "uncertain":
            return action
        return await self._finish(action, "uncertain", "delivery_outcome_unknown")

    async def _target(self, account_ref: str) -> RetentionContactTarget:
        value = await self._executor.target(account_ref)
        return RetentionContactTarget.model_validate(value.model_dump(mode="json"))

    def _event(self, action: RetentionContactAction) -> RetentionContactEvent:
        return RetentionContactEvent(
            action_id=action.action_id,
            revision=action.revision,
            at=self._clock.now(),
            status=action.status,
            code=action.result_code,
        )

    async def _finish(
        self,
        action: RetentionContactAction,
        status: ContactStatus,
        code: str,
        delivery: RetentionContactDelivery | None = None,
    ) -> RetentionContactAction:
        updated = RetentionContactAction.model_validate(
            {
                **action.model_dump(mode="json"),
                "status": status,
                "result_code": code,
                "revision": action.revision + 1,
                "delivery": delivery.model_dump(mode="json") if delivery is not None else None,
            }
        )
        if await self._store.transition(action, updated, self._event(updated)):
            return updated
        return await self._store.get(action.owner, action.action_id)
