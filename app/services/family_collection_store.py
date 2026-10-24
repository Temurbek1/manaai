"""Private collection ledger: one durable occurrence, no provider retries or model work."""

import asyncio
import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.family_collection import (
    CollectionSourceCounts,
    FamilyCollectionPolicy,
    FamilyCollectionWindow,
    FamilyCollectionWork,
    FamilyInventoryPage,
    next_family_collection_window,
)
from app.mana_ai.domain.family_sources import (
    ChildAppUsageFacts,
    ChildBatteryFacts,
    FamilySourceKey,
    FamilySourceReceipt,
    FamilySourceTarget,
)

_TABLES = {
    "collection_policy",
    "collection_windows",
    "collection_pages",
    "collection_queue",
    "collection_work",
    "collection_parents",
}
_APPLICATION_ID = 1296125527


def _utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("An aware collection clock is required")
    return value.astimezone(UTC)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class SqliteFamilyCollectionStore:
    def __init__(
        self,
        path: Path,
        *,
        binding: str,
        policy: FamilyCollectionPolicy,
        sources: tuple[FamilySourceKey, ...],
    ) -> None:
        if not binding or len(binding) > 256 or not sources or len(set(sources)) != len(sources):
            raise ValueError("Explicit unique registered collection sources are required")
        if path == Path(":memory:"):
            raise ValueError("Collection requires durable private storage")
        self._path, self._binding, self.policy, self.sources = path, binding, policy, sources
        self._configuration = json.dumps(
            {"binding": binding, "policy": policy.model_dump(mode="json"), "sources": sources},
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def page_size(self) -> int:
        return self.policy.page_size

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def initialize(self, now: datetime) -> None:
        await asyncio.to_thread(self._initialize, _utc(now))

    def _initialize(self, now: datetime) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._path.is_symlink() or self._path.parent.is_symlink():
            raise ValueError("Collection storage cannot use symlinks")
        try:
            descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with self._connection() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            app, version = (
                db.execute("PRAGMA application_id").fetchone()[0],
                db.execute("PRAGMA user_version").fetchone()[0],
            )
            if (
                tables
                and (tables != _TABLES or app != _APPLICATION_ID or version != 1)
                or not tables
                and (app or version)
            ):
                raise ValueError("Collection needs its dedicated supported database")
            statements = (
                "CREATE TABLE IF NOT EXISTS collection_policy (id INTEGER PRIMARY "
                "KEY CHECK(id=1), "
                "configuration TEXT NOT NULL,next_due TEXT NOT "
                "NULL,population_offset INTEGER NOT NULL DEFAULT 0,"
                "inventory_blocked TEXT)",
                "CREATE TABLE IF NOT EXISTS collection_windows (window_id TEXT "
                "PRIMARY KEY,"
                "scheduled_at TEXT NOT NULL UNIQUE,deadline TEXT NOT NULL,status "
                "TEXT NOT NULL,"
                "reason TEXT,published_at TEXT,publication "
                "TEXT,inventory_exhausted INTEGER NOT NULL DEFAULT "
                "0,inventory_changed INTEGER NOT NULL DEFAULT 0,"
                "last_total INTEGER,started_offset INTEGER NOT NULL)",
                "CREATE TABLE IF NOT EXISTS collection_pages (id INTEGER PRIMARY "
                "KEY,window_id TEXT NOT NULL,"
                "offset INTEGER NOT NULL,claim_id TEXT NOT NULL,phase TEXT NOT "
                "NULL,claimed_at TEXT NOT NULL,"
                "expires_at TEXT NOT NULL,payload_hash TEXT,parent_count "
                "INTEGER,total_parents INTEGER,"
                "UNIQUE(window_id,offset))",
                "CREATE INDEX IF NOT EXISTS collection_inventory_budget ON "
                "collection_pages(claimed_at)",
                "CREATE TABLE IF NOT EXISTS collection_queue (id INTEGER PRIMARY "
                "KEY,parent_id TEXT NOT NULL,"
                "child_id INTEGER NOT NULL,source TEXT NOT NULL,discovered_at TEXT "
                "NOT NULL,"
                "UNIQUE(parent_id,child_id,source))",
                "CREATE TABLE IF NOT EXISTS collection_work (id INTEGER PRIMARY "
                "KEY,window_id TEXT NOT NULL,"
                "parent_id TEXT NOT NULL,child_id INTEGER NOT NULL,source TEXT NOT "
                "NULL,target TEXT NOT NULL,"
                "claim_id TEXT NOT NULL,phase TEXT NOT NULL,claimed_at TEXT NOT "
                "NULL,expires_at TEXT NOT NULL,"
                "observed INTEGER NOT NULL DEFAULT 0,result "
                "TEXT,UNIQUE(window_id,parent_id,child_id,source))",
                "CREATE UNIQUE INDEX IF NOT EXISTS collection_one_unresolved ON "
                "collection_work"
                "(parent_id,child_id,source) WHERE phase IN ('claimed','unknown')",
                "CREATE TABLE IF NOT EXISTS collection_parents (window_id TEXT NOT "
                "NULL,parent_id TEXT NOT NULL,"
                "PRIMARY KEY(window_id,parent_id))",
            )
            for statement in statements:
                db.execute(statement)
            known = db.execute("SELECT configuration FROM collection_policy WHERE id=1").fetchone()
            if known and known[0] != self._configuration:
                raise ValueError(
                    "Collection policy/binding cannot change behind existing occurrences"
                )
            db.execute(
                "INSERT OR IGNORE INTO collection_policy(id,configuration,next_due) VALUES(1,?,?)",
                (
                    self._configuration,
                    next_family_collection_window(now - timedelta(microseconds=1)).isoformat(),
                ),
            )
            db.execute(f"PRAGMA application_id={_APPLICATION_ID}")
            db.execute("PRAGMA user_version=1")

    def _recover(self, db: sqlite3.Connection, now: datetime) -> None:
        stamp = now.isoformat()
        if db.execute(
            "SELECT 1 FROM collection_pages WHERE phase='claimed' AND expires_at<=?", (stamp,)
        ).fetchone():
            db.execute(
                "UPDATE collection_pages SET phase='unknown' WHERE phase='claimed' "
                "AND expires_at<=?",
                (stamp,),
            )
            db.execute(
                "UPDATE collection_policy SET "
                "inventory_blocked='inventory_unknown' WHERE id=1 AND "
                "inventory_blocked IS NULL"
            )
        db.execute(
            "UPDATE collection_work SET phase='unknown' WHERE phase='claimed' AND expires_at<=?",
            (stamp,),
        )

        db.execute(
            "UPDATE collection_windows SET status=CASE WHEN EXISTS(SELECT 1 "
            "FROM collection_work w "
            "WHERE w.window_id=collection_windows.window_id AND w.phase IN "
            "('claimed','unknown')) "
            "OR EXISTS(SELECT 1 FROM collection_pages p WHERE "
            "p.window_id=collection_windows.window_id "
            "AND p.phase IN ('claimed','unknown')) THEN 'unknown' ELSE "
            "'partial' END,reason='window_expired' "
            "WHERE status='collecting' AND deadline<=?",
            (stamp,),
        )

        for row in db.execute(
            "SELECT window_id FROM collection_windows WHERE "
            "status!='collecting' AND publication IS NULL"
        ).fetchall():
            self._publish(db, row[0], now)

    def _manifest(self, db: sqlite3.Connection, identity: str) -> FamilyCollectionWindow:
        row = db.execute(
            "SELECT * FROM collection_windows WHERE window_id=?", (identity,)
        ).fetchone()
        if row is None:
            raise ParentChatError("collection_window_not_found", 404)
        if row["publication"] is not None:
            return FamilyCollectionWindow.model_validate_json(row["publication"])
        counts = []
        for source in self.sources:
            values: dict[str, Any] = {"source": source}
            records = db.execute(
                "SELECT phase,result FROM collection_work WHERE window_id=? AND source=?",
                (identity, source),
            ).fetchall()
            values["target_reads"] = len(records)
            for record in records:
                value = json.loads(record["result"]) if record["result"] else {}
                status = value.get(
                    "status",
                    "unknown" if record["phase"] in {"claimed", "unknown"} else record["phase"],
                )
                key = (
                    "completed"
                    if status == "completed"
                    else "unknown"
                    if status in {"pending", "unknown"}
                    else "failed"
                    if status == "failed"
                    else "skipped"
                )
                values[key] = values.get(key, 0) + 1
                for key in (
                    "cache_hits",
                    "available",
                    "undated",
                    "low_battery_records",
                    "partial_counter_pages",
                ):
                    values[key] = values.get(key, 0) + int(value.get(key, False))
            dates = [json.loads(r["result"]) for r in records if r["result"]]
            collected = [
                datetime.fromisoformat(v["collected_at"]) for v in dates if v.get("collected_at")
            ]
            observed = [
                datetime.fromisoformat(v["observed_at"]) for v in dates if v.get("observed_at")
            ]
            values["oldest_snapshot_collection_at"] = min(collected) if collected else None
            provider_checks = [
                datetime.fromisoformat(v["read_finished_at"])
                for v in dates
                if v.get("read_finished_at")
                and not v.get("cache_hits")
                and v.get("status") == "completed"
            ]
            values["latest_provider_check_at"] = max(provider_checks) if provider_checks else None
            values["first_observation_at"] = min(observed) if observed else None
            values["last_observation_at"] = max(observed) if observed else None
            counts.append(CollectionSourceCounts.model_validate(values))
        return FamilyCollectionWindow(
            window_id=row["window_id"],
            scheduled_at=row["scheduled_at"],
            deadline=row["deadline"],
            status=row["status"],
            reason=row["reason"],
            published_at=row["published_at"],
            inventory_start_offset=row["started_offset"],
            total_parents_reported=row["last_total"],
            pending_targets=db.execute("SELECT COUNT(*) FROM collection_queue").fetchone()[0],
            pages=db.execute(
                "SELECT COUNT(*) FROM collection_pages WHERE window_id=?", (identity,)
            ).fetchone()[0],
            parents_seen=db.execute(
                "SELECT COUNT(*) FROM collection_parents WHERE window_id=?", (identity,)
            ).fetchone()[0],
            targets=sum(c.target_reads for c in counts),
            inventory_exhausted=bool(row["inventory_exhausted"]),
            inventory_changed=bool(row["inventory_changed"]),
            counts=tuple(counts),
        )

    def _publish(
        self, db: sqlite3.Connection, identity: str, now: datetime
    ) -> FamilyCollectionWindow:
        db.execute(
            "UPDATE collection_windows SET published_at=COALESCE(published_at,?) WHERE window_id=?",
            (now.isoformat(), identity),
        )
        result = self._manifest(db, identity)
        if result.status == "collecting":
            raise ValueError("A running collection cannot publish a terminal manifest")
        db.execute(
            "UPDATE collection_windows SET publication=COALESCE(publication,?) WHERE window_id=?",
            (result.model_dump_json(), identity),
        )
        return result

    async def manifest(self, identity: UUID) -> FamilyCollectionWindow:
        def read() -> FamilyCollectionWindow:
            with self._connection() as db:
                return self._manifest(db, str(identity))

        return await asyncio.to_thread(read)

    async def latest(self, limit: int = 10) -> tuple[FamilyCollectionWindow, ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid window page")

        def read() -> tuple[FamilyCollectionWindow, ...]:
            with self._connection() as db:
                return tuple(
                    self._manifest(db, r[0])
                    for r in db.execute(
                        "SELECT window_id FROM collection_windows ORDER BY scheduled_at "
                        "DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                )

        return await asyncio.to_thread(read)

    async def claim_next(
        self, now: datetime
    ) -> FamilyCollectionWork | FamilyCollectionWindow | None:
        return await asyncio.to_thread(self._claim_next, _utc(now))

    def _claim_next(self, now: datetime) -> FamilyCollectionWork | FamilyCollectionWindow | None:
        with self._connection() as db:
            self._recover(db, now)
            # An expired source claim gets one SQL-only observation, never another dispatch.
            unknown = db.execute(
                "SELECT w.*,c.deadline FROM collection_work w JOIN "
                "collection_windows c "
                "ON c.window_id=w.window_id WHERE w.phase='unknown' AND "
                "w.observed=0 ORDER BY w.id LIMIT 1"
            ).fetchone()
            if unknown:
                db.execute("UPDATE collection_work SET observed=1 WHERE id=?", (unknown["id"],))
                return FamilyCollectionWork(
                    window_id=unknown["window_id"],
                    claim_id=unknown["claim_id"],
                    kind="observe_source",
                    position=unknown["id"],
                    target=FamilySourceTarget.model_validate_json(unknown["target"]),
                    deadline=unknown["deadline"],
                )
            active = db.execute(
                "SELECT * FROM collection_windows WHERE status='collecting' ORDER "
                "BY scheduled_at LIMIT 1"
            ).fetchone()
            policy = db.execute("SELECT * FROM collection_policy WHERE id=1").fetchone()
            due = datetime.fromisoformat(policy["next_due"])
            if active is None and due <= now:
                identity = str(uuid5(NAMESPACE_URL, self._configuration + "\0" + due.isoformat()))
                late = (now - due).total_seconds() > self.policy.start_grace_seconds
                db.execute(
                    "INSERT INTO collection_windows(window_id,scheduled_at,deadline,sta"
                    "tus,reason,started_offset) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        identity,
                        due.isoformat(),
                        (due + timedelta(seconds=self.policy.duration_seconds)).isoformat(),
                        "skipped" if late else "collecting",
                        "missed_window" if late else policy["inventory_blocked"],
                        policy["population_offset"],
                    ),
                )
                db.execute(
                    "UPDATE collection_policy SET next_due=? WHERE id=1",
                    (next_family_collection_window(now).isoformat(),),
                )
                if late:
                    return self._publish(db, identity, now)
                active = db.execute(
                    "SELECT * FROM collection_windows WHERE window_id=?", (identity,)
                ).fetchone()
            if active is None:
                return None
            identity = active["window_id"]
            reads = db.execute(
                "SELECT COUNT(*) FROM collection_work WHERE window_id=?", (identity,)
            ).fetchone()[0]
            queued = db.execute(
                "SELECT q.* FROM collection_queue q WHERE NOT EXISTS(SELECT 1 FROM "
                "collection_work w "
                "WHERE w.parent_id=q.parent_id AND w.child_id=q.child_id AND "
                "w.source=q.source AND "
                "(w.window_id=? OR w.phase IN ('claimed','unknown'))) ORDER BY "
                "q.id LIMIT 1",
                (identity,),
            ).fetchone()
            expires = min(
                now + timedelta(seconds=self.policy.claim_seconds),
                datetime.fromisoformat(active["deadline"]),
            )
            claim = str(uuid4())
            if queued:
                if reads >= self.policy.reads_per_window:
                    return self._stop(db, identity, "read_capacity", now)
                target = FamilySourceTarget(
                    parent_id=queued["parent_id"],
                    child_id=queued["child_id"],
                    source=queued["source"],
                    request_id=uuid5(
                        UUID(identity),
                        f"{queued['parent_id']}:{queued['child_id']}:{queued['source']}",
                    ),
                )
                cursor = db.execute(
                    "INSERT INTO collection_work(window_id,parent_id,child_id,source,ta"
                    "rget,claim_id,phase,claimed_at,expires_at) "
                    "VALUES(?,?,?,?,?,?,'claimed',?,?)",
                    (
                        identity,
                        target.parent_id,
                        target.child_id,
                        target.source,
                        target.model_dump_json(),
                        claim,
                        now.isoformat(),
                        expires.isoformat(),
                    ),
                )
                assert cursor.lastrowid is not None
                db.execute("DELETE FROM collection_queue WHERE id=?", (queued["id"],))
                return FamilyCollectionWork(
                    window_id=identity,
                    claim_id=claim,
                    kind="source",
                    position=cursor.lastrowid,
                    target=target,
                    deadline=active["deadline"],
                )
            if (
                db.execute(
                    "SELECT 1 FROM collection_work WHERE window_id=? AND phase='claimed'",
                    (identity,),
                ).fetchone()
                or db.execute(
                    "SELECT 1 FROM collection_pages WHERE window_id=? AND phase='claimed'",
                    (identity,),
                ).fetchone()
            ):
                return None
            if active["inventory_exhausted"]:
                unsettled = db.execute(
                    "SELECT 1 FROM collection_work WHERE window_id=? AND phase='unknown'",
                    (identity,),
                ).fetchone()
                pending = db.execute("SELECT 1 FROM collection_queue LIMIT 1").fetchone()
                refused = db.execute(
                    "SELECT 1 FROM collection_work WHERE window_id=? AND "
                    "(phase='skipped' OR json_extract(result,'$.status')='failed')",
                    (identity,),
                ).fetchone()
                db.execute(
                    "UPDATE collection_windows SET status=?,reason=?,published_at=? "
                    "WHERE window_id=?",
                    (
                        "unknown"
                        if unsettled
                        else "partial"
                        if pending or refused
                        else "completed",
                        "unknown_source"
                        if unsettled
                        else "prior_unknown_targets"
                        if pending
                        else "source_refused_or_failed"
                        if refused
                        else None,
                        now.isoformat(),
                        identity,
                    ),
                )
                return self._publish(db, identity, now)
            if reads >= self.policy.reads_per_window:
                return self._stop(db, identity, "read_capacity", now)
            pages = db.execute(
                "SELECT COUNT(*) FROM collection_pages WHERE window_id=?", (identity,)
            ).fetchone()[0]
            reserved = db.execute(
                "SELECT COUNT(*)*2 FROM collection_pages WHERE claimed_at>?",
                ((now - timedelta(days=1)).isoformat(),),
            ).fetchone()[0]
            if (
                policy["inventory_blocked"]
                or pages >= self.policy.pages_per_window
                or reserved + 2 > self.policy.inventory_attempts_per_24h
            ):
                return self._stop(
                    db, identity, policy["inventory_blocked"] or "inventory_capacity", now
                )
            offset = policy["population_offset"]
            if db.execute(
                "SELECT 1 FROM collection_pages WHERE window_id=? AND offset=?", (identity, offset)
            ).fetchone():
                return self._stop(db, identity, "inventory_not_advanced", now)
            cursor = db.execute(
                "INSERT INTO collection_pages(window_id,offset,claim_id,phase,claim"
                "ed_at,expires_at) "
                "VALUES(?,?,?,'claimed',?,?)",
                (identity, offset, claim, now.isoformat(), expires.isoformat()),
            )
            assert cursor.lastrowid is not None
            return FamilyCollectionWork(
                window_id=identity,
                claim_id=claim,
                kind="inventory",
                position=cursor.lastrowid,
                offset=offset,
                deadline=active["deadline"],
            )

    def _stop(
        self, db: sqlite3.Connection, identity: str, reason: str, now: datetime
    ) -> FamilyCollectionWindow:
        unknown = (
            db.execute(
                "SELECT 1 FROM collection_pages WHERE window_id=? AND phase='unknown'", (identity,)
            ).fetchone()
            or db.execute(
                "SELECT 1 FROM collection_work WHERE window_id=? AND phase='unknown'", (identity,)
            ).fetchone()
        )
        db.execute(
            "UPDATE collection_windows SET status=?,reason=?,published_at=? "
            "WHERE window_id=? AND status='collecting'",
            ("unknown" if unknown else "partial", reason, now.isoformat(), identity),
        )
        return self._publish(db, identity, now)

    async def finish_page(
        self, work: FamilyCollectionWork, page: FamilyInventoryPage, now: datetime
    ) -> None:
        await asyncio.to_thread(self._finish_page, work, page, _utc(now))

    def _finish_page(
        self, work: FamilyCollectionWork, page: FamilyInventoryPage, now: datetime
    ) -> None:
        checked = FamilyInventoryPage.model_validate(page.model_dump())
        if checked.offset != work.offset or checked.limit != self.policy.page_size:
            raise ValueError("A collection page must match its original claim")
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM collection_pages WHERE id=? AND window_id=? AND claim_id=?",
                (work.position, str(work.window_id), str(work.claim_id)),
            ).fetchone()
            if row is None:
                raise ValueError("Unknown collection page claim")
            if row["phase"] not in {"claimed", "unknown"}:
                return
            if (
                not datetime.fromisoformat(row["claimed_at"]) - timedelta(seconds=5)
                <= checked.collected_at
                <= now
            ):
                raise ValueError("Invalid inventory collection time")
            active = db.execute(
                "SELECT * FROM collection_windows WHERE window_id=?", (str(work.window_id),)
            ).fetchone()
            late = (
                row["phase"] == "unknown"
                or now >= work.deadline
                or active["status"] != "collecting"
            )
            db.execute(
                "UPDATE collection_pages SET "
                "phase=?,payload_hash=?,parent_count=?,total_parents=? WHERE id=?",
                (
                    "late" if late else "recorded",
                    _digest(checked.model_dump_json()),
                    len(checked.families),
                    checked.total_parents,
                    work.position,
                ),
            )
            if late:
                db.execute(
                    "UPDATE collection_policy SET inventory_blocked=NULL WHERE id=1 "
                    "AND inventory_blocked='inventory_unknown'"
                )
                return
            targets = {
                (p.parent_id, c, s)
                for p in checked.families
                for c in p.connected_child_ids
                for s in self.sources
            }
            size = db.execute("SELECT COUNT(*) FROM collection_queue").fetchone()[0]
            if size + len(targets) > self.policy.maximum_queued_targets:
                self._stop(db, str(work.window_id), "target_capacity", now)
                return
            for family in checked.families:
                if db.execute(
                    "SELECT 1 FROM collection_parents WHERE window_id=? AND parent_id=?",
                    (str(work.window_id), family.parent_id),
                ).fetchone():
                    db.execute(
                        "UPDATE collection_windows SET inventory_changed=1 WHERE window_id=?",
                        (str(work.window_id),),
                    )
                db.execute(
                    "INSERT OR IGNORE INTO collection_parents VALUES(?,?)",
                    (str(work.window_id), family.parent_id),
                )
            for parent, child, source in sorted(targets):
                db.execute(
                    "INSERT OR IGNORE INTO "
                    "collection_queue(parent_id,child_id,source,discovered_at) "
                    "SELECT ?,?,?,? WHERE NOT EXISTS(SELECT 1 FROM collection_work "
                    "WHERE window_id=? AND parent_id=? AND child_id=? AND source=?)",
                    (
                        parent,
                        child,
                        source,
                        now.isoformat(),
                        str(work.window_id),
                        parent,
                        child,
                        source,
                    ),
                )
            changed = (
                active["last_total"] is not None and active["last_total"] != checked.total_parents
            )
            db.execute(
                "UPDATE collection_windows SET "
                "inventory_exhausted=?,inventory_changed=MAX(inventory_changed,?),l"
                "ast_total=? WHERE window_id=?",
                (int(checked.exhausted), int(changed), checked.total_parents, str(work.window_id)),
            )
            db.execute(
                "UPDATE collection_policy SET population_offset=? WHERE id=1",
                (0 if checked.exhausted else checked.offset + len(checked.families),),
            )

    async def fail_page(
        self, work: FamilyCollectionWork, code: str, now: datetime, *, unknown: bool
    ) -> None:
        def fail() -> None:
            with self._connection() as db:
                row = db.execute(
                    "SELECT phase FROM collection_pages WHERE id=? AND claim_id=?",
                    (work.position, str(work.claim_id)),
                ).fetchone()
                if row is None or row[0] != "claimed":
                    return
                db.execute(
                    "UPDATE collection_pages SET phase=? WHERE id=?",
                    ("unknown" if unknown else "failed", work.position),
                )
                db.execute(
                    "UPDATE collection_policy SET inventory_blocked=? WHERE id=1",
                    ("inventory_unknown" if unknown else code,),
                )
                db.execute(
                    "UPDATE collection_windows SET status=?,reason=? WHERE window_id=?",
                    ("unknown" if unknown else "partial", code, str(work.window_id)),
                )
                self._publish(db, str(work.window_id), _utc(now))

        await asyncio.to_thread(fail)

    async def finish_source(
        self,
        work: FamilyCollectionWork,
        receipt: FamilySourceReceipt | None,
        now: datetime,
        *,
        refusal: str | None = None,
        stop_window: bool = False,
    ) -> None:
        if work.target is None:
            raise ValueError("A source claim is required")
        result: dict[str, Any] = {
            "status": "unknown" if refusal is None else "skipped",
            "refusal": refusal,
        }
        if receipt is not None:
            checked = FamilySourceReceipt.model_validate(receipt.model_dump())
            if (checked.parent_id, checked.child_id, checked.source, checked.request_id) != (
                work.target.parent_id,
                work.target.child_id,
                work.target.source,
                work.target.request_id,
            ):
                raise ValueError("Collection receipt does not match its original source claim")
            facts = checked.facts if checked.status == "completed" else None
            result = {
                "status": checked.status,
                "receipt_hash": _digest(checked.model_dump_json()),
                "snapshot_id": str(checked.snapshot_id) if checked.snapshot_id else None,
                "facts_fingerprint": facts.fingerprint() if facts else None,
                "cache_hits": checked.cache_hit and checked.status == "completed",
                "available": facts is not None and facts.status == "available",
                "undated": facts is not None
                and facts.status == "available"
                and facts.observed_at is None,
                "low_battery_records": isinstance(facts, ChildBatteryFacts)
                and facts.percent is not None
                and facts.percent <= 20,
                "partial_counter_pages": isinstance(facts, ChildAppUsageFacts)
                and not facts.complete,
                "collected_at": facts.collected_at.isoformat() if facts else None,
                "observed_at": facts.observed_at.isoformat()
                if facts and facts.observed_at
                else None,
                "source_updated_at": facts.source_updated_at.isoformat()
                if facts and facts.source_updated_at
                else None,
                "read_finished_at": checked.finished_at.isoformat()
                if checked.finished_at
                else None,
            }

        def finish() -> None:
            with self._connection() as db:
                row = db.execute(
                    "SELECT phase FROM collection_work WHERE id=? AND window_id=? AND claim_id=?",
                    (work.position, str(work.window_id), str(work.claim_id)),
                ).fetchone()
                if row is None:
                    raise ValueError("Unknown collection source claim")
                if row[0] not in {"claimed", "unknown"}:
                    return
                phase = (
                    "unknown"
                    if result["status"] in {"pending", "unknown"}
                    else "skipped"
                    if refusal
                    else "recorded"
                )
                db.execute(
                    "UPDATE collection_work SET phase=?,result=?,observed=1 WHERE id=?",
                    (phase, json.dumps(result, sort_keys=True), work.position),
                )
                if stop_window:
                    self._stop(db, str(work.window_id), refusal or "source_capacity", _utc(now))

        await asyncio.to_thread(finish)
