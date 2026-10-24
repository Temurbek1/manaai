"""Dedicated shared family-source cache and conservative, one-shot read ledger."""

import asyncio
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.family_sources import (
    ChildBatteryFacts,
    FamilySourceChange,
    FamilySourceClaim,
    FamilySourceLimits,
    FamilySourceReceipt,
    FamilySourceTarget,
)

_TABLES = {"source_policy", "source_reads", "source_snapshots", "source_heads", "source_changes"}
_APPLICATION = 1296125507


class SqliteFamilySourceStore:
    """No family chat/schema migration and no source, model or send side effects."""

    def __init__(self, path: Path, *, binding: str, limits: FamilySourceLimits) -> None:
        if not binding or len(binding) > 256 or binding == "unverified":
            raise ValueError("A confirmed source binding is required")
        if path == Path(":memory:"):
            raise ValueError("Source admissions require durable storage")
        self._path, self._binding = path, binding
        self._limits = FamilySourceLimits.model_validate(limits.model_dump())

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, isolation_level=None, timeout=10)
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

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._path.is_symlink() or self._path.parent.is_symlink():
            raise ValueError("Source storage cannot use symlinks")
        try:
            descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with self._connection() as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            application = connection.execute("PRAGMA application_id").fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if tables - _TABLES or application not in {0, _APPLICATION} or version not in {0, 1}:
                raise ValueError("Source cache requires its dedicated database")
            if tables and (application != _APPLICATION or tables != _TABLES or version != 1):
                raise ValueError("Incomplete or unrelated source schema")
            statements = (
                "CREATE TABLE IF NOT EXISTS source_policy ("
                "id INTEGER PRIMARY KEY CHECK(id=1), binding TEXT NOT NULL, "
                "limits TEXT NOT NULL, blocked INTEGER NOT NULL DEFAULT 0)",
                "CREATE TABLE IF NOT EXISTS source_reads ("
                "parent_id TEXT NOT NULL, request_id TEXT NOT NULL, child_id INTEGER NOT NULL, "
                "started_at TEXT NOT NULL, status TEXT NOT NULL "
                "CHECK(status IN ('pending','completed','failed','unknown')), "
                "units INTEGER NOT NULL CHECK(units IN (0,2)), "
                "payload TEXT NOT NULL, PRIMARY KEY(parent_id,request_id))",
                "CREATE UNIQUE INDEX IF NOT EXISTS source_one_unresolved ON source_reads(child_id) "
                "WHERE status IN ('pending','unknown')",
                "CREATE INDEX IF NOT EXISTS source_rolling_budget ON source_reads(started_at)",
                "CREATE TABLE IF NOT EXISTS source_snapshots ("
                "snapshot_id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, child_id INTEGER NOT NULL, "
                "fingerprint TEXT NOT NULL, payload TEXT NOT NULL, "
                "UNIQUE(parent_id,child_id,fingerprint))",
                "CREATE TABLE IF NOT EXISTS source_heads ("
                "parent_id TEXT NOT NULL, child_id INTEGER NOT NULL, snapshot_id TEXT NOT NULL, "
                "checked_at TEXT NOT NULL, PRIMARY KEY(parent_id,child_id))",
                "CREATE TABLE IF NOT EXISTS source_changes ("
                "id INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, parent_id TEXT NOT NULL, "
                "payload TEXT NOT NULL)",
            )
            for statement in statements:
                connection.execute(statement)
            known = connection.execute(
                "SELECT binding,limits FROM source_policy WHERE id=1"
            ).fetchone()
            if known is not None and (
                known["binding"] != self._binding
                or known["limits"] != self._limits.model_dump_json()
            ):
                raise ValueError("Source binding/limits cannot change behind existing admissions")
            connection.execute(
                "INSERT OR IGNORE INTO source_policy(id,binding,limits) VALUES(1,?,?)",
                (self._binding, self._limits.model_dump_json()),
            )
            connection.execute(f"PRAGMA application_id={_APPLICATION}")
            connection.execute("PRAGMA user_version=1")

    @staticmethod
    def _time(now: datetime) -> datetime:
        if now.utcoffset() is None:
            raise ValueError("Source clock must be timezone-aware")
        return now.astimezone(UTC)

    def _known(
        self, connection: sqlite3.Connection, target: FamilySourceTarget
    ) -> FamilySourceReceipt | None:
        row = connection.execute(
            "SELECT payload FROM source_reads WHERE parent_id=? AND request_id=?",
            (target.parent_id, str(target.request_id)),
        ).fetchone()
        if row is None:
            return None
        receipt = FamilySourceReceipt.model_validate_json(row["payload"])
        if (
            receipt.child_id != target.child_id
            or receipt.parent_id != target.parent_id
            or receipt.request_id != target.request_id
        ):
            raise ParentChatError("family_source_request_conflict", 409)
        return receipt

    async def observation(self, target: FamilySourceTarget) -> FamilySourceReceipt:
        def observe() -> FamilySourceReceipt:
            with self._connection() as connection:
                known = self._known(connection, target)
                if known is None:
                    raise ParentChatError("family_source_request_not_found", 404)
                return known

        return await asyncio.to_thread(observe)

    async def claim(self, target: FamilySourceTarget, now: datetime) -> FamilySourceClaim:
        return await asyncio.to_thread(self._claim, target, self._time(now))

    def _claim(self, target: FamilySourceTarget, now: datetime) -> FamilySourceClaim:
        with self._connection() as connection:
            known = self._known(connection, target)
            if known is not None:
                return FamilySourceClaim(receipt=known, admitted=False, read_provider=False)
            if connection.execute("SELECT blocked FROM source_policy WHERE id=1").fetchone()[0]:
                raise ParentChatError("family_source_circuit_open", 503)
            if connection.execute(
                "SELECT 1 FROM source_reads WHERE child_id=? AND status IN ('pending','unknown')",
                (target.child_id,),
            ).fetchone():
                raise ParentChatError("family_source_read_unresolved", 409)
            budget = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(units),0) FROM source_reads WHERE started_at>?",
                ((now - timedelta(days=1)).isoformat(),),
            ).fetchone()
            if budget[0] >= self._limits.requests_per_24h:
                raise ParentChatError("family_source_request_limit", 429)
            head = connection.execute(
                "SELECT h.snapshot_id,h.checked_at,s.payload,s.fingerprint FROM source_heads h "
                "LEFT JOIN source_snapshots s ON s.snapshot_id=h.snapshot_id "
                "AND s.parent_id=h.parent_id AND s.child_id=h.child_id "
                "WHERE h.parent_id=? AND h.child_id=?",
                (target.parent_id, target.child_id),
            ).fetchone()
            if head is not None and (
                head["payload"] is None
                or ChildBatteryFacts.model_validate_json(head["payload"]).fingerprint()
                != head["fingerprint"]
            ):
                raise ParentChatError("family_source_cache_invalid", 503)
            cache = head is not None and (
                now - timedelta(seconds=self._limits.minimum_interval_seconds)
                < datetime.fromisoformat(head["checked_at"])
                <= now
            )
            if not cache:
                previous = connection.execute(
                    "SELECT started_at FROM source_reads WHERE child_id=? AND units>0 "
                    "ORDER BY started_at DESC LIMIT 1",
                    (target.child_id,),
                ).fetchone()
                if previous and now < datetime.fromisoformat(previous[0]) + timedelta(
                    seconds=self._limits.minimum_interval_seconds
                ):
                    raise ParentChatError("family_source_read_cooldown", 429)
                if budget[1] + 2 > self._limits.document_units_per_24h:
                    raise ParentChatError("family_source_document_limit", 429)
            receipt = FamilySourceReceipt(
                parent_id=target.parent_id,
                child_id=target.child_id,
                request_id=target.request_id,
                status="pending",
                started_at=now,
                cache_hit=cache,
                document_units_reserved=0 if cache else 2,
                snapshot_id=UUID(head["snapshot_id"]) if cache else None,
                facts=ChildBatteryFacts.model_validate_json(head["payload"]) if cache else None,
            )
            connection.execute(
                "INSERT INTO source_reads VALUES(?,?,?,?,?,?,?)",
                (
                    target.parent_id,
                    str(target.request_id),
                    target.child_id,
                    now.isoformat(),
                    "pending",
                    receipt.document_units_reserved,
                    receipt.model_dump_json(),
                ),
            )
            return FamilySourceClaim(receipt=receipt, admitted=True, read_provider=not cache)

    async def complete(
        self, target: FamilySourceTarget, facts: ChildBatteryFacts, now: datetime
    ) -> FamilySourceReceipt:
        return await asyncio.to_thread(self._complete, target, facts, self._time(now))

    def _complete(
        self, target: FamilySourceTarget, facts: ChildBatteryFacts, now: datetime
    ) -> FamilySourceReceipt:
        facts = ChildBatteryFacts.model_validate(facts.model_dump())
        if facts.child_id != target.child_id:
            raise ParentChatError("family_source_snapshot_mismatch", 503)
        fingerprint = facts.fingerprint()
        with self._connection() as connection:
            receipt = self._known(connection, target)
            if receipt is None:
                raise ParentChatError("family_source_request_not_found", 404)
            if receipt.status != "pending":
                return receipt
            if now < receipt.started_at:
                raise ValueError("Source completion cannot precede admission")
            if receipt.cache_hit:
                if receipt.facts is None or receipt.facts != facts:
                    raise ValueError("Cached receipt must retain its original facts")
                snapshot_id = receipt.snapshot_id
            else:
                known = connection.execute(
                    "SELECT snapshot_id,payload FROM source_snapshots "
                    "WHERE parent_id=? AND child_id=? AND fingerprint=?",
                    (target.parent_id, target.child_id, fingerprint),
                ).fetchone()
                snapshot_id = UUID(known["snapshot_id"]) if known else uuid4()
                if known:
                    facts = ChildBatteryFacts.model_validate_json(known["payload"])
                else:
                    connection.execute(
                        "INSERT INTO source_snapshots VALUES(?,?,?,?,?)",
                        (
                            str(snapshot_id),
                            target.parent_id,
                            target.child_id,
                            fingerprint,
                            facts.model_dump_json(),
                        ),
                    )
                head = connection.execute(
                    "SELECT snapshot_id FROM source_heads WHERE parent_id=? AND child_id=?",
                    (target.parent_id, target.child_id),
                ).fetchone()
                if head is None or head[0] != str(snapshot_id):
                    event = FamilySourceChange(
                        event_id=uuid4(),
                        parent_id=target.parent_id,
                        child_id=target.child_id,
                        snapshot_id=snapshot_id,
                        fingerprint=fingerprint,
                        recorded_at=now,
                    )
                    connection.execute(
                        "INSERT INTO source_changes(event_id,parent_id,payload) VALUES(?,?,?)",
                        (str(event.event_id), target.parent_id, event.model_dump_json()),
                    )
                connection.execute(
                    "INSERT INTO source_heads VALUES(?,?,?,?) ON CONFLICT(parent_id,child_id) "
                    "DO UPDATE SET snapshot_id=excluded.snapshot_id,checked_at=excluded.checked_at",
                    (target.parent_id, target.child_id, str(snapshot_id), now.isoformat()),
                )
            completed = FamilySourceReceipt.model_validate(
                receipt.model_dump()
                | {
                    "status": "completed",
                    "finished_at": now,
                    "snapshot_id": snapshot_id,
                    "facts": facts,
                }
            )
            connection.execute(
                "UPDATE source_reads SET status='completed',payload=? "
                "WHERE parent_id=? AND request_id=?",
                (completed.model_dump_json(), target.parent_id, str(target.request_id)),
            )
            return completed

    async def fail(
        self,
        target: FamilySourceTarget,
        now: datetime,
        *,
        code: str,
        unknown: bool,
        close_source: bool,
    ) -> FamilySourceReceipt:
        def fail() -> FamilySourceReceipt:
            with self._connection() as connection:
                receipt = self._known(connection, target)
                if receipt is None:
                    raise ParentChatError("family_source_request_not_found", 404)
                if receipt.status != "pending":
                    return receipt
                failed = FamilySourceReceipt.model_validate(
                    receipt.model_dump()
                    | {
                        "status": "unknown" if unknown else "failed",
                        "finished_at": self._time(now),
                        "error_code": code,
                        "facts": None,
                        "snapshot_id": None,
                    }
                )
                connection.execute(
                    "UPDATE source_reads SET status=?,payload=? WHERE parent_id=? AND request_id=?",
                    (
                        failed.status,
                        failed.model_dump_json(),
                        target.parent_id,
                        str(target.request_id),
                    ),
                )
                if close_source:
                    connection.execute("UPDATE source_policy SET blocked=1 WHERE id=1")
                return failed

        return await asyncio.to_thread(fail)

    async def changes(
        self, parent_id: str, *, after: int = 0, limit: int = 50
    ) -> list[tuple[int, FamilySourceChange]]:
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid change page")

        def read() -> list[tuple[int, FamilySourceChange]]:
            with self._connection() as connection:
                return [
                    (row["id"], FamilySourceChange.model_validate_json(row["payload"]))
                    for row in connection.execute(
                        "SELECT id,payload FROM source_changes WHERE parent_id=? AND id>? "
                        "ORDER BY id LIMIT ?",
                        (parent_id, after, limit),
                    )
                ]

        return await asyncio.to_thread(read)

    async def snapshot(self, parent_id: str, child_id: int, snapshot_id: UUID) -> ChildBatteryFacts:
        def read_snapshot() -> ChildBatteryFacts:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT payload,fingerprint FROM source_snapshots "
                    "WHERE snapshot_id=? AND parent_id=? AND child_id=?",
                    (str(snapshot_id), parent_id, child_id),
                ).fetchone()
                if row is None:
                    raise ParentChatError("family_source_snapshot_not_found", 404)
                facts = ChildBatteryFacts.model_validate_json(row["payload"])
                if facts.child_id != child_id or facts.fingerprint() != row["fingerprint"]:
                    raise ParentChatError("family_source_cache_invalid", 503)
                return facts

        return await asyncio.to_thread(read_snapshot)
