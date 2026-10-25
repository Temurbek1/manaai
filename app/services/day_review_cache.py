"""Source v6: captured dated-page changes reuse the existing coalesced review queue."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.family_day_usage import (
    DAY_USAGE_SOURCE,
    DayUsageReceipt,
    DayUsageTarget,
    FamilyDayUsagePage,
    day_child_fingerprint,
)
from app.mana_ai.domain.family_sources import FamilySourceChange, ObservedSourceKey
from app.mana_ai.domain.source_reviews import SourceReviewSnapshot, SourceReviewWork
from app.services.day_usage_cache import SqliteDayUsageCache, day_page_fingerprint


class SqliteDayReviewCache(SqliteDayUsageCache):
    _schema_version = 6
    _extra_tables = SqliteDayUsageCache._extra_tables | frozenset(
        {"day_review_captures", "day_review_heads"}
    )

    def __init__(self, path: Path, *, dated_reviews_enabled: bool = False, **source: Any) -> None:
        self._dated_reviews_enabled = dated_reviews_enabled
        super().__init__(path, **source)

    def _upgrade_versions(self) -> set[int]:
        return super()._upgrade_versions() | {5}

    def _version_tables(self, version: int) -> set[str]:
        result = super()._version_tables(version)
        return result | set(SqliteDayUsageCache._extra_tables) if version == 5 else result

    def _extra_schema(self) -> tuple[str, ...]:
        return super()._extra_schema() + (
            "CREATE TABLE IF NOT EXISTS day_review_captures(parent_id TEXT NOT "
            "NULL,request_id TEXT NOT NULL,enabled INTEGER NOT NULL CHECK(enabled IN "
            "(0,1)),PRIMARY KEY(parent_id,request_id))",
            "CREATE TABLE IF NOT EXISTS day_review_heads(parent_id TEXT NOT NULL,child_id "
            "INTEGER NOT NULL,day TEXT NOT NULL,snapshot_id TEXT NOT NULL,family_id TEXT NOT "
            "NULL,fingerprint TEXT NOT NULL,checked_at TEXT NOT NULL,PRIMARY "
            "KEY(parent_id,child_id))",
        )

    def _day_admitted(self, db: sqlite3.Connection, target: DayUsageTarget) -> None:
        db.execute(
            "INSERT INTO day_review_captures VALUES(?,?,?)",
            (
                target.parent_id,
                str(target.request_id),
                int(self._dated_reviews_enabled and self._dispatch_enabled),
            ),
        )

    def _day_finalized(
        self,
        db: sqlite3.Connection,
        target: DayUsageTarget,
        result: DayUsageReceipt,
        page: FamilyDayUsagePage | None,
        checked_at: datetime | None,
    ) -> None:
        capture = db.execute(
            "SELECT enabled FROM day_review_captures WHERE parent_id=? AND request_id=?",
            (target.parent_id, str(target.request_id)),
        ).fetchone()
        if capture is None:
            return  # A v5 in-flight request never gains this consumer.
        owner = db.execute(
            "SELECT job_id FROM day_usage_owners WHERE parent_id=? AND request_id=?",
            (target.parent_id, str(target.request_id)),
        ).fetchone()
        enabled = bool(capture[0]) and self._dated_reviews_enabled and self._dispatch_enabled
        if page is not None and checked_at is not None:
            assert result.family_snapshot_id is not None
            for facts in page.children:
                day = target.requested_day.isoformat()
                old = db.execute(
                    "SELECT * FROM day_review_heads WHERE parent_id=? AND child_id=?",
                    (target.parent_id, facts.child_id),
                ).fetchone()
                if old is not None and old["day"] > day:
                    continue  # An explicit historical query cannot replace newer review evidence.
                fingerprint = day_child_fingerprint(facts, target.requested_day)
                if old is not None and old["fingerprint"] == fingerprint:
                    db.execute(
                        "UPDATE day_review_heads SET checked_at=? WHERE parent_id=? AND child_id=?",
                        (checked_at.isoformat(), target.parent_id, facts.child_id),
                    )
                    continue
                db.execute(
                    "UPDATE review_events SET phase='superseded' WHERE parent_id=? AND "
                    "child_id=? AND phase='queued' AND event_id IN (SELECT event_id FROM "
                    "source_changes WHERE json_extract(payload,'$.source')=?)",
                    (target.parent_id, facts.child_id, DAY_USAGE_SOURCE),
                )
                identity = uuid5(result.family_snapshot_id, str(facts.child_id))
                event = FamilySourceChange(
                    event_id=uuid4(),
                    parent_id=target.parent_id,
                    child_id=facts.child_id,
                    snapshot_id=identity,
                    fingerprint=fingerprint,
                    recorded_at=checked_at,
                    source=DAY_USAGE_SOURCE,
                    requested_day=target.requested_day,
                )
                db.execute(
                    "INSERT INTO source_changes(event_id,parent_id,payload) VALUES(?,?,?)",
                    (str(event.event_id), target.parent_id, event.model_dump_json()),
                )
                native = owner is not None and facts.child_id == target.child_id
                phase = (
                    "native"
                    if native
                    else "disabled"
                    if not enabled
                    else "empty"
                    if not facts.entries
                    else "queued"
                )
                db.execute(
                    "INSERT INTO review_events VALUES(?,?,?,?,?,NULL,?)",
                    (
                        str(event.event_id),
                        target.parent_id,
                        facts.child_id,
                        checked_at.isoformat(),
                        phase,
                        owner[0] if native else None,
                    ),
                )
                db.execute(
                    "INSERT INTO day_review_heads VALUES(?,?,?,?,?,?,?) ON "
                    "CONFLICT(parent_id,child_id) DO UPDATE SET "
                    "day=excluded.day,snapshot_id=excluded.snapshot_id,family_id=excluded.family_id,fingerprint=excluded.fingerprint,checked_at=excluded.checked_at",
                    (
                        target.parent_id,
                        facts.child_id,
                        day,
                        str(identity),
                        str(result.family_snapshot_id),
                        fingerprint,
                        checked_at.isoformat(),
                    ),
                )
        if enabled and owner is not None and result.facts is not None:
            # Exact equivalent pending facts now belong to this verified native review.
            fingerprint = day_child_fingerprint(result.facts, result.requested_day)
            db.execute(
                "UPDATE review_events SET phase='native',owner_job_id=? WHERE parent_id=? "
                "AND child_id=? AND phase='queued' AND event_id IN (SELECT event_id FROM "
                "source_changes WHERE json_extract(payload,'$.source')=? AND "
                "json_extract(payload,'$.requested_day')=? AND "
                "json_extract(payload,'$.fingerprint')=?)",
                (
                    owner[0],
                    target.parent_id,
                    target.child_id,
                    DAY_USAGE_SOURCE,
                    target.requested_day.isoformat(),
                    fingerprint,
                ),
            )

    def _review_sources(self) -> tuple[ObservedSourceKey, ...]:
        return super()._review_sources() + (
            (DAY_USAGE_SOURCE,) if self._dated_reviews_enabled else ()
        )

    def _review_snapshot(
        self, db: sqlite3.Connection, parent: str, child: int, source: ObservedSourceKey
    ) -> tuple[SourceReviewSnapshot, datetime] | None:
        if source != DAY_USAGE_SOURCE:
            return super()._review_snapshot(db, parent, child, source)
        head = db.execute(
            "SELECT h.*,s.payload,s.fingerprint AS page_fingerprint FROM day_review_heads h "
            "LEFT JOIN day_usage_snapshots s ON s.snapshot_id=h.family_id AND "
            "s.parent_id=h.parent_id AND s.day=h.day WHERE h.parent_id=? AND h.child_id=?",
            (parent, child),
        ).fetchone()
        if head is None:
            return None
        if head["payload"] is None:
            raise ParentChatError("source_review_state_invalid", 503)
        page = FamilyDayUsagePage.model_validate_json(head["payload"])
        facts = next((c for c in page.children if c.child_id == child), None)
        if (
            facts is None
            or day_page_fingerprint(page) != head["page_fingerprint"]
            or page.parent_id != parent
            or page.requested_day.isoformat() != head["day"]
            or str(uuid5(UUID(head["family_id"]), str(child))) != head["snapshot_id"]
        ):
            raise ParentChatError("source_review_state_invalid", 503)
        if not facts.entries:
            return None
        snapshot = SourceReviewSnapshot(
            source=source,
            snapshot_id=head["snapshot_id"],
            fingerprint=head["fingerprint"],
            facts=facts,
            requested_day=page.requested_day,
        )
        return snapshot, datetime.fromisoformat(head["checked_at"])

    def _claim_review(self, now: datetime) -> SourceReviewWork | None:
        if not self._dated_reviews_enabled:
            with self._connection() as db:
                db.execute(
                    "UPDATE review_events SET phase='disabled' WHERE phase='queued' AND "
                    "event_id IN (SELECT event_id FROM source_changes WHERE "
                    "json_extract(payload,'$.source')=?)",
                    (DAY_USAGE_SOURCE,),
                )
                db.execute(
                    "UPDATE review_batches SET "
                    "phase='skipped',payload=json_set(payload,'$.phase','skipped',"
                    "'$.reason','dated_reviews_disabled','$.dispatch_now',json('false')) "
                    "WHERE phase IN ('preparing','prepared') AND EXISTS(SELECT 1 FROM "
                    "json_each(review_batches.payload,'$.bundle.snapshots') s "
                    "WHERE json_extract(s.value,'$.source')=?)",
                    (DAY_USAGE_SOURCE,),
                )
        return super()._claim_review(now)
