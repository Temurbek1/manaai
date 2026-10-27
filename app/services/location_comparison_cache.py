"""Source v9: freeze one prior own-child GPS observation before a new read."""

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
from app.mana_ai.domain.source_reviews import (
    SavedLocationComparison,
    SourceReviewBundle,
    SourceReviewSnapshot,
    SourceReviewWork,
)
from app.services.usage_comparison_cache import SqliteUsageComparisonCache

_TABLES = frozenset({"location_comparison_admissions", "location_comparison_heads"})


class SqliteLocationComparisonCache(SqliteUsageComparisonCache):
    _schema_version = 9
    _extra_tables = SqliteUsageComparisonCache._extra_tables | _TABLES

    def __init__(
        self, path: Path, *, location_comparisons_enabled: bool = False, **source: Any
    ) -> None:
        self._location_comparisons_enabled = location_comparisons_enabled
        super().__init__(path, **source)

    def _upgrade_versions(self) -> set[int]:
        return super()._upgrade_versions() | {8}

    def _version_tables(self, version: int) -> set[str]:
        return (
            super()._version_tables(version) | set(SqliteUsageComparisonCache._extra_tables)
            if version == 8
            else super()._version_tables(version)
        )

    def _extra_schema(self) -> tuple[str, ...]:
        return super()._extra_schema() + (
            "CREATE TABLE IF NOT EXISTS location_comparison_admissions("
            "parent_id TEXT NOT NULL,request_id TEXT NOT NULL,enabled INTEGER NOT NULL "
            "CHECK(enabled IN (0,1)),previous_payload TEXT,PRIMARY KEY(parent_id,request_id))",
            "CREATE TABLE IF NOT EXISTS location_comparison_heads(parent_id TEXT NOT NULL,"
            "child_id INTEGER NOT NULL,snapshot_id TEXT NOT NULL,previous_payload TEXT,"
            "PRIMARY KEY(parent_id,child_id))",
        )

    def _source_admitted(
        self,
        connection: sqlite3.Connection,
        target: FamilySourceTarget,
        receipt: FamilySourceReceipt,
    ) -> None:
        super()._source_admitted(connection, target, receipt)
        if target.source != LOCATION_SOURCE:
            return
        enabled = (
            self._location_comparisons_enabled and self._location_enabled and self._dispatch_enabled
        )
        previous = None
        if enabled and not receipt.cache_hit:
            loaded = self._review_snapshot(
                connection, target.parent_id, target.child_id, LOCATION_SOURCE
            )
            if loaded is not None:
                snapshot, checked_at = loaded
                if not snapshot.facts.collected_at <= checked_at <= receipt.started_at:
                    raise ParentChatError("location_comparison_state_invalid", 503)
                previous = snapshot.model_dump_json()
                if len(previous.encode()) > 8192:
                    raise ParentChatError("location_comparison_state_invalid", 503)
        connection.execute(
            "INSERT INTO location_comparison_admissions VALUES(?,?,?,?)",
            (target.parent_id, str(target.request_id), int(enabled), previous),
        )

    def _source_changed(self, connection: sqlite3.Connection, event: FamilySourceChange) -> None:
        super()._source_changed(connection, event)
        if event.source != LOCATION_SOURCE:
            return
        capture = connection.execute(
            "SELECT c.enabled,c.previous_payload FROM source_reads r "
            "JOIN location_comparison_admissions c ON c.parent_id=r.parent_id "
            "AND c.request_id=r.request_id WHERE r.parent_id=? AND r.child_id=? "
            "AND r.status='pending' AND json_extract(r.payload,'$.source')=?",
            (event.parent_id, event.child_id, LOCATION_SOURCE),
        ).fetchall()
        if len(capture) > 1:
            raise ParentChatError("location_comparison_state_invalid", 503)
        previous = capture[0]["previous_payload"] if capture and capture[0]["enabled"] else None
        connection.execute(
            "INSERT INTO location_comparison_heads VALUES(?,?,?,?) "
            "ON CONFLICT(parent_id,child_id) DO UPDATE SET snapshot_id=excluded.snapshot_id,"
            "previous_payload=excluded.previous_payload",
            (event.parent_id, event.child_id, str(event.snapshot_id), previous),
        )

    def _freeze_review_bundle(
        self, db: sqlite3.Connection, bundle: SourceReviewBundle
    ) -> SourceReviewBundle:
        bundle = super()._freeze_review_bundle(db, bundle)
        if LOCATION_SOURCE not in bundle.changed_sources:
            return bundle
        current = next(s for s in bundle.snapshots if s.source == LOCATION_SOURCE)
        row = db.execute(
            "SELECT snapshot_id,previous_payload FROM location_comparison_heads "
            "WHERE parent_id=? AND child_id=?",
            (bundle.parent_id, bundle.child_id),
        ).fetchone()
        if row is None or row["snapshot_id"] != str(current.snapshot_id):
            return bundle
        if row["previous_payload"] is None:
            return bundle
        if not self._location_comparisons_enabled:
            raise ParentChatError("location_comparisons_disabled", 503)
        if len(row["previous_payload"].encode()) > 8192:
            raise ParentChatError("location_comparison_state_invalid", 503)
        previous = SourceReviewSnapshot.model_validate_json(row["previous_payload"])
        saved = db.execute(
            "SELECT payload,fingerprint FROM location_snapshots "
            "WHERE parent_id=? AND child_id=? AND snapshot_id=?",
            (bundle.parent_id, bundle.child_id, str(previous.snapshot_id)),
        ).fetchone()
        if (
            saved is None
            or saved["fingerprint"] != previous.fingerprint
            or saved["payload"] != previous.facts.model_dump_json()
        ):
            raise ParentChatError("location_comparison_state_invalid", 503)
        if previous.snapshot_id == current.snapshot_id:
            return bundle  # Recollection never manufactures a second observation.
        return SourceReviewBundle.model_validate(
            bundle.model_dump()
            | {
                "location_comparison": SavedLocationComparison(
                    current_snapshot_id=current.snapshot_id,
                    current_fingerprint=current.fingerprint,
                    previous=previous,
                )
            }
        )

    def _claim_review(self, now: datetime) -> SourceReviewWork | None:
        if not self._location_comparisons_enabled:
            with self._connection() as db:
                db.execute(
                    "UPDATE review_events SET phase='disabled' WHERE phase='queued' AND "
                    "event_id IN (SELECT c.event_id FROM source_changes c "
                    "JOIN location_comparison_heads h ON h.parent_id=c.parent_id "
                    "AND h.child_id=json_extract(c.payload,'$.child_id') "
                    "WHERE json_extract(c.payload,'$.source')=? "
                    "AND h.previous_payload IS NOT NULL)",
                    (LOCATION_SOURCE,),
                )
                db.execute(
                    "UPDATE review_batches SET phase='skipped',payload=json_set(payload,"
                    "'$.phase','skipped','$.reason','location_comparisons_disabled',"
                    "'$.dispatch_now',json('false')) WHERE phase IN ('preparing','prepared') "
                    "AND json_type(payload,'$.bundle.location_comparison') IS NOT NULL"
                )
        return super()._claim_review(now)
