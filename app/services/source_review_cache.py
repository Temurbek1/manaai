"""Source-cache v4: shared snapshots, immutable coalesced reviews and native ownership."""

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.family_sources import (
    FamilySourceChange,
    FamilySourceClaim,
    FamilySourceLimits,
    FamilySourceTarget,
    ObservedSourceKey,
    source_facts,
)
from app.mana_ai.domain.source_reviews import (
    SourceAnalysisOwner,
    SourceReviewBundle,
    SourceReviewPolicy,
    SourceReviewSnapshot,
    SourceReviewWork,
)
from app.mana_ai.domain.source_safety import SourceSafetyPolicy
from app.services.multi_family_source_store import SqliteMultiFamilySourceStore

_TABLES = frozenset({"review_policy", "review_owners", "review_events", "review_batches"})


class SqliteSourceReviewCache(SqliteMultiFamilySourceStore):
    _schema_version = 4
    _extra_tables = SqliteMultiFamilySourceStore._extra_tables | _TABLES

    def __init__(
        self,
        path: Path,
        *,
        binding: str,
        limits: FamilySourceLimits,
        policy: SourceSafetyPolicy,
        review_policy: SourceReviewPolicy,
        enabled: bool = False,
    ) -> None:
        super().__init__(path, binding=binding, limits=limits, policy=policy, enabled=enabled)
        self._review_policy = SourceReviewPolicy.model_validate(review_policy.model_dump())

    def _upgrade_versions(self) -> set[int]:
        return super()._upgrade_versions() | {3}

    def _version_tables(self, version: int) -> set[str]:
        result = super()._version_tables(version)
        return result | set(SqliteMultiFamilySourceStore._extra_tables) if version == 3 else result

    def _extra_schema(self) -> tuple[str, ...]:
        return super()._extra_schema() + (
            "CREATE TABLE IF NOT EXISTS review_policy (id INTEGER PRIMARY KEY CHECK(id=1),"
            "payload TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS review_owners (parent_id TEXT NOT NULL,request_id TEXT "
            "NOT NULL,child_id INTEGER NOT NULL,source TEXT NOT NULL,job_id TEXT NOT NULL,"
            "PRIMARY KEY(parent_id,request_id))",
            "CREATE TABLE IF NOT EXISTS review_events (event_id TEXT PRIMARY KEY,parent_id TEXT "
            "NOT NULL,child_id INTEGER NOT NULL,recorded_at TEXT NOT NULL,phase TEXT NOT NULL,"
            "review_id TEXT,owner_job_id TEXT)",
            "CREATE INDEX IF NOT EXISTS review_event_ready ON review_events(phase,recorded_at)",
            "CREATE TABLE IF NOT EXISTS review_batches (review_id TEXT PRIMARY KEY,parent_id "
            "TEXT NOT NULL,child_id INTEGER NOT NULL,digest TEXT NOT NULL,phase TEXT NOT NULL,"
            "payload TEXT NOT NULL,bundle_hash TEXT NOT NULL,UNIQUE(parent_id,child_id,digest))",
        )

    def _initialize_additional(self, connection: sqlite3.Connection) -> None:
        super()._initialize_additional(connection)
        payload = self._review_policy.model_dump_json()
        old = connection.execute("SELECT payload FROM review_policy WHERE id=1").fetchone()
        if old is not None and old[0] != payload:
            raise ValueError("Captured source-review policy cannot change")
        connection.execute("INSERT OR IGNORE INTO review_policy VALUES(1,?)", (payload,))

    def _review_sources(self) -> tuple[ObservedSourceKey, ...]:
        return ("firebase.child_battery.v1", "manakids.child_app_usage.v1")

    def _freeze_review_bundle(
        self, db: sqlite3.Connection, bundle: SourceReviewBundle
    ) -> SourceReviewBundle:
        return bundle

    def _review_snapshot(
        self, db: sqlite3.Connection, parent: str, child: int, source: ObservedSourceKey
    ) -> tuple[SourceReviewSnapshot, datetime] | None:
        if source == "manakids.family_day_app_usage.v1":
            raise ParentChatError("source_review_state_invalid", 503)
        head = db.execute(
            f"SELECT s.*,h.checked_at FROM {self._heads(source)} h "
            f"JOIN {self._snapshots(source)} s ON s.snapshot_id=h.snapshot_id "
            "AND s.parent_id=h.parent_id AND s.child_id=h.child_id "
            "WHERE h.parent_id=? AND h.child_id=?",
            (parent, child),
        ).fetchone()
        if head is None:
            return None
        snapshot = SourceReviewSnapshot(
            source=source,
            snapshot_id=head["snapshot_id"],
            fingerprint=head["fingerprint"],
            facts=source_facts(json.loads(head["payload"]), source),
        )
        return snapshot, datetime.fromisoformat(head["checked_at"])

    def _source_changed(self, connection: sqlite3.Connection, event: FamilySourceChange) -> None:
        # New v4 events belong to this consumer. Historical v2 dispatches retain
        # their exact capture and continue through the existing legacy worker.
        if event.source == "firebase.child_battery.v1":
            connection.execute(
                "INSERT INTO source_safety_admissions VALUES(?,?,?)",
                (str(event.event_id), 0, self._policy.model_dump_json()),
            )
        owner = connection.execute(
            "SELECT o.job_id FROM review_owners o JOIN source_reads r "
            "ON r.parent_id=o.parent_id AND r.request_id=o.request_id "
            "WHERE o.parent_id=? AND o.child_id=? AND o.source=? AND r.status='pending'",
            (event.parent_id, event.child_id, event.source),
        ).fetchone()
        phase = "native" if owner else "queued" if self._dispatch_enabled else "disabled"
        connection.execute(
            "INSERT INTO review_events VALUES(?,?,?,?,?,NULL,?)",
            (
                str(event.event_id),
                event.parent_id,
                event.child_id,
                event.recorded_at.isoformat(),
                phase,
                owner[0] if owner else None,
            ),
        )

    async def claim_for_analysis(
        self, target: FamilySourceTarget, owner: SourceAnalysisOwner, now: datetime
    ) -> FamilySourceClaim:
        if owner.parent_id != target.parent_id:
            raise ParentChatError("source_review_owner_mismatch", 403)

        def bind() -> None:
            with self._connection() as db:
                prior = db.execute(
                    "SELECT child_id,source,job_id FROM review_owners WHERE parent_id=? "
                    "AND request_id=?",
                    (target.parent_id, str(target.request_id)),
                ).fetchone()
                expected = (target.child_id, target.source, str(owner.job_id))
                if prior is not None:
                    if tuple(prior) != expected:
                        raise ParentChatError("source_review_owner_mismatch", 409)
                    return
                if self._known(db, target) is not None:
                    raise ParentChatError("source_review_owner_mismatch", 409)
                db.execute(
                    "INSERT INTO review_owners VALUES(?,?,?,?,?)",
                    (
                        target.parent_id,
                        str(target.request_id),
                        *expected,
                    ),
                )

        await asyncio.to_thread(bind)
        claim = await self.claim(target, now)
        if claim.receipt.cache_hit and claim.receipt.snapshot_id is not None:

            def consume_queued() -> None:
                with self._connection() as db:
                    db.execute(
                        "UPDATE review_events SET phase='native',owner_job_id=? "
                        "WHERE parent_id=? AND child_id=? AND phase='queued' AND event_id IN "
                        "(SELECT event_id FROM source_changes WHERE parent_id=? AND "
                        "json_extract(payload,'$.snapshot_id')=?)",
                        (
                            str(owner.job_id),
                            target.parent_id,
                            target.child_id,
                            target.parent_id,
                            str(claim.receipt.snapshot_id),
                        ),
                    )

            await asyncio.to_thread(consume_queued)
        return claim

    @staticmethod
    def _review(row: sqlite3.Row) -> SourceReviewWork:
        work = SourceReviewWork.model_validate_json(row["payload"])
        if (
            str(work.review_id) != row["review_id"]
            or work.bundle.parent_id != row["parent_id"]
            or work.bundle.child_id != row["child_id"]
            or work.bundle.digest() != row["digest"]
            or work.phase != row["phase"]
            or hashlib.sha256(work.bundle.model_dump_json().encode()).hexdigest()
            != row["bundle_hash"]
        ):
            raise ParentChatError("source_review_state_invalid", 503)
        return work

    @staticmethod
    def _save_review(db: sqlite3.Connection, work: SourceReviewWork) -> None:
        work = SourceReviewWork.model_validate(work.model_dump())
        db.execute(
            "UPDATE review_batches SET phase=?,payload=? WHERE review_id=?",
            (
                work.phase,
                work.model_dump_json(exclude={"dispatch_now"}),
                str(work.review_id),
            ),
        )

    async def claim_next_review(self, now: datetime) -> SourceReviewWork | None:
        if not self._dispatch_enabled:
            return None
        return await asyncio.to_thread(self._claim_review, self._time(now))

    def _claim_review(self, now: datetime) -> SourceReviewWork | None:
        with self._connection() as db:
            for row in db.execute(
                "SELECT * FROM review_batches WHERE phase='preparing' AND "
                "julianday(json_extract(payload,'$.bundle.frozen_at'))<=julianday(?) LIMIT 100",
                (
                    (
                        now - timedelta(seconds=self._review_policy.preparation_lease_seconds)
                    ).isoformat(),
                ),
            ).fetchall():
                pending = self._review(row)
                self._save_review(
                    db,
                    pending.model_copy(
                        update={
                            "phase": "unknown",
                            "reason": "preparation_unknown",
                        }
                    ),
                )
            old = db.execute(
                "SELECT * FROM review_batches WHERE phase IN ('prepared','dispatching') "
                "ORDER BY rowid LIMIT 1"
            ).fetchone()
            if old is not None:
                work = self._review(old)
                if work.phase == "prepared":
                    work = work.model_copy(update={"phase": "dispatching"})
                    self._save_review(db, work)
                    return work.model_copy(update={"dispatch_now": True})
                return work  # Exact SQL reconciliation only, never redispatch.
            ready = db.execute(
                "SELECT parent_id,child_id FROM review_events e WHERE phase='queued' "
                "AND NOT EXISTS(SELECT 1 FROM source_reads r WHERE r.child_id=e.child_id "
                "AND r.status='pending') AND NOT EXISTS(SELECT 1 FROM review_batches b "
                "WHERE b.child_id=e.child_id AND b.phase IN "
                "('preparing','prepared','dispatching','unknown')) "
                "GROUP BY parent_id,child_id HAVING MAX(recorded_at)<=? "
                "ORDER BY MIN(recorded_at) LIMIT 1",
                ((now - timedelta(seconds=self._review_policy.coalesce_seconds)).isoformat(),),
            ).fetchone()
            if ready is None:
                return None
            parent, child = ready
            if db.execute(
                "SELECT 1 FROM source_reads WHERE child_id=? AND status='pending'",
                (child,),
            ).fetchone():
                return None
            events = db.execute(
                "SELECT e.event_id,c.payload FROM review_events e JOIN source_changes c "
                "ON c.event_id=e.event_id WHERE e.parent_id=? AND e.child_id=? "
                "AND e.phase='queued' "
                "ORDER BY c.id LIMIT ?",
                (parent, child, self._review_policy.maximum_events + 1),
            ).fetchall()
            if len(events) > self._review_policy.maximum_events:
                db.execute(
                    "UPDATE review_events SET phase='overflow' WHERE parent_id=? "
                    "AND child_id=? AND phase='queued'",
                    (parent, child),
                )
                return None
            changed = {FamilySourceChange.model_validate_json(e["payload"]).source for e in events}
            snapshots = []
            for source in self._review_sources():
                loaded = self._review_snapshot(db, parent, child, source)
                if loaded is None:
                    if source not in changed:
                        continue
                    raise ParentChatError("source_review_state_invalid", 503)
                snapshot, checked_at = loaded
                if (
                    not now - timedelta(seconds=self._review_policy.maximum_collection_age_seconds)
                    <= checked_at
                    <= now
                ):
                    if source not in changed:
                        continue
                    db.execute(
                        "UPDATE review_events SET phase='stale' WHERE parent_id=? "
                        "AND child_id=? AND phase='queued'",
                        (parent, child),
                    )
                    return None
                snapshots.append(snapshot)
            bundle = self._freeze_review_bundle(
                db,
                SourceReviewBundle(
                    parent_id=parent,
                    child_id=child,
                    snapshots=tuple(snapshots),
                    changed_sources=tuple(sorted(changed)),
                    frozen_at=now,
                ),
            )
            duplicate = db.execute(
                "SELECT review_id FROM review_batches WHERE parent_id=? "
                "AND child_id=? AND digest=?",
                (parent, child, bundle.digest()),
            ).fetchone()
            work = SourceReviewWork(review_id=uuid4(), bundle=bundle, phase="preparing")
            if duplicate is None:
                db.execute(
                    "INSERT INTO review_batches VALUES(?,?,?,?,?,?,?)",
                    (
                        str(work.review_id),
                        parent,
                        child,
                        bundle.digest(),
                        work.phase,
                        work.model_dump_json(),
                        hashlib.sha256(bundle.model_dump_json().encode()).hexdigest(),
                    ),
                )
            for event in events:
                db.execute(
                    "UPDATE review_events SET phase=?,review_id=? WHERE event_id=?",
                    (
                        "duplicate" if duplicate else "captured",
                        duplicate[0] if duplicate else str(work.review_id),
                        event["event_id"],
                    ),
                )
            return None if duplicate else work

    async def update_review(
        self, work: SourceReviewWork, *, expected_phase: str
    ) -> SourceReviewWork:
        def update() -> SourceReviewWork:
            with self._connection() as db:
                row = db.execute(
                    "SELECT * FROM review_batches WHERE review_id=?", (str(work.review_id),)
                ).fetchone()
                if row is None:
                    raise ParentChatError("source_review_not_found", 404)
                current = self._review(row)
                if current.phase != expected_phase:
                    return current
                if current.bundle != work.bundle:
                    raise ParentChatError("source_review_context_changed", 409)
                if (
                    work.phase == "prepared"
                    and work.profile_collected_at is not None
                    and (work.profile_collected_at - work.bundle.frozen_at).total_seconds()
                    >= self._review_policy.preparation_lease_seconds
                ):
                    work_value = work.model_copy(
                        update={
                            "phase": "unknown",
                            "reason": "preparation_unknown",
                        }
                    )
                    self._save_review(db, work_value)
                    return work_value
                self._save_review(db, work)
                return work

        return await asyncio.to_thread(update)

    async def reviews(self, parent_id: str, *, limit: int = 100) -> list[SourceReviewWork]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("A bounded review page is required")

        def read() -> list[SourceReviewWork]:
            with self._connection() as db:
                return [
                    self._review(row)
                    for row in db.execute(
                        "SELECT * FROM review_batches WHERE parent_id=? "
                        "ORDER BY rowid DESC LIMIT ?",
                        (parent_id, limit),
                    ).fetchall()
                ]

        return await asyncio.to_thread(read)
