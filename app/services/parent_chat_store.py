"""Dedicated, single-host SQLite persistence, never the operations database.

Short IMMEDIATE transactions serialize admission across workers. No transaction is
held during HTTP/model calls. A lost submitted receipt remains reserved indefinitely.
"""

import asyncio
import hashlib
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.domain.chat import (
    ChatQuota,
    ParentChatHistory,
    ParentChatMessage,
    ParentChatRequest,
    ParentChatResponse,
    StoredChatTurn,
)


class SqliteParentChatStore:
    _schema_version = 1

    def _supported_versions(self) -> set[int]:
        return {0, 1, self._schema_version}

    def _allowed_tables(self) -> set[str]:
        return {"parent_chat_turns", "parent_chat_quota"}

    def _extra_schema(self) -> str:
        return ""

    def _on_admitted(
        self,
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        now: datetime,
    ) -> None:
        """Extension work shares the admission transaction; legacy mode is unchanged."""

    def _valid_decision(
        self,
        connection: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        now: datetime,
    ) -> bool:
        return receipt.question_id is None

    def _on_settled(
        self,
        connection: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        """Extension work shares verified accounting and publication, never a callback."""

    def _on_failed(
        self, connection: sqlite3.Connection, turn: StoredChatTurn, *, unknown: bool
    ) -> None:
        """No queue state exists in the legacy adapter."""

    def __init__(
        self, path: Path, *, daily_limit: int, timezone: str, max_attempts: int = 20
    ) -> None:
        self._path = path
        self._limit = daily_limit
        self._zone = ZoneInfo(timezone)
        self._max_attempts = max_attempts

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self._path.is_symlink():
            raise RuntimeError("Parent chat storage must not be a symbolic link")
        try:
            descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with self._connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name != 'sqlite_sequence'"
                )
            }
            if tables - self._allowed_tables():
                raise RuntimeError("Parent chat requires a dedicated database")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in self._supported_versions():
                raise RuntimeError("Unsupported parent chat storage version")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(f"""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS parent_chat_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    parent_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    day TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reserved INTEGER NOT NULL CHECK(reserved >= 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    answer TEXT,
                    result TEXT,
                    error_code TEXT,
                    error_status INTEGER,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    model TEXT,
                    UNIQUE(parent_id, request_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS parent_chat_one_pending
                    ON parent_chat_turns(parent_id)
                    WHERE status IN ('preparing', 'submitted', 'unknown');
                CREATE INDEX IF NOT EXISTS parent_chat_history
                    ON parent_chat_turns(parent_id, id);
                CREATE TABLE IF NOT EXISTS parent_chat_quota (
                    parent_id TEXT NOT NULL,
                    day TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0 CHECK(used >= 0),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(parent_id, day)
                );
                {self._extra_schema()}
                PRAGMA user_version={self._schema_version};
                COMMIT;
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self._path.resolve().as_uri() + "?mode=rw",
            uri=True,
            timeout=10,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def _period(self, now: datetime) -> tuple[str, datetime]:
        if now.utcoffset() is None:
            raise ValueError("Parent chat requires an aware clock")
        local = now.astimezone(self._zone)
        tomorrow = local.date() + timedelta(days=1)
        return local.date().isoformat(), datetime.combine(
            tomorrow, datetime.min.time(), self._zone
        ).astimezone(UTC)

    @staticmethod
    def _utc(now: datetime) -> datetime:
        if now.utcoffset() is None:
            raise ValueError("Parent chat requires an aware clock")
        return now.astimezone(UTC)

    def _quota(self, connection: sqlite3.Connection, parent_id: str, now: datetime) -> ChatQuota:
        day, reset = self._period(now)
        row = connection.execute(
            "SELECT used FROM parent_chat_quota WHERE parent_id=? AND day=?", (parent_id, day)
        ).fetchone()
        used = row[0] if row is not None else 0
        reserved = connection.execute(
            "SELECT COALESCE(SUM(reserved), 0) FROM parent_chat_turns "
            "WHERE parent_id=? AND day=? AND status IN ('preparing', 'submitted', 'unknown')",
            (parent_id, day),
        ).fetchone()[0]
        unresolved = (
            connection.execute(
                "SELECT 1 FROM parent_chat_turns WHERE parent_id=? "
                "AND status IN ('submitted', 'unknown') LIMIT 1",
                (parent_id,),
            ).fetchone()
            is not None
        )
        return ChatQuota(
            daily_limit=self._limit,
            used_tokens=used,
            reserved_tokens=reserved,
            remaining_tokens=max(0, self._limit - used - reserved),
            resets_at=reset,
            timezone=self._zone.key,
            blocked_by_unresolved_request=unresolved,
        )

    @staticmethod
    def _recover_pre_dispatch(
        connection: sqlite3.Connection, parent_id: str, now: datetime
    ) -> None:
        cutoff = (now - timedelta(minutes=5)).isoformat()
        connection.execute(
            "UPDATE parent_chat_turns SET status='failed', reserved=0, "
            "error_code='preparation_abandoned', error_status=503 "
            "WHERE parent_id=? AND status='preparing' AND created_at < ?",
            (parent_id, cutoff),
        )
        connection.execute(
            "UPDATE parent_chat_turns SET status='unknown', error_code='model_receipt_unknown', "
            "error_status=503 WHERE parent_id=? AND status='submitted' AND updated_at < ?",
            (parent_id, cutoff),
        )

    async def admit(self, request: ParentChatRequest, now: datetime) -> StoredChatTurn:
        return await asyncio.to_thread(self._admit, request, now)

    def _admit(self, request: ParentChatRequest, now: datetime) -> StoredChatTurn:
        now = self._utc(now)
        failure: ParentChatError | None = None
        admitted: StoredChatTurn | None = None
        with self._transaction() as connection:
            self._recover_pre_dispatch(connection, request.parent_id, now)
            existing = connection.execute(
                "SELECT * FROM parent_chat_turns WHERE parent_id=? AND request_id=?",
                (request.parent_id, str(request.request_id)),
            ).fetchone()
            if existing is not None:
                if existing["request_digest"] != self._digest(request):
                    failure = ParentChatError("request_id_conflict", 409)
                elif existing["result"] is not None:
                    admitted = self._turn(existing)
                else:
                    failure = ParentChatError(
                        existing["error_code"] or "request_in_progress",
                        existing["error_status"] or 409,
                    )
            elif (
                connection.execute(
                    "SELECT 1 FROM parent_chat_turns WHERE parent_id=? "
                    "AND status IN ('preparing', 'submitted', 'unknown')",
                    (request.parent_id,),
                ).fetchone()
                is not None
            ):
                failure = ParentChatError("previous_request_unresolved", 409)
            else:
                quota = self._quota(connection, request.parent_id, now)
                day, _ = self._period(now)
                connection.execute(
                    "INSERT OR IGNORE INTO parent_chat_quota(parent_id, day) VALUES (?, ?)",
                    (request.parent_id, day),
                )
                attempts = connection.execute(
                    "SELECT attempts FROM parent_chat_quota WHERE parent_id=? AND day=?",
                    (request.parent_id, day),
                ).fetchone()[0]
                retry = max(1, int((quota.resets_at - now).total_seconds()))
                if quota.remaining_tokens < 32:
                    failure = ParentChatError("daily_token_budget_exceeded", 429, retry_after=retry)
                elif attempts >= self._max_attempts:
                    failure = ParentChatError(
                        "daily_request_limit_exceeded", 429, retry_after=retry
                    )
                else:
                    cursor = connection.execute(
                        "INSERT INTO parent_chat_turns "
                        "(parent_id, request_id, message, request_digest, day, status, reserved, "
                        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'preparing', ?, ?, ?)",
                        (
                            request.parent_id,
                            str(request.request_id),
                            request.message,
                            self._digest(request),
                            day,
                            quota.remaining_tokens,
                            now.isoformat(),
                            now.isoformat(),
                        ),
                    )
                    assert cursor.lastrowid is not None
                    self._on_admitted(connection, request, cursor.lastrowid, now)
                    connection.execute(
                        "UPDATE parent_chat_quota SET attempts=attempts+1 "
                        "WHERE parent_id=? AND day=?",
                        (request.parent_id, day),
                    )
                    row = connection.execute(
                        "SELECT * FROM parent_chat_turns WHERE id=?", (cursor.lastrowid,)
                    ).fetchone()
                    admitted = self._turn(row)
        if failure is not None:
            raise failure
        assert admitted is not None
        return admitted

    @staticmethod
    def _digest(request: ParentChatRequest) -> str:
        return hashlib.sha256(request.model_dump_json().encode()).hexdigest()

    @staticmethod
    def _turn(row: sqlite3.Row) -> StoredChatTurn:
        return StoredChatTurn(
            turn_id=row["id"],
            request_id=row["request_id"],
            parent_id=row["parent_id"],
            message=row["message"],
            status=row["status"],
            reserved_tokens=row["reserved"],
            created_at=datetime.fromisoformat(row["created_at"]),
            answer=row["answer"],
            error_code=row["error_code"],
            result=ParentChatResponse.model_validate_json(row["result"]) if row["result"] else None,
        )

    async def recent_completed(self, parent_id: str, limit: int) -> list[StoredChatTurn]:
        return await asyncio.to_thread(self._recent_completed, parent_id, limit)

    def _recent_completed(self, parent_id: str, limit: int) -> list[StoredChatTurn]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM parent_chat_turns WHERE parent_id=? AND status='completed' "
                "ORDER BY id DESC LIMIT ?",
                (parent_id, limit),
            ).fetchall()
            return [self._turn(row) for row in reversed(rows)]

    async def submit(self, turn: StoredChatTurn, *, reserved_tokens: int, now: datetime) -> None:
        await asyncio.to_thread(self._submit, turn, reserved_tokens, now)

    def _submit(self, turn: StoredChatTurn, reserved_tokens: int, now: datetime) -> None:
        now = self._utc(now)
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE parent_chat_turns SET status='submitted', reserved=?, updated_at=? "
                "WHERE id=? AND parent_id=? AND status='preparing' AND reserved>=? "
                "AND created_at>=?",
                (
                    reserved_tokens,
                    now.isoformat(),
                    turn.turn_id,
                    turn.parent_id,
                    reserved_tokens,
                    (now - timedelta(minutes=5)).isoformat(),
                ),
            ).rowcount
            if changed != 1:
                raise ParentChatError("request_no_longer_admitted", 409)

    async def fail(
        self, turn: StoredChatTurn, *, code: str, status_code: int = 503, unknown: bool = False
    ) -> None:
        await asyncio.to_thread(self._fail, turn, code, status_code, unknown)

    def _fail(self, turn: StoredChatTurn, code: str, status_code: int, unknown: bool) -> None:
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE parent_chat_turns SET status=?, reserved=CASE WHEN ? THEN reserved ELSE 0 "
                "END, error_code=?, error_status=? WHERE id=? AND parent_id=? "
                "AND status IN ('preparing', 'submitted')",
                (
                    "unknown" if unknown else "failed",
                    unknown,
                    code,
                    status_code,
                    turn.turn_id,
                    turn.parent_id,
                ),
            ).rowcount
            if changed:
                self._on_failed(connection, turn, unknown=unknown)

    async def settle(
        self,
        turn: StoredChatTurn,
        *,
        receipt: ChatModelReceipt,
        now: datetime,
        history_turns: int,
        context_at: datetime,
    ) -> ParentChatResponse:
        return await asyncio.to_thread(self._settle, turn, receipt, now, history_turns, context_at)

    def _settle(
        self,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        now: datetime,
        history_turns: int,
        context_at: datetime,
    ) -> ParentChatResponse:
        now = self._utc(now)
        result: ParentChatResponse | None = None
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM parent_chat_turns WHERE id=? AND parent_id=?",
                (turn.turn_id, turn.parent_id),
            ).fetchone()
            if row is None or row["status"] not in {"submitted", "unknown"}:
                raise ParentChatError("request_no_longer_admitted", 409)
            connection.execute(
                "UPDATE parent_chat_quota SET used=used+? WHERE parent_id=? AND day=?",
                (receipt.usage.total, turn.parent_id, row["day"]),
            )
            within_reservation = receipt.usage.total <= row["reserved"]
            valid = (
                receipt.completed
                and bool(receipt.answer)
                and within_reservation
                and self._valid_decision(connection, turn, receipt, now)
            )
            code = "model_answer_unavailable" if within_reservation else "model_usage_exceeded_hold"
            connection.execute(
                "UPDATE parent_chat_turns SET status=?, reserved=0, updated_at=?, "
                "error_code=?, error_status=?, input_tokens=?, output_tokens=?, model=? WHERE id=?",
                (
                    "completed" if valid else ("failed" if within_reservation else "unknown"),
                    now.isoformat(),
                    None if valid else code,
                    None if valid else 502,
                    receipt.usage.input_tokens,
                    receipt.usage.output_tokens,
                    receipt.model,
                    turn.turn_id,
                ),
            )
            if valid:
                assert receipt.answer is not None
                result = ParentChatResponse(
                    parent_id=turn.parent_id,
                    request_id=turn.request_id,
                    answer=receipt.answer,
                    model=receipt.model,
                    usage=receipt.usage,
                    quota=self._quota(connection, turn.parent_id, now),
                    history_turns_included=history_turns,
                    child_context_collected_at=context_at,
                )
                connection.execute(
                    "UPDATE parent_chat_turns SET answer=?, result=? WHERE id=?",
                    (receipt.answer, result.model_dump_json(), turn.turn_id),
                )
            self._on_settled(connection, turn, receipt, valid=bool(valid))
        if result is None:
            raise ParentChatError(code, 502)
        return result

    async def quota(self, parent_id: str, now: datetime) -> ChatQuota:
        return await asyncio.to_thread(self._read_quota, parent_id, now)

    def _read_quota(self, parent_id: str, now: datetime) -> ChatQuota:
        with self._connect() as connection:
            return self._quota(connection, parent_id, now)

    async def history(
        self, parent_id: str, *, before: int | None, limit: int, now: datetime
    ) -> ParentChatHistory:
        return await asyncio.to_thread(self._history, parent_id, before, limit, now)

    def _history(
        self, parent_id: str, before: int | None, limit: int, now: datetime
    ) -> ParentChatHistory:
        now = self._utc(now)
        with self._transaction() as connection:
            self._recover_pre_dispatch(connection, parent_id, now)
            return self._history_in_transaction(connection, parent_id, before, limit, now)

    def _history_in_transaction(
        self,
        connection: sqlite3.Connection,
        parent_id: str,
        before: int | None,
        limit: int,
        now: datetime,
    ) -> ParentChatHistory:
        rows = connection.execute(
            "SELECT * FROM parent_chat_turns WHERE parent_id=? AND (? IS NULL OR id < ?) "
            "ORDER BY id DESC LIMIT ?",
            (parent_id, before, before, limit + 1),
        ).fetchall()
        latest = connection.execute(
            "SELECT request_id, status, error_code FROM parent_chat_turns "
            "WHERE parent_id=? ORDER BY id DESC LIMIT 1",
            (parent_id,),
        ).fetchone()
        selected = rows[:limit]
        messages: list[ParentChatMessage] = []
        for row in reversed(selected):
            for role in ("user", "assistant"):
                content = row["message"] if role == "user" else row["answer"]
                if content is not None and (role != "user" or content):
                    messages.append(
                        ParentChatMessage(
                            turn_id=row["id"],
                            request_id=UUID(row["request_id"]),
                            role=role,
                            content=content,
                            created_at=datetime.fromisoformat(
                                row["created_at"] if role == "user" else row["updated_at"]
                            ),
                            status=row["status"],
                        )
                    )
        return ParentChatHistory(
            parent_id=parent_id,
            messages=messages,
            next_before_turn_id=selected[-1]["id"] if len(rows) > limit else None,
            quota=self._quota(connection, parent_id, now),
            latest_request_id=latest["request_id"] if latest else None,
            latest_request_status=latest["status"] if latest else None,
            latest_error_code=latest["error_code"] if latest else None,
        )
