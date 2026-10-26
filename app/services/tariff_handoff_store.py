"""Family v33: one verified native manager call can carry a typed tariff enquiry."""

import asyncio
import hashlib
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.application.upsell_text import TARIFF_HANDOFF_PLACEHOLDER
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.client_upsell import UpsellChoice, UpsellEnquiry, UpsellIntent
from app.mana_ai.domain.family_agents import ParentTouchMessageRequest, ParentTouchMessageState
from app.mana_ai.domain.parent_touch_manager import (
    ParentTouchManagerHandoff,
    ParentTouchManagerScope,
)
from app.services.inline_upsell_store import SqliteClosedInlineUpsellStore, SqliteInlineUpsellStore

_TABLES = {"manager_tariff_admissions", "manager_tariff_decisions"}


def _tariff_receipt(receipt: ChatModelReceipt) -> ChatModelReceipt:
    handoff = receipt.manager_handoff
    try:
        if handoff is None:
            return receipt
        checked = ParentTouchManagerHandoff.model_validate(handoff.model_dump())
        enquiry = checked.tariff_enquiry
        if checked.target != "upsell" or enquiry is None:
            raise ValueError("No typed tariff enquiry")
        return replace(
            receipt,
            manager_handoff=None,
            upsell_enquiry=enquiry if enquiry.currency is None else None,
            upsell_choice=UpsellChoice.model_validate(enquiry.model_dump())
            if enquiry.currency is not None
            else None,
        )
    except (ValueError, TypeError, ValidationError):
        return replace(receipt, manager_handoff=None, completed=False, answer=None)


