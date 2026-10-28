"""Family43: one strong owning review for explicitly dated reminder requests."""

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.application.direct_reminders import direct_reminder_request
from app.mana_ai.domain.chat import StoredChatTurn
from app.mana_ai.domain.direct_reminders import DirectReminderRequest
from app.mana_ai.domain.family_agents import ParentTouchReviewedTurn, ReviewedMessage
from app.mana_ai.domain.parent_touch_manager import ParentTouchManagerScope
from app.services.parent_setup_store import SqliteClosedParentSetupStore, SqliteParentSetupStore
from app.services.proactive_parent_store import _current_context

_TABLE = "direct_reminder_routes"


class SqliteDirectReminderStore(SqliteParentSetupStore):
    _schema_version = 43

    def __init__(
        self, path: Path, *, direct_reminders_enabled: bool = False, **family: Any
    ) -> None:
        self._direct_reminders_enabled = direct_reminders_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {42}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS direct_reminder_routes(
          turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,request_hash TEXT NOT NULL,
          payload TEXT NOT NULL,fingerprint TEXT NOT NULL);
        """
        )

    def _defer_initial_review(
        self,
        db: sqlite3.Connection,
        request: ParentTouchReviewedTurn,
        turn_id: int,
        now: datetime,
        context: str,
    ) -> bool:
        deferred = super()._defer_initial_review(db, request, turn_id, now, context)
        if (
            not deferred
            or not self._direct_reminders_enabled
            or request.reply_to_question_id is not None
            or request.reply_to_confirmation_id is not None
        ):
            return deferred
        contact = _current_context(db, request.parent_id, now)
        parsed = direct_reminder_request(
            request.message,
            now=now,
            timezone=contact.timezone if contact else self._zone.key,
            timezone_basis="verified_contact"
            if contact
            else "application_default_requires_confirmation",
        )
        if (
            parsed is None
            or parsed.candidate.due_at is None
            or not (
                now + timedelta(seconds=60)
                <= parsed.candidate.due_at
                <= now + timedelta(days=self._reminder_policy.maximum_delay_days)
            )
        ):
            return deferred
        changed = db.execute(
            "UPDATE parent_touch_manager_turns SET phase='cap_waiting',choice='reminder' "
            "WHERE parent_id=? AND turn_id=? AND phase='queued' AND choice IS NULL",
            (request.parent_id, turn_id),
        )
        if changed.rowcount == 1:
            payload = parsed.model_dump_json()
            db.execute(
                "INSERT INTO direct_reminder_routes VALUES(?,?,?,?,?)",
                (
                    turn_id,
                    request.parent_id,
                    self._digest(request),
                    payload,
                    hashlib.sha256(payload.encode()).hexdigest(),
                ),
            )
        return deferred

    def _direct_request(
        self, db: sqlite3.Connection, parent: str, turn_id: int
    ) -> DirectReminderRequest | None:
        row = db.execute(
            "SELECT r.*,t.request_digest,t.message,t.created_at FROM direct_reminder_routes r "
            "JOIN parent_chat_turns t ON t.id=r.turn_id AND t.parent_id=r.parent_id "
            "WHERE r.parent_id=? AND r.turn_id=?",
            (parent, turn_id),
        ).fetchone()
        if row is None:
            return None
        try:
            parsed = DirectReminderRequest.model_validate_json(row["payload"])
            if (
                row["request_hash"] != row["request_digest"]
                or parsed.captured_at != datetime.fromisoformat(row["created_at"])
                or hashlib.sha256(row["payload"].encode()).hexdigest() != row["fingerprint"]
                or parsed.candidate.content not in row["message"]
            ):
                raise ValueError("Changed literal reminder route")
            rederived = direct_reminder_request(
                row["message"],
                now=parsed.captured_at,
                timezone=parsed.candidate.timezone,
                timezone_basis="verified_contact"
                if parsed.timezone_basis == "verified_contact"
                else "application_default_requires_confirmation",
            )
            if rederived != parsed:
                raise ValueError("The captured route no longer matches its full request")
        except (ValueError, TypeError):
            raise ParentChatError("direct_reminder_capture_invalid", 503) from None
        return parsed

    async def direct_reminder_request(
        self, parent_id: str, turn_id: int
    ) -> DirectReminderRequest | None:
        def read() -> DirectReminderRequest | None:
            with self._connect() as db:
                parsed = self._direct_request(db, parent_id, turn_id)
                if parsed is not None and not self._direct_reminders_enabled:
                    raise ParentChatError("direct_reminder_disabled", 503)
                return parsed

        return await asyncio.to_thread(read)

    async def manager_scope(self, parent_id: str, turn_id: int) -> ParentTouchManagerScope | None:
        await self.direct_reminder_request(parent_id, turn_id)
        return await super().manager_scope(parent_id, turn_id)

    async def claim_reviewed_response(
        self, now: datetime
    ) -> tuple[ReviewedMessage, ParentTouchReviewedTurn] | None:
        def fence() -> None:
            with self._transaction() as db:
                rows = db.execute(
                    "SELECT t.* FROM parent_chat_turns t JOIN direct_reminder_routes r "
                    "ON r.turn_id=t.id AND r.parent_id=t.parent_id WHERE t.status='preparing' "
                    "ORDER BY t.id LIMIT ?",
                    (self._safety_limits.max_pending_jobs + 1,),
                ).fetchall()
                if len(rows) > self._safety_limits.max_pending_jobs:
                    raise ParentChatError("direct_reminder_queue_overflow", 503)
                for row in rows:
                    code = (
                        "direct_reminder_disabled" if not self._direct_reminders_enabled else None
                    )
                    try:
                        self._direct_request(db, row["parent_id"], row["id"])
                    except ParentChatError:
                        code = "direct_reminder_capture_invalid"
                    if code:
                        db.execute(
                            "UPDATE parent_chat_turns SET status='failed',reserved=0,"
                            "error_code=?,error_status=503 WHERE id=?",
                            (code, row["id"]),
                        )
                        self._on_failed(db, self._turn(row), unknown=False)

        await asyncio.to_thread(fence)
        return await super().claim_reviewed_response(now)

    def _validate_chat_submission(
        self, db: sqlite3.Connection, turn: StoredChatTurn, now: datetime
    ) -> None:
        super()._validate_chat_submission(db, turn, now)
        if (
            self._direct_request(db, turn.parent_id, turn.turn_id)
            and not self._direct_reminders_enabled
        ):
            raise ParentChatError("direct_reminder_disabled", 503)

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        try:
            parsed = self._direct_request(db, turn.parent_id, turn.turn_id)
        except ParentChatError:
            return False
        if parsed is not None:
            if not self._direct_reminders_enabled:
                return False
            if receipt.reminder_candidate is not None:
                actual, expected = receipt.reminder_candidate, parsed.candidate
                if (
                    actual.content.removesuffix(".") != expected.content.removesuffix(".")
                    or actual.due_at != expected.due_at
                    or actual.timezone != expected.timezone
                ):
                    return False
        return super()._valid_decision(db, turn, receipt, now)


class SqliteClosedDirectReminderStore(SqliteClosedParentSetupStore):
    _schema_version = 43

    def __init__(self, path: Path, **family: Any) -> None:
        super().__init__(path, **family)
        self._schema_version = 43

    def _supported_versions(self) -> set[int]:
        return {43}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}
