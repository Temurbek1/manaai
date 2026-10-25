"""Family v18 captures dated reads only on newly admitted eligible turns."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ParentChatRequest
from app.services.retention_expiry_store import (
    SqliteClosedRetentionExpiryStore,
    SqliteRetentionExpiryStore,
)


class SqliteDatedSourceSafetyStore(SqliteRetentionExpiryStore):
    _schema_version = 18
    _source_contract = 3

    def __init__(self, path: Path, *, day_tools_enabled: bool = False, **family: Any) -> None:
        self._day_tools_enabled = day_tools_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {17}

    def _on_admitted(
        self,
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        now: datetime,
    ) -> None:
        super()._on_admitted(connection, request, turn_id, now)
        if not self._day_tools_enabled:
            connection.execute(
                "UPDATE source_tool_turns SET profile=? WHERE parent_id=? AND turn_id=? AND "
                "profile=?",
                (self._observation_native_policy, request.parent_id, turn_id, self._native_policy),
            )

    def _captured_protocol(self, payload: str) -> int:
        result = super()._captured_protocol(payload)
        if result == 3 and not self._day_tools_enabled:
            raise ParentChatError("family_day_usage_not_enabled", 503)
        return result


class SqliteClosedDatedSourceSafetyStore(SqliteClosedRetentionExpiryStore):
    _schema_version = 18

    def _supported_versions(self) -> set[int]:
        return {18}
