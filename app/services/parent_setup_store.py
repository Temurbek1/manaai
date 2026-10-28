"""Family v42: source-backed parent setup support, not fictitious chat inactivity."""

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.domain.chat import ParentChatRequest, ResponseLanguage, StoredChatTurn
from app.mana_ai.domain.family_agents import (
    FamilyQuestion,
    ParentTouchRequest,
    ParentTouchReviewedTurn,
)
from app.mana_ai.domain.parent_setup import (
    ParentSetupFact,
    ParentSetupNotice,
    ParentSetupPolicy,
    setup_observation_current,
)
from app.mana_ai.domain.parent_touch_manager import ParentTouchManagerScope
from app.services.compact_source_tool_store import (
    SqliteClosedCompactSourceToolStore,
    SqliteCompactSourceToolStore,
)
from app.services.proactive_parent_store import _current_context

_TABLES = {
    "setup_policy",
    "setup_heads",
    "setup_epochs",
    "setup_notices",
    "setup_reply_captures",
    "setup_help_captures",
}


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


def _semantic(fact: ParentSetupFact) -> str:
    return _hash(fact.model_dump_json(exclude={"collected_at"}))


def setup_text(fact: ParentSetupFact, language: ResponseLanguage, timezone: str) -> tuple[str, str]:
    local = fact.collected_at.astimezone(ZoneInfo(timezone))
    offset = local.strftime("%z")
    at = f"{local:%d.%m.%Y %H:%M} (UTC{offset[:3]}:{offset[3:]})"
    fact_text, question = {
        "ru": (
            f"В профиле MANA, проверенном {at}, нет подключённого ребёнка.",
            "Помочь с подключением ребёнка?",
        ),
        "uz-Latn": (
            f"{at} da tekshirilgan MANA profilida ulangan bola yo‘q.",
            "Bolani ulashda yordam beraymi?",
        ),
        "uz-Cyrl": (
            f"{at} да текширилган MANA профилида уланган бола йўқ.",
            "Болани улашда ёрдам берайми?",
        ),
        "en": (
            f"The MANA profile checked at {at} has no linked child.",
            "Would you like help linking your child?",
        ),
    }[language]
    return fact_text + " " + question, question


