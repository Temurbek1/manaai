"""Family v37: explicitly captured two-point reviews remain read-only and stoppable."""

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.child_location import LocationComparisonView
from app.mana_ai.domain.child_safety import SafetyJob
from app.mana_ai.domain.family_agents import FamilyQuestion, ParentTouchDeliveryRequest
from app.mana_ai.domain.source_reviews import location_comparison_view
from app.services.compact_parent_publication_store import (
    SqliteClosedCompactParentPublicationStore,
    SqliteCompactParentPublicationStore,
)

_TABLE = "location_comparison_jobs"


class SqliteLocationComparisonSafetyStore(SqliteCompactParentPublicationStore):
    _schema_version = 37

    def __init__(
        self, path: Path, *, location_comparisons_enabled: bool = False, **family: Any
    ) -> None:
        self._location_comparisons_enabled = location_comparisons_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {36}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}

    def _extra_schema(self) -> str:
        return super()._extra_schema() + (
            "CREATE TABLE IF NOT EXISTS location_comparison_jobs("
            "job_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL);"
        )

    def _allow_location_comparison(self) -> bool:
        return self._location_comparisons_enabled

    def _notice_location_comparison(self, job: SafetyJob) -> LocationComparisonView | None:
        bundle = job.context.source_review
        return location_comparison_view(bundle) if bundle is not None else None

    def _on_observation_job_admitted(
        self, db: sqlite3.Connection, identity: str, parent: str
    ) -> None:
        super()._on_observation_job_admitted(db, identity, parent)
        captured = db.execute(
            "SELECT 1 FROM child_safety_jobs WHERE job_id=? AND parent_id=? "
            "AND json_type(context,'$.source_review.location_comparison') IS NOT NULL",
            (identity, parent),
        ).fetchone()
        if captured:
            if not self._location_comparisons_enabled:
                raise ParentChatError("location_comparisons_disabled", 503)
            db.execute("INSERT INTO location_comparison_jobs VALUES(?,?)", (identity, parent))

    def _check_job(self, db: sqlite3.Connection, row: sqlite3.Row) -> None:
        if (
            not self._location_comparisons_enabled
            and db.execute(
                "SELECT 1 FROM location_comparison_jobs WHERE job_id=? AND parent_id=?",
                (row["job_id"], row["parent_id"]),
            ).fetchone()
        ):
            raise ParentChatError("location_comparisons_disabled", 503)

    def _validate_safety_submission(
        self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> None:
        super()._validate_safety_submission(db, row, now)
        self._check_job(db, row)

    def _validate_safety_publication(
        self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> None:
        super()._validate_safety_publication(db, row, now)
        self._check_job(db, row)

    async def claim_next(self, now: datetime) -> SafetyJob | None:
        if not self._location_comparisons_enabled:

            def stop() -> None:
                with self._transaction() as db:
                    db.execute(
                        "UPDATE child_safety_jobs SET status='failed',reserved=0,"
                        "error_code='location_comparisons_disabled',updated_at=? "
                        "WHERE status='queued' "
                        "AND job_id IN (SELECT job_id FROM location_comparison_jobs)",
                        (self._utc(now).isoformat(),),
                    )

            await asyncio.to_thread(stop)
        return await super().claim_next(now)

    def _suppress_comparison_notices(self, db: sqlite3.Connection) -> None:
        if not self._location_comparisons_enabled:
            db.execute(
                "UPDATE family_notices SET status='cancelled' "
                "WHERE status IN ('queued','deferred') "
                "AND json_type(payload,'$.location_comparison') IS NOT NULL"
            )

    def _admit_extra_context(
        self,
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        selected: FamilyQuestion | None,
        now: datetime,
    ) -> str | None:
        self._suppress_comparison_notices(connection)
        return super()._admit_extra_context(connection, request, turn_id, selected, now)

    async def next_delivery(self, now: datetime) -> ParentTouchDeliveryRequest | None:
        if not self._location_comparisons_enabled:

            def stop() -> None:
                with self._transaction() as db:
                    self._suppress_comparison_notices(db)

            await asyncio.to_thread(stop)
        return await super().next_delivery(now)

    def _turn_has_comparison(self, db: sqlite3.Connection, turn: StoredChatTurn) -> bool:
        return (
            db.execute(
                "SELECT 1 FROM family_touch_evidence WHERE parent_id=? AND turn_id=? "
                "AND json_type(payload,'$.notice.location_comparison') IS NOT NULL",
                (turn.parent_id, turn.turn_id),
            ).fetchone()
            is not None
        )

    def _validate_chat_submission(
        self, db: sqlite3.Connection, turn: StoredChatTurn, now: datetime
    ) -> None:
        super()._validate_chat_submission(db, turn, now)
        if not self._location_comparisons_enabled and self._turn_has_comparison(db, turn):
            raise ParentChatError("location_comparisons_disabled", 503)

    def _valid_decision(
        self,
        connection: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        now: datetime,
    ) -> bool:
        return not (
            not self._location_comparisons_enabled and self._turn_has_comparison(connection, turn)
        ) and super()._valid_decision(connection, turn, receipt, now)

    def _push_delivery_ready(
        self, connection: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> bool:
        if (
            not self._location_comparisons_enabled
            and connection.execute(
                "SELECT 1 FROM family_notices WHERE parent_id=? AND delivered_turn_id=? "
                "AND json_type(payload,'$.location_comparison') IS NOT NULL",
                (row["parent_id"], row["turn_id"]),
            ).fetchone()
        ):
            return False
        return super()._push_delivery_ready(connection, row, now)


class SqliteClosedLocationComparisonSafetyStore(SqliteClosedCompactParentPublicationStore):
    _schema_version = 37

    def __init__(self, path: Path, **family: Any) -> None:
        super().__init__(path, **family)
        self._schema_version = 37

    def _supported_versions(self) -> set[int]:
        return {37}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}
