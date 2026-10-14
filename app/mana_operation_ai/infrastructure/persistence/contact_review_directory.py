from sqlalchemy import select

from app.mana_operation_ai.application.admin_service import ActorContext
from app.mana_operation_ai.application.auth_ports import AdminAuthRepository
from app.mana_operation_ai.domain.auth import AdminUser
from app.mana_operation_ai.domain.contact_reviews import ContactReviewer
from app.mana_operation_ai.domain.enums import AdminUserStatus, UserRole
from app.mana_operation_ai.infrastructure.persistence.database import OperationDatabase
from app.mana_operation_ai.infrastructure.persistence.models import AdminUserRow


class AdminContactReviewDirectory:
    def __init__(self, users: AdminAuthRepository, database: OperationDatabase) -> None:
        self._users = users
        self._sessions = database.session_factory

    @staticmethod
    def _reviewer(user: AdminUser) -> bool:
        return user.status == AdminUserStatus.ACTIVE and user.role in {
            UserRole.ADMIN,
            UserRole.APPROVER,
        }

    @staticmethod
    def _view(user: AdminUser) -> ContactReviewer:
        return ContactReviewer(user_id=user.user_id, label=user.display_name or user.user_id)

    async def eligible(self, actor: ActorContext, *, owner: bool = False) -> bool:
        user = await self._users.get_user(actor.actor_id)
        roles = (
            {UserRole.OPERATOR, UserRole.APPROVER, UserRole.ADMIN}
            if owner
            else {UserRole.APPROVER, UserRole.ADMIN}
        )
        return bool(
            user
            and user.status == AdminUserStatus.ACTIVE
            and user.role == actor.role
            and user.role in roles
        )

    async def authorized_owner(self, owner: str) -> bool:
        user = await self._users.get_user(owner)
        return bool(
            user
            and user.status == AdminUserStatus.ACTIVE
            and user.role in {UserRole.OPERATOR, UserRole.APPROVER, UserRole.ADMIN}
        )

    async def reviewer(self, user_id: str) -> ContactReviewer | None:
        user = await self._users.get_user(user_id)
        return self._view(user) if user and self._reviewer(user) else None

    async def reviewers(self, owner: str) -> list[ContactReviewer]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AdminUserRow)
                .where(
                    AdminUserRow.user_id != owner,
                    AdminUserRow.status == "active",
                    AdminUserRow.role.in_(("approver", "admin")),
                )
                .order_by(AdminUserRow.user_id)
                .limit(21)
            )
            return [self._view(AdminUser.model_validate(row.payload)) for row in rows]
