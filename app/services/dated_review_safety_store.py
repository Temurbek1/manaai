"""Family v19: dated source reviews share the existing specialist and chat lifecycle."""

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.child_safety import SafetyContextSnapshot, SafetyJob, SafetyJobView
from app.mana_ai.domain.source_reviews import SourceReviewWork
from app.services.dated_source_safety_store import (
    SqliteClosedDatedSourceSafetyStore,
    SqliteDatedSourceSafetyStore,
)


class SqliteDatedReviewSafetyStore(SqliteDatedSourceSafetyStore):
    _schema_version = 19

    def __init__(self, path: Path, *, dated_reviews_enabled: bool = False, **family: Any) -> None:
        self._dated_reviews_enabled = dated_reviews_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {18}

    def _admit_source_review(
        self, work: SourceReviewWork, now: datetime, allow_new: bool
    ) -> SafetyJobView:
        dated = any(s.requested_day is not None for s in work.bundle.snapshots)
        return super()._admit_source_review(
            work, now, allow_new and (self._dated_reviews_enabled or not dated)
        )

    async def claim_next(self, now: datetime) -> SafetyJob | None:
        if not self._dated_reviews_enabled:

            def stop() -> None:
                with self._transaction() as db:
                    db.execute(
                        "UPDATE child_safety_jobs SET "
                        "status='failed',reserved=0,error_code='dated_source_review_disabled',"
                        "updated_at=? WHERE status='queued' AND kind='source_review' "
                        "AND json_extract(context,'$.version')=4",
                        (self._utc(now).isoformat(),),
                    )

            await asyncio.to_thread(stop)
        return await super().claim_next(now)

    def _validate_safety_publication(
        self, connection: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> None:
        super()._validate_safety_publication(connection, row, now)
        if (
            row["kind"] == "source_review"
            and not self._dated_reviews_enabled
            and SafetyContextSnapshot.model_validate_json(row["context"]).version == 4
        ):
            raise ParentChatError("dated_source_review_disabled", 503)


class SqliteClosedDatedReviewSafetyStore(SqliteClosedDatedSourceSafetyStore):
    _schema_version = 19

    def _supported_versions(self) -> set[int]:
        return {19}
