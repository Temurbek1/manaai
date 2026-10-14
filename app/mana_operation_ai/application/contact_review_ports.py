from datetime import datetime
from typing import Protocol

from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.domain.contact_reviews import ContactReviewer, ContactReviewGrant
from app.mana_operation_ai.domain.retention_contact import RetentionContactAction


class ContactReviewStore(Protocol):
    async def by_action(self, action_id: str) -> ContactReviewGrant | None: ...

    async def by_id(self, review_id: str) -> ContactReviewGrant | None: ...

    async def create(self, grant: ContactReviewGrant) -> ContactReviewGrant: ...

    async def revoke(self, grant: ContactReviewGrant, *, at: datetime) -> ContactReviewGrant: ...

    async def pending(self, reviewer_id: str, *, now: datetime) -> list[ContactReviewGrant]: ...


class ContactReviewDirectory(Protocol):
    async def authorized_owner(self, owner: str) -> bool: ...

    async def eligible(self, actor: ActorContext, *, owner: bool = False) -> bool: ...

    async def reviewer(self, user_id: str) -> ContactReviewer | None: ...

    async def reviewers(self, owner: str) -> list[ContactReviewer]: ...


class RetentionContactReviewAccess(Protocol):
    async def owner_for_review(
        self, actor: ActorContext, action_id: str, *, now: datetime
    ) -> str | None: ...

    async def allowed(
        self, actor: ActorContext, action: RetentionContactAction, *, now: datetime
    ) -> bool: ...