class SqliteParentSetupStore(SqliteCompactSourceToolStore):
    _schema_version = 42

    def __init__(
        self,
        path: Path,
        *,
        parent_setup_enabled: bool = False,
        parent_setup_policy: ParentSetupPolicy | None = None,
        setup_binding: str,
        **family: Any,
    ) -> None:
        if not setup_binding or len(setup_binding) > 512:
            raise ValueError("Setup support requires its exact MANA profile source binding")
        self._parent_setup_enabled = parent_setup_enabled
        self._setup_policy = ParentSetupPolicy.model_validate(
            (parent_setup_policy or ParentSetupPolicy()).model_dump()
        )
        self._setup_binding = setup_binding
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {41}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS setup_policy(
          id INTEGER PRIMARY KEY CHECK(id=1),configuration TEXT NOT NULL,closed TEXT,
          scan_after TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS setup_heads(
          parent_id TEXT PRIMARY KEY,payload TEXT NOT NULL,digest TEXT NOT NULL,
          collected_at TEXT NOT NULL,epoch_id TEXT,known INTEGER NOT NULL CHECK(known IN(0,1)));
        CREATE TABLE IF NOT EXISTS setup_epochs(
          epoch_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,origin TEXT NOT NULL,
          origin_hash TEXT NOT NULL,phase TEXT NOT NULL
          CHECK(phase IN('pending','disabled','cancelled','published')),
          captured_at TEXT NOT NULL,turn_id INTEGER);
        CREATE INDEX IF NOT EXISTS setup_pending ON setup_epochs(phase,epoch_id);
        CREATE TABLE IF NOT EXISTS setup_notices(
          epoch_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,turn_id INTEGER NOT NULL UNIQUE,
          question_id TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,fingerprint TEXT NOT NULL,
          published_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS setup_parent_notices ON setup_notices(parent_id,published_at);
        CREATE TABLE IF NOT EXISTS setup_reply_captures(
          parent_id TEXT NOT NULL,turn_id INTEGER PRIMARY KEY,question_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS setup_help_captures(
          turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,question_id TEXT NOT NULL,
          proof_hash TEXT NOT NULL,depth INTEGER NOT NULL CHECK(depth BETWEEN 1 AND 3),
          protocol INTEGER NOT NULL CHECK(protocol=1));
        """
        )

    def _initialize(self) -> None:
        configuration = json.dumps(
            {"policy": self._setup_policy.model_dump(), "binding": self._setup_binding},
            sort_keys=True,
        )
        if self._path.exists():
            with self._connect() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='setup_policy'").fetchone():
                    row = db.execute("SELECT configuration FROM setup_policy WHERE id=1").fetchone()
                    if row and row[0] != configuration:
                        raise ValueError("Setup policy/source cannot reset existing captures")
        super()._initialize()
        with self._transaction() as db:
            db.execute("INSERT OR IGNORE INTO setup_policy VALUES(1,?,NULL,'')", (configuration,))
            if (
                db.execute("SELECT configuration FROM setup_policy WHERE id=1").fetchone()[0]
                != configuration
            ):
                raise ValueError("Setup policy/source changed during initialization")

    def _setup_open(self, db: sqlite3.Connection) -> bool:
        return bool(
            self._parent_setup_enabled
            and self._parent_questions_enabled
            and self._manager_enabled
            and not db.execute("SELECT closed FROM setup_policy WHERE id=1").fetchone()[0]
        )

    def _cancel_setup(self, db: sqlite3.Connection, parent: str, *, pending: bool = True) -> None:
        if pending:
            db.execute(
                "UPDATE setup_epochs SET phase='cancelled' WHERE parent_id=? AND phase='pending'",
                (parent,),
            )
        db.execute(
            (
                "UPDATE family_questions SET status='cancelled' WHERE parent_id=? "
                "AND status='awaiting_reply' "
            )
            + (
                "AND child_id IS NULL AND question_id IN(SELECT question_id FROM "
                "setup_notices WHERE parent_id=?)"
            ),
            (parent, parent),
        )

    async def close_setup_source(self) -> None:
        def close() -> None:
            with self._transaction() as db:
                db.execute(
                    "UPDATE setup_policy SET closed=COALESCE(closed,'source_closed') WHERE id=1"
                )
                db.execute("UPDATE setup_epochs SET phase='cancelled' WHERE phase='pending'")
                db.execute(
                    "UPDATE family_questions SET status='cancelled' "
                    "WHERE child_id IS NULL AND status='awaiting_reply' "
                    "AND question_id IN(SELECT question_id FROM setup_notices)"
                )

        await asyncio.to_thread(close)

    async def invalidate_setup_profile(self, parent_id: str, now: datetime) -> None:
        def invalidate() -> None:
            with self._transaction() as db:
                row = db.execute(
                    "SELECT collected_at FROM setup_heads WHERE parent_id=?", (parent_id,)
                ).fetchone()
                if row and datetime.fromisoformat(row[0]) <= self._utc(now):
                    db.execute("UPDATE setup_heads SET known=0 WHERE parent_id=?", (parent_id,))
                    self._cancel_setup(db, parent_id)

        await asyncio.to_thread(invalidate)

    async def observe_setup_facts(self, facts: tuple[ParentSetupFact, ...], now: datetime) -> bool:
        def observe() -> bool:
            validated = tuple(ParentSetupFact.model_validate(f.model_dump()) for f in facts)
            if len(validated) > 100 or len({f.parent_id for f in validated}) != len(validated):
                raise ParentChatError("setup_observation_invalid", 503)
            current = self._utc(now)
            if any(
                not setup_observation_current(f, current, self._setup_policy) for f in validated
            ):
                return False
            with self._transaction() as db:
                if db.execute("SELECT closed FROM setup_policy WHERE id=1").fetchone()[0]:
                    return False
                for fact in validated:
                    self._put_setup_fact(
                        db,
                        fact.model_copy(update={"collected_at": self._utc(fact.collected_at)}),
                        current,
                    )
                return not bool(
                    db.execute("SELECT closed FROM setup_policy WHERE id=1").fetchone()[0]
                )

        return await asyncio.to_thread(observe)

    def _setup_head(
        self, db: sqlite3.Connection, parent: str
    ) -> tuple[sqlite3.Row, ParentSetupFact] | None:
        row = db.execute("SELECT * FROM setup_heads WHERE parent_id=?", (parent,)).fetchone()
        if row is None:
            return None
        try:
            fact = ParentSetupFact.model_validate_json(row["payload"])
            if (
                fact.parent_id != parent
                or _semantic(fact) != row["digest"]
                or fact.collected_at.isoformat() != row["collected_at"]
            ):
                raise ValueError("Changed setup observation")
        except (ValueError, TypeError):
            raise ParentChatError("setup_observation_invalid", 503) from None
        return row, fact

    def _put_setup_fact(self, db: sqlite3.Connection, fact: ParentSetupFact, now: datetime) -> None:
        try:
            previous = self._setup_head(db, fact.parent_id)
        except ParentChatError:
            db.execute("UPDATE setup_policy SET closed='integrity' WHERE id=1")
            return
        if previous is not None:
            row, old = previous
            if old.collected_at > fact.collected_at:
                return
            if old.collected_at == fact.collected_at:
                if old != fact:
                    db.execute(
                        "UPDATE setup_policy SET closed='conflicting_observation' WHERE id=1"
                    )
                return
        elif (
            db.execute("SELECT COUNT(*) FROM setup_heads").fetchone()[0]
            >= self._setup_policy.maximum_profiles
        ):
            db.execute("UPDATE setup_policy SET closed='capacity' WHERE id=1")
            return
        epoch: str | None = None
        if not fact.connected_child_ids:
            if previous is not None and not previous[1].connected_child_ids:
                epoch = previous[0]["epoch_id"]
                if epoch is None:
                    db.execute("UPDATE setup_policy SET closed='integrity' WHERE id=1")
                    return
            else:
                if (
                    db.execute("SELECT COUNT(*) FROM setup_epochs").fetchone()[0]
                    >= self._setup_policy.maximum_epochs
                ):
                    db.execute("UPDATE setup_policy SET closed='capacity' WHERE id=1")
                    return
                epoch = str(
                    uuid5(
                        NAMESPACE_URL,
                        "mana:setup-epoch-v1:" + self._setup_binding + ":" + fact.model_dump_json(),
                    )
                )
                payload = fact.model_dump_json()
                db.execute(
                    "INSERT INTO setup_epochs VALUES(?,?,?,?,?,?,NULL)",
                    (
                        epoch,
                        fact.parent_id,
                        payload,
                        _hash(payload),
                        "pending" if self._setup_open(db) else "disabled",
                        now.isoformat(),
                    ),
                )
        else:
            self._cancel_setup(db, fact.parent_id)
        db.execute(
            "INSERT OR REPLACE INTO setup_heads VALUES(?,?,?,?,?,1)",
            (
                fact.parent_id,
                fact.model_dump_json(),
                _semantic(fact),
                fact.collected_at.isoformat(),
                epoch,
            ),
        )

    def _retention_daily_count(self, db: sqlite3.Connection, now: datetime) -> int:
        return super()._retention_daily_count(db, now) + int(
            db.execute(
                "SELECT COUNT(*) FROM setup_notices WHERE published_at>?",
                ((now - timedelta(days=1)).isoformat(),),
            ).fetchone()[0]
        )

    def _retention_recent(self, db: sqlite3.Connection, parent: str, now: datetime) -> bool:
        return super()._retention_recent(db, parent, now) or bool(
            db.execute(
                "SELECT 1 FROM setup_notices WHERE parent_id=? AND published_at>?",
                (
                    parent,
                    (
                        now - timedelta(hours=self._expiry_policy.minimum_outreach_interval_hours)
                    ).isoformat(),
                ),
            ).fetchone()
        )

    async def publish_setup(self, now: datetime) -> bool:
        return await asyncio.to_thread(self._publish_setup, self._utc(now))

    def _publish_setup(self, now: datetime) -> bool:
        with self._transaction() as db:
            if not self._setup_open(db):
                db.execute("UPDATE setup_epochs SET phase='cancelled' WHERE phase='pending'")
                return False
            if self._retention_daily_count(db, now) >= min(
                self._retention_policy.daily_outreach_limit, self._setup_policy.daily_global_limit
            ):
                return False
            cursor = db.execute("SELECT scan_after FROM setup_policy WHERE id=1").fetchone()[0]
            rows = db.execute(
                (
                    "SELECT * FROM setup_epochs WHERE phase='pending' AND epoch_id>? "
                    "ORDER BY epoch_id LIMIT 100"
                ),
                (cursor,),
            ).fetchall()
            for row in rows:
                db.execute("UPDATE setup_policy SET scan_after=? WHERE id=1", (row["epoch_id"],))
                parent = row["parent_id"]
                try:
                    head = self._setup_head(db, parent)
                    origin = ParentSetupFact.model_validate_json(row["origin"])
                    if (
                        _hash(row["origin"]) != row["origin_hash"]
                        or origin.parent_id != parent
                        or origin.connected_child_ids
                    ):
                        raise ValueError("Changed setup origin")
                except (ValueError, TypeError, ParentChatError):
                    db.execute("UPDATE setup_policy SET closed='integrity' WHERE id=1")
                    return False
                if head is None or head[0]["epoch_id"] != row["epoch_id"] or not head[0]["known"]:
                    continue
                fact = head[1]
                if fact.connected_child_ids or not setup_observation_current(
                    fact, now, self._setup_policy
                ):
                    continue
                if (
                    not self._contact_ready(db, parent, now)
                    or not self._expiry_parent_ready(db, parent, now)
                    or self._manager_priority(db, parent, 0, now)
                    or self._retention_recent(db, parent, now)
                    or db.execute(
                        "SELECT 1 FROM setup_notices WHERE parent_id=? AND published_at>?",
                        (
                            parent,
                            (now - timedelta(days=self._setup_policy.cooldown_days)).isoformat(),
                        ),
                    ).fetchone()
                    or db.execute(
                        (
                            "SELECT 1 FROM family_notices WHERE parent_id=? AND kind='urgent' "
                            "AND created_at>?"
                        ),
                        (
                            parent,
                            (
                                now
                                - timedelta(hours=self._expiry_policy.urgent_notice_cooldown_hours)
                            ).isoformat(),
                        ),
                    ).fetchone()
                ):
                    continue
                if (
                    db.execute(
                        (
                            "SELECT COUNT(*) FROM family_questions WHERE parent_id=? AND "
                            "status IN('queued','offered','awaiting_reply','held')"
                        ),
                        (parent,),
                    ).fetchone()[0]
                    >= self._question_limit
                ):
                    continue
                contact = _current_context(db, parent, now)
                assert contact is not None
                identity = uuid5(NAMESPACE_URL, "mana:setup-invitation-v1:" + row["epoch_id"])
                qid = uuid5(identity, "parent-setup-question-v1")
                text, question_text = setup_text(fact, contact.language, contact.timezone)
                result = self._host_reply(db, None, parent, identity, text, now)
                question = FamilyQuestion(
                    question_id=qid,
                    parent_id=parent,
                    child_id=None,
                    scope="parent",
                    information_key="parent.child_link_setup",
                    question=question_text,
                    reason=(
                        "A complete dated MANA profile has no linked child; offer setup "
                        "help, not an online-state or risk assertion."
                    ),
                    priority=0,
                    status="awaiting_reply",
                    observed_at=fact.collected_at,
                    expires_at=now
                    + timedelta(seconds=self._setup_policy.question_validity_seconds),
                    created_at=now,
                    offered_turn_id=result.turn_id,
                )
                db.execute(
                    (
                        "INSERT INTO "
                        "family_questions(question_id,parent_id,child_id,information_key,status,"
                        "payload,created_at,expires_at,priority,offered_turn_id) "
                        "VALUES(?,?,NULL,?,'awaiting_reply',?,?,?,?,?)"
                    ),
                    (
                        str(qid),
                        parent,
                        question.information_key,
                        question.model_dump_json(),
                        now.isoformat(),
                        question.expires_at.isoformat(),
                        0,
                        result.turn_id,
                    ),
                )
                db.execute(
                    (
                        "INSERT INTO "
                        "family_turn_metadata(parent_id,turn_id,kind,offered_question_id,"
                        "published_question_id,language_turn_id,language_reference) "
                        "VALUES(?,?,'parent_setup',?,?,?,?)"
                    ),
                    (parent, result.turn_id, str(qid), str(qid), result.turn_id, contact.language),
                )
                payload = ParentSetupNotice(
                    parent_id=parent,
                    epoch_id=row["epoch_id"],
                    question_id=qid,
                    text=text,
                    question=question_text,
                    source_fact=fact,
                    contact=_hash(contact.model_dump_json()),
                    language=contact.language,
                    timezone=contact.timezone,
                ).model_dump_json()
                db.execute(
                    "INSERT INTO setup_notices VALUES(?,?,?,?,?,?,?)",
                    (
                        row["epoch_id"],
                        parent,
                        result.turn_id,
                        str(qid),
                        payload,
                        _hash(payload),
                        now.isoformat(),
                    ),
                )
                db.execute(
                    "UPDATE setup_epochs SET phase='published',turn_id=? WHERE epoch_id=?",
                    (result.turn_id, row["epoch_id"]),
                )
                self._retention_event(
                    db, parent, row["epoch_id"], "parent_setup_published", now, result.turn_id
                )
                self._queue_push(db, parent, result.turn_id, "retention", now)
                return True
            if len(rows) < 100:
                db.execute("UPDATE setup_policy SET scan_after='' WHERE id=1")
            return False

    def _setup_notice(
        self, db: sqlite3.Connection, parent: str, question_id: str
    ) -> sqlite3.Row | None:
        row = db.execute(
            (
                "SELECT n.*,t.answer FROM setup_notices n JOIN parent_chat_turns "
                "t ON t.id=n.turn_id AND t.parent_id=n.parent_id WHERE "
                "n.parent_id=? AND n.question_id=? AND t.status='completed'"
            ),
            (parent, question_id),
        ).fetchone()
        if row is not None:
            try:
                proof = ParentSetupNotice.model_validate_json(row["payload"])
                if (
                    _hash(row["payload"]) != row["fingerprint"]
                    or proof.parent_id != parent
                    or str(proof.question_id) != question_id
                    or str(proof.epoch_id) != row["epoch_id"]
                    or proof.origin != "profile_child_link_setup_v1"
                    or setup_text(proof.source_fact, proof.language, proof.timezone)
                    != (proof.text, proof.question)
                    or proof.text != row["answer"]
                ):
                    raise ValueError("Changed setup question proof")
            except (ValueError, TypeError, KeyError):
                raise ParentChatError("setup_question_invalid", 503) from None
        return cast(sqlite3.Row | None, row)

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        if isinstance(request, ParentTouchRequest) and request.reply_to_question_id is not None:
            own = self._setup_notice(db, request.parent_id, str(request.reply_to_question_id))
            if own is not None and not (
                self._parent_setup_enabled and self._parent_questions_enabled
            ):
                raise ParentChatError("parent_setup_disabled", 503)
        super()._on_admitted(db, request, turn_id, now)
        if isinstance(request, ParentTouchRequest) and request.reply_to_question_id is not None:
            own = self._setup_notice(db, request.parent_id, str(request.reply_to_question_id))
            if own is not None:
                db.execute(
                    "INSERT INTO setup_reply_captures VALUES(?,?,?)",
                    (request.parent_id, turn_id, str(request.reply_to_question_id)),
                )
                db.execute(
                    "INSERT INTO setup_help_captures VALUES(?,?,?,?,1,1)",
                    (
                        turn_id,
                        request.parent_id,
                        str(request.reply_to_question_id),
                        own["fingerprint"],
                    ),
                )
            else:
                previous = db.execute(
                    "SELECT h.question_id,h.proof_hash,h.depth "
                    "FROM parent_clarification_questions q "
                    "JOIN setup_help_captures h ON h.turn_id=q.turn_id AND h.parent_id=q.parent_id "
                    "WHERE q.parent_id=? AND q.question_id=?",
                    (request.parent_id, str(request.reply_to_question_id)),
                ).fetchone()
                if previous is not None:
                    if previous[2] >= 3:
                        raise ParentChatError("setup_help_turn_limit", 409)
                    db.execute(
                        "INSERT INTO setup_help_captures VALUES(?,?,?,?,?,1)",
                        (turn_id, request.parent_id, previous[0], previous[1], previous[2] + 1),
                    )

    def _setup_help(self, db: sqlite3.Connection, parent: str, turn_id: int) -> sqlite3.Row | None:
        capture = db.execute(
            "SELECT * FROM setup_help_captures WHERE parent_id=? AND turn_id=?",
            (parent, turn_id),
        ).fetchone()
        if capture:
            own = self._setup_notice(db, parent, capture["question_id"])
            if (
                own is None
                or own["fingerprint"] != capture["proof_hash"]
                or capture["protocol"] != 1
                or not 1 <= capture["depth"] <= 3
            ):
                raise ParentChatError("setup_help_capture_invalid", 503)
        return cast(sqlite3.Row | None, capture)

    async def manager_scope(self, parent_id: str, turn_id: int) -> ParentTouchManagerScope | None:
        scope = await super().manager_scope(parent_id, turn_id)
        if scope is None or scope.stage != "route":
            return scope

        def captured() -> bool:
            with self._connect() as db:
                row = self._setup_help(db, parent_id, turn_id)
                if row is not None and not self._setup_open(db):
                    raise ParentChatError("parent_setup_disabled", 503)
                return row is not None

        return (
            scope.model_copy(update={"setup_help_protocol": 1})
            if await asyncio.to_thread(captured)
            else scope
        )

    def _setup_reply_open(self, db: sqlite3.Connection, turn: StoredChatTurn) -> None:
        help_capture = self._setup_help(db, turn.parent_id, turn.turn_id)
        row = db.execute(
            "SELECT question_id FROM setup_reply_captures WHERE parent_id=? AND turn_id=?",
            (turn.parent_id, turn.turn_id),
        ).fetchone()
        if row or help_capture:
            if not self._setup_open(db):
                raise ParentChatError("parent_setup_disabled", 503)
            if row and self._setup_notice(db, turn.parent_id, row[0]) is None:
                raise ParentChatError("setup_question_invalid", 503)

    def _validate_chat_submission(
        self, db: sqlite3.Connection, turn: StoredChatTurn, now: datetime
    ) -> None:
        super()._validate_chat_submission(db, turn, now)
        self._setup_reply_open(db, turn)

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        try:
            self._setup_reply_open(db, turn)
        except ParentChatError:
            return False
        return super()._valid_decision(db, turn, receipt, now)

    def _question_reply_needs_safety(
        self, db: sqlite3.Connection, request: ParentTouchReviewedTurn, turn_id: int
    ) -> bool:
        if request.reply_to_question_id is not None:
            own = self._setup_notice(db, request.parent_id, str(request.reply_to_question_id))
            if (
                own is not None
                and db.execute(
                    (
                        "SELECT 1 FROM family_questions WHERE parent_id=? AND "
                        "question_id=? AND child_id IS NULL AND status='answered' AND "
                        "answer_turn_id=?"
                    ),
                    (request.parent_id, str(request.reply_to_question_id), turn_id),
                ).fetchone()
            ):
                return False
        return super()._question_reply_needs_safety(db, request, turn_id)

    async def answered_parent_question(self, parent_id: str, turn_id: int) -> str | None:
        def read() -> str | None:
            with self._connect() as db:
                row = db.execute(
                    (
                        "SELECT question_id FROM family_questions WHERE parent_id=? AND "
                        "child_id IS NULL AND status='answered' AND answer_turn_id=?"
                    ),
                    (parent_id, turn_id),
                ).fetchone()
                if row is None:
                    return None
                own = self._setup_notice(db, parent_id, row[0])
                return cast(str, own["answer"]) if own else None

        own = await asyncio.to_thread(read)
        return (
            own if own is not None else await super().answered_parent_question(parent_id, turn_id)
        )

    def _on_retention_opt_out(self, db: sqlite3.Connection, parent_id: str) -> None:
        super()._on_retention_opt_out(db, parent_id)
        self._cancel_setup(db, parent_id)

    def _push_delivery_ready(self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> bool:
        notice = db.execute(
            "SELECT * FROM setup_notices WHERE parent_id=? AND turn_id=?",
            (row["parent_id"], row["turn_id"]),
        ).fetchone()
        if notice is not None:
            if not self._setup_open(db):
                return False
            try:
                own = self._setup_notice(db, row["parent_id"], notice["question_id"])
                head = self._setup_head(db, row["parent_id"])
            except ParentChatError:
                return False
            if (
                own is None
                or head is None
                or not head[0]["known"]
                or head[0]["epoch_id"] != notice["epoch_id"]
                or head[1].connected_child_ids
                or not setup_observation_current(head[1], now, self._setup_policy)
            ):
                return False
        return super()._push_delivery_ready(db, row, now)


class SqliteClosedParentSetupStore(SqliteClosedCompactSourceToolStore):
    _schema_version = 42

    def __init__(self, path: Path, **family: Any) -> None:
        super().__init__(path, **family)
        self._schema_version = 42

    def _supported_versions(self) -> set[int]:
        return {42}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
