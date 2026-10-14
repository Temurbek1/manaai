"""Human-selected single-action disclosure; never a model grant or topic membership."""

from datetime import datetime

from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.application.contact_review_ports import (
    ContactReviewDirectory,
    ContactReviewStore,
)
from app.mana_operation_ai.application.ports import Clock, IdGenerator
from app.mana_operation_ai.application.retention.contact import RetentionContactService
from app.mana_operation_ai.application.workspace_retention_contacts import (
    WorkspaceRetentionContacts,
)
from app.mana_operation_ai.domain.contact_reviews import (
    ContactReviewCreate,
    ContactReviewer,
    ContactReviewGrant,
    ContactReviewItem,
    ContactReviewOptions,
    ContactReviewPage,
    ContactReviewReceipt,
)
from app.mana_operation_ai.domain.retention_contact import (
    RetentionContactAction,
    RetentionContactDecision,
)
from app.mana_operation_ai.domain.workspace_retention_contacts import (
    WorkspaceContactReconcile,
    WorkspaceContactView,
)


class ContactReviewAccess:
    def __init__(
        self, store: ContactReviewStore, directory: ContactReviewDirectory, *, enabled: bool
    ) -> None:
        self.store, self.directory, self.enabled = store, directory, enabled

    async def owner_for_review(
        self, actor: ActorContext, action_id: str, *, now: datetime
    ) -> str | None:
        if not self.enabled or not await self.directory.eligible(actor):
            return None
        grant = await self.store.by_action(action_id)
        if (
            not grant
            or str(grant.request.reviewer_id) != actor.actor_id
            or grant.revoked_at
            or now >= grant.expires_at
            or not await self.directory.authorized_owner(grant.owner)
        ):
            return None
        return grant.owner

    async def allowed(
        self, actor: ActorContext, action: RetentionContactAction, *, now: datetime
    ) -> bool:
        if not self.enabled or not await self.directory.eligible(actor):
            return False
        grant = await self.store.by_action(action.action_id)
        return bool(
            grant
            and grant.matches(action)
            and str(grant.request.reviewer_id) == actor.actor_id
            and grant.revoked_at is None
            and now < grant.expires_at
            and await self.directory.authorized_owner(grant.owner)
        )


