"""Explicit closed readers: retain newer history without downgrading its schema."""

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ParentChatRequest
from app.services.child_safety_store import SqliteChildSafetyStore
from app.services.family_agent_store import SqliteFamilyAgentStore
from app.services.touch_evidence_store import SqliteTouchEvidenceStore


async def family_storage_version(path: Path) -> int:
    def read() -> int:
        if path.is_symlink():
            raise RuntimeError("Family storage must not be a symbolic link")
        if not path.exists():
            return 0
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    return await asyncio.to_thread(read)


class SqliteClosedSafetyBrokerStore(SqliteTouchEvidenceStore):
    """V5 observation/Parent-Touch only. No safety job admission, budget or worker."""

    def _supported_versions(self) -> set[int]:
        return {5}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | set(SqliteChildSafetyStore.child_tables)

    def _extra_schema(self) -> str:
        return ""  # Existing schema only; no migration/recapture when disabling analysis.


class SqliteFamilyCompatibilityStore(SqliteFamilyAgentStore):
    """V2–v5 history-only, or the older v4 broker when safety execution is closed."""

    def __init__(
        self,
        path: Path,
        *,
        version: int,
        history_only: bool,
        daily_limit: int,
        timezone: str,
        max_attempts: int = 20,
        question_limit: int = 100,
    ) -> None:
        if version not in {2, 3, 4, 5}:
            raise ValueError("Unsupported closed family reader version")
        super().__init__(
            path,
            daily_limit=daily_limit,
            timezone=timezone,
            max_attempts=max_attempts,
            question_limit=question_limit,
        )
        self._schema_version = version
        self._history_only = history_only

    def _supported_versions(self) -> set[int]:
        return {self._schema_version}

    def _allowed_tables(self) -> set[str]:
        return (
            super()._allowed_tables()
            | set(SqliteChildSafetyStore.child_tables)
            | set(SqliteTouchEvidenceStore.evidence_tables)
        )

    def _extra_schema(self) -> str:
        return ""

    def _on_admitted(
        self,
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        now: datetime,
    ) -> None:
        if self._history_only:
            raise ParentChatError("family_runtime_disabled", 503)
        super()._on_admitted(connection, request, turn_id, now)
