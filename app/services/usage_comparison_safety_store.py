"""Family v30: only newly captured adjacent-day source reviews gain comparison context."""

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.child_safety import SafetyJob
from app.mana_ai.domain.source_reviews import CounterComparisonView, counter_comparison_view
from app.services.parent_clarification_store import (
    SqliteClosedParentClarificationStore,
    SqliteParentClarificationStore,
)

_TABLE = "usage_comparison_jobs"


class SqliteUsageComparisonSafetyStore(SqliteParentClarificationStore):
    _schema_version = 30

    def __init__(self, path: Path, *, comparisons_enabled: bool = False, **family: Any) -> None:
        self._comparisons_enabled = comparisons_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {29}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}

    def _extra_schema(self) -> str:
        return super()._extra_schema() + (
            "CREATE TABLE IF NOT EXISTS usage_comparison_jobs("
            "job_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL);"
        )

    def _allow_usage_comparison(self) -> bool:
        return self._comparisons_enabled

    def _notice_counter_comparison(self, job: SafetyJob) -> CounterComparisonView | None:
        bundle = job.context.source_review
        return counter_comparison_view(bundle) if bundle is not None else None

    def _on_observation_job_admitted(
        self, db: sqlite3.Connection, identity: str, parent: str
    ) -> None:
        super()._on_observation_job_admitted(db, identity, parent)
        captured = db.execute(
            "SELECT 1 FROM child_safety_jobs WHERE job_id=? AND parent_id=? "
            "AND json_type(context,'$.source_review.usage_comparison') IS NOT NULL",
            (identity, parent),
        ).fetchone()
        if captured:
            if not self._comparisons_enabled:
                raise ParentChatError("usage_comparisons_disabled", 503)
            db.execute("INSERT INTO usage_comparison_jobs VALUES(?,?)", (identity, parent))

    async def claim_next(self, now: datetime) -> SafetyJob | None:
        if not self._comparisons_enabled:

            def stop() -> None:
                with self._transaction() as db:
                    db.execute(
                        "UPDATE child_safety_jobs SET status='failed',reserved=0,"
                        "error_code='usage_comparisons_disabled',updated_at=? "
                        "WHERE status='queued' "
                        "AND job_id IN (SELECT job_id FROM usage_comparison_jobs)",
                        (self._utc(now).isoformat(),),
                    )

            await asyncio.to_thread(stop)
        return await super().claim_next(now)

    def _validate_safety_publication(
        self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> None:
        super()._validate_safety_publication(db, row, now)
        if (
            not self._comparisons_enabled
            and db.execute(
                "SELECT 1 FROM usage_comparison_jobs WHERE job_id=? AND parent_id=?",
                (row["job_id"], row["parent_id"]),
            ).fetchone()
        ):
            raise ParentChatError("usage_comparisons_disabled", 503)


class SqliteClosedUsageComparisonSafetyStore(SqliteClosedParentClarificationStore):
    _schema_version = 30

    def _supported_versions(self) -> set[int]:
        return {30}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}