class SqliteTariffHandoffStore(SqliteInlineUpsellStore):
    _schema_version = 33

    def __init__(self, path: Path, *, tariff_handoff_enabled: bool = False, **family: Any) -> None:
        self._tariff_handoff_enabled = tariff_handoff_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {32}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS manager_tariff_admissions(
            turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,direct_call_id TEXT);
        CREATE TABLE IF NOT EXISTS manager_tariff_decisions(
            turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,call_id TEXT NOT NULL,
            payload TEXT NOT NULL,fingerprint TEXT NOT NULL);
        """
        )

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        super()._on_admitted(db, request, turn_id, now)
        if (
            self._tariff_handoff_enabled
            and db.execute(
                "SELECT 1 FROM upsell_inline_admissions a JOIN parent_touch_manager_turns m "
                "ON m.turn_id=a.turn_id AND m.parent_id=a.parent_id "
                "WHERE a.turn_id=? AND a.parent_id=? AND m.phase='queued'",
                (turn_id, request.parent_id),
            ).fetchone()
        ):
            db.execute(
                "INSERT INTO manager_tariff_admissions VALUES(?,?,NULL)",
                (turn_id, request.parent_id),
            )

    @staticmethod
    def _captured(db: sqlite3.Connection, parent: str, turn: int) -> bool:
        return bool(
            db.execute(
                "SELECT 1 FROM manager_tariff_admissions WHERE parent_id=? AND turn_id=?",
                (parent, turn),
            ).fetchone()
        )

    async def manager_scope(self, parent_id: str, turn_id: int) -> ParentTouchManagerScope | None:
        scope = await super().manager_scope(parent_id, turn_id)
        if scope is None:
            return None

        def captured() -> bool:
            with self._connect() as db:
                return self._captured(db, parent_id, turn_id)

        if not await asyncio.to_thread(captured):
            return scope
        if not self._tariff_handoff_enabled:
            raise ParentChatError("tariff_handoff_disabled", 503)
        return scope.model_copy(update={"tariff_handoff_enabled": scope.stage == "route"})

    def _direct_manager_result(self, receipt: ChatModelReceipt) -> bool:
        return (
            receipt.manager_handoff is not None
            and receipt.manager_handoff.tariff_enquiry is not None
        )

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        captured = self._captured(db, turn.parent_id, turn.turn_id)
        if captured and not self._tariff_handoff_enabled:
            return False
        if not self._direct_manager_result(receipt):
            return super()._valid_decision(db, turn, receipt, now)
        handoff = receipt.manager_handoff
        normalized = _tariff_receipt(receipt)
        root = db.execute(
            "SELECT status FROM parent_chat_turns WHERE id=? AND parent_id=?",
            (turn.turn_id, turn.parent_id),
        ).fetchone()
        manager = db.execute(
            "SELECT phase,input_tokens FROM parent_touch_manager_turns "
            "WHERE turn_id=? AND parent_id=?",
            (turn.turn_id, turn.parent_id),
        ).fetchone()
        if (
            not captured
            or not self._inline_enabled
            or not self._currency_enabled
            or handoff is None
            or not normalized.completed
            or receipt.answer != TARIFF_HANDOFF_PLACEHOLDER
            or receipt.upsell_choice is not None
            or receipt.upsell_enquiry is not None
            or receipt.reminder_candidate is not None
            or receipt.clarification_question is not None
            or receipt.question_id is not None
            or receipt.notice_id is not None
            or root is None
            or root[0] != "submitted"
            or manager is None
            or manager["phase"] != "routing"
            or manager["input_tokens"] is not None
            or now >= turn.created_at + timedelta(minutes=5)
        ):
            return False
        db.execute(
            "UPDATE parent_touch_manager_turns SET phase='cap_running',choice='upsell',call_id=? "
            "WHERE turn_id=? AND parent_id=?",
            (handoff.call_id, turn.turn_id, turn.parent_id),
        )
        valid = super()._valid_decision(db, turn, normalized, now)
        if valid:
            assert handoff.tariff_enquiry is not None
            payload = handoff.tariff_enquiry.model_dump_json()
            changed = db.execute(
                "UPDATE manager_tariff_admissions SET direct_call_id=? "
                "WHERE turn_id=? AND parent_id=? AND direct_call_id IS NULL",
                (handoff.call_id, turn.turn_id, turn.parent_id),
            )
            if changed.rowcount != 1:
                raise ParentChatError("tariff_handoff_pairing_changed", 503)
            db.execute(
                "INSERT INTO manager_tariff_decisions VALUES(?,?,?,?,?)",
                (
                    turn.turn_id,
                    turn.parent_id,
                    handoff.call_id,
                    payload,
                    hashlib.sha256(payload.encode()).hexdigest(),
                ),
            )
        return valid

    def _on_settled(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        # Raw usage has already been charged by the common atomic settlement.
        normalized = _tariff_receipt(receipt) if self._direct_manager_result(receipt) else receipt
        super()._on_settled(db, turn, normalized, valid=valid)

    def _settle_handoff(
        self, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> None:
        if not self._tariff_handoff_enabled:
            with self._connect() as db:
                captured = self._captured(db, turn.parent_id, turn.turn_id)
            if captured:
                receipt = replace(receipt, completed=False)
        super()._settle_handoff(turn, receipt, now)

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
            question = db.execute(
                "SELECT origin_turn_id FROM upsell_currency_questions "
                "WHERE parent_id=? AND answer_turn_id=?",
                (row["parent_id"], row["origin_turn_id"]),
            ).fetchone()
            origin = question[0] if question else row["origin_turn_id"]
            admission = db.execute(
                "SELECT direct_call_id FROM manager_tariff_admissions "
                "WHERE turn_id=? AND parent_id=?",
                (origin, row["parent_id"]),
            ).fetchone()
            if admission is None:
                continue
            if not self._tariff_handoff_enabled:
                self._cancel_pending(db, row, now, "tariff_handoff_disabled")
            elif admission[0] is not None and not self._valid_pairing(
                db, row, origin, admission[0]
            ):
                self._cancel_pending(db, row, now, "tariff_handoff_pairing_changed")

    @staticmethod
    def _valid_pairing(db: sqlite3.Connection, row: sqlite3.Row, origin: int, call: str) -> bool:
        saved = db.execute(
            "SELECT d.*,m.call_id AS manager_call FROM manager_tariff_decisions d "
            "JOIN parent_touch_manager_turns m ON m.turn_id=d.turn_id AND m.parent_id=d.parent_id "
            "WHERE d.turn_id=? AND d.parent_id=?",
            (origin, row["parent_id"]),
        ).fetchone()
        intent_row = db.execute(
            "SELECT payload FROM upsell_intents WHERE intent_id=? AND parent_id=?",
            (row["intent_id"], row["parent_id"]),
        ).fetchone()
        if (
            saved is None
            or saved["call_id"] != call
            or saved["manager_call"] != call
            or hashlib.sha256(saved["payload"].encode()).hexdigest() != saved["fingerprint"]
            or intent_row is None
        ):
            return False
        try:
            enquiry = UpsellEnquiry.model_validate_json(saved["payload"])
            intent = UpsellIntent.model_validate_json(intent_row[0])
            expected = intent.choice.model_dump()
            if origin != row["origin_turn_id"]:
                expected["currency"] = None
            return enquiry == UpsellEnquiry.model_validate(expected)
        except (ValueError, TypeError, ValidationError):
            return False

    def _currency_resolved(
        self,
        db: sqlite3.Connection,
        request: ParentTouchMessageRequest,
        result: ParentTouchMessageState,
        intent: UpsellIntent,
        now: datetime,
    ) -> ParentTouchMessageState:
        if (
            not self._tariff_handoff_enabled
            and db.execute(
                "SELECT 1 FROM upsell_currency_questions q JOIN manager_tariff_admissions a "
                "ON a.turn_id=q.origin_turn_id AND a.parent_id=q.parent_id "
                "WHERE q.parent_id=? AND q.answer_turn_id=?",
                (request.parent_id, result.turn_id),
            ).fetchone()
        ):
            raise ParentChatError("tariff_handoff_disabled", 503)
        return super()._currency_resolved(db, request, result, intent, now)


class SqliteClosedTariffHandoffStore(SqliteClosedInlineUpsellStore):
    _schema_version = 33

    def _supported_versions(self) -> set[int]:
        return {33}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