class WorkspaceContactReviews:
    def __init__(
        self,
        *,
        access: ContactReviewAccess,
        contacts: RetentionContactService,
        workspace: WorkspaceRetentionContacts,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._access, self._contacts, self._workspace, self._clock, self._ids = (
            access,
            contacts,
            workspace,
            clock,
            ids,
        )

    async def _identity(self, actor: ActorContext, *, owner: bool = False) -> None:
        if not self._access.enabled:
            raise ChatError("Согласование другим сотрудником отключено.", 503)
        if not await self._access.directory.eligible(actor, owner=owner):
            raise ChatError("Нужна действующая учётная запись с правом согласования.", 403)

    async def _owned(
        self, actor: ActorContext, topic: str, turn: str, action_id: str
    ) -> RetentionContactAction:
        await self._identity(actor, owner=True)
        return await self._workspace._bound(actor, topic, turn, action_id)

    async def _receipt(self, grant: ContactReviewGrant) -> ContactReviewReceipt:
        reviewer = await self._access.directory.reviewer(str(grant.request.reviewer_id))
        return ContactReviewReceipt(
            review_id=grant.review_id,
            reviewer=reviewer
            or ContactReviewer(
                user_id=str(grant.request.reviewer_id), label="Сотрудник недоступен"
            ),
            expires_at=grant.expires_at,
            revoked=grant.revoked_at is not None,
        )

    async def options(
        self, actor: ActorContext, topic: str, turn: str, action_id: str
    ) -> ContactReviewOptions:
        action = await self._owned(actor, topic, turn, action_id)
        grant = await self._access.store.by_action(action.action_id)
        if grant and not grant.matches(action):
            raise ChatError("Согласование требует проверки исходного действия.", 503)
        reviewers = await self._access.directory.reviewers(actor.actor_id)
        return ContactReviewOptions(
            reviewers=reviewers[:20],
            more_omitted=len(reviewers) > 20,
            review=await self._receipt(grant) if grant else None,
        )

    async def share(
        self,
        actor: ActorContext,
        topic: str,
        turn: str,
        action_id: str,
        request: ContactReviewCreate,
    ) -> ContactReviewReceipt:
        action = await self._owned(actor, topic, turn, action_id)
        previous = await self._access.store.by_action(action_id)
        if previous:
            if (
                previous.owner != actor.actor_id
                or previous.request != request
                or not previous.matches(action)
            ):
                raise ChatError("Для действия уже сохранено другое согласование.", 409)
            return await self._receipt(previous)
        if str(request.reviewer_id) == actor.actor_id or not await self._access.directory.reviewer(
            str(request.reviewer_id)
        ):
            raise ChatError("Выберите другого действующего согласующего сотрудника.", 403)
        if (
            action.status != "proposed"
            or action.decision is not None
            or action.turn_id is None
            or action.fingerprint != request.fingerprint
            or self._clock.now() >= action.expires_at
        ):
            raise ChatError("Предложение изменилось или срок истёк.", 409)
        grant = await self._access.store.create(
            ContactReviewGrant(
                review_id=self._ids.new(),
                owner=actor.actor_id,
                action_id=action_id,
                topic_id=topic,
                turn_id=turn,
                request=request,
                created_at=self._clock.now(),
                expires_at=action.expires_at,
            )
        )
        return await self._receipt(grant)

    async def revoke(
        self,
        actor: ActorContext,
        topic: str,
        turn: str,
        action_id: str,
        request: WorkspaceContactReconcile,
    ) -> ContactReviewReceipt:
        action = await self._owned(actor, topic, turn, action_id)
        grant = await self._access.store.by_action(action_id)
        if not grant or not grant.matches(action) or request.fingerprint != action.fingerprint:
            raise ChatError("Согласование не найдено или изменилось.", 404)
        return await self._receipt(await self._access.store.revoke(grant, at=self._clock.now()))

    async def item(self, actor: ActorContext, review_id: str) -> ContactReviewItem:
        await self._identity(actor)
        grant = await self._access.store.by_id(review_id)
        if not grant or str(grant.request.reviewer_id) != actor.actor_id:
            raise ChatError("Согласование не найдено.", 404)
        action = await self._contacts.get(actor, grant.action_id)
        return ContactReviewItem(
            review_id=review_id, action=self._workspace.view(action, actor_id=actor.actor_id)
        )

    async def page(self, actor: ActorContext) -> ContactReviewPage:
        await self._identity(actor)
        grants = await self._access.store.pending(actor.actor_id, now=self._clock.now())
        return ContactReviewPage(
            items=[await self.item(actor, grant.review_id) for grant in grants[:20]],
            more_omitted=len(grants) > 20,
        )

    async def decide(
        self, actor: ActorContext, review_id: str, action_id: str, request: RetentionContactDecision
    ) -> WorkspaceContactView:
        item = await self.item(actor, review_id)
        if item.action.action_id != action_id:
            raise ChatError("Действие не относится к этому согласованию.", 404)
        action = await self._contacts.decide(actor, action_id, request)
        return self._workspace.view(action, actor_id=actor.actor_id)

    async def reconcile(
        self,
        actor: ActorContext,
        review_id: str,
        action_id: str,
        request: WorkspaceContactReconcile,
    ) -> WorkspaceContactView:
        item = await self.item(actor, review_id)
        if item.action.action_id != action_id or item.action.fingerprint != request.fingerprint:
            raise ChatError("Действие не относится к этому согласованию.", 404)
        return self._workspace.view(
            await self._contacts.reconcile(actor, action_id), actor_id=actor.actor_id
        )
