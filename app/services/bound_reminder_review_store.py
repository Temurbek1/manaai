"""Family45: a new strong semantic review bound to one exact literal proposal."""

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from app.mana_ai.application.bound_reminder_review import BOUND_REMINDER_PREPARE_ACK
from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.domain.bound_reminder_review import BoundReminderDecision
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.direct_reminders import DirectReminderRequest
from app.mana_ai.domain.family_agents import ParentTouchReviewedTurn, ReviewedMessage
from app.mana_ai.domain.parent_touch_manager import ParentTouchManagerScope
from app.services.compact_manager_decision_store import (
    SqliteClosedCompactManagerDecisionStore,
    SqliteCompactManagerDecisionStore,
)

_TABLE = "bound_reminder_reviews"
_PREFIX = "bound-review-v1:"


def _pair(row: sqlite3.Row | dict[str, Any]) -> str:
    identity = [
        row[k]
        for k in (
            "parent_id",
            "turn_id",
            "request_hash",
            "direct_fingerprint",
            "manager_binding",
            "manager_model",
            "clarifications",
        )
    ]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


class SqliteBoundReminderReviewStore(SqliteCompactManagerDecisionStore):
    _schema_version = 45

    def __init__(
        self, path: Path, *, bound_reminder_reviews_enabled: bool = False, **family: Any
    ) -> None:
        self._bound_reminder_reviews_enabled = bound_reminder_reviews_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {44}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS bound_reminder_reviews(
          turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,request_hash TEXT NOT NULL,
          direct_fingerprint TEXT NOT NULL,manager_binding TEXT NOT NULL,
          manager_model TEXT NOT NULL,clarifications INTEGER NOT NULL CHECK(clarifications IN(0,1)),
          fingerprint TEXT NOT NULL,decision_kind TEXT CHECK(decision_kind IN('prepare','reply')),
          accepted INTEGER CHECK(accepted IN(0,1)),recorded_at TEXT);
        """
        )

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        super()._on_admitted(db, request, turn_id, now)
        if not self._bound_reminder_reviews_enabled or self._pending(db, request.parent_id, now):
            return
        row = db.execute(
            "SELECT d.*,m.binding,m.model,m.phase,m.choice FROM direct_reminder_routes d "
            "JOIN parent_touch_manager_turns m ON m.turn_id=d.turn_id AND m.parent_id=d.parent_id "
            "WHERE d.parent_id=? AND d.turn_id=?",
            (request.parent_id, turn_id),
        ).fetchone()
        if row is None or row["phase"] != "cap_waiting" or row["choice"] != "reminder":
            return
        capture: dict[str, Any] = {
            "parent_id": request.parent_id,
            "turn_id": turn_id,
            "request_hash": self._digest(request),
            "direct_fingerprint": row["fingerprint"],
            "manager_binding": row["binding"],
            "manager_model": row["model"],
            "clarifications": int(
                self._clarifications_enabled
                and bool(
                    db.execute(
                        "SELECT 1 FROM parent_clarification_admissions "
                        "WHERE parent_id=? AND turn_id=?",
                        (request.parent_id, turn_id),
                    ).fetchone()
                )
            ),
        }
        if row["request_hash"] != capture["request_hash"]:
            raise ParentChatError("bound_reminder_capture_invalid", 503)
        db.execute(
            "UPDATE direct_reminder_routes SET request_hash=? WHERE parent_id=? AND turn_id=?",
            (_PREFIX + capture["request_hash"], request.parent_id, turn_id),
        )
        db.execute(
            "INSERT INTO bound_reminder_reviews VALUES(?,?,?,?,?,?,?,?,NULL,NULL,NULL)",
            (
                turn_id,
                request.parent_id,
                capture["request_hash"],
                capture["direct_fingerprint"],
                capture["manager_binding"],
                capture["manager_model"],
                capture["clarifications"],
                _pair(capture),
            ),
        )

    def _bound_capture(self, db: sqlite3.Connection, parent: str, turn: int) -> sqlite3.Row | None:
        capture = db.execute(
            "SELECT * FROM bound_reminder_reviews WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        original = db.execute(
            "SELECT d.request_hash,d.payload,d.fingerprint,t.request_digest,m.binding,m.model,"
            "m.choice,m.call_id FROM direct_reminder_routes d "
            "JOIN parent_chat_turns t ON t.id=d.turn_id AND t.parent_id=d.parent_id "
            "JOIN parent_touch_manager_turns m ON m.turn_id=d.turn_id AND m.parent_id=d.parent_id "
            "WHERE d.parent_id=? AND d.turn_id=?",
            (parent, turn),
        ).fetchone()
        marked = original is not None and original["request_hash"].startswith("bound-review-")
        if capture is None and not marked:
            return None
        if (
            capture is None
            or original is None
            or original["request_hash"] != _PREFIX + capture["request_hash"]
            or capture["request_hash"] != original["request_digest"]
            or capture["direct_fingerprint"] != original["fingerprint"]
            or hashlib.sha256(original["payload"].encode()).hexdigest() != original["fingerprint"]
            or capture["manager_binding"] != original["binding"]
            or capture["manager_model"] != original["model"]
            or capture["fingerprint"] != _pair(capture)
            or original["choice"] != "reminder"
            or original["call_id"] is not None
        ):
            raise ParentChatError("bound_reminder_capture_invalid", 503)
        return cast(sqlite3.Row, capture)

    def _direct_request_digest(
        self, db: sqlite3.Connection, parent: str, turn_id: int, digest: str
    ) -> str:
        capture = self._bound_capture(db, parent, turn_id)
        return (
            cast(str, capture["request_hash"])
            if capture
            else super()._direct_request_digest(db, parent, turn_id, digest)
        )

    async def bound_reminder_review_request(
        self, parent_id: str, turn_id: int
    ) -> DirectReminderRequest | None:
        def read() -> DirectReminderRequest | None:
            with self._connect() as db:
                if self._bound_capture(db, parent_id, turn_id) is None:
                    return None
                if not self._bound_reminder_reviews_enabled:
                    raise ParentChatError("bound_reminder_review_disabled", 503)
                return self._direct_request(db, parent_id, turn_id)

        return await asyncio.to_thread(read)

    async def manager_scope(self, parent_id: str, turn_id: int) -> ParentTouchManagerScope | None:
        await self.bound_reminder_review_request(parent_id, turn_id)
        scope = await super().manager_scope(parent_id, turn_id)
        if scope is None or scope.stage != "reminder":
            return scope

        def clarifications() -> bool:
            with self._connect() as db:
                row = self._bound_capture(db, parent_id, turn_id)
                return bool(row and row["clarifications"] and self._clarifications_enabled)

        return scope.model_copy(
            update={"clarifications_enabled": await asyncio.to_thread(clarifications)}
        )

    async def claim_reviewed_response(
        self, now: datetime
    ) -> tuple[ReviewedMessage, ParentTouchReviewedTurn] | None:
        def fence() -> None:
            with self._transaction() as db:
                rows = db.execute(
                    "SELECT t.* FROM parent_chat_turns t "
                    "LEFT JOIN direct_reminder_routes d "
                    "ON d.turn_id=t.id AND d.parent_id=t.parent_id "
                    "LEFT JOIN bound_reminder_reviews b "
                    "ON b.turn_id=t.id AND b.parent_id=t.parent_id "
                    "WHERE t.status='preparing' AND (b.turn_id IS NOT NULL "
                    "OR d.request_hash LIKE 'bound-review-%') ORDER BY t.id LIMIT ?",
                    (self._safety_limits.max_pending_jobs + 1,),
                ).fetchall()
                if len(rows) > self._safety_limits.max_pending_jobs:
                    raise ParentChatError("bound_reminder_queue_overflow", 503)
                for row in rows:
                    code = (
                        None
                        if self._bound_reminder_reviews_enabled
                        else "bound_reminder_review_disabled"
                    )
                    try:
                        self._bound_capture(db, row["parent_id"], row["id"])
                    except ParentChatError as exc:
                        code = exc.code
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
            self._bound_capture(db, turn.parent_id, turn.turn_id) is not None
            and not self._bound_reminder_reviews_enabled
        ):
            raise ParentChatError("bound_reminder_review_disabled", 503)

    def _clarification_scope_matches(self, db: sqlite3.Connection, turn: StoredChatTurn) -> bool:
        capture = self._bound_capture(db, turn.parent_id, turn.turn_id)
        if capture is None:
            return super()._clarification_scope_matches(db, turn)
        return bool(
            self._bound_reminder_reviews_enabled
            and capture["clarifications"]
            and db.execute(
                "SELECT 1 FROM parent_clarification_admissions a JOIN parent_touch_manager_turns m "
                "ON m.turn_id=a.turn_id AND m.parent_id=a.parent_id WHERE a.parent_id=? "
                "AND a.turn_id=? AND m.phase='cap_running' AND m.choice='reminder'",
                (turn.parent_id, turn.turn_id),
            ).fetchone()
        )

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        try:
            capture = self._bound_capture(db, turn.parent_id, turn.turn_id)
            decision = receipt.bound_reminder_decision
            if capture is None:
                return decision is None and super()._valid_decision(db, turn, receipt, now)
            if not self._bound_reminder_reviews_enabled or decision is None:
                return False
            decision = BoundReminderDecision.model_validate(decision.model_dump(), strict=True)
            request = self._direct_request(db, turn.parent_id, turn.turn_id)
            if request is None or any(
                (
                    receipt.native_manager_invocation,
                    receipt.manager_handoff,
                    receipt.question_id,
                    receipt.notice_id,
                    receipt.upsell_choice,
                    receipt.upsell_enquiry,
                    receipt.reminder_question_text,
                    receipt.upsell_question_text,
                )
            ):
                return False
            if decision.kind == "prepare":
                matches = (
                    receipt.reminder_candidate == request.candidate
                    and receipt.answer == BOUND_REMINDER_PREPARE_ACK
                    and receipt.clarification_question is None
                )
            else:
                answer = "\n\n".join(
                    p for p in ((decision.body or "").strip(), decision.question) if p
                )
                matches = (
                    receipt.reminder_candidate is None
                    and receipt.answer == answer
                    and receipt.clarification_question == decision.question
                )
            return bool(matches and super()._valid_decision(db, turn, receipt, now))
        except (ValueError, TypeError, ParentChatError):
            return False

    def _on_settled(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        super()._on_settled(db, turn, receipt, valid=valid)
        choice = receipt.bound_reminder_decision
        kind = (
            choice.kind
            if isinstance(choice, BoundReminderDecision) and choice.kind in {"prepare", "reply"}
            else None
        )
        db.execute(
            "UPDATE bound_reminder_reviews SET decision_kind=?,accepted=?,recorded_at="
            "(SELECT updated_at FROM parent_chat_turns WHERE id=?) WHERE parent_id=? AND turn_id=?",
            (kind, int(valid), turn.turn_id, turn.parent_id, turn.turn_id),
        )


class SqliteClosedBoundReminderReviewStore(SqliteClosedCompactManagerDecisionStore):
    _schema_version = 45

    def __init__(self, path: Path, **family: Any) -> None:
        super().__init__(path, **family)
        self._schema_version = 45

    def _supported_versions(self) -> set[int]:
        return {45}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}
