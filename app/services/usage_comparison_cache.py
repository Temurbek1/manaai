"""Source v8: freeze one saved adjacent query day on new dated-source admissions."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.family_day_usage import (
    DAY_USAGE_SOURCE,
    DayUsageReceipt,
    DayUsageTarget,
    FamilyDayUsagePage,
    day_child_fingerprint,
)
from app.mana_ai.domain.source_reviews import (
    SavedUsageComparison,
    SourceReviewBundle,
    SourceReviewSnapshot,
    SourceReviewWork,
)
from app.services.day_usage_cache import day_page_fingerprint
from app.services.location_source_cache import SqliteLocationSourceCache

_TABLES = frozenset({"usage_comparison_admissions", "usage_comparison_heads"})


class SqliteUsageComparisonCache(SqliteLocationSourceCache):
    _schema_version = 8
    _extra_tables = SqliteLocationSourceCache._extra_tables | _TABLES

    def __init__(self, path: Path, *, comparisons_enabled: bool = False, **source: Any) -> None:
        self._comparisons_enabled = comparisons_enabled
        super().__init__(path, **source)

    def _upgrade_versions(self) -> set[int]:
        return super()._upgrade_versions() | {7}

    def _version_tables(self, version: int) -> set[str]:
        return (
            super()._version_tables(version) | set(SqliteLocationSourceCache._extra_tables)
            if version == 7
            else super()._version_tables(version)
        )

    def _extra_schema(self) -> tuple[str, ...]:
        return super()._extra_schema() + (
            "CREATE TABLE IF NOT EXISTS usage_comparison_admissions(parent_id TEXT NOT NULL,"
            "request_id TEXT NOT NULL,enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),"
            "PRIMARY KEY(parent_id,request_id))",
            "CREATE TABLE IF NOT EXISTS usage_comparison_heads(parent_id TEXT NOT NULL,"
            "child_id INTEGER NOT NULL,snapshot_id TEXT NOT NULL,previous_payload TEXT,"
            "PRIMARY KEY(parent_id,child_id))",
        )

    def _day_admitted(self, db: sqlite3.Connection, target: DayUsageTarget) -> None:
        super()._day_admitted(db, target)
        db.execute(
            "INSERT INTO usage_comparison_admissions VALUES(?,?,?)",
            (
                target.parent_id,
                str(target.request_id),
                int(
                    self._comparisons_enabled
                    and self._dated_reviews_enabled
                    and self._dispatch_enabled
                ),
            ),
        )

    def _previous(
        self, db: sqlite3.Connection, target: DayUsageTarget, child: int, checked_at: datetime
    ) -> SourceReviewSnapshot | None:
        day = target.requested_day - timedelta(days=1)
        row = db.execute(
            "SELECT s.* FROM day_usage_heads h JOIN day_usage_snapshots s "
            "ON s.snapshot_id=h.snapshot_id AND s.parent_id=h.parent_id AND s.day=h.day "
            "WHERE h.parent_id=? AND h.day=?",
            (target.parent_id, day.isoformat()),
        ).fetchone()
        if row is None:
            return None
        # Stored normalization repeats app labels per counter and can exceed the
        # original HTTP body's limit while remaining inside its typed family bounds.
        if len(row["payload"].encode()) > 1048576:
            raise ParentChatError("usage_comparison_state_invalid", 503)
        page = FamilyDayUsagePage.model_validate_json(row["payload"])
        if (
            page.parent_id != target.parent_id
            or page.requested_day != day
            or page.collected_at > checked_at
            or day_page_fingerprint(page) != row["fingerprint"]
        ):
            raise ParentChatError("usage_comparison_state_invalid", 503)
        facts = next((c for c in page.children if c.child_id == child), None)
        if facts is None or not facts.entries:
            return None
        return SourceReviewSnapshot(
            source=DAY_USAGE_SOURCE,
            requested_day=day,
            snapshot_id=uuid5(UUID(row["snapshot_id"]), str(child)),
            fingerprint=day_child_fingerprint(facts, day),
            facts=facts,
        )

    def _day_finalized(
        self,
        db: sqlite3.Connection,
        target: DayUsageTarget,
        result: DayUsageReceipt,
        page: FamilyDayUsagePage | None,
        checked_at: datetime | None,
    ) -> None:
        changed = []
        if page is not None:
            for facts in page.children:
                old = db.execute(
                    "SELECT day,fingerprint FROM day_review_heads WHERE parent_id=? AND child_id=?",
                    (target.parent_id, facts.child_id),
                ).fetchone()
                if old is None or (
                    old["day"] <= target.requested_day.isoformat()
                    and old["fingerprint"] != day_child_fingerprint(facts, target.requested_day)
                ):
                    changed.append(facts)
        super()._day_finalized(db, target, result, page, checked_at)
        capture = db.execute(
            "SELECT enabled FROM usage_comparison_admissions WHERE parent_id=? AND request_id=?",
            (target.parent_id, str(target.request_id)),
        ).fetchone()
        if capture is None or page is None or checked_at is None:
            return  # No historical capture/backfill, including an old in-flight completion.
        assert result.family_snapshot_id is not None
        for facts in changed:
            previous = (
                self._previous(db, target, facts.child_id, checked_at)
                if capture[0]
                and self._comparisons_enabled
                and self._dated_reviews_enabled
                and self._dispatch_enabled
                and facts.entries
                else None
            )
            db.execute(
                "INSERT INTO usage_comparison_heads VALUES(?,?,?,?) "
                "ON CONFLICT(parent_id,child_id) DO UPDATE SET "
                "snapshot_id=excluded.snapshot_id,previous_payload=excluded.previous_payload",
                (
                    target.parent_id,
                    facts.child_id,
                    str(uuid5(result.family_snapshot_id, str(facts.child_id))),
                    previous.model_dump_json() if previous is not None else None,
                ),
            )

    def _freeze_review_bundle(
        self, db: sqlite3.Connection, bundle: SourceReviewBundle
    ) -> SourceReviewBundle:
        bundle = super()._freeze_review_bundle(db, bundle)
        if DAY_USAGE_SOURCE not in bundle.changed_sources:
            return bundle
        current = next(s for s in bundle.snapshots if s.source == DAY_USAGE_SOURCE)
        row = db.execute(
            "SELECT * FROM usage_comparison_heads WHERE parent_id=? AND child_id=?",
            (bundle.parent_id, bundle.child_id),
        ).fetchone()
        if (
            row is None
            or row["snapshot_id"] != str(current.snapshot_id)
            or row["previous_payload"] is None
        ):
            return bundle
        if not self._comparisons_enabled:
            raise ParentChatError("usage_comparisons_disabled", 503)
        previous = SourceReviewSnapshot.model_validate_json(row["previous_payload"])
        return SourceReviewBundle.model_validate(
            bundle.model_dump()
            | {
                "usage_comparison": SavedUsageComparison(
                    current_snapshot_id=current.snapshot_id,
                    current_fingerprint=current.fingerprint,
                    previous=previous,
                )
            }
        )

    def _claim_review(self, now: datetime) -> SourceReviewWork | None:
        if not self._comparisons_enabled:
            with self._connection() as db:
                db.execute(
                    "UPDATE review_events SET phase='disabled' WHERE phase='queued' AND "
                    "event_id IN (SELECT c.event_id FROM source_changes c "
                    "JOIN usage_comparison_heads h ON h.parent_id=c.parent_id "
                    "AND h.child_id=json_extract(c.payload,'$.child_id') "
                    "AND h.snapshot_id=json_extract(c.payload,'$.snapshot_id') "
                    "WHERE json_extract(c.payload,'$.source')=? "
                    "AND h.previous_payload IS NOT NULL)",
                    (DAY_USAGE_SOURCE,),
                )
                db.execute(
                    "UPDATE review_batches SET phase='skipped',payload=json_set(payload,"
                    "'$.phase','skipped','$.reason','usage_comparisons_disabled',"
                    "'$.dispatch_now',json('false')) WHERE phase IN ('preparing','prepared') "
                    "AND json_type(payload,'$.bundle.usage_comparison') IS NOT NULL"
                )
        return super()._claim_review(now)
