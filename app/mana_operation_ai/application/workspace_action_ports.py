from datetime import datetime
from typing import Protocol

from app.mana_operation_ai.domain.workspace_actions import (
    WorkspaceActionHistory,
    WorkspaceActionReceipt,
)


class WorkspaceActionStore(Protocol):
    async def get(
        self, owner: str, topic_id: str, turn_id: str, proposal_id: str
    ) -> WorkspaceActionReceipt | None: ...

    async def admit(
        self, owner: str, receipt: WorkspaceActionReceipt
    ) -> tuple[WorkspaceActionReceipt, bool]: ...

    async def finish(self, owner: str, receipt: WorkspaceActionReceipt) -> None: ...

    async def receipts(
        self,
        owner: str,
        topic_id: str,
        *,
        turn_id: str | None = None,
        before: datetime | None = None,
        limit: int = 3,
    ) -> list[WorkspaceActionReceipt]: ...


class WorkspaceActionHistoryReader(Protocol):
    async def history(
        self, owner: str, topic_id: str, *, before: datetime
    ) -> list[WorkspaceActionHistory]: ...
