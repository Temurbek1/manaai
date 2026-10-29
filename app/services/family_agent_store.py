"""Durable specialist intents; only Parent-Touch can publish into the one chat."""

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.application.parent_languages import neutral_parent_reply, parent_language
from app.mana_ai.domain.chat import ParentChatRequest, ResponseLanguage, StoredChatTurn
from app.mana_ai.domain.commercial_conversation import CommercialConversationContext
from app.mana_ai.domain.family_agents import (
    AgentQuestionPage,
    AgentQuestionReceipt,
    AgentQuestionRequest,
    FamilyQuestion,
    ParentTouchDeferredTurn,
    ParentTouchDeliveryTurn,
    ParentTouchEvidence,
    ParentTouchHistory,
    ParentTouchMessageRequest,
    ParentTouchMessageState,
    ParentTouchNotice,
    ParentTouchQuestion,
    ParentTouchRequest,
    ParentTouchReviewedTurn,
)
from app.services.parent_chat_store import SqliteParentChatStore


class SqliteFamilyAgentStore(SqliteParentChatStore):
    """Opt-in family reader. Older readers must refuse, never downgrade, its schema."""

    _schema_version = 3

    async def commercial_preference_control(
        self, request: ParentTouchMessageRequest, now: datetime
    ) -> ParentTouchMessageState | None:
        """Legacy readers have no host-command or commercial preference contract."""
        return None

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {2}

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
        return super()._allowed_tables() | {
            "family_questions",
            "family_question_intents",
            "family_turn_metadata",
            "family_intent_claims",
            "family_intent_admissions",
            "family_information_revisions",
        }

    def _question_schema(self) -> str:
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
        """

    def _extra_schema(self) -> str:
        return (
            self._question_schema()
            + """
            CREATE TABLE IF NOT EXISTS family_question_intents (
                parent_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                digest TEXT NOT NULL,
                question_id TEXT NOT NULL,
                coalesced INTEGER NOT NULL,
                PRIMARY KEY(parent_id, agent_id, request_id)
            );
            CREATE INDEX IF NOT EXISTS family_intent_digest
                ON family_question_intents(parent_id, agent_id, digest);
            CREATE TABLE IF NOT EXISTS family_turn_metadata (
                parent_id TEXT NOT NULL,
                turn_id INTEGER NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                offered_question_id TEXT,
                published_question_id TEXT,
                language_turn_id INTEGER NOT NULL,
                language_reference TEXT NOT NULL,
                PRIMARY KEY(parent_id, turn_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS family_delivery_context
                ON family_turn_metadata(parent_id, offered_question_id, language_turn_id)
                WHERE kind='delivery';
            CREATE TABLE IF NOT EXISTS family_intent_claims (
                parent_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                digest TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                error_code TEXT,
                error_status INTEGER,
                PRIMARY KEY(parent_id, agent_id, digest)
            );
            CREATE TABLE IF NOT EXISTS family_intent_admissions (
                parent_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                digest TEXT NOT NULL,
                PRIMARY KEY(parent_id, agent_id, request_id)
            );
            CREATE TABLE IF NOT EXISTS family_information_revisions (
                parent_id TEXT NOT NULL,
                child_id INTEGER NOT NULL,
                information_key TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                question_id TEXT NOT NULL,
                PRIMARY KEY(parent_id, child_id, information_key, source_revision)
            );
        """
        )

    @staticmethod
    def _digest(request: ParentChatRequest) -> str:
        if isinstance(request, ParentTouchReviewedTurn):
            return SqliteParentChatStore._digest(request)
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
        self._bind_answer(connection, request, turn_id)
        self._capture_communication(connection, request, turn_id, now)

    @staticmethod
    def _bind_answer(
        connection: sqlite3.Connection, request: ParentChatRequest, turn_id: int
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

    def _capture_communication(
        self,
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        now: datetime,
    ) -> None:
        selected = self._offer_in_transaction(connection, request.parent_id, turn_id, now)
        anchor = self._admit_extra_context(connection, request, turn_id, selected, now)
        language_turn_id, reference = turn_id, request.message
        delivery = isinstance(request, ParentTouchDeliveryTurn)
        if not delivery and parent_language(reference) is None and neutral_parent_reply(reference):
            previous = self._previous_language(connection, request.parent_id, turn_id)
            if previous is not None:
                reference = previous["reference"]
        if delivery:
            if anchor is None:
                raise ParentChatError("no_question_ready_for_delivery", 409)
            language_turn_id, reference = self._delivery_language(
                connection, request.parent_id, turn_id, now
            )
            if isinstance(request, ParentTouchDeferredTurn):
                anchor = self._resume_delivery_anchor(
                    connection, request, anchor, language_turn_id, now
                )
            elif (
                connection.execute(
                    "SELECT 1 FROM family_turn_metadata WHERE parent_id=? "
                    "AND (kind='delivery' OR offered_question_id LIKE 'notice:%') "
                    "AND offered_question_id=? AND language_turn_id=?",
                    (request.parent_id, anchor, language_turn_id),
                ).fetchone()
                is not None
            ):
                raise ParentChatError("delivery_context_already_processed", 409)
        connection.execute(
            "INSERT INTO family_turn_metadata(parent_id,turn_id,kind,offered_question_id,"
            "language_turn_id,language_reference) VALUES(?,?,?,?,?,?)",
            (
                request.parent_id,
                turn_id,
                "delivery" if delivery else "message",
                anchor,
                language_turn_id,
                reference,
            ),
        )

    def _delivery_language(
        self, connection: sqlite3.Connection, parent_id: str, turn_id: int, now: datetime
    ) -> tuple[int, str]:
        """Legacy delivery requires real prior text; scoped adapters may bind preferences."""
        previous = self._previous_language(connection, parent_id, turn_id)
        if previous is None:
            raise ParentChatError("parent_language_not_established", 409)
        return previous["id"], previous["reference"]

    async def language_hint(self, parent_id: str, turn_id: int) -> ResponseLanguage | None:
        return None

    async def answered_parent_question(self, parent_id: str, turn_id: int) -> str | None:
        return None

    async def commercial_context(
        self, parent_id: str, turn_id: int
    ) -> CommercialConversationContext | None:
        return None

    def _resume_delivery_anchor(
        self,
        connection: sqlite3.Connection,
        request: ParentTouchDeferredTurn,
        anchor: str,
        language_turn_id: int,
        now: datetime,
    ) -> str:
        original = connection.execute(
            "SELECT t.*,m.offered_question_id,m.language_turn_id,m.kind "
            "FROM parent_chat_turns t JOIN family_turn_metadata m "
            "ON m.turn_id=t.id AND m.parent_id=t.parent_id "
            "WHERE t.parent_id=? AND t.request_id=?",
            (request.parent_id, str(request.resume_deferred_request_id)),
        ).fetchone()
        day, _ = self._period(now)

        def before_generation_budget_refusal(row: sqlite3.Row) -> bool:
            return bool(
                row["status"] == "failed"
                and row["error_code"] == "daily_token_budget_exceeded"
                and row["input_tokens"] is None
                and row["output_tokens"] is None
                and row["reserved"] == 0
                and row["day"] < day
            )

        if (
            original is None
            or original["kind"] != "delivery"
            or original["message"] != ""
            or not before_generation_budget_refusal(original)
            or original["language_turn_id"] != language_turn_id
            or not original["offered_question_id"]
            or original["offered_question_id"].split(":quota:", 1)[0] != anchor
        ):
            raise ParentChatError("delivery_resume_not_eligible", 409)
        attempts = connection.execute(
            "SELECT t.* FROM family_turn_metadata m JOIN parent_chat_turns t "
            "ON t.id=m.turn_id AND t.parent_id=m.parent_id WHERE m.parent_id=? "
            "AND m.language_turn_id=? AND (m.offered_question_id=? "
            "OR m.offered_question_id LIKE ?)",
            (request.parent_id, language_turn_id, anchor, anchor + ":quota:%"),
        ).fetchall()
        if not attempts or any(not before_generation_budget_refusal(row) for row in attempts):
            raise ParentChatError("delivery_resume_not_eligible", 409)
        # The original metadata/result/digest remain immutable. SQL uniqueness of
        # this new day-specific slot prevents competing nonces from redispatching.
        return f"{anchor}:quota:{day}"

    @staticmethod
    def _previous_language(
        connection: sqlite3.Connection, parent_id: str, turn_id: int
    ) -> sqlite3.Row | None:
        return cast(
            sqlite3.Row | None,
            connection.execute(
                "SELECT t.id,COALESCE(m.language_reference,t.message) AS reference "
                "FROM parent_chat_turns t LEFT JOIN family_turn_metadata m "
                "ON m.parent_id=t.parent_id AND m.turn_id=t.id "
                "WHERE t.parent_id=? AND t.id<? AND t.message!='' ORDER BY t.id DESC LIMIT 1",
                (parent_id, turn_id),
            ).fetchone(),
        )

    def _admit_extra_context(
        self,
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        selected: FamilyQuestion | None,
        now: datetime,
    ) -> str | None:
        return str(selected.question_id) if selected else None

    async def evidence_for_turn(
        self, parent_id: str, turn_id: int, connected: tuple[int, ...]
    ) -> "ParentTouchEvidence | None":
        return None

    async def delivered_notice(
        self, parent_id: str, request_id: UUID
    ) -> "ParentTouchNotice | None":
        return None

    def _valid_decision(
        self,
        connection: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        now: datetime,
    ) -> bool:
        if receipt.clarification_question is not None:
            return False
        if receipt.upsell_choice is not None:
            return False
        if receipt.reminder_candidate is not None:
            return False  # Only the explicit assistant profile may accept this new protocol.
        if receipt.notice_id is not None:
            return False
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
            "UPDATE family_turn_metadata SET published_question_id=? WHERE parent_id=? "
            "AND turn_id=?",
            (
                str(receipt.question_id) if valid and receipt.question_id else None,
                turn.parent_id,
                turn.turn_id,
            ),
        )
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

    async def language_reference(self, parent_id: str, turn_id: int) -> str | None:
        def read() -> str | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT language_reference FROM family_turn_metadata WHERE parent_id=? "
                    "AND turn_id=?",
                    (parent_id, turn_id),
                ).fetchone()
                return row[0] if row else None

        return await asyncio.to_thread(read)

    @staticmethod
    def _public_question(row: sqlite3.Row) -> ParentTouchQuestion:
        return ParentTouchQuestion(
            question_id=row["question_id"],
            child_id=row["child_id"],
            turn_id=row["turn_id"],
            scope="parent" if row["child_id"] is None else None,
        )

    async def asked_question(self, parent_id: str, request_id: UUID) -> ParentTouchQuestion | None:
        def read() -> ParentTouchQuestion | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT q.question_id,q.child_id,m.turn_id FROM family_turn_metadata m "
                    "JOIN parent_chat_turns t ON t.id=m.turn_id AND t.parent_id=m.parent_id "
                    "JOIN family_questions q ON q.question_id=m.published_question_id "
                    "AND q.parent_id=m.parent_id WHERE m.parent_id=? AND t.request_id=? "
                    "AND t.status='completed'",
                    (parent_id, str(request_id)),
                ).fetchone()
                return self._public_question(row) if row else None

        return await asyncio.to_thread(read)

    async def touch_history(
        self, parent_id: str, *, before: int | None, limit: int, now: datetime
    ) -> ParentTouchHistory:
        def read() -> ParentTouchHistory:
            with self._transaction() as connection:
                self._recover_pre_dispatch(connection, parent_id, self._utc(now))
                history = self._history_in_transaction(connection, parent_id, before, limit, now)
                active = connection.execute(
                    "SELECT question_id,child_id,offered_turn_id AS turn_id FROM family_questions "
                    "WHERE parent_id=? AND status='awaiting_reply'",
                    (parent_id,),
                ).fetchone()
                ids = {
                    message.turn_id for message in history.messages if message.role == "assistant"
                }
                questions: list[ParentTouchQuestion] = []
                for turn_id in sorted(ids):
                    row = connection.execute(
                        "SELECT q.question_id,q.child_id,m.turn_id FROM family_turn_metadata m "
                        "JOIN family_questions q ON q.question_id=m.published_question_id "
                        "AND q.parent_id=m.parent_id WHERE m.parent_id=? AND m.turn_id=?",
                        (parent_id, turn_id),
                    ).fetchone()
                    if row is not None:
                        questions.append(self._public_question(row))
                result = ParentTouchHistory(
                    **history.model_dump(),
                    active_question=self._public_question(active) if active else None,
                    message_questions=questions,
                )
                return self._enrich_history(connection, result)

        return await asyncio.to_thread(read)

    def _enrich_history(
        self, connection: sqlite3.Connection, history: ParentTouchHistory
    ) -> ParentTouchHistory:
        return history

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

    def _alias_intent(
        self,
        connection: sqlite3.Connection,
        request: AgentQuestionRequest,
        question_id: str,
        *,
        coalesced: bool,
    ) -> AgentQuestionReceipt:
        connection.execute(
            "INSERT INTO family_question_intents VALUES(?,?,?,?,?,?)",
            (
                request.parent_id,
                request.agent_id,
                str(request.request_id),
                self._question_digest(request),
                question_id,
                int(coalesced),
            ),
        )
        result = self._known_intent(connection, request)
        assert result is not None
        return result

    def _duplicate_intent(
        self,
        connection: sqlite3.Connection,
        request: AgentQuestionRequest,
    ) -> AgentQuestionReceipt | None:
        row = connection.execute(
            "SELECT question_id FROM family_question_intents WHERE parent_id=? AND agent_id=? "
            "AND digest=? LIMIT 1",
            (request.parent_id, request.agent_id, self._question_digest(request)),
        ).fetchone()
        if row is None:
            row = connection.execute(
                "SELECT question_id FROM family_information_revisions WHERE parent_id=? "
                "AND child_id=? AND information_key=? AND source_revision=?",
                (
                    request.parent_id,
                    request.child_id,
                    request.information_key,
                    request.source_revision,
                ),
            ).fetchone()
        if row is not None:
            connection.execute(
                "UPDATE family_questions SET priority=MAX(priority,?) WHERE parent_id=? "
                "AND question_id=? AND status='queued'",
                (request.priority, request.parent_id, row["question_id"]),
            )
            return self._alias_intent(connection, request, row["question_id"], coalesced=True)
        return None

    async def claim_intent(
        self,
        request: AgentQuestionRequest,
        now: datetime,
    ) -> AgentQuestionReceipt | None:
        def claim() -> AgentQuestionReceipt | None:
            failure: ParentChatError | None = None
            with self._transaction() as connection:
                known = self._known_intent(connection, request)
                if known is not None:
                    return known
                digest = self._question_digest(request)
                alias = connection.execute(
                    "SELECT digest FROM family_intent_admissions WHERE parent_id=? "
                    "AND agent_id=? AND request_id=?",
                    (request.parent_id, request.agent_id, str(request.request_id)),
                ).fetchone()
                if alias is not None and alias[0] != digest:
                    raise ParentChatError("request_id_conflict", 409)
                duplicate = self._duplicate_intent(connection, request)
                if duplicate is not None:
                    return duplicate
                connection.execute(
                    "INSERT OR IGNORE INTO family_intent_admissions VALUES(?,?,?,?)",
                    (request.parent_id, request.agent_id, str(request.request_id), digest),
                )
                row = connection.execute(
                    "SELECT * FROM family_intent_claims WHERE parent_id=? "
                    "AND agent_id=? AND digest=?",
                    (request.parent_id, request.agent_id, digest),
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO family_intent_claims"
                        "(parent_id,agent_id,digest,status,created_at) "
                        "VALUES(?,?,?,'preparing',?)",
                        (request.parent_id, request.agent_id, digest, self._utc(now).isoformat()),
                    )
                else:
                    failure = ParentChatError(
                        row["error_code"] or "intent_already_admitted", row["error_status"] or 409
                    )
            if failure is not None:
                raise failure
            return None

        return await asyncio.to_thread(claim)

    async def finish_intent(
        self,
        request: AgentQuestionRequest,
        now: datetime,
    ) -> AgentQuestionReceipt:
        def finish() -> AgentQuestionReceipt:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT status FROM family_intent_claims WHERE parent_id=? "
                    "AND agent_id=? AND digest=?",
                    (request.parent_id, request.agent_id, self._question_digest(request)),
                ).fetchone()
                if row is None or row[0] != "preparing":
                    raise ParentChatError("intent_no_longer_admitted", 409)
                result = self._enqueue_in_transaction(connection, request, self._utc(now))
                connection.execute(
                    "UPDATE family_intent_claims SET status='completed' WHERE parent_id=? "
                    "AND agent_id=? AND digest=?",
                    (request.parent_id, request.agent_id, self._question_digest(request)),
                )
                return result

        return await asyncio.to_thread(finish)

    async def fail_intent(self, request: AgentQuestionRequest, error: ParentChatError) -> None:
        def fail() -> None:
            with self._transaction() as connection:
                connection.execute(
                    "UPDATE family_intent_claims SET status='failed',error_code=?,error_status=? "
                    "WHERE parent_id=? AND agent_id=? AND digest=? AND status='preparing'",
                    (
                        error.code,
                        error.status_code,
                        request.parent_id,
                        request.agent_id,
                        self._question_digest(request),
                    ),
                )

        await asyncio.to_thread(fail)

    async def enqueue(self, request: AgentQuestionRequest, now: datetime) -> AgentQuestionReceipt:
        return await asyncio.to_thread(self._enqueue, request, now)

    def _enqueue(self, request: AgentQuestionRequest, now: datetime) -> AgentQuestionReceipt:
        now = self._utc(now)
        with self._transaction() as connection:
            return self._enqueue_in_transaction(connection, request, now)

    def _enqueue_in_transaction(
        self,
        connection: sqlite3.Connection,
        request: AgentQuestionRequest,
        now: datetime,
    ) -> AgentQuestionReceipt:
        known = self._known_intent(connection, request)
        if known is not None:
            return known
        duplicate = self._duplicate_intent(connection, request)
        if duplicate is not None:
            return duplicate
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
            "INSERT OR IGNORE INTO family_information_revisions VALUES(?,?,?,?,?)",
            (
                request.parent_id,
                request.child_id,
                request.information_key,
                request.source_revision,
                str(question.question_id),
            ),
        )
        return self._alias_intent(
            connection, request, str(question.question_id), coalesced=coalesced
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
