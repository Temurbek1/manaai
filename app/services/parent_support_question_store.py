"""Family v28: parent-scoped support questions reuse the single specialist queue."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.client_retention import ParentTouchRetentionTurn, RetentionIntent
from app.mana_ai.domain.family_agents import (
    FamilyQuestion,
    ParentTouchRequest,
    ParentTouchReviewedTurn,
)
from app.services.family_agent_store import SqliteFamilyAgentStore
from app.services.safety_remainder_store import (
    SqliteClosedSafetyRemainderStore,
    SqliteSafetyRemainderStore,
)

_TABLE = "retention_parent_question_captures"


class SqliteParentSupportQuestionStore(SqliteSafetyRemainderStore):
    _schema_version = 28

    def __init__(
        self, path: Path, *, parent_questions_enabled: bool = False, **family: Any
    ) -> None:
        self._parent_questions_enabled = parent_questions_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {27}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}

    def _question_schema(self) -> str:
        return super()._question_schema().replace("child_id INTEGER NOT NULL", "child_id INTEGER")

    def _extra_schema(self) -> str:
        schema = super()._extra_schema()
        queue_schema = self._question_schema()
        migrate = False
        if self._path.exists():
            with self._connect() as db:
                migrate = any(
                    row[1] == "child_id" and row[3]
                    for row in db.execute("PRAGMA table_info(family_questions)")
                )
                if (
                    migrate
                    and db.execute(
                        "SELECT 1 FROM sqlite_master WHERE "
                        "type='view' OR (type='trigger' AND tbl_name='family_questions') "
                        "OR (type='index' AND tbl_name='family_questions' "
                        "AND name NOT LIKE 'sqlite_autoindex_%' "
                        "AND name NOT IN ('family_one_open_information',"
                        "'family_one_active_question','family_question_order'))"
                    ).fetchone()
                ):
                    raise RuntimeError("Unsupported question queue schema migration")
        # Runs inside the owning BEGIN IMMEDIATE, including index/sequence preservation.
        # No old payload, ID, answer binding or pending state is rewritten.
        migration = ""
        if migrate:
            migration = (
                "CREATE TEMP TABLE parent_question_sequence(value INTEGER);"
                "INSERT INTO parent_question_sequence SELECT seq FROM sqlite_sequence "
                "WHERE name='family_questions';"
                "DROP INDEX family_one_open_information;"
                "DROP INDEX family_one_active_question;"
                "DROP INDEX family_question_order;"
                "ALTER TABLE family_questions RENAME TO family_questions_v27;"
                + queue_schema
                + "INSERT INTO family_questions SELECT * FROM family_questions_v27;"
                "INSERT INTO sqlite_sequence(name,seq) SELECT 'family_questions',value "
                "FROM parent_question_sequence WHERE NOT EXISTS "
                "(SELECT 1 FROM sqlite_sequence WHERE name='family_questions');"
                "UPDATE sqlite_sequence SET seq=MAX(seq,COALESCE("
                "(SELECT value FROM parent_question_sequence),0)) WHERE name='family_questions';"
                "DROP TABLE family_questions_v27;DROP TABLE parent_question_sequence;"
            )
        return (
            migration
            + schema
            + """
        CREATE TABLE IF NOT EXISTS retention_parent_question_captures(
            turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,
            intent_id TEXT NOT NULL UNIQUE,question_id TEXT NOT NULL UNIQUE);
        """
        )

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        if (
            isinstance(request, ParentTouchRequest)
            and request.reply_to_question_id is not None
            and not self._parent_questions_enabled
            and db.execute(
                "SELECT 1 FROM retention_parent_question_captures "
                "WHERE parent_id=? AND question_id=?",
                (request.parent_id, str(request.reply_to_question_id)),
            ).fetchone()
        ):
            raise ParentChatError("parent_support_questions_disabled", 503)
        super()._on_admitted(db, request, turn_id, now)
        if not self._parent_questions_enabled or not isinstance(request, ParentTouchRetentionTurn):
            return
        row = db.execute(
            "SELECT payload FROM retention_intents WHERE intent_id=? AND turn_id=?",
            (str(request.retention_intent_id), turn_id),
        ).fetchone()
        if row is None:
            raise ParentChatError("retention_intent_not_active", 409)
        intent = RetentionIntent.model_validate_json(row[0])
        identity = uuid5(NAMESPACE_URL, f"mana:retention-support-question:{intent.intent_id}")
        question = FamilyQuestion(
            question_id=identity,
            parent_id=intent.parent_id,
            child_id=None,
            scope="parent",
            information_key="parent.support_need",
            question="Clarify the parent's support need about the historical topic or MANA.",
            reason="Chat inactivity permits a support check-in, not an app-churn or risk claim.",
            priority=0,
            status="offered",
            observed_at=intent.admitted_at,
            expires_at=intent.expires_at,
            created_at=now,
            offered_turn_id=turn_id,
        )
        db.execute(
            "INSERT INTO family_questions(question_id,parent_id,child_id,information_key,status,"
            "payload,created_at,expires_at,priority,offered_turn_id) "
            "VALUES(?,?,NULL,?,'offered',?,?,?,?,?)",
            (
                str(identity),
                intent.parent_id,
                question.information_key,
                question.model_dump_json(),
                now.isoformat(),
                intent.expires_at.isoformat(),
                question.priority,
                turn_id,
            ),
        )
        db.execute(
            "INSERT INTO family_turn_metadata(parent_id,turn_id,kind,offered_question_id,"
            "language_turn_id,language_reference) VALUES(?,?,'retention_support',?,?,?)",
            (intent.parent_id, turn_id, str(identity), turn_id, intent.language),
        )
        db.execute(
            "INSERT INTO retention_parent_question_captures VALUES(?,?,?,?)",
            (turn_id, intent.parent_id, str(intent.intent_id), str(identity)),
        )

    async def retention_question(self, parent_id: str, turn_id: int) -> FamilyQuestion | None:
        if not self._parent_questions_enabled:
            return None
        return await self.question_for_turn(parent_id, turn_id)

    def _on_retention_opt_out(self, db: sqlite3.Connection, parent_id: str) -> None:
        super()._on_retention_opt_out(db, parent_id)
        # An explicit refusal closes only this owner's published support question.
        # Keep child questions and uncertain in-flight questions/usage intact.
        db.execute(
            "UPDATE family_questions SET status='cancelled' WHERE parent_id=? "
            "AND child_id IS NULL AND status='awaiting_reply' AND question_id IN "
            "(SELECT question_id FROM retention_parent_question_captures WHERE parent_id=?)",
            (parent_id, parent_id),
        )

    def _question_reply_needs_safety(
        self, db: sqlite3.Connection, request: ParentTouchReviewedTurn, turn_id: int
    ) -> bool:
        if (
            request.reply_to_question_id is not None
            and db.execute(
                "SELECT 1 FROM retention_parent_question_captures c "
                "JOIN family_questions q ON q.question_id=c.question_id "
                "AND q.parent_id=c.parent_id "
                "WHERE c.parent_id=? AND c.question_id=? AND q.answer_turn_id=? "
                "AND q.status='answered' AND q.child_id IS NULL",
                (request.parent_id, str(request.reply_to_question_id), turn_id),
            ).fetchone()
        ):
            return False
        return super()._question_reply_needs_safety(db, request, turn_id)

    @staticmethod
    def _capture(db: sqlite3.Connection, turn: StoredChatTurn) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            db.execute(
                "SELECT * FROM retention_parent_question_captures WHERE parent_id=? AND turn_id=?",
                (turn.parent_id, turn.turn_id),
            ).fetchone(),
        )

    async def answered_parent_question(self, parent_id: str, turn_id: int) -> str | None:
        def read() -> str | None:
            with self._connect() as db:
                row = db.execute(
                    "SELECT t.answer FROM family_questions q "
                    "JOIN retention_parent_question_captures c ON c.question_id=q.question_id "
                    "AND c.parent_id=q.parent_id AND c.turn_id=q.offered_turn_id "
                    "JOIN parent_chat_turns t ON t.id=c.turn_id AND t.parent_id=c.parent_id "
                    "WHERE q.parent_id=? AND q.answer_turn_id=? AND q.child_id IS NULL "
                    "AND q.status='answered' AND t.status='completed'",
                    (parent_id, turn_id),
                ).fetchone()
                return cast(str | None, row[0]) if row else None

        return await asyncio.to_thread(read)

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        captured = self._capture(db, turn)
        if captured is None:
            return super()._valid_decision(db, turn, receipt, now)
        return bool(
            self._parent_questions_enabled
            and str(receipt.question_id) == captured["question_id"]
            and super()._valid_decision(db, turn, replace(receipt, question_id=None), now)
            and SqliteFamilyAgentStore._valid_decision(self, db, turn, receipt, now)
        )

    def _on_settled(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        super()._on_settled(db, turn, receipt, valid=valid)
        if self._capture(db, turn) is not None:
            SqliteFamilyAgentStore._on_settled(self, db, turn, receipt, valid=valid)
            if not valid:
                db.execute(
                    "UPDATE family_questions SET status='cancelled' "
                    "WHERE parent_id=? AND offered_turn_id=? AND child_id IS NULL",
                    (turn.parent_id, turn.turn_id),
                )

    def _on_failed(self, db: sqlite3.Connection, turn: StoredChatTurn, *, unknown: bool) -> None:
        super()._on_failed(db, turn, unknown=unknown)
        if self._capture(db, turn) is not None:
            db.execute(
                "UPDATE family_questions SET status=? WHERE parent_id=? AND offered_turn_id=? "
                "AND status='offered' AND child_id IS NULL",
                ("held" if unknown else "cancelled", turn.parent_id, turn.turn_id),
            )

    @staticmethod
    def _recover_pre_dispatch(db: sqlite3.Connection, parent_id: str, now: datetime) -> None:
        SqliteSafetyRemainderStore._recover_pre_dispatch(db, parent_id, now)
        # Parent support belongs only to its captured Retention turn, never generic
        # safety delivery, deferred re-admission or another paid attempt.
        db.execute(
            "UPDATE family_questions SET status='cancelled' WHERE parent_id=? "
            "AND child_id IS NULL AND status='queued' AND question_id IN "
            "(SELECT question_id FROM retention_parent_question_captures WHERE parent_id=?)",
            (parent_id, parent_id),
        )


class SqliteClosedParentSupportQuestionStore(SqliteClosedSafetyRemainderStore):
    _schema_version = 28

    def _supported_versions(self) -> set[int]:
        return {28}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}
