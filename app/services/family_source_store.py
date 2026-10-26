"""Dedicated shared family-source cache and conservative, one-shot read ledger."""

import asyncio
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.family_sources import (
    ChildSourceFacts,
    FamilySourceChange,
    FamilySourceClaim,
    FamilySourceKey,
    FamilySourceLimits,
    FamilySourceReceipt,
    FamilySourceTarget,
    source_facts,
)
from app.mana_ai.domain.source_reviews import SourceAnalysisOwner

_TABLES = {"source_policy", "source_reads", "source_snapshots", "source_heads", "source_changes"}
_APPLICATION = 1296125507


class SqliteFamilySourceStore:
    """No family chat/schema migration and no source, model or send side effects."""

    _schema_version = 1
    _extra_tables: frozenset[str] = frozenset()

    def _version_tables(self, version: int) -> set[str]:
        return _TABLES | self._extra_tables if version == self._schema_version else _TABLES

    def _upgrade_versions(self) -> set[int]:
        return {1}

    def _check_source(self, source: FamilySourceKey) -> None:
        if source != "firebase.child_battery.v1":
            raise ParentChatError("family_source_not_enabled", 503)

    def _snapshots(self, source: FamilySourceKey) -> str:
        return "source_snapshots"

    def _heads(self, source: FamilySourceKey) -> str:
        return "source_heads"

    def _circuit(self, source: FamilySourceKey) -> str:
        return "source_policy"

    def _extra_schema(self) -> tuple[str, ...]:
        return ()

    def _initialize_additional(self, connection: sqlite3.Connection) -> None:
        """Optional consumers initialize atomically with their private schema."""

    def _source_changed(self, connection: sqlite3.Connection, event: FamilySourceChange) -> None:
        """Capture optional consumer admission in the same source transaction."""

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
            expected = _TABLES | self._extra_tables
            if (
                tables - expected
                or application not in {0, _APPLICATION}
                or version not in {0, self._schema_version} | self._upgrade_versions()
            ):
                raise ValueError("Source cache requires its dedicated database")
            original_tables = self._version_tables(version)
            if tables and (
                application != _APPLICATION or tables != original_tables or version == 0
            ):
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
            for statement in statements + self._extra_schema():
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
            self._initialize_additional(connection)
            connection.execute(f"PRAGMA application_id={_APPLICATION}")
            connection.execute(f"PRAGMA user_version={self._schema_version}")

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
            or receipt.source != target.source
        ):
            raise ParentChatError("family_source_request_conflict", 409)
        return receipt

    async def observation(self, target: FamilySourceTarget) -> FamilySourceReceipt:
        self._check_source(target.source)

        def observe() -> FamilySourceReceipt:
            with self._connection() as connection:
                known = self._known(connection, target)
                if known is None:
                    raise ParentChatError("family_source_request_not_found", 404)
                return known

        return await asyncio.to_thread(observe)

    async def claim(self, target: FamilySourceTarget, now: datetime) -> FamilySourceClaim:
        return await asyncio.to_thread(self._claim, target, self._time(now))

    async def claim_for_analysis(
        self, target: FamilySourceTarget, owner: SourceAnalysisOwner, now: datetime
    ) -> FamilySourceClaim:
        raise ParentChatError("source_review_owner_not_enabled", 503)

    def _claim(self, target: FamilySourceTarget, now: datetime) -> FamilySourceClaim:
        self._check_source(target.source)
        with self._connection() as connection:
            known = self._known(connection, target)
            if known is not None:
                return FamilySourceClaim(receipt=known, admitted=False, read_provider=False)
            if connection.execute(
                f"SELECT blocked FROM {self._circuit(target.source)} WHERE id=1"
            ).fetchone()[0]:
                raise ParentChatError("family_source_circuit_open", 503)
            if connection.execute(
                "SELECT 1 FROM source_reads WHERE child_id=? "
                "AND json_extract(payload,'$.source')=? AND status IN ('pending','unknown')",
                (target.child_id, target.source),
            ).fetchone():
                raise ParentChatError("family_source_read_unresolved", 409)
            budget = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(units),0) FROM source_reads WHERE started_at>?",
                ((now - timedelta(days=1)).isoformat(),),
            ).fetchone()
            if budget[0] >= self._limits.requests_per_24h:
                raise ParentChatError("family_source_request_limit", 429)
            head = connection.execute(
                f"SELECT h.snapshot_id,h.checked_at,s.payload,s.fingerprint "
                f"FROM {self._heads(target.source)} h "
                f"LEFT JOIN {self._snapshots(target.source)} s ON s.snapshot_id=h.snapshot_id "
                "AND s.parent_id=h.parent_id AND s.child_id=h.child_id "
                "WHERE h.parent_id=? AND h.child_id=?",
                (target.parent_id, target.child_id),
            ).fetchone()
            if head is not None and (
                head["payload"] is None
                or source_facts(json.loads(head["payload"]), target.source).fingerprint()
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
                    "SELECT started_at FROM source_reads WHERE child_id=? "
                    "AND json_extract(payload,'$.source')=? "
                    "AND json_extract(payload,'$.cache_hit')=0 "
                    "ORDER BY started_at DESC LIMIT 1",
                    (target.child_id, target.source),
                ).fetchone()
                if previous and now < datetime.fromisoformat(previous[0]) + timedelta(
                    seconds=self._limits.minimum_interval_seconds
                ):
                    raise ParentChatError("family_source_read_cooldown", 429)
                units = 0 if target.source == "manakids.child_app_usage.v1" else 2
                if budget[1] + units > self._limits.document_units_per_24h:
                    raise ParentChatError("family_source_document_limit", 429)
            receipt = FamilySourceReceipt(
                parent_id=target.parent_id,
                child_id=target.child_id,
                request_id=target.request_id,
                source=target.source,
                status="pending",
                started_at=now,
                cache_hit=cache,
                document_units_reserved=0
                if cache or target.source == "manakids.child_app_usage.v1"
                else 2,
                snapshot_id=UUID(head["snapshot_id"]) if cache else None,
                facts=source_facts(json.loads(head["payload"]), target.source) if cache else None,
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
        self, target: FamilySourceTarget, facts: ChildSourceFacts, now: datetime
    ) -> FamilySourceReceipt:
        return await asyncio.to_thread(self._complete, target, facts, self._time(now))

    def _complete(
        self, target: FamilySourceTarget, facts: ChildSourceFacts, now: datetime
    ) -> FamilySourceReceipt:
        self._check_source(target.source)
        facts = source_facts(facts.model_dump(), target.source)
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
                    f"SELECT snapshot_id,payload FROM {self._snapshots(target.source)} "
                    "WHERE parent_id=? AND child_id=? AND fingerprint=?",
                    (target.parent_id, target.child_id, fingerprint),
                ).fetchone()
                snapshot_id = UUID(known["snapshot_id"]) if known else uuid4()
                if known:
                    facts = source_facts(json.loads(known["payload"]), target.source)
                else:
                    connection.execute(
                        f"INSERT INTO {self._snapshots(target.source)} VALUES(?,?,?,?,?)",
                        (
                            str(snapshot_id),
                            target.parent_id,
                            target.child_id,
                            fingerprint,
                            facts.model_dump_json(),
                        ),
                    )
                head = connection.execute(
                    f"SELECT snapshot_id FROM {self._heads(target.source)} "
                    "WHERE parent_id=? AND child_id=?",
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
                        source=target.source,
                    )
                    connection.execute(
                        "INSERT INTO source_changes(event_id,parent_id,payload) VALUES(?,?,?)",
                        (str(event.event_id), target.parent_id, event.model_dump_json()),
                    )
                    self._source_changed(connection, event)
                connection.execute(
                    f"INSERT INTO {self._heads(target.source)} VALUES(?,?,?,?) "
                    "ON CONFLICT(parent_id,child_id) "
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
        self._check_source(target.source)

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
                    connection.execute(
                        f"UPDATE {self._circuit(target.source)} SET blocked=1 WHERE id=1"
                    )
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

    async def snapshot(
        self,
        parent_id: str,
        child_id: int,
        snapshot_id: UUID,
        *,
        source: FamilySourceKey = "firebase.child_battery.v1",
    ) -> ChildSourceFacts:
        self._check_source(source)

        def read_snapshot() -> ChildSourceFacts:
            with self._connection() as connection:
                row = connection.execute(
                    f"SELECT payload,fingerprint FROM {self._snapshots(source)} "
                    "WHERE snapshot_id=? AND parent_id=? AND child_id=?",
                    (str(snapshot_id), parent_id, child_id),
                ).fetchone()
                if row is None:
                    raise ParentChatError("family_source_snapshot_not_found", 404)
                facts = source_facts(json.loads(row["payload"]), source)
                if facts.child_id != child_id or facts.fingerprint() != row["fingerprint"]:
                    raise ParentChatError("family_source_cache_invalid", 503)
                return facts

        return await asyncio.to_thread(read_snapshot)
