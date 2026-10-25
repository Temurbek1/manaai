"""Captured review-first messages, without retrying an old turn or a paid call.

The existing five-minute preparation deadline also bounds review waiting. The
worker claims communication once, after a successful specialist receipt. A lost
claim is not reclaimed; ordinary preparation/unknown recovery remains fail closed.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from uuid import UUID

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.parent_languages import neutral_parent_reply, parent_language
from app.mana_ai.domain.chat import ParentChatRequest
from app.mana_ai.domain.child_safety import SafetyStoredResult
from app.mana_ai.domain.family_agents import (
    ParentTouchReviewedTurn,
    ParentTouchReviewGuidance,
    ReviewedMessage,
)
from app.services.child_safety_store import SqliteChildSafetyStore
from app.services.family_compatibility_store import SqliteClosedSafetyBrokerStore
from app.services.parent_chat_store import SqliteParentChatStore

REVIEW_TABLE = "family_reviewed_messages"


class SqliteReviewedMessageStore(SqliteChildSafetyStore):
    _schema_version = 6

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {5}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {REVIEW_TABLE}

    def _defer_initial_review(
        self,
        connection: sqlite3.Connection,
        request: ParentTouchReviewedTurn,
        turn_id: int,
        now: datetime,
        context: str,
    ) -> bool:
        return False

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
            CREATE TABLE IF NOT EXISTS family_reviewed_messages (
                turn_id INTEGER PRIMARY KEY,
                parent_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                request TEXT NOT NULL,
                phase TEXT NOT NULL CHECK(phase IN ('waiting','claimed')),
                guidance TEXT,
                claimed_at TEXT,
                UNIQUE(parent_id,request_id)
            );
        """
        )

    def _on_admitted(
        self,
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        now: datetime,
    ) -> None:
        if not isinstance(request, ParentTouchReviewedTurn):
            super()._on_admitted(connection, request, turn_id, now)
            return
        # Bound unmaterialized events as well as the specialist job queue, before
        # saving text or consuming the explicit answer binding.
        waiting = connection.execute(
            "SELECT COUNT(*) FROM family_reviewed_messages m JOIN parent_chat_turns t "
            "ON t.id=m.turn_id WHERE t.status='preparing'"
        ).fetchone()[0]
        if waiting >= self._safety_limits.max_pending_jobs:
            raise ParentChatError("reviewed_message_queue_full", 429)
        self._bind_answer(connection, request, turn_id)
        reference = request.message
        if parent_language(reference) is None and neutral_parent_reply(reference):
            previous = self._previous_language(connection, request.parent_id, turn_id)
            if previous is not None:
                reference = previous["reference"]
        # The explicit new protocol delays choice/evidence capture until review
        # succeeds. Existing synchronous admissions retain their old ordering.
        connection.execute(
            "INSERT INTO family_turn_metadata(parent_id,turn_id,kind,language_turn_id,"
            "language_reference) VALUES(?,?,'review_first',?,?)",
            (request.parent_id, turn_id, turn_id, reference),
        )
        snapshot = self._snapshot(connection, request.parent_id, turn_id).model_copy(
            update={"review_first": True}
        )
        if len(snapshot.model_dump_json().encode()) > self._safety_limits.max_context_bytes:
            raise ParentChatError("safety_context_too_large", 422)
        if not self._defer_initial_review(
            connection, request, turn_id, now, snapshot.model_dump_json()
        ):
            connection.execute(
                "INSERT INTO child_safety_parent_events(turn_id,parent_id,created_at,context) "
                "VALUES(?,?,?,?)",
                (turn_id, request.parent_id, now.isoformat(), snapshot.model_dump_json()),
            )
        connection.execute(
            "INSERT INTO family_reviewed_messages(turn_id,parent_id,request_id,request,phase) "
            "VALUES(?,?,?,?,'waiting')",
            (turn_id, request.parent_id, str(request.request_id), request.model_dump_json()),
        )

    def _recover(self, connection: sqlite3.Connection, now: datetime) -> None:
        super()._recover(connection, now)
        # Expired chat cannot start a fresh paid review. Submitted/unknown stay intact.
        connection.execute(
            "UPDATE child_safety_jobs SET status='failed',reserved=0,"
            "error_code='reviewed_message_no_longer_admitted',updated_at=? "
            "WHERE status='queued' AND kind='parent_message' AND EXISTS "
            "(SELECT 1 FROM family_reviewed_messages m JOIN parent_chat_turns t ON t.id=m.turn_id "
            "WHERE m.parent_id=child_safety_jobs.parent_id "
            "AND m.turn_id=child_safety_jobs.parent_turn_cutoff "
            "AND (t.status!='preparing' OR t.created_at<?))",
            (now.isoformat(), (now - timedelta(minutes=5)).isoformat()),
        )

    def _validate_safety_publication(
        self, connection: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> None:
        if row["kind"] != "parent_message":
            return
        origin = connection.execute(
            "SELECT t.status,t.created_at FROM family_reviewed_messages m "
            "JOIN parent_chat_turns t ON t.id=m.turn_id AND t.parent_id=m.parent_id "
            "WHERE m.parent_id=? AND m.turn_id=?",
            (row["parent_id"], row["parent_turn_cutoff"]),
        ).fetchone()
        if origin and (
            origin["status"] != "preparing"
            or origin["created_at"] < (now - timedelta(minutes=5)).isoformat()
        ):
            raise ParentChatError("reviewed_message_no_longer_admitted", 409)

    @staticmethod
    def _message(
        connection: sqlite3.Connection, parent_id: str, request_id: UUID
    ) -> ReviewedMessage:
        row = connection.execute(
            "SELECT t.*,m.phase FROM family_reviewed_messages m JOIN parent_chat_turns t "
            "ON t.id=m.turn_id AND t.parent_id=m.parent_id "
            "WHERE m.parent_id=? AND m.request_id=?",
            (parent_id, str(request_id)),
        ).fetchone()
        if row is None:
            raise ParentChatError("reviewed_message_not_found", 404)
        return ReviewedMessage(
            turn=SqliteParentChatStore._turn(row),
            phase=("awaiting_review" if row["phase"] == "waiting" else "responding")
            if row["status"] in {"preparing", "submitted"}
            else row["status"],
        )

    async def admit_reviewed(
        self, request: ParentTouchReviewedTurn, now: datetime, *, allow_new: bool
    ) -> ReviewedMessage:
        def existing() -> ReviewedMessage | None:
            with self._transaction() as connection:
                self._recover_pre_dispatch(connection, request.parent_id, self._utc(now))
                row = connection.execute(
                    "SELECT request_digest FROM parent_chat_turns "
                    "WHERE parent_id=? AND request_id=?",
                    (request.parent_id, str(request.request_id)),
                ).fetchone()
                if row is None:
                    return None
                if row[0] != self._digest(request):
                    raise ParentChatError("request_id_conflict", 409)
                return self._message(connection, request.parent_id, request.request_id)

        previous = await asyncio.to_thread(existing)
        if previous is not None:
            return previous
        if not allow_new:
            raise ParentChatError("reviewed_message_worker_unavailable", 503)
        try:
            await self.admit(request, now)
        except ParentChatError:
            # Another process may have admitted the exact intent between the
            # lookup and IMMEDIATE admission. Observe, never dispatch here.
            previous = await asyncio.to_thread(existing)
            if previous is None:
                raise
            return previous
        return await self.reviewed_message(request.parent_id, request.request_id, now)

    async def reviewed_message(
        self, parent_id: str, request_id: UUID, now: datetime
    ) -> ReviewedMessage:
        def read() -> ReviewedMessage:
            with self._transaction() as connection:
                self._recover_pre_dispatch(connection, parent_id, self._utc(now))
                return self._message(connection, parent_id, request_id)

        return await asyncio.to_thread(read)

    async def claim_reviewed_response(
        self, now: datetime
    ) -> tuple[ReviewedMessage, ParentTouchReviewedTurn] | None:
        def claim() -> tuple[ReviewedMessage, ParentTouchReviewedTurn] | None:
            utc = self._utc(now)
            with self._transaction() as connection:
                # Select only terminal reviews or expired preparations; a prefix
                # of budget-waiting families must not starve ready messages.
                rows = connection.execute(
                    "SELECT m.*,t.created_at,j.status AS review_status,j.result,"
                    "j.allowed_child_ids,"
                    "j.updated_at AS reviewed_at,j.parent_turn_cutoff,j.kind FROM "
                    "family_reviewed_messages m JOIN parent_chat_turns t ON t.id=m.turn_id "
                    "LEFT JOIN child_safety_parent_events e ON e.turn_id=t.id "
                    "LEFT JOIN child_safety_jobs j "
                    "ON j.job_id=e.job_id AND j.parent_id=m.parent_id "
                    "WHERE m.phase='waiting' AND t.status='preparing' AND "
                    "(j.status IN ('completed','failed','unknown') OR t.created_at<?) "
                    "ORDER BY t.id LIMIT 100",
                    ((utc - timedelta(minutes=5)).isoformat(),),
                ).fetchall()
                for row in rows:
                    parent_id, request_id = row["parent_id"], UUID(row["request_id"])
                    self._recover_pre_dispatch(connection, parent_id, utc)
                    state = self._message(connection, parent_id, request_id)
                    if state.turn.status != "preparing":
                        continue
                    if row["review_status"] != "completed":
                        connection.execute(
                            "UPDATE parent_chat_turns SET status='failed',reserved=0,error_code="
                            "'child_safety_review_unavailable',error_status=503 WHERE id=?",
                            (row["turn_id"],),
                        )
                        self._on_failed(connection, state.turn, unknown=False)
                        continue
                    result = SafetyStoredResult.model_validate_json(row["result"])
                    if (
                        row["parent_turn_cutoff"] != row["turn_id"]
                        or row["kind"] != "parent_message"
                        or result.analysis is not None
                        or result.followup_summary is None
                        or row["allowed_child_ids"] is None
                    ):
                        raise ParentChatError("reviewed_message_context_invalid", 503)
                    guidance = ParentTouchReviewGuidance(
                        summary=result.followup_summary,
                        reviewed_at=row["reviewed_at"],
                        parent_message_at=row["created_at"],
                        authorized_child_ids=tuple(json.loads(row["allowed_child_ids"])),
                    )
                    request = ParentTouchReviewedTurn.model_validate_json(row["request"])
                    if request.parent_id != parent_id or request.request_id != request_id:
                        raise ParentChatError("reviewed_message_context_invalid", 503)
                    selected = self._offer_in_transaction(
                        connection, parent_id, row["turn_id"], utc
                    )
                    anchor = self._admit_extra_context(
                        connection, request, row["turn_id"], selected, utc
                    )
                    connection.execute(
                        "UPDATE family_turn_metadata SET offered_question_id=? WHERE turn_id=? "
                        "AND parent_id=? AND offered_question_id IS NULL",
                        (anchor, row["turn_id"], parent_id),
                    )
                    connection.execute(
                        "UPDATE family_reviewed_messages "
                        "SET phase='claimed',guidance=?,claimed_at=? "
                        "WHERE turn_id=? AND phase='waiting'",
                        (guidance.model_dump_json(), utc.isoformat(), row["turn_id"]),
                    )
                    return self._message(connection, parent_id, request_id), request
                return None

        return await asyncio.to_thread(claim)

    async def review_guidance(
        self, parent_id: str, turn_id: int, connected: tuple[int, ...]
    ) -> ParentTouchReviewGuidance:
        def read() -> ParentTouchReviewGuidance:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT guidance FROM family_reviewed_messages WHERE parent_id=? AND turn_id=? "
                    "AND phase='claimed'",
                    (parent_id, turn_id),
                ).fetchone()
                if row is None or row[0] is None:
                    raise ParentChatError("reviewed_message_context_invalid", 503)
                value = ParentTouchReviewGuidance.model_validate_json(row[0])
                if not set(value.authorized_child_ids).issubset(connected):
                    raise ParentChatError("reviewed_message_child_not_authorized", 403)
                return value

        return await asyncio.to_thread(read)


