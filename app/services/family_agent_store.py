"""Durable specialist intents; only Parent-Touch can publish into the one chat."""

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.family_agents import (
    AgentQuestionPage,
    AgentQuestionReceipt,
    AgentQuestionRequest,
    FamilyQuestion,
    ParentTouchRequest,
)
from app.services.parent_chat_store import SqliteParentChatStore


class SqliteFamilyAgentStore(SqliteParentChatStore):
    """Opt-in v2 reader. The released v1 reader must refuse this schema, not downgrade it."""

    _schema_version = 2

    def __init__(
        self,
        path: Path,
        *,
        daily_limit: int,
        timezone: str,
        max_attempts: int = 20,
        question_limit: int = 100,
    ) -> None:
        super().__init__(
            path, daily_limit=daily_limit, timezone=timezone, max_attempts=max_attempts
        )
        if not 1 <= question_limit <= 1000:
            raise ValueError("Pending question ceiling must be between 1 and 1000")
        self._question_limit = question_limit

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {"family_questions", "family_question_intents"}

    def _extra_schema(self) -> str:
        return """
            CREATE TABLE IF NOT EXISTS family_questions (
                position INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id TEXT NOT NULL UNIQUE,
                parent_id TEXT NOT NULL,
                child_id INTEGER NOT NULL,
                information_key TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                priority INTEGER NOT NULL,
                offered_turn_id INTEGER,
                answer_turn_id INTEGER,
                UNIQUE(parent_id, answer_turn_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS family_one_open_information
                ON family_questions(parent_id, child_id, information_key)
                WHERE status IN ('queued', 'offered', 'awaiting_reply', 'held');
            CREATE UNIQUE INDEX IF NOT EXISTS family_one_active_question
                ON family_questions(parent_id)
                WHERE status IN ('offered', 'awaiting_reply', 'held');
            CREATE INDEX IF NOT EXISTS family_question_order
                ON family_questions(parent_id, status, priority DESC, position);
            CREATE TABLE IF NOT EXISTS family_question_intents (
                parent_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                digest TEXT NOT NULL,
                question_id TEXT NOT NULL,
                coalesced INTEGER NOT NULL,
                PRIMARY KEY(parent_id, agent_id, request_id)
            );
        """

    @staticmethod
    def _digest(request: ParentChatRequest) -> str:
        if isinstance(request, ParentTouchRequest) and request.reply_to_question_id is None:
            request = ParentChatRequest.model_validate(
                request.model_dump(exclude={"reply_to_question_id"})
            )
        return SqliteParentChatStore._digest(request)

    def _on_admitted(
        self,
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        now: datetime,
    ) -> None:
        if isinstance(request, ParentTouchRequest) and request.reply_to_question_id is not None:
            row = connection.execute(
                "SELECT * FROM family_questions WHERE parent_id=? AND question_id=? "
                "AND status='awaiting_reply' AND offered_turn_id<?",
                (request.parent_id, str(request.reply_to_question_id), turn_id),
            ).fetchone()
            if row is None:
                raise ParentChatError("question_reply_mismatch", 409)
            connection.execute(
                "UPDATE family_questions SET status='answered',answer_turn_id=? "
                "WHERE question_id=?",
                (turn_id, row["question_id"]),
            )
        self._offer_in_transaction(connection, request.parent_id, turn_id, now)

    def _valid_decision(
        self,
        connection: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        now: datetime,
    ) -> bool:
        if receipt.question_id is None:
            return True
        return (
            connection.execute(
                "SELECT 1 FROM family_questions WHERE parent_id=? AND offered_turn_id=? "
                "AND question_id=? AND status IN ('offered','held') AND expires_at>?",
                (turn.parent_id, turn.turn_id, str(receipt.question_id), now.isoformat()),
            ).fetchone()
            is not None
        )

    def _on_settled(
        self,
        connection: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        connection.execute(
            "UPDATE family_questions SET status=? WHERE parent_id=? AND offered_turn_id=? "
            "AND status IN ('offered','held')",
            (
                "awaiting_reply" if valid and receipt.question_id is not None else "queued",
                turn.parent_id,
                turn.turn_id,
            ),
        )

    def _on_failed(
        self, connection: sqlite3.Connection, turn: StoredChatTurn, *, unknown: bool
    ) -> None:
        connection.execute(
            "UPDATE family_questions SET status=? WHERE parent_id=? AND offered_turn_id=? "
            "AND status='offered'",
            ("held" if unknown else "queued", turn.parent_id, turn.turn_id),
        )

    @staticmethod
    def _recover_pre_dispatch(
        connection: sqlite3.Connection, parent_id: str, now: datetime
    ) -> None:
        SqliteParentChatStore._recover_pre_dispatch(connection, parent_id, now)
        connection.execute(
            "UPDATE family_questions SET status='queued' WHERE parent_id=? AND status='offered' "
            "AND offered_turn_id IN (SELECT id FROM parent_chat_turns WHERE parent_id=? "
            "AND status='failed')",
            (parent_id, parent_id),
        )
        connection.execute(
            "UPDATE family_questions SET status='held' WHERE parent_id=? AND status='offered' "
            "AND offered_turn_id IN (SELECT id FROM parent_chat_turns WHERE parent_id=? "
            "AND status='unknown')",
            (parent_id, parent_id),
        )

    async def question_for_turn(self, parent_id: str, turn_id: int) -> FamilyQuestion | None:
        def read() -> FamilyQuestion | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM family_questions WHERE parent_id=? AND offered_turn_id=? "
                    "AND status='offered'",
                    (parent_id, turn_id),
                ).fetchone()
                return self._question(row) if row is not None else None

        return await asyncio.to_thread(read)

    @staticmethod
    def _question(row: sqlite3.Row) -> FamilyQuestion:
        question = FamilyQuestion.model_validate(
            FamilyQuestion.model_validate_json(row["payload"]).model_dump()
            | {
                "status": row["status"],
                "priority": row["priority"],
                "offered_turn_id": row["offered_turn_id"],
                "answer_turn_id": row["answer_turn_id"],
            }
        )
        if (
            str(question.question_id) != row["question_id"]
            or question.parent_id != row["parent_id"]
            or question.child_id != row["child_id"]
            or question.information_key != row["information_key"]
        ):
            raise ParentChatError("question_state_unavailable", 503)
        return question

    @staticmethod
    def _question_digest(request: AgentQuestionRequest) -> str:
        return hashlib.sha256(request.model_dump_json(exclude={"request_id"}).encode()).hexdigest()

    def _known_intent(
        self, connection: sqlite3.Connection, request: AgentQuestionRequest
    ) -> AgentQuestionReceipt | None:
        intent = connection.execute(
            "SELECT * FROM family_question_intents WHERE parent_id=? AND agent_id=? "
            "AND request_id=?",
            (request.parent_id, request.agent_id, str(request.request_id)),
        ).fetchone()
        if intent is None:
            return None
        if intent["digest"] != self._question_digest(request):
            raise ParentChatError("request_id_conflict", 409)
        row = connection.execute(
            "SELECT * FROM family_questions WHERE question_id=? AND parent_id=?",
            (intent["question_id"], request.parent_id),
        ).fetchone()
        if row is None:
            raise ParentChatError("question_state_unavailable", 503)
        return AgentQuestionReceipt(
            request_id=request.request_id,
            question=self._question(row),
            coalesced=bool(intent["coalesced"]),
        )

    async def known_intent(self, request: AgentQuestionRequest) -> AgentQuestionReceipt | None:
        def read() -> AgentQuestionReceipt | None:
            with self._connect() as connection:
                return self._known_intent(connection, request)

        return await asyncio.to_thread(read)

    async def enqueue(self, request: AgentQuestionRequest, now: datetime) -> AgentQuestionReceipt:
        return await asyncio.to_thread(self._enqueue, request, now)

    def _enqueue(self, request: AgentQuestionRequest, now: datetime) -> AgentQuestionReceipt:
        now = self._utc(now)
        with self._transaction() as connection:
            known = self._known_intent(connection, request)
            if known is not None:
                return known
            if request.observed_at > now + timedelta(minutes=5) or request.expires_at <= now:
                raise ParentChatError("question_outside_observation_window", 422)
            # Only unsent questions can expire automatically. An offered/unknown
            # generation may already have cost money and never frees by clock alone.
            connection.execute(
                "UPDATE family_questions SET status='expired' WHERE parent_id=? "
                "AND status='queued' AND expires_at<=?",
                (request.parent_id, now.isoformat()),
            )
            row = connection.execute(
                "SELECT * FROM family_questions WHERE parent_id=? AND child_id=? "
                "AND information_key=? AND status IN ('queued','offered','awaiting_reply','held')",
                (request.parent_id, request.child_id, request.information_key),
            ).fetchone()
            coalesced = row is not None
            if row is None:
                count = connection.execute(
                    "SELECT COUNT(*) FROM family_questions WHERE parent_id=? "
                    "AND status IN ('queued','offered','awaiting_reply','held')",
                    (request.parent_id,),
                ).fetchone()[0]
                if count >= self._question_limit:
                    raise ParentChatError("parent_question_queue_full", 429)
                question = FamilyQuestion(
                    question_id=uuid4(),
                    parent_id=request.parent_id,
                    child_id=request.child_id,
                    information_key=request.information_key,
                    question=request.question,
                    reason=request.reason,
                    priority=request.priority,
                    status="queued",
                    observed_at=request.observed_at,
                    expires_at=request.expires_at,
                    created_at=now,
                )
                connection.execute(
                    "INSERT INTO family_questions(question_id,parent_id,child_id,information_key,"
                    "status,payload,created_at,expires_at,priority) "
                    "VALUES(?,?,?,?,'queued',?,?,?,?)",
                    (
                        str(question.question_id),
                        request.parent_id,
                        request.child_id,
                        request.information_key,
                        question.model_dump_json(),
                        now.isoformat(),
                        request.expires_at.astimezone(now.tzinfo).isoformat(),
                        request.priority,
                    ),
                )
            else:
                question = self._question(row)
                if row["status"] == "queued" and request.priority > row["priority"]:
                    connection.execute(
                        "UPDATE family_questions SET priority=? WHERE question_id=?",
                        (request.priority, row["question_id"]),
                    )
                    question = question.model_copy(update={"priority": request.priority})
            connection.execute(
                "INSERT INTO family_question_intents VALUES(?,?,?,?,?,?)",
                (
                    request.parent_id,
                    request.agent_id,
                    str(request.request_id),
                    self._question_digest(request),
                    str(question.question_id),
                    int(coalesced),
                ),
            )
            return AgentQuestionReceipt(
                request_id=request.request_id, question=question, coalesced=coalesced
            )

    async def questions(
        self, parent_id: str, *, after: int | None = None, limit: int = 20
    ) -> AgentQuestionPage:
        if not 1 <= limit <= 100 or after is not None and after < 0:
            raise ParentChatError("invalid_question_cursor", 422)

        def read() -> AgentQuestionPage:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM family_questions WHERE parent_id=? AND position>? "
                    "ORDER BY position LIMIT ?",
                    (parent_id, after or 0, limit + 1),
                ).fetchall()
            selected = rows[:limit]
            return AgentQuestionPage(
                parent_id=parent_id,
                questions=[self._question(row) for row in selected],
                next_after=selected[-1]["position"] if len(rows) > limit else None,
            )

        return await asyncio.to_thread(read)

    async def offer_next(
        self, parent_id: str, *, turn_id: int, now: datetime
    ) -> FamilyQuestion | None:
        def offer() -> FamilyQuestion | None:
            with self._transaction() as connection:
                return self._offer_in_transaction(connection, parent_id, turn_id, self._utc(now))

        return await asyncio.to_thread(offer)

    def _offer_in_transaction(
        self,
        connection: sqlite3.Connection,
        parent_id: str,
        turn_id: int,
        now: datetime,
    ) -> FamilyQuestion | None:
        turn = connection.execute(
            "SELECT * FROM parent_chat_turns WHERE id=? AND parent_id=?",
            (turn_id, parent_id),
        ).fetchone()
        if turn is None or turn["status"] != "preparing":
            raise ParentChatError("request_no_longer_admitted", 409)
        active = connection.execute(
            "SELECT * FROM family_questions WHERE parent_id=? "
            "AND status IN ('offered','awaiting_reply','held')",
            (parent_id,),
        ).fetchone()
        if active is not None:
            if active["offered_turn_id"] == turn_id and active["status"] == "offered":
                return self._question(active)
            return None
        connection.execute(
            "UPDATE family_questions SET status='expired' WHERE parent_id=? "
            "AND status='queued' AND expires_at<=?",
            (parent_id, now.isoformat()),
        )
        row = connection.execute(
            "SELECT * FROM family_questions WHERE parent_id=? AND status='queued' "
            "ORDER BY priority DESC, position LIMIT 1",
            (parent_id,),
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            "UPDATE family_questions SET status='offered',offered_turn_id=? WHERE question_id=?",
            (turn_id, row["question_id"]),
        )
        return self._question(row).model_copy(
            update={"status": "offered", "offered_turn_id": turn_id}
        )
