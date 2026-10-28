"""Family v39: freeze same-parent quoted terms for new explicit refinement turns."""

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.upsell_text import upsell_result
from app.mana_ai.domain.chat import ParentChatRequest, ParentChatResponse
from app.mana_ai.domain.client_upsell import UpsellChoice, UpsellEnquiry, UpsellIntent, UpsellQuote
from app.mana_ai.domain.family_agents import ParentTouchReviewedTurn
from app.mana_ai.domain.tariff_followups import TariffFollowupContext, TariffRequestMessage
from app.services.compact_parent_publication_store import _publication_profile
from app.services.saved_observation_safety_store import (
    SqliteClosedSavedObservationSafetyStore,
    SqliteSavedObservationSafetyStore,
)

_TABLE = "tariff_followup_captures"


def _fingerprint(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


class SqliteTariffFollowupStore(SqliteSavedObservationSafetyStore):
    _schema_version = 39

    def __init__(
        self, path: Path, *, tariff_followups_enabled: bool = False, **family: Any
    ) -> None:
        self._tariff_followups_enabled = tariff_followups_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {38}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}

    def _extra_schema(self) -> str:
        return super()._extra_schema() + (
            "CREATE TABLE IF NOT EXISTS tariff_followup_captures("
            "turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,"
            "payload TEXT NOT NULL,fingerprint TEXT NOT NULL,manager_binding TEXT NOT NULL);"
            "CREATE INDEX IF NOT EXISTS tariff_followup_parent "
            "ON tariff_followup_captures(parent_id,turn_id);"
            "CREATE INDEX IF NOT EXISTS upsell_parent_delivery "
            "ON upsell_intents(parent_id,delivered_turn_id);"
        )

    @staticmethod
    def _request_message(row: sqlite3.Row) -> TariffRequestMessage:
        return TariffRequestMessage(
            turn_id=row["id"], request_id=row["request_id"], message=row["message"]
        )

    def _origin_messages(
        self, db: sqlite3.Connection, intent: UpsellIntent
    ) -> tuple[TariffRequestMessage, ...]:
        row = db.execute(
            "SELECT id,request_id,message FROM parent_chat_turns WHERE id=? AND parent_id=?",
            (intent.origin_turn_id, intent.parent_id),
        ).fetchone()
        if row is None:
            raise ValueError("Missing original tariff request")
        latest = self._request_message(row)
        if intent.choice.parent_quote in latest.message:
            return (latest,)
        currency = db.execute(
            "SELECT origin_turn_id,terms FROM upsell_currency_questions "
            "WHERE parent_id=? AND answer_turn_id=? AND status='resolved'",
            (intent.parent_id, intent.origin_turn_id),
        ).fetchone()
        if currency is None:
            raise ValueError("Unbound tariff request currency")
        terms = UpsellEnquiry.model_validate_json(currency["terms"])
        resolved = UpsellChoice.model_validate(
            {**terms.model_dump(), "currency": latest.message.strip().upper()}
        )
        original = db.execute(
            "SELECT id,request_id,message FROM parent_chat_turns WHERE id=? AND parent_id=?",
            (currency["origin_turn_id"], intent.parent_id),
        ).fetchone()
        if original is None or resolved != intent.choice:
            raise ValueError("Changed tariff currency binding")
        return (self._request_message(original), latest)

    def _prior_context(
        self,
        db: sqlite3.Connection,
        request: ParentTouchReviewedTurn,
        turn_id: int,
        now: datetime,
    ) -> TariffFollowupContext | None:
        latest = db.execute(
            "SELECT * FROM parent_chat_turns WHERE parent_id=? AND id<? ORDER BY id DESC LIMIT 1",
            (request.parent_id, turn_id),
        ).fetchone()
        if latest is None or latest["status"] != "completed" or not latest["answer"]:
            return None
        if request.reply_to_question_id is not None:
            bound = db.execute(
                "SELECT q.offered_turn_id FROM family_questions q "
                "JOIN parent_clarification_questions c ON c.question_id=q.question_id "
                "AND c.parent_id=q.parent_id AND c.turn_id=q.offered_turn_id "
                "WHERE q.parent_id=? AND q.question_id=? AND q.answer_turn_id=? "
                "AND q.status='answered'",
                (request.parent_id, str(request.reply_to_question_id), turn_id),
            ).fetchone()
            if bound is None or bound[0] != latest["id"]:
                return None
            previous = self._followup(db, request.parent_id, latest["id"])
            if previous is None:
                return None
            if len(previous.refinement_requests) == 2:
                raise ParentChatError("tariff_followup_context_limit", 409)
            return TariffFollowupContext.model_validate(
                {
                    **previous.model_dump(),
                    "turn_id": turn_id,
                    "captured_at": now,
                    "refinement_requests": (
                        *previous.refinement_requests,
                        self._request_message(latest),
                    ),
                }
            )
        row = db.execute(
            "SELECT payload,quote FROM upsell_intents WHERE parent_id=? "
            "AND status='published' AND delivered_turn_id=? LIMIT 1",
            (request.parent_id, latest["id"]),
        ).fetchone()
        if row is None or row["quote"] is None or latest["result"] is None:
            return None
        intent = UpsellIntent.model_validate_json(row["payload"])
        quote = UpsellQuote.model_validate_json(row["quote"])
        response = ParentChatResponse.model_validate_json(latest["result"])
        if (
            response.parent_id != request.parent_id
            or str(response.request_id) != latest["request_id"]
            or response.answer != latest["answer"]
            or response.answer != upsell_result(quote, intent.language)
            or quote.objective != intent.choice.objective
        ):
            raise ParentChatError("tariff_followup_origin_invalid", 409)
        return TariffFollowupContext(
            parent_id=request.parent_id,
            turn_id=turn_id,
            captured_at=now,
            origin_intent=intent,
            origin_messages=self._origin_messages(db, intent),
            quote=quote,
            delivered_turn_id=latest["id"],
            delivered_request_id=latest["request_id"],
            delivered_answer=latest["answer"],
            delivered_at=datetime.fromisoformat(latest["updated_at"]),
        )

    def _new_publication_protocol(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> Literal[1, 2, 3, 4, 5, 6]:
        original = super()._new_publication_protocol(db, request, turn_id, now)
        if (
            not self._tariff_followups_enabled
            or original != 5
            or not isinstance(request, ParentTouchReviewedTurn)
        ):
            return original
        try:
            context = self._prior_context(db, request, turn_id, now)
        except (ValueError, TypeError):
            raise ParentChatError("tariff_followup_origin_invalid", 409) from None
        if (
            context is None
            or not now - timedelta(hours=6) <= context.quote.catalog_collected_at <= now
        ):
            return original
        binding = db.execute(
            "SELECT binding FROM parent_touch_manager_turns WHERE parent_id=? AND turn_id=?",
            (request.parent_id, turn_id),
        ).fetchone()[0]
        payload = context.model_dump_json()
        db.execute(
            "INSERT INTO tariff_followup_captures VALUES(?,?,?,?,?)",
            (turn_id, request.parent_id, payload, _fingerprint(payload), binding),
        )
        return 6

    def _followup(
        self, db: sqlite3.Connection, parent: str, turn: int
    ) -> TariffFollowupContext | None:
        row = db.execute(
            "SELECT * FROM tariff_followup_captures WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        if row is None:
            return None
        if not self._tariff_followups_enabled:
            raise ParentChatError("tariff_followups_disabled", 503)
        manager = db.execute(
            "SELECT binding FROM parent_touch_manager_turns WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        if manager is None or row["manager_binding"] != manager[0]:
            raise ParentChatError("tariff_followup_capture_invalid", 409)
        if _fingerprint(row["payload"]) != row["fingerprint"]:
            raise ParentChatError("tariff_followup_capture_invalid", 409)
        try:
            context = TariffFollowupContext.model_validate_json(row["payload"])
        except (ValueError, TypeError):
            raise ParentChatError("tariff_followup_capture_invalid", 409) from None
        if context.parent_id != parent or context.turn_id != turn:
            raise ParentChatError("tariff_followup_capture_invalid", 409)
        return context

    def _publication(
        self, db: sqlite3.Connection, parent: str, turn: int | None
    ) -> Literal[1, 2, 3, 4, 5, 6] | None:
        version = super()._publication(db, parent, turn)
        has_capture = db.execute(
            "SELECT 1 FROM tariff_followup_captures WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        if bool(has_capture) != (version == 6):
            raise ParentChatError("tariff_followup_capture_invalid", 409)
        if version == 6 and (turn is None or self._followup(db, parent, turn) is None):
            raise ParentChatError("tariff_followup_capture_invalid", 409)
        return version

    def _captured_protocol(self, payload: str) -> int:
        if _publication_profile(payload)[1] == 6 and not self._tariff_followups_enabled:
            raise ParentChatError("tariff_followups_disabled", 503)
        return super()._captured_protocol(payload)

    async def tariff_followup_context(
        self, parent_id: str, turn_id: int
    ) -> TariffFollowupContext | None:
        def read() -> TariffFollowupContext | None:
            with self._connect() as db:
                version = self._publication(db, parent_id, turn_id)
                return self._followup(db, parent_id, turn_id) if version == 6 else None

        return await asyncio.to_thread(read)


class SqliteClosedTariffFollowupStore(SqliteClosedSavedObservationSafetyStore):
    def __init__(self, path: Path, **family: Any) -> None:
        super().__init__(path, **family)
        self._schema_version = 39

    def _supported_versions(self) -> set[int]:
        return {39}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}
