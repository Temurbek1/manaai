"""Family v29: one reactive question from a newly captured Parent-Touch manager turn."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.application.parent_languages import neutral_parent_reply, parent_language
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.family_agents import (
    FamilyQuestion,
    ParentTouchRequest,
    ParentTouchReviewedTurn,
    ParentTouchText,
)
from app.mana_ai.domain.parent_touch_manager import ParentTouchManagerScope
from app.services.parent_support_question_store import (
    SqliteClosedParentSupportQuestionStore,
    SqliteParentSupportQuestionStore,
)

_TABLES = {"parent_clarification_admissions", "parent_clarification_questions"}


class SqliteParentClarificationStore(SqliteParentSupportQuestionStore):
    _schema_version = 29

    def __init__(self, path: Path, *, clarifications_enabled: bool = False, **family: Any) -> None:
        self._clarifications_enabled = clarifications_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {28}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS parent_clarification_admissions(
            turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS parent_clarification_questions(
            turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,question_id TEXT NOT NULL UNIQUE);
        """
        )

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        if (
            not self._clarifications_enabled
            and isinstance(request, ParentTouchRequest)
            and request.reply_to_question_id is not None
            and db.execute(
                "SELECT 1 FROM parent_clarification_questions WHERE parent_id=? AND question_id=?",
                (request.parent_id, str(request.reply_to_question_id)),
            ).fetchone()
        ):
            raise ParentChatError("parent_clarifications_disabled", 503)
        super()._on_admitted(db, request, turn_id, now)

    def _defer_initial_review(
        self,
        db: sqlite3.Connection,
        request: ParentTouchReviewedTurn,
        turn_id: int,
        now: datetime,
        context: str,
    ) -> bool:
        previous = None
        if (
            self._clarifications_enabled
            and parent_language(request.message) is None
            and (
                neutral_parent_reply(request.message)
                or request.message.strip().casefold().rstrip(".!?") in {"android", "iphone", "ios"}
            )
        ):
            previous = db.execute(
                "SELECT m.language,f.language_reference FROM parent_clarification_questions q "
                "JOIN family_questions a ON a.question_id=q.question_id "
                "AND a.parent_id=q.parent_id JOIN parent_touch_manager_turns m "
                "ON m.turn_id=q.turn_id AND m.parent_id=q.parent_id "
                "JOIN family_turn_metadata f ON f.turn_id=q.turn_id "
                "AND f.parent_id=q.parent_id WHERE q.parent_id=? "
                "AND a.answer_turn_id=? AND a.status='answered'",
                (request.parent_id, turn_id),
            ).fetchone()
            if previous is not None:
                # Presentation survives an urgent specialist interruption too.
                db.execute(
                    "UPDATE family_turn_metadata SET language_reference=? WHERE turn_id=? "
                    "AND parent_id=?",
                    (previous["language_reference"], turn_id, request.parent_id),
                )
        deferred = super()._defer_initial_review(db, request, turn_id, now, context)
        if deferred and self._clarifications_enabled:
            if previous is not None:
                # The explicit answer inherits the question's frozen language,
                # never current contact preferences or source/action grants.
                db.execute(
                    "UPDATE parent_touch_manager_turns SET language=? WHERE turn_id=? "
                    "AND parent_id=?",
                    (previous["language"], turn_id, request.parent_id),
                )
            db.execute(
                "INSERT INTO parent_clarification_admissions VALUES(?,?)",
                (turn_id, request.parent_id),
            )
        return deferred

    async def manager_scope(self, parent_id: str, turn_id: int) -> ParentTouchManagerScope | None:
        scope = await super().manager_scope(parent_id, turn_id)
        if scope is None:
            return scope

        def captured() -> sqlite3.Row | None:
            with self._connect() as db:
                return cast(
                    sqlite3.Row | None,
                    db.execute(
                        "SELECT m.language_reference FROM parent_clarification_admissions a "
                        "JOIN family_turn_metadata m ON m.turn_id=a.turn_id "
                        "AND m.parent_id=a.parent_id WHERE a.parent_id=? AND a.turn_id=?",
                        (parent_id, turn_id),
                    ).fetchone(),
                )

        row = await asyncio.to_thread(captured)
        if row is None:
            return scope
        if scope.stage == "route" and not self._clarifications_enabled:
            raise ParentChatError("parent_clarifications_disabled", 503)
        reference = row["language_reference"]
        return scope.model_copy(
            update={
                "clarifications_enabled": scope.stage == "route",
                "language_reference": reference if parent_language(reference) is None else None,
            }
        )

    def _question_reply_needs_safety(
        self, db: sqlite3.Connection, request: ParentTouchReviewedTurn, turn_id: int
    ) -> bool:
        if (
            request.reply_to_question_id is not None
            and db.execute(
                "SELECT 1 FROM parent_clarification_questions c JOIN family_questions q "
                "ON q.question_id=c.question_id AND q.parent_id=c.parent_id "
                "WHERE c.parent_id=? AND c.question_id=? AND q.child_id IS NULL "
                "AND q.status='answered' AND q.answer_turn_id=?",
                (request.parent_id, str(request.reply_to_question_id), turn_id),
            ).fetchone()
        ):
            return False
        return super()._question_reply_needs_safety(db, request, turn_id)

    async def answered_parent_question(self, parent_id: str, turn_id: int) -> str | None:
        def read() -> str | None:
            with self._connect() as db:
                row = db.execute(
                    "SELECT t.answer FROM parent_clarification_questions c JOIN family_questions q "
                    "ON q.question_id=c.question_id AND q.parent_id=c.parent_id "
                    "AND q.offered_turn_id=c.turn_id JOIN parent_chat_turns t "
                    "ON t.id=c.turn_id AND t.parent_id=c.parent_id WHERE c.parent_id=? "
                    "AND q.answer_turn_id=? AND q.status='answered' AND t.status='completed'",
                    (parent_id, turn_id),
                ).fetchone()
                return cast(str | None, row[0]) if row else None

        own = await asyncio.to_thread(read)
        return (
            own if own is not None else await super().answered_parent_question(parent_id, turn_id)
        )

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        question = receipt.clarification_question
        if question is None:
            return super()._valid_decision(db, turn, receipt, now)
        if (
            not self._clarifications_enabled
            or receipt.question_id
            or receipt.notice_id
            or receipt.manager_handoff
            or receipt.upsell_choice
            or receipt.reminder_candidate
            or not receipt.answer
            or not receipt.answer.endswith(question)
        ):
            return False
        try:
            ParentTouchText(body=receipt.answer[: -len(question)].strip(), question=question)
        except (ValueError, ValidationError):
            return False
        return self._clarification_scope_matches(db, turn) and super()._valid_decision(
            db, turn, replace(receipt, clarification_question=None), now
        )

    def _clarification_scope_matches(self, db: sqlite3.Connection, turn: StoredChatTurn) -> bool:
        row = db.execute(
            "SELECT 1 FROM parent_clarification_admissions a JOIN parent_touch_manager_turns m "
            "ON m.turn_id=a.turn_id AND m.parent_id=a.parent_id WHERE a.parent_id=? "
            "AND a.turn_id=? AND m.phase='routing' AND m.choice IS NULL",
            (turn.parent_id, turn.turn_id),
        ).fetchone()
        return row is not None

    def _on_settled(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        super()._on_settled(db, turn, receipt, valid=valid)
        if not valid or receipt.clarification_question is None:
            return
        now = datetime.fromisoformat(
            db.execute(
                "SELECT updated_at FROM parent_chat_turns WHERE id=?", (turn.turn_id,)
            ).fetchone()[0]
        )
        identity = uuid5(
            NAMESPACE_URL, f"mana:parent-clarification:{turn.parent_id}:{turn.request_id}"
        )
        question = FamilyQuestion(
            question_id=identity,
            parent_id=turn.parent_id,
            child_id=None,
            scope="parent",
            information_key="parent.intent_clarification",
            question=receipt.clarification_question,
            reason="Clarification of this parent-initiated request; no source or action authority.",
            priority=1,
            status="awaiting_reply",
            observed_at=now,
            expires_at=now + timedelta(days=1),
            created_at=now,
            offered_turn_id=turn.turn_id,
        )
        db.execute(
            "INSERT INTO family_questions(question_id,parent_id,child_id,information_key,status,"
            "payload,created_at,expires_at,priority,offered_turn_id) "
            "VALUES(?,?,NULL,?,'awaiting_reply',?,?,?,?,?)",
            (
                str(identity),
                turn.parent_id,
                question.information_key,
                question.model_dump_json(),
                now.isoformat(),
                question.expires_at.isoformat(),
                question.priority,
                turn.turn_id,
            ),
        )
        db.execute(
            "INSERT INTO parent_clarification_questions VALUES(?,?,?)",
            (turn.turn_id, turn.parent_id, str(identity)),
        )
        db.execute(
            "UPDATE family_turn_metadata SET published_question_id=? "
            "WHERE parent_id=? AND turn_id=?",
            (str(identity), turn.parent_id, turn.turn_id),
        )


class SqliteClosedParentClarificationStore(SqliteClosedParentSupportQuestionStore):
    _schema_version = 29

    def _supported_versions(self) -> set[int]:
        return {29}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
