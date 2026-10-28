"Private v21: one metered manager decision before optional owning specialist work."

import asyncio
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from app.mana_ai.application.chat_ports import ChatModelReceipt, ChatReplyDeferred, ParentChatError
from app.mana_ai.application.parent_languages import parent_language
from app.mana_ai.domain.chat import ChatTokens, ParentChatResponse, StoredChatTurn
from app.mana_ai.domain.family_agents import (
    ParentTouchEvidence,
    ParentTouchReviewedTurn,
    ReviewedMessage,
)
from app.mana_ai.domain.parent_touch_manager import (
    ParentTouchManagerHandoff,
    ParentTouchManagerScope,
)
from app.services.proactive_parent_store import _current_context
from app.services.reviewed_message_store import SqliteReviewedMessageStore
from app.services.shared_conversion_profile_store import (
    SqliteClosedSharedConversionProfileStore,
    SqliteSharedConversionProfileStore,
)

_TABLE = "parent_touch_manager_turns"


class SqliteParentTouchManagerStore(SqliteSharedConversionProfileStore):
    _schema_version = 21

    def _direct_manager_result(self, receipt: ChatModelReceipt) -> bool:
        return False

    def _valid_manager_handoff(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        now: datetime,
    ) -> bool:
        """Validate an additional captured native protocol after raw usage is charged."""
        return True

    def _on_manager_handoff_settled(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        """Optional private decision audit inside the same owning transaction."""

    def __init__(
        self,
        path: Path,
        *,
        manager_enabled: bool = False,
        manager_binding: str,
        manager_model: str,
        **family: Any,
    ) -> None:
        if not manager_binding or len(manager_binding) > 256 or not 0 < len(manager_model) <= 128:
            raise ValueError("An explicit parent-manager model binding is required")
        self._manager_enabled = manager_enabled
        self._manager_binding, self._manager_model = manager_binding, manager_model
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {20}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS parent_touch_manager_turns(
          turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,binding TEXT NOT NULL,
          model TEXT NOT NULL,language TEXT NOT NULL,context TEXT NOT NULL,phase TEXT NOT NULL
          CHECK(phase IN ('queued','routing','cap_waiting','cap_running','review_waiting',
                         'finished','failed','unknown')),
          choice TEXT,call_id TEXT,input_tokens INTEGER,output_tokens INTEGER,
          receipt_model TEXT,recorded_at TEXT);
        CREATE INDEX IF NOT EXISTS parent_touch_manager_pending
          ON parent_touch_manager_turns(phase,turn_id);
        """
        )

    def _manager_priority(
        self, db: sqlite3.Connection, parent: str, turn: int, now: datetime
    ) -> bool:
        return self._priority_waiting(db, parent, now, turn) or bool(
            db.execute(
                (
                    "SELECT 1 FROM child_safety_jobs WHERE parent_id=? AND status IN "
                    "('queued','preparing','submitted','unknown','metered') LIMIT 1"
                ),
                (parent,),
            ).fetchone()
        )

    def _expiry_parent_ready(self, db: sqlite3.Connection, parent: str, now: datetime) -> bool:
        return not self._manager_enabled or not bool(
            db.execute(
                "SELECT 1 FROM parent_chat_turns WHERE parent_id=? AND message<>'' "
                "AND created_at>? LIMIT 1",
                (
                    parent,
                    (
                        now - timedelta(seconds=self._conversion_policy.conversation_idle_seconds)
                    ).isoformat(),
                ),
            ).fetchone()
        )

    def _defer_initial_review(
        self,
        db: sqlite3.Connection,
        request: ParentTouchReviewedTurn,
        turn_id: int,
        now: datetime,
        context: str,
    ) -> bool:
        if (
            not self._manager_enabled
            or self._question_reply_needs_safety(db, request, turn_id)
            or self._manager_priority(db, request.parent_id, turn_id, now)
        ):
            return False
        reference = db.execute(
            ("SELECT language_reference FROM family_turn_metadata WHERE turn_id=? AND parent_id=?"),
            (turn_id, request.parent_id),
        ).fetchone()[0]
        contact = _current_context(db, request.parent_id, now)
        language = parent_language(reference) or (contact.language if contact else "en")
        db.execute(
            (
                "INSERT INTO "
                "parent_touch_manager_turns(turn_id,parent_id,binding,model,language,context,phase)"
                " VALUES(?,?,?,?,?,?,'queued')"
            ),
            (
                turn_id,
                request.parent_id,
                self._manager_binding,
                self._manager_model,
                language,
                context,
            ),
        )
        return True

    def _question_reply_needs_safety(
        self, db: sqlite3.Connection, request: ParentTouchReviewedTurn, turn_id: int
    ) -> bool:
        return request.reply_to_question_id is not None

    @staticmethod
    def _message(db: sqlite3.Connection, parent_id: str, request_id: UUID) -> ReviewedMessage:
        result = SqliteReviewedMessageStore._message(db, parent_id, request_id)
        manager = db.execute(
            ("SELECT phase FROM parent_touch_manager_turns WHERE parent_id=? AND turn_id=?"),
            (parent_id, result.turn.turn_id),
        ).fetchone()
        if (
            manager
            and manager[0] in {"queued", "routing", "cap_waiting", "cap_running"}
            and result.turn.status == "preparing"
        ):
            return result.model_copy(update={"phase": "responding"})
        return result

    async def claim_reviewed_response(
        self, now: datetime
    ) -> tuple[ReviewedMessage, ParentTouchReviewedTurn] | None:
        def claim() -> tuple[ReviewedMessage, ParentTouchReviewedTurn] | None:
            utc = self._utc(now)
            with self._transaction() as db:
                rows = db.execute(
                    "SELECT m.*,t.request_id,t.created_at FROM "
                    "parent_touch_manager_turns m JOIN parent_chat_turns t ON "
                    "t.id=m.turn_id AND t.parent_id=m.parent_id WHERE m.phase IN "
                    "('queued','cap_waiting','review_waiting') AND "
                    "t.status='preparing' ORDER BY t.id LIMIT 100"
                ).fetchall()
                for row in rows:
                    self._recover_pre_dispatch(db, row["parent_id"], utc)
                    state = self._message(db, row["parent_id"], UUID(row["request_id"]))
                    if state.turn.status != "preparing":
                        continue
                    code = (
                        "parent_manager_disabled"
                        if not self._manager_enabled
                        else "parent_manager_profile_changed"
                        if row["binding"] != self._manager_binding
                        else None
                    )
                    if (
                        code is None
                        and row["phase"] != "review_waiting"
                        and self._manager_priority(db, row["parent_id"], row["turn_id"], utc)
                    ):
                        code = "parent_manager_priority_changed"
                    if code:
                        db.execute(
                            (
                                "UPDATE parent_chat_turns SET "
                                "status='failed',reserved=0,error_code=?,error_status=503 WHERE "
                                "id=?"
                            ),
                            (code, row["turn_id"]),
                        )
                        self._on_failed(db, state.turn, unknown=False)
                        continue
                    if row["phase"] == "review_waiting":
                        continue
                    phase = "routing" if row["phase"] == "queued" else "cap_running"
                    db.execute(
                        "UPDATE parent_touch_manager_turns SET phase=? WHERE turn_id=?",
                        (phase, row["turn_id"]),
                    )
                    db.execute(
                        (
                            "UPDATE family_reviewed_messages SET phase='claimed',claimed_at=? "
                            "WHERE turn_id=?"
                        ),
                        (utc.isoformat(), row["turn_id"]),
                    )
                    saved = db.execute(
                        "SELECT request FROM family_reviewed_messages WHERE turn_id=?",
                        (row["turn_id"],),
                    ).fetchone()[0]
                    return self._message(
                        db, row["parent_id"], UUID(row["request_id"])
                    ), ParentTouchReviewedTurn.model_validate_json(saved)
            return None

        managed = await asyncio.to_thread(claim)
        return managed if managed is not None else await super().claim_reviewed_response(now)

    async def manager_scope(self, parent_id: str, turn_id: int) -> ParentTouchManagerScope | None:
        def read() -> ParentTouchManagerScope | None:
            with self._connect() as db:
                row = db.execute(
                    ("SELECT * FROM parent_touch_manager_turns WHERE parent_id=? AND turn_id=?"),
                    (parent_id, turn_id),
                ).fetchone()
                if not row or row["phase"] not in {"routing", "cap_running", "review_waiting"}:
                    return None
                if not self._manager_enabled or row["binding"] != self._manager_binding:
                    raise ParentChatError("parent_manager_disabled_or_changed", 503)
                return ParentTouchManagerScope(
                    language=row["language"],
                    stage="route" if row["phase"] == "routing" else row["choice"],
                    upsell_enabled=bool(
                        db.execute(
                            "SELECT 1 FROM upsell_turns WHERE parent_id=? AND turn_id=?",
                            (parent_id, turn_id),
                        ).fetchone()
                    ),
                    reminders_enabled=bool(
                        db.execute(
                            "SELECT 1 FROM assistant_turns WHERE parent_id=? AND turn_id=?",
                            (parent_id, turn_id),
                        ).fetchone()
                    ),
                )

        return await asyncio.to_thread(read)

    async def evidence_for_turn(
        self, parent_id: str, turn_id: int, connected: tuple[int, ...]
    ) -> ParentTouchEvidence | None:
        def manager_without_evidence() -> bool:
            with self._connect() as db:
                row = db.execute(
                    (
                        "SELECT t.choice,m.guidance FROM parent_touch_manager_turns t JOIN"
                        " family_reviewed_messages m ON m.turn_id=t.turn_id AND "
                        "m.parent_id=t.parent_id WHERE t.parent_id=? AND t.turn_id=?"
                    ),
                    (parent_id, turn_id),
                ).fetchone()
                return row is not None and (
                    row["choice"] != "child_safety" or row["guidance"] is None
                )

        if await asyncio.to_thread(manager_without_evidence):
            return None
        return await super().evidence_for_turn(parent_id, turn_id, connected)

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        row = db.execute(
            ("SELECT * FROM parent_touch_manager_turns WHERE parent_id=? AND turn_id=?"),
            (turn.parent_id, turn.turn_id),
        ).fetchone()
        if row and (not self._manager_enabled or row["binding"] != self._manager_binding):
            return False
        if row and row["phase"] not in {"routing", "cap_running", "review_waiting"}:
            return False
        if row and not (
            receipt.model == row["model"] or receipt.model.startswith(row["model"] + "-")
        ):
            return False
        if (
            row
            and row["phase"] in {"routing", "cap_running"}
            and self._manager_priority(db, turn.parent_id, turn.turn_id, now)
        ):
            return False
        if receipt.manager_handoff is not None:
            return False
        if row:
            target = row["choice"] if row["phase"] != "routing" else None
            if receipt.reminder_candidate is not None and target != "reminder":
                return False
            if receipt.upsell_choice is not None and target != "upsell":
                return False
            if target != "child_safety" and (receipt.question_id or receipt.notice_id):
                return False
        return super()._valid_decision(db, turn, receipt, now)

    async def settle(
        self,
        turn: StoredChatTurn,
        *,
        receipt: ChatModelReceipt,
        now: datetime,
        history_turns: int,
        context_at: datetime,
    ) -> ParentChatResponse:
        if receipt.manager_handoff is not None and not self._direct_manager_result(receipt):
            await asyncio.to_thread(self._settle_handoff, turn, receipt, self._utc(now))
            raise ChatReplyDeferred()
        return await super().settle(
            turn, receipt=receipt, now=now, history_turns=history_turns, context_at=context_at
        )

    def _settle_handoff(
        self, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> None:
        code: str | None = None
        with self._transaction() as db:
            root = db.execute(
                "SELECT * FROM parent_chat_turns WHERE id=? AND parent_id=?",
                (turn.turn_id, turn.parent_id),
            ).fetchone()
            manager = db.execute(
                ("SELECT * FROM parent_touch_manager_turns WHERE turn_id=? AND parent_id=?"),
                (turn.turn_id, turn.parent_id),
            ).fetchone()
            if (
                root is None
                or root["status"] not in {"submitted", "unknown"}
                or manager is None
                or manager["input_tokens"] is not None
            ):
                raise ParentChatError("manager_request_no_longer_admitted", 409)
            db.execute(
                ("UPDATE parent_chat_quota SET used=used+? WHERE parent_id=? AND day=?"),
                (receipt.usage.total, turn.parent_id, root["day"]),
            )
            if not self._valid_manager_handoff(db, turn, receipt, now):
                code = "parent_manager_decision_invalid"
            handoff = None
            try:
                assert receipt.manager_handoff is not None
                handoff = ParentTouchManagerHandoff.model_validate(
                    receipt.manager_handoff.model_dump()
                )
            except (ValueError, TypeError):
                code = "parent_manager_decision_invalid"
            if handoff is not None and handoff.tariff_enquiry is not None:
                code = "parent_manager_decision_invalid"
            if not receipt.completed or receipt.usage.total > root["reserved"]:
                code = "parent_manager_usage_or_decision_invalid"
            if (
                root["status"] != "submitted"
                or manager["phase"] != "routing"
                or not self._manager_enabled
                or manager["binding"] != self._manager_binding
                or root["created_at"] < (now - timedelta(minutes=5)).isoformat()
            ):
                code = "parent_manager_no_longer_admitted"
            if self._manager_priority(db, turn.parent_id, turn.turn_id, now):
                code = "parent_manager_priority_changed"
            if (
                receipt.answer is not None
                or receipt.question_id
                or receipt.notice_id
                or receipt.reminder_candidate
                or receipt.upsell_choice
                or receipt.upsell_enquiry
            ):
                code = "parent_manager_decision_invalid"
            if not (
                receipt.model == manager["model"]
                or receipt.model.startswith(manager["model"] + "-")
            ):
                code = "parent_manager_profile_changed"
            if handoff and handoff.target in {"upsell", "reminder"}:
                table = "upsell_turns" if handoff.target == "upsell" else "assistant_turns"
                if not db.execute(
                    f"SELECT 1 FROM {table} WHERE turn_id=? AND parent_id=?",
                    (turn.turn_id, turn.parent_id),
                ).fetchone():
                    code = "parent_manager_capability_unavailable"
            used = db.execute(
                "SELECT used FROM parent_chat_quota WHERE parent_id=? AND day=?",
                (turn.parent_id, root["day"]),
            ).fetchone()[0]
            held = db.execute(
                (
                    "SELECT COALESCE(SUM(reserved),0) FROM parent_chat_turns WHERE "
                    "parent_id=? AND id<>? AND status IN "
                    "('preparing','submitted','unknown')"
                ),
                (turn.parent_id, turn.turn_id),
            ).fetchone()[0]
            remaining = max(0, self._limit - used - held)
            if remaining < 128:
                code = "daily_token_budget_exceeded"
            db.execute(
                (
                    "UPDATE parent_touch_manager_turns SET "
                    "input_tokens=?,output_tokens=?,receipt_model=?,recorded_at=? "
                    "WHERE turn_id=?"
                ),
                (
                    receipt.usage.input_tokens,
                    receipt.usage.output_tokens,
                    receipt.model,
                    now.isoformat(),
                    turn.turn_id,
                ),
            )
            if code:
                db.execute(
                    (
                        "UPDATE parent_chat_turns SET "
                        "status='failed',reserved=0,error_code=?,error_status=503,input_tokens=?,output_tokens=?,model=?"
                        " WHERE id=?"
                    ),
                    (
                        code,
                        receipt.usage.input_tokens,
                        receipt.usage.output_tokens,
                        receipt.model,
                        turn.turn_id,
                    ),
                )
                self._on_failed(db, turn, unknown=False)
            else:
                assert handoff is not None
                phase = "review_waiting" if handoff.target == "child_safety" else "cap_waiting"
                db.execute(
                    (
                        "UPDATE parent_touch_manager_turns SET phase=?,choice=?,call_id=? "
                        "WHERE turn_id=?"
                    ),
                    (phase, handoff.target, handoff.call_id, turn.turn_id),
                )
                db.execute(
                    (
                        "UPDATE parent_chat_turns SET "
                        "status='preparing',reserved=?,updated_at=? WHERE id=?"
                    ),
                    (remaining, now.isoformat(), turn.turn_id),
                )
                db.execute(
                    (
                        "UPDATE family_reviewed_messages SET "
                        "phase='waiting',claimed_at=NULL WHERE turn_id=?"
                    ),
                    (turn.turn_id,),
                )
                if handoff.target == "child_safety":
                    db.execute(
                        (
                            "INSERT INTO "
                            "child_safety_parent_events(turn_id,parent_id,created_at,context) "
                            "VALUES(?,?,?,?)"
                        ),
                        (turn.turn_id, turn.parent_id, root["created_at"], manager["context"]),
                    )
            self._on_manager_handoff_settled(db, turn, receipt, valid=code is None)
        if code:
            raise ParentChatError(code, 503)

    def _on_settled(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        super()._on_settled(db, turn, receipt, valid=valid)
        row = db.execute(
            ("SELECT * FROM parent_touch_manager_turns WHERE parent_id=? AND turn_id=?"),
            (turn.parent_id, turn.turn_id),
        ).fetchone()
        if row is None:
            return
        if row["input_tokens"] is not None:
            usage = ChatTokens(
                input_tokens=row["input_tokens"] + receipt.usage.input_tokens,
                output_tokens=row["output_tokens"] + receipt.usage.output_tokens,
            )
            db.execute(
                ("UPDATE parent_chat_turns SET input_tokens=?,output_tokens=? WHERE id=?"),
                (usage.input_tokens, usage.output_tokens, turn.turn_id),
            )
            if valid:
                result = ParentChatResponse.model_validate_json(
                    db.execute(
                        "SELECT result FROM parent_chat_turns WHERE id=?", (turn.turn_id,)
                    ).fetchone()[0]
                )
                db.execute(
                    "UPDATE parent_chat_turns SET result=? WHERE id=?",
                    (result.model_copy(update={"usage": usage}).model_dump_json(), turn.turn_id),
                )
        else:
            db.execute(
                (
                    "UPDATE parent_touch_manager_turns SET "
                    "input_tokens=?,output_tokens=?,receipt_model=?,recorded_at=(SELECT"
                    " updated_at FROM parent_chat_turns WHERE id=?) WHERE turn_id=?"
                ),
                (
                    receipt.usage.input_tokens,
                    receipt.usage.output_tokens,
                    receipt.model,
                    turn.turn_id,
                    turn.turn_id,
                ),
            )
        db.execute(
            "UPDATE parent_touch_manager_turns SET phase=? WHERE turn_id=?",
            ("finished" if valid else "failed", turn.turn_id),
        )

    def _on_failed(self, db: sqlite3.Connection, turn: StoredChatTurn, *, unknown: bool) -> None:
        super()._on_failed(db, turn, unknown=unknown)
        db.execute(
            ("UPDATE parent_touch_manager_turns SET phase=? WHERE turn_id=? AND parent_id=?"),
            ("unknown" if unknown else "failed", turn.turn_id, turn.parent_id),
        )


class SqliteClosedParentTouchManagerStore(SqliteClosedSharedConversionProfileStore):
    _schema_version = 21

    def _supported_versions(self) -> set[int]:
        return {21}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}
