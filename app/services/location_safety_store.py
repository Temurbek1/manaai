"""Family v23: GPS tools exist only in new explicitly captured native source scopes."""

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ParentChatRequest
from app.mana_ai.domain.child_location import LOCATION_SOURCE
from app.mana_ai.domain.child_safety import SafetyContextSnapshot, SafetyJob, SafetyJobView
from app.mana_ai.domain.source_reviews import SourceReviewWork
from app.mana_ai.domain.source_tools import SourceToolPreparedInput
from app.services.trial_period_store import SqliteClosedTrialPeriodStore, SqliteTrialPeriodStore

_TABLE = "location_tool_captures"


class SqliteLocationSafetyStore(SqliteTrialPeriodStore):
    _schema_version = 23

    def __init__(self, path: Path, *, location_enabled: bool = False, **family: Any) -> None:
        self._location_enabled = location_enabled
        super().__init__(path, **family)
        self._location_native_policy = json.dumps(
            json.loads(self._native_policy) | {"location_prompt_version": 2},
            sort_keys=True,
            separators=(",", ":"),
        )

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {22}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS location_tool_captures(
          turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,
          enabled INTEGER NOT NULL CHECK(enabled IN (0,1)));
        """
        )

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        super()._on_admitted(db, request, turn_id, now)
        native = db.execute(
            "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?",
            (request.parent_id, turn_id),
        ).fetchone()
        if native is not None:
            enabled = (
                self._location_enabled
                and self._day_tools_enabled
                and native[0] == self._native_policy
            )
            db.execute(
                "INSERT INTO location_tool_captures VALUES(?,?,?)",
                (
                    turn_id,
                    request.parent_id,
                    int(enabled),
                ),
            )
            if enabled:
                db.execute(
                    "UPDATE source_tool_turns SET profile=? WHERE parent_id=? AND turn_id=?",
                    (self._location_native_policy, request.parent_id, turn_id),
                )

    def _captured_protocol(self, payload: str) -> int:
        if payload == self._location_native_policy:
            if not self._location_enabled or not self._day_tools_enabled:
                raise ParentChatError("family_source_not_enabled", 503)
            return 3
        return super()._captured_protocol(payload)

    def _location_prompt(self, db: sqlite3.Connection, parent: str, turn: int) -> Literal[2] | None:
        row = db.execute(
            "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?", (parent, turn)
        ).fetchone()
        return 2 if row and row[0] == self._location_native_policy else None

    def _location_capture(self, db: sqlite3.Connection, parent: str, turn: int) -> bool:
        row = db.execute(
            "SELECT enabled FROM location_tool_captures WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        enabled = bool(row and row[0])
        if enabled and not self._location_enabled:
            raise ParentChatError("family_source_not_enabled", 503)
        return enabled

    async def native_location_enabled(self, job: SafetyJob) -> bool:
        def read() -> bool:
            with self._connect() as db:
                return self._location_capture(db, job.view.parent_id, job.view.parent_turn_cutoff)

        return await asyncio.to_thread(read)

    async def native_location_prompt_version(self, job: SafetyJob) -> Literal[2] | None:
        def read() -> Literal[2] | None:
            with self._connect() as db:
                self._location_capture(db, job.view.parent_id, job.view.parent_turn_cutoff)
                return self._location_prompt(db, job.view.parent_id, job.view.parent_turn_cutoff)

        return await asyncio.to_thread(read)

    def _validate_native_scope(
        self, db: sqlite3.Connection, job: SafetyJob, prepared: SourceToolPreparedInput
    ) -> None:
        expected = self._location_capture(db, job.view.parent_id, job.view.parent_turn_cutoff)
        if prepared.scope.location_enabled is not (
            True if expected else None
        ) or prepared.scope.location_prompt_version != self._location_prompt(
            db, job.view.parent_id, job.view.parent_turn_cutoff
        ):
            raise ParentChatError("native_source_preparation_denied", 409)

    def _validate_safety_publication(
        self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> None:
        super()._validate_safety_publication(db, row, now)
        if row["kind"] == "parent_message":
            self._location_capture(db, row["parent_id"], row["parent_turn_cutoff"])
        elif row["kind"] == "source_review" and not self._location_enabled:
            context = SafetyContextSnapshot.model_validate_json(row["context"])
            if context.source_review and any(
                s.source == LOCATION_SOURCE for s in context.source_review.snapshots
            ):
                raise ParentChatError("location_source_review_disabled", 503)

    def _admit_source_review(
        self, work: SourceReviewWork, now: datetime, allow_new: bool
    ) -> SafetyJobView:
        location = any(s.source == LOCATION_SOURCE for s in work.bundle.snapshots)
        return super()._admit_source_review(
            work, now, allow_new and (self._location_enabled or not location)
        )

    async def claim_next(self, now: datetime) -> SafetyJob | None:
        if not self._location_enabled:

            def stop() -> None:
                with self._transaction() as db:
                    db.execute(
                        "UPDATE child_safety_jobs SET status='failed',reserved=0,"
                        "error_code='location_source_review_disabled',updated_at=? "
                        "WHERE status='queued' AND kind='source_review' AND EXISTS("
                        "SELECT 1 FROM json_each(context,'$.source_review.snapshots') s "
                        "WHERE json_extract(s.value,'$.source')=?)",
                        (self._utc(now).isoformat(), LOCATION_SOURCE),
                    )

            await asyncio.to_thread(stop)
        return await super().claim_next(now)


class SqliteClosedLocationSafetyStore(SqliteClosedTrialPeriodStore):
    _schema_version = 23

    def _supported_versions(self) -> set[int]:
        return {23}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}
