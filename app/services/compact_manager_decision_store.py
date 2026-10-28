"""Family44: new-turn native decisions, paired private capture and atomic audit."""

import asyncio
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.application.compact_manager_decision import parse_compact_manager_decision
from app.mana_ai.application.upsell_text import TARIFF_HANDOFF_PLACEHOLDER
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.client_upsell import UpsellIntent
from app.mana_ai.domain.compact_manager_decision import CompactManagerInvocation
from app.mana_ai.domain.family_agents import (
    ParentTouchMessageRequest,
    ParentTouchMessageState,
    ParentTouchReviewedTurn,
    ReviewedMessage,
)
from app.mana_ai.domain.parent_touch_manager import (
    ParentTouchManagerHandoff,
    ParentTouchManagerScope,
)
from app.services.direct_reminder_store import (
    SqliteClosedDirectReminderStore,
    SqliteDirectReminderStore,
)

_PREFIX = "native-manager-v2:"
_LEGACY_PREFIX = "native-manager-v1:"
_TABLES = {
    "compact_manager_admissions",
    "compact_manager_decisions",
    "compact_manager_rejections",
}
_FAILURES = {"provider_output_invalid", "reply_schema_invalid", "reply_language_mismatch"}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class SqliteCompactManagerDecisionStore(SqliteDirectReminderStore):
    _schema_version = 44

    def __init__(
        self, path: Path, *, compact_decisions_enabled: bool = False, **family: Any
    ) -> None:
        self._compact_decisions_enabled = compact_decisions_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {43}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS compact_manager_admissions(
          turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,binding TEXT NOT NULL,
          request_hash TEXT NOT NULL,scope TEXT,scope_hash TEXT);
        CREATE TABLE IF NOT EXISTS compact_manager_decisions(
          turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,payload TEXT NOT NULL,
          fingerprint TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS compact_manager_rejections(
          turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,reason TEXT NOT NULL
            CHECK(reason IN ('capture_invalid','disabled','output_invalid','owning_rejected')),
          failure_code TEXT CHECK(failure_code IS NULL OR failure_code IN
            ('provider_output_invalid','reply_schema_invalid','reply_language_mismatch')),
          call_id TEXT,kind TEXT CHECK(kind IS NULL OR kind IN
            ('reply','child_safety','reminder','upsell')),recorded_at TEXT NOT NULL);
        """
        )

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        super()._on_admitted(db, request, turn_id, now)
        if not self._compact_decisions_enabled:
            return
        manager = db.execute(
            "SELECT binding,phase FROM parent_touch_manager_turns WHERE parent_id=? AND turn_id=?",
            (request.parent_id, turn_id),
        ).fetchone()
        if manager is None or manager["phase"] != "queued":
            return
        changed = db.execute(
            "UPDATE parent_publication_captures SET manager_binding=? "
            "WHERE parent_id=? AND turn_id=? AND manager_binding=?",
            (_PREFIX + manager["binding"], request.parent_id, turn_id, manager["binding"]),
        )
        if changed.rowcount != 1:
            raise ParentChatError("compact_manager_capture_unavailable", 503)
        db.execute(
            "INSERT INTO compact_manager_admissions VALUES(?,?,?,?,NULL,NULL)",
            (
                turn_id,
                request.parent_id,
                _PREFIX + manager["binding"],
                self._digest(request),
            ),
        )

    def _native_capture(
        self, db: sqlite3.Connection, parent: str, turn: int | None
    ) -> sqlite3.Row | None:
        publication = db.execute(
            "SELECT manager_binding FROM parent_publication_captures "
            "WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        capture = db.execute(
            "SELECT * FROM compact_manager_admissions WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        binding = publication[0] if publication else ""
        marked = isinstance(binding, str) and binding.startswith("native-manager-")
        if not marked and capture is None:
            observed = db.execute(
                "SELECT 1 FROM compact_manager_decisions WHERE parent_id=? AND turn_id=? "
                "UNION ALL SELECT 1 FROM compact_manager_rejections "
                "WHERE parent_id=? AND turn_id=?",
                (parent, turn, parent, turn),
            ).fetchone()
            if observed is not None:
                raise ParentChatError("compact_manager_capture_invalid", 503)
            return None
        original = db.execute(
            "SELECT m.binding,t.request_digest FROM parent_touch_manager_turns m "
            "JOIN parent_chat_turns t ON t.id=m.turn_id AND t.parent_id=m.parent_id "
            "WHERE m.parent_id=? AND m.turn_id=?",
            (parent, turn),
        ).fetchone()
        if (
            capture is None
            or original is None
            or binding not in {_PREFIX + original["binding"], _LEGACY_PREFIX + original["binding"]}
            or capture["binding"]
            != (binding if binding.startswith(_PREFIX) else original["binding"])
            or capture["request_hash"] != original["request_digest"]
        ):
            raise ParentChatError("compact_manager_capture_invalid", 503)
        return cast(sqlite3.Row, capture)

    def _publication_manager_binding(
        self, db: sqlite3.Connection, parent: str, turn: int | None, binding: str
    ) -> str:
        capture = self._native_capture(db, parent, turn)
        if capture is not None:
            settled = db.execute(
                "SELECT m.input_tokens,t.status FROM parent_touch_manager_turns m "
                "JOIN parent_chat_turns t ON t.id=m.turn_id AND t.parent_id=m.parent_id "
                "WHERE m.parent_id=? AND m.turn_id=?",
                (parent, turn),
            ).fetchone()
            if settled and settled[0] is not None and settled[1] != "completed":
                assert turn is not None
                self._require_native_continuation(db, parent, turn)
        return (
            cast(str, capture["binding"]).removeprefix(_PREFIX)
            if capture is not None
            else super()._publication_manager_binding(db, parent, turn, binding)
        )

    @staticmethod
    def _scope(capture: sqlite3.Row) -> ParentTouchManagerScope:
        try:
            if not capture["scope"] or _hash(capture["scope"]) != capture["scope_hash"]:
                raise ValueError("Lost captured native scope")
            scope = ParentTouchManagerScope.model_validate_json(capture["scope"])
            if scope.stage != "route" or scope.compact_decision_protocol is not None:
                raise ValueError("Changed original native scope")
            return scope
        except (ValueError, TypeError):
            raise ParentChatError("compact_manager_scope_invalid", 503) from None

    def _saved_invocation(
        self, db: sqlite3.Connection, parent: str, turn: int, capture: sqlite3.Row
    ) -> CompactManagerInvocation:
        row = db.execute(
            "SELECT d.*,m.call_id,m.choice FROM compact_manager_decisions d "
            "JOIN parent_touch_manager_turns m ON m.turn_id=d.turn_id AND m.parent_id=d.parent_id "
            "WHERE d.parent_id=? AND d.turn_id=?",
            (parent, turn),
        ).fetchone()
        try:
            if row is None or _hash(row["payload"]) != row["fingerprint"]:
                raise ValueError("Lost native decision audit")
            invocation = CompactManagerInvocation.model_validate_json(row["payload"])
            parse_compact_manager_decision(invocation.decision.model_dump(), self._scope(capture))
            if (
                invocation.decision.kind == "reply"
                or invocation.call_id != row["call_id"]
                or invocation.decision.kind != row["choice"]
            ):
                raise ValueError("Changed native handoff pairing")
            return invocation
        except (ValueError, TypeError):
            raise ParentChatError("compact_manager_pairing_invalid", 503) from None

    def _require_native_continuation(
        self, db: sqlite3.Connection, parent: str, turn: int, *, kind: str | None = None
    ) -> CompactManagerInvocation | None:
        """Gate new owning work, never raw receipt/cost reconciliation or history."""
        capture = self._native_capture(db, parent, turn)
        if capture is None:
            return None
        if not self._compact_decisions_enabled:
            raise ParentChatError("compact_manager_disabled", 503)
        invocation = self._saved_invocation(db, parent, turn, capture)
        if kind is not None and invocation.decision.kind != kind:
            raise ParentChatError("compact_manager_pairing_invalid", 503)
        return invocation

    async def manager_scope(self, parent_id: str, turn_id: int) -> ParentTouchManagerScope | None:
        scope = await super().manager_scope(parent_id, turn_id)
        if scope is None:
            return None

        def capture_scope() -> int | None:
            with self._transaction() as db:
                capture = self._native_capture(db, parent_id, turn_id)
                if capture is None:
                    return None
                if scope.stage != "route":
                    self._require_native_continuation(db, parent_id, turn_id)
                    return None
                if not self._compact_decisions_enabled:
                    raise ParentChatError("compact_manager_disabled", 503)
                payload = scope.model_dump_json()
                if capture["scope"] is None:
                    db.execute(
                        "UPDATE compact_manager_admissions SET scope=?,scope_hash=? "
                        "WHERE parent_id=? AND turn_id=?",
                        (payload, _hash(payload), parent_id, turn_id),
                    )
                elif capture["scope"] != payload or capture["scope_hash"] != _hash(payload):
                    raise ParentChatError("compact_manager_scope_invalid", 503)
                return 2 if capture["binding"].startswith(_PREFIX) else 1

        protocol = await asyncio.to_thread(capture_scope)
        return (
            scope.model_copy(update={"compact_decision_protocol": protocol})
            if protocol is not None
            else scope
        )

    def _native_valid(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt
    ) -> bool:
        try:
            capture = self._native_capture(db, turn.parent_id, turn.turn_id)
            invocation = receipt.native_manager_invocation
            if capture is None:
                return invocation is None
            manager = db.execute(
                "SELECT * FROM parent_touch_manager_turns WHERE parent_id=? AND turn_id=?",
                (turn.parent_id, turn.turn_id),
            ).fetchone()
            if manager is None:
                return False
            if manager["input_tokens"] is not None:
                self._require_native_continuation(db, turn.parent_id, turn.turn_id)
                return invocation is None
            if (
                not self._compact_decisions_enabled
                or invocation is None
                or manager["phase"] != "routing"
            ):
                return False
            checked = CompactManagerInvocation.model_validate(invocation.model_dump())
            decision = parse_compact_manager_decision(
                checked.decision.model_dump(), self._scope(capture)
            )
            if any(
                (
                    receipt.reminder_candidate,
                    receipt.upsell_choice,
                    receipt.upsell_enquiry,
                    receipt.question_id,
                    receipt.notice_id,
                )
            ):
                return False
            if decision.kind == "reply":
                expected = "\n\n".join(
                    part for part in ((decision.body or "").strip(), decision.question) if part
                )
                return (
                    receipt.manager_handoff is None
                    and receipt.answer == expected
                    and receipt.clarification_question == decision.question
                )
            expected_handoff = ParentTouchManagerHandoff(
                target=decision.kind, call_id=checked.call_id, tariff_enquiry=decision.enquiry
            )
            return (
                receipt.manager_handoff == expected_handoff
                and receipt.clarification_question is None
                and receipt.answer
                == (TARIFF_HANDOFF_PLACEHOLDER if decision.enquiry is not None else None)
            )
        except (ValueError, TypeError, ParentChatError):
            return False

    def _audit_native(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
        initial: bool,
    ) -> None:
        if not initial:
            return
        invocation = receipt.native_manager_invocation
        if not valid:
            self._audit_native_rejection(db, turn, receipt)
            return
        if invocation is None:
            return
        if self._native_capture(db, turn.parent_id, turn.turn_id) is None:
            raise ParentChatError("compact_manager_capture_invalid", 503)
        payload = invocation.model_dump_json()
        db.execute(
            "INSERT INTO compact_manager_decisions VALUES(?,?,?,?)",
            (turn.turn_id, turn.parent_id, payload, _hash(payload)),
        )

    def _audit_native_rejection(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt
    ) -> None:
        expected = db.execute(
            "SELECT 1 FROM parent_publication_captures WHERE parent_id=? AND turn_id=? "
            "AND manager_binding LIKE 'native-manager-%' UNION ALL "
            "SELECT 1 FROM compact_manager_admissions WHERE parent_id=? AND turn_id=?",
            (turn.parent_id, turn.turn_id, turn.parent_id, turn.turn_id),
        ).fetchone()
        if expected is None:
            return
        reason = "owning_rejected"
        call_id = kind = None
        try:
            capture = self._native_capture(db, turn.parent_id, turn.turn_id)
            if capture is None:
                raise ParentChatError("compact_manager_capture_invalid", 503)
            original_scope = self._scope(capture)
            if receipt.native_manager_invocation is not None:
                checked = CompactManagerInvocation.model_validate(
                    receipt.native_manager_invocation.model_dump(), strict=True
                )
                parse_compact_manager_decision(checked.decision.model_dump(), original_scope)
                call_id, kind = checked.call_id, checked.decision.kind
            if not self._compact_decisions_enabled:
                reason = "disabled"
            elif not receipt.completed or receipt.native_manager_invocation is None:
                reason = "output_invalid"
        except ParentChatError:
            reason = "capture_invalid"
        except (ValueError, TypeError):
            reason = "output_invalid"
        failure = receipt.failure_code
        recorded_at = db.execute(
            "SELECT COALESCE(m.recorded_at,t.updated_at) FROM parent_chat_turns t "
            "LEFT JOIN parent_touch_manager_turns m ON m.turn_id=t.id AND m.parent_id=t.parent_id "
            "WHERE t.parent_id=? AND t.id=?",
            (turn.parent_id, turn.turn_id),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO compact_manager_rejections VALUES(?,?,?,?,?,?,?)",
            (
                turn.turn_id,
                turn.parent_id,
                reason,
                failure if isinstance(failure, str) and failure in _FAILURES else None,
                call_id,
                kind,
                recorded_at,
            ),
        )

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        return self._native_valid(db, turn, receipt) and super()._valid_decision(
            db, turn, receipt, now
        )

    def _on_settled(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        manager = db.execute(
            "SELECT input_tokens FROM parent_touch_manager_turns WHERE parent_id=? AND turn_id=?",
            (turn.parent_id, turn.turn_id),
        ).fetchone()
        self._audit_native(
            db, turn, receipt, valid=valid, initial=manager is not None and manager[0] is None
        )
        super()._on_settled(db, turn, receipt, valid=valid)

    def _valid_manager_handoff(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        return self._native_valid(db, turn, receipt) and super()._valid_manager_handoff(
            db, turn, receipt, now
        )

    def _on_manager_handoff_settled(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        self._audit_native(db, turn, receipt, valid=valid, initial=True)
        super()._on_manager_handoff_settled(db, turn, receipt, valid=valid)

    def _validate_chat_submission(
        self, db: sqlite3.Connection, turn: StoredChatTurn, now: datetime
    ) -> None:
        super()._validate_chat_submission(db, turn, now)
        capture = self._native_capture(db, turn.parent_id, turn.turn_id)
        if capture is None:
            return
        row = db.execute(
            "SELECT input_tokens FROM parent_touch_manager_turns WHERE parent_id=? AND turn_id=?",
            (turn.parent_id, turn.turn_id),
        ).fetchone()
        if row and row[0] is not None:
            self._require_native_continuation(db, turn.parent_id, turn.turn_id)
        elif not self._compact_decisions_enabled:
            raise ParentChatError("compact_manager_disabled", 503)
        else:
            self._scope(capture)

    async def claim_reviewed_response(
        self, now: datetime
    ) -> tuple[ReviewedMessage, ParentTouchReviewedTurn] | None:
        def fence() -> None:
            with self._transaction() as db:
                rows = db.execute(
                    "SELECT t.* FROM parent_chat_turns t JOIN parent_touch_manager_turns m "
                    "ON m.turn_id=t.id AND m.parent_id=t.parent_id "
                    "LEFT JOIN parent_publication_captures p "
                    "ON p.turn_id=t.id AND p.parent_id=t.parent_id "
                    "LEFT JOIN compact_manager_admissions a "
                    "ON a.turn_id=t.id AND a.parent_id=t.parent_id "
                    "LEFT JOIN compact_manager_decisions d "
                    "ON d.turn_id=t.id AND d.parent_id=t.parent_id "
                    "LEFT JOIN compact_manager_rejections r "
                    "ON r.turn_id=t.id AND r.parent_id=t.parent_id "
                    "WHERE t.status='preparing' "
                    "AND (p.manager_binding LIKE 'native-manager-%' OR a.turn_id IS NOT NULL "
                    "OR d.turn_id IS NOT NULL OR r.turn_id IS NOT NULL) "
                    "ORDER BY t.id LIMIT ?",
                    (self._safety_limits.max_pending_jobs + 1,),
                ).fetchall()
                if len(rows) > self._safety_limits.max_pending_jobs:
                    raise ParentChatError("compact_manager_queue_overflow", 503)
                for row in rows:
                    code = (
                        "compact_manager_disabled" if not self._compact_decisions_enabled else None
                    )
                    try:
                        capture = self._native_capture(db, row["parent_id"], row["id"])
                        manager = db.execute(
                            "SELECT input_tokens FROM parent_touch_manager_turns WHERE "
                            "parent_id=? AND turn_id=?",
                            (row["parent_id"], row["id"]),
                        ).fetchone()
                        if capture is not None and manager and manager[0] is not None:
                            self._require_native_continuation(db, row["parent_id"], row["id"])
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

    def _validate_safety_submission(
        self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> None:
        if row["kind"] == "parent_message":
            native = self._require_native_continuation(
                db, row["parent_id"], row["parent_turn_cutoff"], kind="child_safety"
            )
            if native is not None:
                self._presentation(db, row["parent_id"], row["parent_turn_cutoff"])
        super()._validate_safety_submission(db, row, now)

    def _validate_safety_publication(
        self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> None:
        if row["kind"] == "parent_message":
            self._require_native_continuation(
                db, row["parent_id"], row["parent_turn_cutoff"], kind="child_safety"
            )
        super()._validate_safety_publication(db, row, now)

    @staticmethod
    def _tariff_native_origin(db: sqlite3.Connection, parent: str, turn: int) -> int:
        answer = db.execute(
            "SELECT origin_turn_id FROM upsell_currency_questions "
            "WHERE parent_id=? AND answer_turn_id=?",
            (parent, turn),
        ).fetchone()
        return cast(int, answer[0]) if answer else turn

    def _fence_pending(self, db: sqlite3.Connection, now: datetime) -> None:
        super()._fence_pending(db, now)
        rows = db.execute(
            "SELECT * FROM upsell_inline_replies WHERE status='waiting' "
            "ORDER BY origin_turn_id LIMIT ?",
            (self._upsell_policy.maximum_pending_global + 1,),
        ).fetchall()
        if len(rows) > self._upsell_policy.maximum_pending_global:
            raise ParentChatError("upsell_reply_queue_overflow", 503)
        for row in rows:
            origin = self._tariff_native_origin(db, row["parent_id"], row["origin_turn_id"])
            try:
                self._require_native_continuation(db, row["parent_id"], origin, kind="upsell")
            except ParentChatError as exc:
                self._cancel_pending(db, row, now, exc.code)

    def _currency_resolved(
        self,
        db: sqlite3.Connection,
        request: ParentTouchMessageRequest,
        result: ParentTouchMessageState,
        intent: UpsellIntent,
        now: datetime,
    ) -> ParentTouchMessageState:
        origin = self._tariff_native_origin(db, request.parent_id, result.turn_id)
        self._require_native_continuation(db, request.parent_id, origin, kind="upsell")
        return super()._currency_resolved(db, request, result, intent, now)


class SqliteClosedCompactManagerDecisionStore(SqliteClosedDirectReminderStore):
    _schema_version = 44

    def __init__(self, path: Path, **family: Any) -> None:
        super().__init__(path, **family)
        self._schema_version = 44

    def _supported_versions(self) -> set[int]:
        return {44}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
