"""Family v15 retention: one bounded Parent-Touch check-in per inactive-chat anchor."""

import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.application.reminder_text import reminder_language
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.client_retention import (
    ClientRetentionPolicy,
    ParentTouchRetentionTurn,
    RetentionIntent,
)
from app.mana_ai.domain.family_agents import (
    FamilyQuestion,
    ParentTouchMessageRequest,
    ParentTouchMessageState,
    ParentTouchReviewedTurn,
)
from app.services.parent_chat_store import SqliteParentChatStore
from app.services.parent_reminder_store import (
    SqliteClosedParentReminderStore,
    SqliteParentReminderStore,
)
from app.services.proactive_parent_store import _current_context, _digest

_TABLES = {
    "retention_policy",
    "retention_intents",
    "retention_turns",
    "retention_opt_outs",
    "retention_events",
}


class SqliteClientRetentionStore(SqliteParentReminderStore):
    _schema_version = 15

    async def retention_question(self, parent_id: str, turn_id: int) -> FamilyQuestion | None:
        return None

    def _on_retention_opt_out(self, db: sqlite3.Connection, parent_id: str) -> None:
        pass

    def __init__(
        self, path: Path, *, retention_policy: ClientRetentionPolicy, **family: Any
    ) -> None:
        super().__init__(path, **family)
        self._retention_policy = ClientRetentionPolicy.model_validate(retention_policy.model_dump())

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {14}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS retention_policy(id INTEGER PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS retention_intents(
            intent_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,anchor INTEGER NOT NULL,
            status TEXT NOT NULL,admitted_at TEXT NOT NULL,turn_id INTEGER,payload TEXT NOT NULL,
            UNIQUE(parent_id,anchor));
        CREATE TABLE IF NOT EXISTS retention_opt_outs(parent_id TEXT PRIMARY KEY,at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS retention_turns(
            turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,intent_id TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS retention_events(
            position INTEGER PRIMARY KEY,intent_id TEXT,parent_id TEXT NOT NULL,
            kind TEXT NOT NULL,at TEXT NOT NULL,turn_id INTEGER);
        CREATE INDEX IF NOT EXISTS retention_intent_state ON retention_intents(status,admitted_at);
        """
        )

    def _initialize(self) -> None:
        if self._path.exists():
            with self._connect() as db:
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='retention_policy'"
                ).fetchone():
                    prior = db.execute("SELECT payload FROM retention_policy WHERE id=1").fetchone()
                    if prior and prior[0] != self._retention_policy.model_dump_json():
                        raise ValueError(
                            "Retention policy cannot reset existing intents or ceilings"
                        )
        super()._initialize()
        with self._transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO retention_policy VALUES(1,?)",
                (self._retention_policy.model_dump_json(),),
            )

    def _contact_ready(self, db: sqlite3.Connection, parent: str, now: datetime) -> bool:
        contact = _current_context(db, parent, now)
        if (
            not self._proactive_enabled
            or contact is None
            or not contact.retention_chat_consent
            or db.execute(
                "SELECT 1 FROM retention_opt_outs WHERE parent_id=?", (parent,)
            ).fetchone()
        ):
            return False
        hour = now.astimezone(ZoneInfo(contact.timezone)).hour
        start, end = (
            self._conversion_policy.quiet_start_hour,
            self._conversion_policy.quiet_end_hour,
        )
        return not (hour >= start or hour < end if start > end else start <= hour < end)

    @staticmethod
    def _retention_event(
        db: sqlite3.Connection,
        parent: str,
        identity: str | None,
        kind: str,
        now: datetime,
        turn_id: int | None = None,
    ) -> None:
        db.execute(
            "INSERT INTO retention_events(intent_id,parent_id,kind,at,turn_id) VALUES(?,?,?,?,?)",
            (identity, parent, kind, now.isoformat(), turn_id),
        )

    @staticmethod
    def _anchor(db: sqlite3.Connection, parent: str) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            db.execute(
                "SELECT id,created_at FROM parent_chat_turns WHERE parent_id=? "
                "AND message<>'' ORDER BY id DESC LIMIT 1",
                (parent,),
            ).fetchone(),
        )

    def _priority_waiting(
        self, db: sqlite3.Connection, parent: str, now: datetime, turn_id: int = 0
    ) -> bool:
        return bool(
            db.execute(
                "SELECT 1 FROM parent_chat_turns WHERE parent_id=? AND id<>? "
                "AND status IN ('preparing','submitted','unknown')",
                (parent, turn_id),
            ).fetchone()
            or db.execute(
                "SELECT 1 FROM family_questions WHERE parent_id=? AND (status IN "
                "('offered','awaiting_reply','held') OR (status='queued' AND expires_at>?)) "
                "AND (offered_turn_id IS NULL OR offered_turn_id<>?)",
                (parent, now.isoformat(), turn_id),
            ).fetchone()
            or db.execute(
                "SELECT 1 FROM family_notices WHERE parent_id=? AND (status IN "
                "('offered','held') OR (status='queued' AND expires_at>?))",
                (parent, now.isoformat()),
            ).fetchone()
            or db.execute(
                "SELECT 1 FROM assistant_reminders WHERE parent_id=? AND "
                "((status='draft' AND json_extract(payload,'$.confirmation_expires_at')>?) "
                "OR (status IN ('scheduled','checking','ready') AND due_at<=?))",
                (parent, now.isoformat(), now.isoformat()),
            ).fetchone()
        )

    def _eligible(
        self, db: sqlite3.Connection, intent: RetentionIntent, now: datetime, turn_id: int = 0
    ) -> bool:
        anchor = self._anchor(db, intent.parent_id)
        contact = _current_context(db, intent.parent_id, now)
        return bool(
            anchor
            and anchor["id"] == intent.anchor_turn_id
            and contact
            and _digest(contact) == intent.contact_digest
            and self._contact_ready(db, intent.parent_id, now)
            and now < intent.expires_at
            and not self._priority_waiting(db, intent.parent_id, now, turn_id)
        )

    async def claim_retention(self, now: datetime) -> RetentionIntent | None:
        return await asyncio.to_thread(self._claim_retention, self._utc(now))

    def _retention_daily_count(self, db: sqlite3.Connection, now: datetime) -> int:
        return int(
            db.execute(
                "SELECT COUNT(*) FROM retention_intents WHERE admitted_at>?",
                ((now - timedelta(days=1)).isoformat(),),
            ).fetchone()[0]
        )

    def _retention_recent(self, db: sqlite3.Connection, parent: str, now: datetime) -> bool:
        return False

    def _claim_retention(self, now: datetime) -> RetentionIntent | None:
        with self._transaction() as db:
            for row in db.execute(
                "SELECT intent_id,payload FROM retention_intents WHERE status='claimed'"
            ).fetchall():
                old = RetentionIntent.model_validate_json(row["payload"])
                if old.expires_at <= now:
                    db.execute(
                        "UPDATE retention_intents SET status='unknown' WHERE intent_id=?",
                        (row["intent_id"],),
                    )
                    self._retention_event(db, old.parent_id, row["intent_id"], "claim_expired", now)
            total = self._retention_daily_count(db, now)
            if total >= self._retention_policy.daily_outreach_limit:
                return None
            cutoff = now - timedelta(days=self._retention_policy.inactive_chat_days)
            rows = db.execute(
                "SELECT t.* FROM parent_contact_contexts c JOIN parent_chat_turns t "
                "ON t.id=(SELECT MAX(p.id) FROM parent_chat_turns p WHERE p.parent_id=c.parent_id "
                "AND p.message<>'') LEFT JOIN retention_intents r ON r.parent_id=t.parent_id "
                "AND r.anchor=t.id WHERE r.intent_id IS NULL AND t.status='completed' "
                "AND t.created_at<=? "
                "AND julianday(c.valid_until)>julianday(?) "
                "AND json_extract(c.payload,'$.retention_chat_consent')=1 "
                "ORDER BY t.id LIMIT 100",
                (cutoff.isoformat(), now.isoformat()),
            ).fetchall()
            for row in rows:
                parent = row["parent_id"]
                if (
                    self._retention_recent(db, parent, now)
                    or not self._contact_ready(db, parent, now)
                    or self._priority_waiting(db, parent, now)
                ):
                    continue
                contact = _current_context(db, parent, now)
                assert contact is not None
                identity = uuid5(
                    NAMESPACE_URL, f"mana:retention:chat-inactive-v1:{parent}:{row['id']}"
                )
                intent = RetentionIntent(
                    intent_id=identity,
                    parent_id=parent,
                    request_id=uuid5(identity, "parent-touch-v1"),
                    anchor_turn_id=row["id"],
                    last_parent_message_at=datetime.fromisoformat(row["created_at"]),
                    admitted_at=now,
                    expires_at=min(
                        contact.valid_until,
                        now + timedelta(seconds=self._retention_policy.preparation_seconds),
                    ),
                    language=contact.language,
                    contact_digest=_digest(contact),
                )
                db.execute(
                    "INSERT INTO retention_intents VALUES(?,?,?,'claimed',?,NULL,?)",
                    (
                        str(identity),
                        parent,
                        intent.anchor_turn_id,
                        now.isoformat(),
                        intent.model_dump_json(),
                    ),
                )
                self._retention_event(db, parent, str(identity), "intent_admitted", now)
                return intent
            return None

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        if not isinstance(request, ParentTouchRetentionTurn):
            super()._on_admitted(db, request, turn_id, now)
            if request.message:
                rows = db.execute(
                    "SELECT intent_id FROM retention_intents WHERE parent_id=? "
                    "AND status='published' AND turn_id<?",
                    (request.parent_id, turn_id),
                ).fetchall()
                for row in rows:
                    db.execute(
                        "UPDATE retention_intents SET status='responded' WHERE intent_id=?",
                        (row[0],),
                    )
                    self._retention_event(
                        db, request.parent_id, row[0], "parent_returned_to_chat", now, turn_id
                    )
            return
        row = db.execute(
            "SELECT * FROM retention_intents WHERE intent_id=? AND parent_id=?",
            (str(request.retention_intent_id), request.parent_id),
        ).fetchone()
        if row is None or row["status"] != "claimed" or row["turn_id"] is not None:
            raise ParentChatError("retention_intent_not_active", 409)
        intent = RetentionIntent.model_validate_json(row["payload"])
        if request.request_id != intent.request_id or not self._eligible(db, intent, now, turn_id):
            raise ParentChatError("retention_intent_changed", 409)
        db.execute(
            "INSERT INTO retention_turns VALUES(?,?,?)",
            (turn_id, request.parent_id, str(intent.intent_id)),
        )
        db.execute(
            "UPDATE retention_intents SET turn_id=? WHERE intent_id=?",
            (turn_id, str(intent.intent_id)),
        )
        self._retention_event(
            db, request.parent_id, str(intent.intent_id), "speaker_admitted", now, turn_id
        )

    async def retention_scope(self, parent_id: str, turn_id: int) -> RetentionIntent:
        def read() -> RetentionIntent:
            with self._connect() as db:
                row = db.execute(
                    "SELECT i.payload FROM retention_turns t JOIN retention_intents i "
                    "ON i.intent_id=t.intent_id WHERE t.parent_id=? AND t.turn_id=?",
                    (parent_id, turn_id),
                ).fetchone()
                if row is None:
                    raise ParentChatError("retention_scope_missing", 503)
                return RetentionIntent.model_validate_json(row[0])

        return await asyncio.to_thread(read)

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        row = db.execute(
            "SELECT i.* FROM retention_turns t JOIN retention_intents i ON i.intent_id=t.intent_id "
            "WHERE t.parent_id=? AND t.turn_id=?",
            (turn.parent_id, turn.turn_id),
        ).fetchone()
        if row is None:
            return super()._valid_decision(db, turn, receipt, now)
        intent = RetentionIntent.model_validate_json(row["payload"])
        return bool(
            row["status"] == "claimed"
            and self._eligible(db, intent, now, turn.turn_id)
            and SqliteParentChatStore._valid_decision(self, db, turn, receipt, now)
        )

    def _on_settled(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        row = db.execute(
            "SELECT intent_id FROM retention_turns WHERE turn_id=? AND parent_id=?",
            (turn.turn_id, turn.parent_id),
        ).fetchone()
        if row is None:
            super()._on_settled(db, turn, receipt, valid=valid)
            return
        db.execute(
            "UPDATE retention_intents SET status=? WHERE intent_id=?",
            ("published" if valid else "suppressed", row[0]),
        )
        now = datetime.fromisoformat(
            db.execute(
                "SELECT updated_at FROM parent_chat_turns WHERE id=?", (turn.turn_id,)
            ).fetchone()[0]
        )
        self._retention_event(
            db, turn.parent_id, row[0], "published" if valid else "suppressed", now, turn.turn_id
        )
        if valid:
            self._queue_push(db, turn.parent_id, turn.turn_id, "retention", now)

    def _on_failed(self, db: sqlite3.Connection, turn: StoredChatTurn, *, unknown: bool) -> None:
        row = db.execute(
            "SELECT intent_id FROM retention_turns WHERE turn_id=?", (turn.turn_id,)
        ).fetchone()
        if row is None:
            super()._on_failed(db, turn, unknown=unknown)
        else:
            db.execute(
                "UPDATE retention_intents SET status=? WHERE intent_id=? AND status='claimed'",
                ("unknown" if unknown else "failed", row[0]),
            )

    async def fail_retention(
        self, intent: RetentionIntent, now: datetime, *, unknown: bool
    ) -> None:
        def fail() -> None:
            with self._transaction() as db:
                db.execute(
                    "UPDATE retention_intents SET status=? WHERE intent_id=? AND status='claimed'",
                    ("unknown" if unknown else "failed", str(intent.intent_id)),
                )

        await asyncio.to_thread(fail)

    async def retention_opt_out(
        self, request: ParentTouchMessageRequest, now: datetime
    ) -> ParentTouchMessageState | None:
        normalized = request.message.strip().rstrip(".!?").casefold()
        if normalized not in {
            "не пиши первым",
            "не напоминай о чате",
            "пиши только если я напишу",
            "stop check-ins",
            "do not message me first",
            "birinchi bo‘lib yozmang",
            "birinchi bo'lib yozmang",
        }:
            return None

        def decline() -> ParentTouchMessageState | None:
            with self._transaction() as db:
                prior = db.execute(
                    "SELECT request_digest FROM parent_chat_turns WHERE parent_id=? "
                    "AND request_id=?",
                    (request.parent_id, str(request.request_id)),
                ).fetchone()
                if prior:
                    if prior[0] != self._digest(ParentTouchReviewedTurn(**request.model_dump())):
                        raise ParentChatError("request_id_conflict", 409)
                    return None
                db.execute(
                    "INSERT OR IGNORE INTO retention_opt_outs VALUES(?,?)",
                    (request.parent_id, self._utc(now).isoformat()),
                )
                db.execute(
                    "UPDATE retention_intents SET status='suppressed' WHERE parent_id=? "
                    "AND status='claimed'",
                    (request.parent_id,),
                )
                db.execute(
                    "UPDATE parent_push_outbox SET status='suppressed',"
                    "error_code='retention_opted_out',"
                    "updated_at=? WHERE parent_id=? AND purpose='retention' AND status='queued'",
                    (self._utc(now).isoformat(), request.parent_id),
                )
                self._retention_event(
                    db, request.parent_id, None, "parent_opted_out", self._utc(now)
                )
                self._on_retention_opt_out(db, request.parent_id)
                contact = _current_context(db, request.parent_id, self._utc(now))
                language = (
                    "en"
                    if normalized in {"stop check-ins", "do not message me first"}
                    else "uz-Latn"
                    if normalized.startswith("birinchi")
                    else reminder_language(request.message, contact.language if contact else "ru")
                )
                answers = {
                    "ru": "Больше не буду первым напоминать об этом чате.",
                    "uz-Latn": "Bu chat haqida birinchi bo‘lib eslatma yubormayman.",
                    "uz-Cyrl": "Бу чат ҳақида биринчи бўлиб эслатма юбормайман.",
                    "en": "I will stop initiating chat check-ins.",
                }
                return self._host_reply(
                    db,
                    request,
                    request.parent_id,
                    request.request_id,
                    answers[language],
                    self._utc(now),
                )

        return await asyncio.to_thread(decline)

    def _push_delivery_ready(self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> bool:
        if row["purpose"] == "retention":
            return self._contact_ready(db, row["parent_id"], now)
        return super()._push_delivery_ready(db, row, now)


class SqliteClosedClientRetentionStore(SqliteClosedParentReminderStore):
    _schema_version = 15

    def _supported_versions(self) -> set[int]:
        return {15}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
