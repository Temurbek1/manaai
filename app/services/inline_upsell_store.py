"""Family v32: verified tariff decisions await one tool result in their original turn."""

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.application.upsell_text import upsell_result
from app.mana_ai.domain.chat import ParentChatRequest, ParentChatResponse, StoredChatTurn
from app.mana_ai.domain.client_upsell import UpsellIntent, UpsellQuote, UpsellWork
from app.mana_ai.domain.family_agents import (
    ParentTouchMessageRequest,
    ParentTouchMessageState,
    ParentTouchReviewedTurn,
    ReviewedMessage,
)
from app.services.upsell_currency_store import (
    SqliteClosedUpsellCurrencyStore,
    SqliteUpsellCurrencyStore,
)

_TABLES = {"upsell_inline_admissions", "upsell_inline_replies"}
_CANCEL = {
    "отмена",
    "отмени подбор",
    "bekor qiling",
    "tarif tanlashni bekor qiling",
    "бекор қилинг",
    "cancel",
    "cancel tariff request",
}
_EXPLICIT_CANCEL = {"отмени подбор", "tarif tanlashni bekor qiling", "cancel tariff request"}
_CANCELLED = {
    "ru": "Подбор тарифов отменён.",
    "uz-Latn": "Tarif tanlash bekor qilindi.",
    "uz-Cyrl": "Тариф танлаш бекор қилинди.",
    "en": "Tariff selection cancelled.",
}


