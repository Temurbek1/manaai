"""Family v27: only new captured observation jobs may reuse a settled remainder."""

import sqlite3
from pathlib import Path
from typing import Any

from app.services.trial_end_store import SqliteClosedTrialEndStore, SqliteTrialEndStore

_TABLES = {"safety_remainder_admissions"}


class SqliteSafetyRemainderStore(SqliteTrialEndStore):
    _schema_version = 27

    def __init__(
        self,
        path: Path,
        *,
        remainder_enabled: bool = False,
        **family: Any,
    ) -> None:
        self._remainder_enabled = remainder_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {26}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS safety_remainder_admissions(
          job_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,
          job_tokens INTEGER NOT NULL CHECK(job_tokens>=64 AND job_tokens<=100000));
        """
        )

    def _on_observation_job_admitted(
        self, connection: sqlite3.Connection, job_id: str, parent_id: str
    ) -> None:
        super()._on_observation_job_admitted(connection, job_id, parent_id)
        if not self._remainder_enabled:
            return
        row = connection.execute(
            "SELECT parent_id,kind FROM child_safety_jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        if (
            row is None
            or row["parent_id"] != parent_id
            or row["kind"] not in {"child_data", "source_review"}
        ):
            raise ValueError("Only the owning new observation job may capture remainder admission")
        connection.execute(
            "INSERT INTO safety_remainder_admissions VALUES(?,?,?)",
            (job_id, parent_id, self._safety_limits.job_tokens),
        )

    def _remaining_eligibility(self) -> str:
        native = super()._remaining_eligibility()
        if not self._remainder_enabled:
            return native
        return (
            "(" + native + ") OR (j.kind IN ('child_data','source_review') "
            "AND EXISTS(SELECT 1 FROM safety_remainder_admissions a "
            "WHERE a.job_id=j.job_id AND a.parent_id=j.parent_id AND a.job_tokens>=64))"
        )

    def _remaining_reserve(
        self, connection: sqlite3.Connection, row: sqlite3.Row, remaining: int, own: int
    ) -> int:
        reserve = super()._remaining_reserve(connection, row, remaining, own)
        capture = connection.execute(
            "SELECT job_tokens FROM safety_remainder_admissions WHERE job_id=? AND parent_id=?",
            (row["job_id"], row["parent_id"]),
        ).fetchone()
        return min(reserve, capture[0]) if capture is not None else reserve


class SqliteClosedSafetyRemainderStore(SqliteClosedTrialEndStore):
    _schema_version = 27

    def _supported_versions(self) -> set[int]:
        return {27}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
