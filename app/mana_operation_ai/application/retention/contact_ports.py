from datetime import datetime
from typing import Protocol

from app.mana_operation_ai.domain.contact_admission import (
    ContactPreparationBinding,
    ContactPreparationClaim,
    ContactPreparationLimits,
)
from app.mana_operation_ai.domain.models import AgentDefinition
from app.mana_operation_ai.domain.retention_contact import (
    RetentionContactAction,
    RetentionContactDelivery,
    RetentionContactEvent,
    RetentionContactMessage,
    RetentionContactParameters,
    RetentionContactTarget,
)
from app.mana_operation_ai.domain.workspace_retention_contacts import WorkspaceContactHistory


class RetentionContactStore(Protocol):
    async def history(
        self, owner: str, topic_id: str, *, before: datetime
    ) -> list[WorkspaceContactHistory]: ...

    async def list_for_turn(
        self, owner: str, topic_id: str, turn_id: str
    ) -> list[RetentionContactAction]: ...

    async def by_request(self, owner: str, request_id: str) -> RetentionContactAction | None: ...

    async def get(self, owner: str, action_id: str) -> RetentionContactAction: ...

    async def admit_preparation(
        self, binding: ContactPreparationBinding, *, limits: ContactPreparationLimits, now: datetime
    ) -> ContactPreparationClaim | None: ...

    async def preparation_pending(self, owner: str, topic_id: str, turn_id: str) -> bool: ...

    async def preparation_request_pending(self, owner: str, request_id: str) -> bool: ...

    async def create(
        self, action: RetentionContactAction, *, preparation: ContactPreparationClaim | None = None
    ) -> RetentionContactAction: ...

    async def transition(
        self,
        previous: RetentionContactAction,
        updated: RetentionContactAction,
        event: RetentionContactEvent,
    ) -> bool: ...


class RetentionContactControls(Protocol):
    async def get_control(self, key: str, *, default: bool = False) -> bool: ...

    async def get_agent(self, agent_id: str) -> AgentDefinition | None: ...


class RetentionContactHistoryReader(Protocol):
    async def history(
        self, owner: str, topic_id: str, *, before: datetime
    ) -> list[WorkspaceContactHistory]: ...


class RetentionContactExecutor(Protocol):
    @property
    def provider_name(self) -> str: ...

    async def target(self, account_ref: str) -> RetentionContactTarget: ...

    async def send(
        self,
        *,
        action_id: str,
        parameters: RetentionContactParameters,
        message: RetentionContactMessage,
        expected_target_sha256: str,
        valid_until: datetime,
    ) -> RetentionContactDelivery: ...

    async def receipt(self, action_id: str) -> RetentionContactDelivery | None: ...