class SqliteClosedReviewedBrokerStore(SqliteClosedSafetyBrokerStore):
    """V6 broker/observation only, without any specialist execution methods."""

    _schema_version = 6

    def _supported_versions(self) -> set[int]:
        return {6}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {REVIEW_TABLE}

    async def admit_reviewed(
        self, request: ParentTouchReviewedTurn, now: datetime, *, allow_new: bool
    ) -> ReviewedMessage:
        def check() -> None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT request_digest FROM parent_chat_turns "
                    "WHERE parent_id=? AND request_id=?",
                    (request.parent_id, str(request.request_id)),
                ).fetchone()
                if row is None:
                    raise ParentChatError("review_first_disabled", 503)
                if row[0] != self._digest(request):
                    raise ParentChatError("request_id_conflict", 409)

        await asyncio.to_thread(check)
        return await self.reviewed_message(request.parent_id, request.request_id, now)

    async def reviewed_message(
        self, parent_id: str, request_id: UUID, now: datetime
    ) -> ReviewedMessage:
        def read() -> ReviewedMessage:
            with self._transaction() as connection:
                self._recover_pre_dispatch(connection, parent_id, self._utc(now))
                return SqliteReviewedMessageStore._message(connection, parent_id, request_id)

        return await asyncio.to_thread(read)

    async def claim_reviewed_response(
        self, now: datetime
    ) -> tuple[ReviewedMessage, ParentTouchReviewedTurn] | None:
        return None

    async def review_guidance(
        self, parent_id: str, turn_id: int, connected: tuple[int, ...]
    ) -> ParentTouchReviewGuidance:
        raise ParentChatError("review_first_disabled", 503)
