"""Source v10: capture exact-time presentation only on new physical GPS admissions."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.child_location import LOCATION_SOURCE
from app.mana_ai.domain.family_sources import (
    FamilySourceChange,
    FamilySourceReceipt,
    FamilySourceTarget,
)
from app.mana_ai.domain.source_reviews import SourceReviewBundle, SourceReviewWork
from app.services.location_comparison_cache import SqliteLocationComparisonCache

_TABLES = frozenset({"location_time_admissions", "location_time_heads"})


class SqliteLocationTimeCache(SqliteLocationComparisonCache):
    _schema_version = 10
    _extra_tables = SqliteLocationComparisonCache._extra_tables | _TABLES

    def __init__(
        self, path: Path, *, location_time_labels_enabled: bool = False, **source: Any
    ) -> None:
        self._location_time_labels_enabled = location_time_labels_enabled
        super().__init__(path, **source)

    def _upgrade_versions(self) -> set[int]:
        return super()._upgrade_versions() | {9}

    def _version_tables(self, version: int) -> set[str]:
        return (
            super()._version_tables(version) | set(SqliteLocationComparisonCache._extra_tables)
            if version == 9
            else super()._version_tables(version)
        )

    def _extra_schema(self) -> tuple[str, ...]:
        return super()._extra_schema() + (
            "CREATE TABLE IF NOT EXISTS location_time_admissions("
            "parent_id TEXT NOT NULL,request_id TEXT NOT NULL,version INTEGER CHECK(version=2),"
            "PRIMARY KEY(parent_id,request_id))",
            "CREATE TABLE IF NOT EXISTS location_time_heads(parent_id TEXT NOT NULL,"
            "child_id INTEGER NOT NULL,snapshot_id TEXT NOT NULL,version INTEGER CHECK(version=2),"
            "PRIMARY KEY(parent_id,child_id))",
        )

    def _source_admitted(
        self, db: sqlite3.Connection, target: FamilySourceTarget, receipt: FamilySourceReceipt
    ) -> None:
        super()._source_admitted(db, target, receipt)
        if target.source != LOCATION_SOURCE or receipt.cache_hit:
            return
        enabled = (
            self._location_time_labels_enabled
            and self._location_comparisons_enabled
            and self._location_enabled
            and self._dispatch_enabled
        )
        db.execute(
            "INSERT INTO location_time_admissions VALUES(?,?,?)",
            (target.parent_id, str(target.request_id), 2 if enabled else None),
        )

    def _source_changed(self, db: sqlite3.Connection, event: FamilySourceChange) -> None:
        super()._source_changed(db, event)
        if event.source != LOCATION_SOURCE:
            return
        rows = db.execute(
            "SELECT t.version FROM source_reads r LEFT JOIN location_time_admissions t "
            "ON t.parent_id=r.parent_id AND t.request_id=r.request_id WHERE r.parent_id=? "
            "AND r.child_id=? AND r.status='pending' AND json_extract(r.payload,'$.source')=?",
            (event.parent_id, event.child_id, LOCATION_SOURCE),
        ).fetchall()
        if len(rows) > 1:
            raise ParentChatError("location_time_capture_invalid", 503)
        # A later stop retains the original marker: it must fence this work rather
        # than silently produce the historical single-day presentation.
        db.execute(
            "INSERT INTO location_time_heads VALUES(?,?,?,?) "
            "ON CONFLICT(parent_id,child_id) DO UPDATE SET snapshot_id=excluded.snapshot_id,"
            "version=excluded.version",
            (
                event.parent_id,
                event.child_id,
                str(event.snapshot_id),
                rows[0]["version"] if rows else None,
            ),
        )

    def _freeze_review_bundle(
        self, db: sqlite3.Connection, bundle: SourceReviewBundle
    ) -> SourceReviewBundle:
        bundle = super()._freeze_review_bundle(db, bundle)
        comparison = bundle.location_comparison
        if comparison is None:
            return bundle
        row = db.execute(
            "SELECT version FROM location_time_heads WHERE parent_id=? AND child_id=? "
            "AND snapshot_id=?",
            (bundle.parent_id, bundle.child_id, str(comparison.current_snapshot_id)),
        ).fetchone()
        if row is None or row[0] is None:
            return bundle
        if row[0] != 2:
            raise ParentChatError("location_time_capture_invalid", 503)
        if not self._location_time_labels_enabled:
            raise ParentChatError("location_time_labels_disabled", 503)
        return SourceReviewBundle.model_validate(
            bundle.model_dump()
            | {
                "location_comparison": comparison.model_dump() | {"presentation_version": 2},
            }
        )

    def _claim_review(self, now: datetime) -> SourceReviewWork | None:
        if not self._location_time_labels_enabled:
            with self._connection() as db:
                db.execute(
                    "UPDATE review_events SET phase='disabled' WHERE phase='queued' AND "
                    "event_id IN (SELECT c.event_id FROM source_changes c "
                    "JOIN location_time_heads h ON h.parent_id=c.parent_id "
                    "AND h.child_id=json_extract(c.payload,'$.child_id') "
                    "WHERE json_extract(c.payload,'$.source')=? AND h.version=2)",
                    (LOCATION_SOURCE,),
                )
                db.execute(
                    "UPDATE review_batches SET phase='skipped',payload=json_set(payload,"
                    "'$.phase','skipped','$.reason','location_time_labels_disabled',"
                    "'$.dispatch_now',json('false')) WHERE phase IN ('preparing','prepared') "
                    "AND json_extract(payload,"
                    "'$.bundle.location_comparison.presentation_version')=2"
                )
        return super()._claim_review(now)
