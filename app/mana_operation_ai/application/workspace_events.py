"""Reading notifications never starts, resumes or retries an agent task."""

import asyncio
from time import monotonic
from typing import Protocol
from uuid import uuid4

from app.mana_operation_ai.application.chat_ports import ChatError
from app.mana_operation_ai.domain.workspace_events import (
    WorkspaceEventPage,
    WorkspaceNotificationPage,
)


class WorkspaceEventRepository(Protocol):
    async def page(self, owner: str, topic_id: str, after: int) -> WorkspaceEventPage: ...
    async def notifications(
        self, owner: str, topic_id: str, after: int
    ) -> WorkspaceNotificationPage: ...


class WorkspaceEventService:
    def __init__(
        self, repository: WorkspaceEventRepository, *, enabled: bool, max_connections: int = 32
    ) -> None:
        self._repository = repository
        self.enabled = enabled
        self._max_connections = max_connections
        self._connections: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, owner: str, seconds: float) -> str:
        async with self._lock:
            now = monotonic()
            self._connections = {
                key: value for key, value in self._connections.items() if value[1] > now
            }
            if (
                len(self._connections) >= self._max_connections
                or sum(value[0] == owner for value in self._connections.values()) >= 3
            ):
                raise ChatError(
                    "Слишком много подключений к прогрессу. Закройте лишние вкладки.", 429
                )
            lease = str(uuid4())
            self._connections[lease] = (owner, now + seconds + 5)
            return lease

    async def release(self, lease: str) -> None:
        async with self._lock:
            self._connections.pop(lease, None)

    async def page(self, owner: str, topic_id: str, after: int = 0) -> WorkspaceEventPage:
        if not self.enabled:
            raise ChatError("Поток рабочего прогресса пока отключён.", 404)
        return await self._repository.page(owner, topic_id, after)

    async def notifications(
        self, owner: str, topic_id: str, after: int = 0
    ) -> WorkspaceNotificationPage:
        if not self.enabled:
            raise ChatError("Поток рабочего прогресса пока отключён.", 404)
        return await self._repository.notifications(owner, topic_id, after)