class SqliteInlineUpsellStore(SqliteUpsellCurrencyStore):
    _schema_version = 32

    def __init__(self, path: Path, *, inline_enabled: bool = False, **family: Any) -> None:
        self._inline_enabled = inline_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {31}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS upsell_inline_admissions(
            turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS upsell_inline_replies(
            intent_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,
            origin_turn_id INTEGER NOT NULL UNIQUE,status TEXT NOT NULL
                CHECK(status IN ('waiting','completed','cancelled')),
            deadline TEXT NOT NULL,payload TEXT NOT NULL,fingerprint TEXT NOT NULL,
            intent_fingerprint TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS upsell_inline_waiting
            ON upsell_inline_replies(status,origin_turn_id);
        """
        )

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        super()._on_admitted(db, request, turn_id, now)
        if (
            self._inline_enabled
            and db.execute(
                "SELECT 1 FROM upsell_currency_admissions WHERE parent_id=? AND turn_id=?",
                (request.parent_id, turn_id),
            ).fetchone()
        ):
            db.execute(
                "INSERT INTO upsell_inline_admissions VALUES(?,?)", (turn_id, request.parent_id)
            )

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        if db.execute(
            "SELECT 1 FROM upsell_inline_admissions WHERE turn_id=? AND parent_id=?",
            (turn.turn_id, turn.parent_id),
        ).fetchone() and (
            not self._inline_enabled or now >= turn.created_at + timedelta(minutes=5)
        ):
            return False
        return super()._valid_decision(db, turn, receipt, now)

    def _on_settled(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        super()._on_settled(db, turn, receipt, valid=valid)
        if not valid or receipt.upsell_choice is None:
            return
        row = db.execute(
            "SELECT i.* FROM upsell_intents i JOIN upsell_inline_admissions a "
            "ON a.turn_id=i.origin_turn_id AND a.parent_id=i.parent_id "
            "WHERE i.origin_turn_id=? AND i.parent_id=? AND i.status='queued'",
            (turn.turn_id, turn.parent_id),
        ).fetchone()
        if row:
            self._stage(db, UpsellIntent.model_validate_json(row["payload"]))

    def _currency_resolved(
        self,
        db: sqlite3.Connection,
        request: ParentTouchMessageRequest,
        result: ParentTouchMessageState,
        intent: UpsellIntent,
        now: datetime,
    ) -> ParentTouchMessageState:
        if not db.execute(
            "SELECT 1 FROM upsell_currency_questions c JOIN upsell_inline_admissions a "
            "ON a.turn_id=c.origin_turn_id AND a.parent_id=c.parent_id "
            "WHERE c.parent_id=? AND c.answer_turn_id=? AND c.status='resolved'",
            (request.parent_id, result.turn_id),
        ).fetchone():
            return result
        if not self._inline_enabled:
            raise ParentChatError("upsell_inline_disabled", 503)
        self._stage(db, intent)
        return result.model_copy(update={"phase": "responding", "response": None})

    def _stage(self, db: sqlite3.Connection, intent: UpsellIntent) -> None:
        row = db.execute(
            "SELECT * FROM parent_chat_turns WHERE id=? AND parent_id=? AND status='completed'",
            (intent.origin_turn_id, intent.parent_id),
        ).fetchone()
        if row is None or row["result"] is None or row["reserved"] != 0:
            raise ParentChatError("upsell_reply_not_settled", 409)
        response = ParentChatResponse.model_validate_json(row["result"])
        payload = response.model_dump_json()
        deadline = min(
            datetime.fromisoformat(row["created_at"]) + timedelta(minutes=5),
            intent.created_at + timedelta(seconds=self._upsell_policy.claim_seconds),
        )
        db.execute(
            "INSERT INTO upsell_inline_replies VALUES(?,?,?,'waiting',?,?,?,?)",
            (
                str(intent.intent_id),
                intent.parent_id,
                intent.origin_turn_id,
                deadline.isoformat(),
                payload,
                hashlib.sha256(payload.encode()).hexdigest(),
                hashlib.sha256(intent.model_dump_json().encode()).hexdigest(),
            ),
        )
        db.execute(
            "UPDATE parent_chat_turns SET status='preparing',answer=NULL,result=NULL "
            "WHERE id=? AND parent_id=?",
            (intent.origin_turn_id, intent.parent_id),
        )
        self._upsell_event(
            db, str(intent.intent_id), "reply_waiting_for_catalog", intent.created_at
        )

    def _settlement_deferred(self, db: sqlite3.Connection, turn: StoredChatTurn) -> bool:
        return bool(
            db.execute(
                "SELECT 1 FROM upsell_inline_replies WHERE origin_turn_id=? AND parent_id=? "
                "AND status='waiting'",
                (turn.turn_id, turn.parent_id),
            ).fetchone()
        )

    @staticmethod
    def _checked_response(row: sqlite3.Row, turn: sqlite3.Row) -> ParentChatResponse:
        if hashlib.sha256(row["payload"].encode()).hexdigest() != row["fingerprint"]:
            raise ValueError("Changed tariff response checkpoint")
        response = ParentChatResponse.model_validate_json(row["payload"])
        if (
            response.parent_id != row["parent_id"]
            or str(response.request_id) != turn["request_id"]
            or response.model != turn["model"]
            or response.usage.input_tokens != (turn["input_tokens"] or 0)
            or response.usage.output_tokens != (turn["output_tokens"] or 0)
        ):
            raise ValueError("Tariff response checkpoint binding mismatch")
        return response

    def _cancel_pending(
        self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime, code: str
    ) -> None:
        db.execute(
            "UPDATE upsell_inline_replies SET status='cancelled' WHERE intent_id=?",
            (row["intent_id"],),
        )
        db.execute(
            "UPDATE upsell_intents SET status='cancelled' WHERE intent_id=? "
            "AND status IN ('queued','checking','ready')",
            (row["intent_id"],),
        )
        db.execute(
            "UPDATE parent_chat_turns SET status='failed',error_code=?,error_status=409,"
            "updated_at=? "
            "WHERE id=? AND parent_id=? AND status='preparing' AND reserved=0",
            (code, now.isoformat(), row["origin_turn_id"], row["parent_id"]),
        )
        self._upsell_event(db, row["intent_id"], code, now)

    def _fence_pending(self, db: sqlite3.Connection, now: datetime) -> None:
        rows = db.execute(
            "SELECT * FROM upsell_inline_replies WHERE status='waiting' "
            "ORDER BY origin_turn_id LIMIT ?",
            (self._upsell_policy.maximum_pending_global + 1,),
        ).fetchall()
        if len(rows) > self._upsell_policy.maximum_pending_global:
            raise ParentChatError("upsell_reply_queue_overflow", 503)
        for row in rows:
            turn = db.execute(
                "SELECT * FROM parent_chat_turns WHERE id=? AND parent_id=?",
                (row["origin_turn_id"], row["parent_id"]),
            ).fetchone()
            code = (
                "upsell_inline_disabled"
                if not self._inline_enabled or not self._currency_enabled
                else "upsell_reply_expired"
                if now >= datetime.fromisoformat(row["deadline"])
                else "upsell_reply_no_longer_waiting"
                if turn is None or turn["status"] != "preparing"
                else None
            )
            if code is None:
                try:
                    self._checked_response(row, turn)
                    intent_row = db.execute(
                        "SELECT payload,parent_id,origin_turn_id,status FROM upsell_intents "
                        "WHERE intent_id=?",
                        (row["intent_id"],),
                    ).fetchone()
                    if (
                        intent_row is None
                        or intent_row["parent_id"] != row["parent_id"]
                        or intent_row["origin_turn_id"] != row["origin_turn_id"]
                        or hashlib.sha256(intent_row["payload"].encode()).hexdigest()
                        != row["intent_fingerprint"]
                    ):
                        raise ValueError("Changed owning tariff enquiry")
                    if intent_row["status"] not in {"queued", "checking", "ready"}:
                        code = "upsell_reply_source_unavailable"
                except (ValueError, ValidationError):
                    code = "upsell_reply_checkpoint_invalid"
            if code is None and self._manager_priority(
                db, row["parent_id"], row["origin_turn_id"], now
            ):
                code = "upsell_reply_interrupted"
            if code:
                self._cancel_pending(db, row, now, code)

    def _recover(self, db: sqlite3.Connection, now: datetime) -> None:
        super()._recover(db, now)
        self._fence_pending(db, now)

    async def claim_reviewed_response(
        self, now: datetime
    ) -> tuple[ReviewedMessage, ParentTouchReviewedTurn] | None:
        if not self._inline_enabled:

            def stop() -> None:
                with self._transaction() as db:
                    rows = db.execute(
                        "SELECT t.* FROM parent_touch_manager_turns m "
                        "JOIN upsell_inline_admissions a ON a.turn_id=m.turn_id "
                        "AND a.parent_id=m.parent_id JOIN parent_chat_turns t "
                        "ON t.id=m.turn_id AND t.parent_id=m.parent_id "
                        "WHERE m.phase IN ('queued','cap_waiting','review_waiting') "
                        "AND t.status='preparing' ORDER BY m.turn_id LIMIT ?",
                        (self._safety_limits.max_pending_jobs + 1,),
                    ).fetchall()
                    if len(rows) > self._safety_limits.max_pending_jobs:
                        raise ParentChatError("upsell_reply_queue_overflow", 503)
                    for row in rows:
                        db.execute(
                            "UPDATE parent_chat_turns SET status='failed',reserved=0,"
                            "error_code='upsell_inline_disabled',error_status=503 WHERE id=?",
                            (row["id"],),
                        )
                        self._on_failed(db, self._turn(row), unknown=False)

            await asyncio.to_thread(stop)
        return await super().claim_reviewed_response(now)

    def _upsell_priority(self, db: sqlite3.Connection, intent: UpsellIntent, now: datetime) -> bool:
        if db.execute(
            "SELECT 1 FROM upsell_inline_replies WHERE intent_id=? AND status='waiting'",
            (str(intent.intent_id),),
        ).fetchone():
            return self._manager_priority(db, intent.parent_id, intent.origin_turn_id, now)
        return super()._upsell_priority(db, intent, now)

    async def claim_upsell(self, now: datetime) -> UpsellWork | None:
        await self._fence(now)
        return await super().claim_upsell(now)

    async def _fence(self, now: datetime) -> None:
        def fence() -> None:
            with self._transaction() as db:
                self._fence_pending(db, self._utc(now))

        await asyncio.to_thread(fence)

    async def upsell_active(self, work: UpsellWork, now: datetime) -> bool:
        await self._fence(now)
        return await super().upsell_active(work, now)

    async def finish_upsell(
        self,
        work: UpsellWork,
        now: datetime,
        *,
        quote: UpsellQuote | None,
        context_at: datetime | None,
        error: str | None = None,
    ) -> None:
        await super().finish_upsell(work, now, quote=quote, context_at=context_at, error=error)
        # The owning source lifecycle can close without a publishable context.
        # Close the waiting parent status too; never refresh or retry that source.
        await self._fence(now)

    def _publish_quote(self, db: sqlite3.Connection, identity: str, now: datetime) -> bool:
        stage = db.execute(
            "SELECT * FROM upsell_inline_replies WHERE intent_id=?", (identity,)
        ).fetchone()
        if stage is None:
            return super()._publish_quote(db, identity, now)
        self._fence_pending(db, now)
        stage = db.execute(
            "SELECT * FROM upsell_inline_replies WHERE intent_id=?", (identity,)
        ).fetchone()
        if stage["status"] != "waiting":
            return True
        row = db.execute("SELECT * FROM upsell_intents WHERE intent_id=?", (identity,)).fetchone()
        if row["status"] != "ready":
            return False
        if row["expires_at"] is None or now >= datetime.fromisoformat(row["expires_at"]):
            self._cancel_pending(db, stage, now, "upsell_reply_expired")
            return True
        if self._upsell_priority(db, UpsellIntent.model_validate_json(row["payload"]), now):
            return False
        turn = db.execute(
            "SELECT * FROM parent_chat_turns WHERE id=? AND parent_id=?",
            (stage["origin_turn_id"], stage["parent_id"]),
        ).fetchone()
        response = self._checked_response(stage, turn)
        intent = UpsellIntent.model_validate_json(row["payload"])
        quote = UpsellQuote.model_validate_json(row["quote"]) if row["quote"] else None
        response = response.model_copy(
            update={
                "answer": upsell_result(quote, intent.language),
                "quota": self._quota(db, intent.parent_id, now),
                "child_context_collected_at": datetime.fromisoformat(row["context_at"])
                if row["context_at"]
                else response.child_context_collected_at,
            }
        )
        db.execute(
            "UPDATE parent_chat_turns SET status='completed',answer=?,result=?,updated_at=? "
            "WHERE id=? AND parent_id=? AND status='preparing' AND reserved=0",
            (
                response.answer,
                response.model_dump_json(),
                now.isoformat(),
                intent.origin_turn_id,
                intent.parent_id,
            ),
        )
        db.execute(
            "UPDATE upsell_inline_replies SET status='completed' WHERE intent_id=?", (identity,)
        )
        db.execute(
            "UPDATE upsell_intents SET status='published',delivered_turn_id=? WHERE intent_id=?",
            (intent.origin_turn_id, identity),
        )
        self._upsell_event(
            db, identity, "inline_quote_published" if quote else "inline_unavailable_published", now
        )
        return True

    async def upsell_currency_control(
        self, request: ParentTouchMessageRequest, now: datetime
    ) -> ParentTouchMessageState | None:
        if (
            request.reply_to_question_id is None
            and request.reply_to_confirmation_id is None
            and request.message.strip().casefold().rstrip(".!?") in _CANCEL
        ):
            result = await asyncio.to_thread(self._cancel_control, request, self._utc(now))
            if result is not None:
                return result
        return await super().upsell_currency_control(request, now)

    def _cancel_control(
        self, request: ParentTouchMessageRequest, now: datetime
    ) -> ParentTouchMessageState | None:
        with self._transaction() as db:
            prior = db.execute(
                "SELECT request_digest FROM parent_chat_turns WHERE parent_id=? AND request_id=?",
                (request.parent_id, str(request.request_id)),
            ).fetchone()
            if prior:
                if prior[0] != self._digest(ParentTouchReviewedTurn(**request.model_dump())):
                    raise ParentChatError("request_id_conflict", 409)
                return None
            self._fence_pending(db, now)
            row = db.execute(
                "SELECT r.*,i.payload AS intent FROM upsell_inline_replies r JOIN upsell_intents i "
                "ON i.intent_id=r.intent_id AND i.parent_id=r.parent_id "
                "WHERE r.parent_id=? AND r.status='waiting'",
                (request.parent_id,),
            ).fetchone()
            if row is None:
                if request.message.strip().casefold().rstrip(".!?") in _EXPLICIT_CANCEL:
                    raise ParentChatError("upsell_reply_not_waiting", 409)
                return None
            recent = db.execute(
                "SELECT COUNT(*),SUM(parent_id=?) FROM assistant_events WHERE "
                "kind='host_message_published' AND at>?",
                (request.parent_id, (now - timedelta(days=1)).isoformat()),
            ).fetchone()
            if (
                recent[0] >= self._reminder_policy.global_commands_per_24h
                or (recent[1] or 0) >= self._reminder_policy.parent_commands_per_24h
            ):
                raise ParentChatError("assistant_command_limit_exceeded", 429)
            self._cancel_pending(db, row, now, "upsell_reply_cancelled")
            language = UpsellIntent.model_validate_json(row["intent"]).language
            return self._host_reply(
                db, request, request.parent_id, request.request_id, _CANCELLED[language], now
            )


class SqliteClosedInlineUpsellStore(SqliteClosedUpsellCurrencyStore):
    _schema_version = 32

    def _supported_versions(self) -> set[int]:
        return {32}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
