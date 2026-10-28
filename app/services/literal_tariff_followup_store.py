"""Family v40: exact host tariff changes reuse the existing inline source lifecycle."""

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid5

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.literal_tariff_followups import (
    apply_literal_tariff_change,
    literal_tariff_change,
)
from app.mana_ai.application.upsell_text import upsell_ack
from app.mana_ai.domain.chat import ParentChatRequest
from app.mana_ai.domain.client_upsell import UpsellIntent, UpsellWork
from app.mana_ai.domain.family_agents import (
    ParentTouchMessageRequest,
    ParentTouchMessageState,
    ParentTouchReviewedTurn,
)
from app.mana_ai.domain.literal_tariff_followups import LiteralTariffDerivation
from app.mana_ai.domain.tariff_followups import TariffFollowupContext, TariffRequestMessage
from app.services.tariff_followup_store import (
    SqliteClosedTariffFollowupStore,
    SqliteTariffFollowupStore,
)

_TABLES = {"tariff_literal_admissions", "tariff_literal_derivations"}


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


class SqliteLiteralTariffFollowupStore(SqliteTariffFollowupStore):
    _schema_version = 40

    def __init__(
        self, path: Path, *, literal_tariff_followups_enabled: bool = False, **family: Any
    ) -> None:
        self._literal_tariff_followups_enabled = literal_tariff_followups_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {39}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return super()._extra_schema() + (
            "CREATE TABLE IF NOT EXISTS tariff_literal_admissions("
            "turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,"
            "enabled INTEGER NOT NULL CHECK(enabled IN (0,1)));"
            "CREATE TABLE IF NOT EXISTS tariff_literal_derivations("
            "turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,"
            "intent_id TEXT NOT NULL UNIQUE,payload TEXT NOT NULL,fingerprint TEXT NOT NULL);"
        )

    def _literal_open(self) -> bool:
        return bool(
            self._literal_tariff_followups_enabled
            and self._tariff_followups_enabled
            and self._inline_enabled
            and self._currency_enabled
            and self._manager_enabled
            and self._tariff_handoff_enabled
            and self._compact_inputs_enabled
            and self._compact_publication_enabled
            and self._compact_manager_enabled
        )

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        super()._on_admitted(db, request, turn_id, now)
        if db.execute(
            "SELECT 1 FROM manager_tariff_admissions WHERE parent_id=? AND turn_id=?",
            (request.parent_id, turn_id),
        ).fetchone():
            db.execute(
                "INSERT INTO tariff_literal_admissions VALUES(?,?,?)",
                (turn_id, request.parent_id, int(self._literal_open())),
            )

    def _currency_resolved(
        self,
        db: sqlite3.Connection,
        request: ParentTouchMessageRequest,
        result: ParentTouchMessageState,
        intent: UpsellIntent,
        now: datetime,
    ) -> ParentTouchMessageState:
        resolved = super()._currency_resolved(db, request, result, intent, now)
        eligible = self._literal_open() and bool(
            db.execute(
                "SELECT 1 FROM upsell_currency_questions c JOIN tariff_literal_admissions a "
                "ON a.turn_id=c.origin_turn_id AND a.parent_id=c.parent_id "
                "WHERE c.parent_id=? AND c.answer_turn_id=? AND a.enabled=1",
                (request.parent_id, result.turn_id),
            ).fetchone()
        )
        db.execute(
            "INSERT INTO tariff_literal_admissions VALUES(?,?,?)",
            (result.turn_id, request.parent_id, int(eligible)),
        )
        return resolved

    def _derivation(
        self, db: sqlite3.Connection, parent: str, turn: int
    ) -> LiteralTariffDerivation | None:
        row = db.execute(
            "SELECT * FROM tariff_literal_derivations WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        if row is None:
            return None
        try:
            if _hash(row["payload"]) != row["fingerprint"]:
                raise ValueError("Changed literal proof")
            proof = LiteralTariffDerivation.model_validate_json(row["payload"])
            expected = apply_literal_tariff_change(proof.context.origin_intent.choice, proof.change)
            if (
                proof.intent.parent_id != parent
                or proof.intent.origin_turn_id != turn
                or str(proof.intent.intent_id) != row["intent_id"]
                or proof.intent.choice != expected
            ):
                raise ValueError("Changed literal proof binding")
        except (ValueError, TypeError):
            raise ParentChatError("literal_tariff_proof_invalid", 409) from None
        return proof

    def _prior_context(
        self,
        db: sqlite3.Connection,
        request: ParentTouchReviewedTurn,
        turn_id: int,
        now: datetime,
    ) -> TariffFollowupContext | None:
        context = super()._prior_context(db, request, turn_id, now)
        if context is None:
            return None
        proof = self._derivation(db, request.parent_id, context.origin_intent.origin_turn_id)
        if proof is None:
            return context
        predecessors: dict[int, TariffRequestMessage] = {}
        for message in (
            *proof.context.literal_predecessors,
            *proof.context.origin_messages,
            *proof.context.refinement_requests,
        ):
            if message.turn_id in predecessors and predecessors[message.turn_id] != message:
                raise ParentChatError("literal_tariff_proof_invalid", 409)
            predecessors[message.turn_id] = message
        if len(predecessors) > 20:
            raise ParentChatError("literal_tariff_context_limit", 409)
        return TariffFollowupContext.model_validate(
            {
                **context.model_dump(),
                "literal_predecessors": tuple(predecessors[key] for key in sorted(predecessors)),
            }
        )

    async def upsell_currency_control(
        self, request: ParentTouchMessageRequest, now: datetime
    ) -> ParentTouchMessageState | None:
        if (
            request.reply_to_question_id is None
            and request.reply_to_confirmation_id is None
            and request.cancel_tariff_request_id is None
        ):
            controlled = await asyncio.to_thread(self._literal_control, request, self._utc(now))
            if controlled is not None:
                return controlled
        return await super().upsell_currency_control(request, now)

    def _literal_control(
        self, request: ParentTouchMessageRequest, now: datetime
    ) -> ParentTouchMessageState | None:
        change = literal_tariff_change(request.message)
        if change is None:
            return None
        with self._transaction() as db:
            prior = db.execute(
                "SELECT request_digest FROM parent_chat_turns WHERE parent_id=? AND request_id=?",
                (request.parent_id, str(request.request_id)),
            ).fetchone()
            if prior:
                if prior[0] != self._digest(ParentTouchReviewedTurn(**request.model_dump())):
                    raise ParentChatError("request_id_conflict", 409)
                return None
            if not self._literal_open():
                return None
            if self._manager_priority(db, request.parent_id, 0, now):
                return None
            try:
                context = self._prior_context(
                    db, ParentTouchReviewedTurn(**request.model_dump()), 2**63 - 1, now
                )
            except (ValueError, TypeError):
                raise ParentChatError("tariff_followup_origin_invalid", 409) from None
            if (
                context is None
                or not now - timedelta(hours=6) <= context.quote.catalog_collected_at <= now
            ):
                return None
            admitted = db.execute(
                "SELECT enabled FROM tariff_literal_admissions WHERE parent_id=? AND turn_id=?",
                (request.parent_id, context.origin_intent.origin_turn_id),
            ).fetchone()
            if admitted is None or not admitted[0]:
                return None
            try:
                choice = apply_literal_tariff_change(context.origin_intent.choice, change)
            except ValueError:
                return None
            pending = db.execute(
                "SELECT COUNT(*),SUM(parent_id=?) FROM upsell_intents WHERE status "
                "IN ('queued','checking','ready')",
                (request.parent_id,),
            ).fetchone()
            if (
                pending[0] >= self._upsell_policy.maximum_pending_global
                or (pending[1] or 0) >= self._upsell_policy.maximum_pending_per_parent
            ):
                raise ParentChatError("upsell_queue_full", 429)
            recent = db.execute(
                "SELECT COUNT(*),SUM(parent_id=?) FROM assistant_events "
                "WHERE kind='host_message_published' AND at>?",
                (request.parent_id, (now - timedelta(days=1)).isoformat()),
            ).fetchone()
            if (
                recent[0] >= self._reminder_policy.global_commands_per_24h
                or (recent[1] or 0) >= self._reminder_policy.parent_commands_per_24h
            ):
                raise ParentChatError("assistant_command_limit_exceeded", 429)
            language = change.language or context.origin_intent.language
            result = self._host_reply(
                db, request, request.parent_id, request.request_id, upsell_ack(language), now
            )
            context = TariffFollowupContext.model_validate(
                {**context.model_dump(), "turn_id": result.turn_id}
            )
            intent = UpsellIntent(
                intent_id=uuid5(request.request_id, "literal-tariff-refinement-v1"),
                parent_id=request.parent_id,
                origin_turn_id=result.turn_id,
                choice=choice,
                language=language,
                created_at=now,
            )
            proof = LiteralTariffDerivation(context=context, change=change, intent=intent)
            payload = proof.model_dump_json()
            db.execute(
                "INSERT INTO tariff_literal_derivations VALUES(?,?,?,?,?)",
                (result.turn_id, request.parent_id, str(intent.intent_id), payload, _hash(payload)),
            )
            db.execute(
                "INSERT INTO tariff_literal_admissions VALUES(?,?,1)",
                (result.turn_id, request.parent_id),
            )
            db.execute(
                "INSERT INTO upsell_intents(intent_id,parent_id,origin_turn_id,status,payload) "
                "VALUES(?,?,?,'queued',?)",
                (
                    str(intent.intent_id),
                    request.parent_id,
                    result.turn_id,
                    intent.model_dump_json(),
                ),
            )
            self._stage(db, intent)
            self._upsell_event(db, str(intent.intent_id), "literal_refinement_admitted", now)
            return result.model_copy(update={"phase": "responding", "response": None})

    def _fence_literal(self, db: sqlite3.Connection, now: datetime) -> None:
        rows = db.execute(
            "SELECT r.*,i.payload AS intent FROM tariff_literal_derivations d "
            "JOIN upsell_intents i ON i.intent_id=d.intent_id AND i.parent_id=d.parent_id "
            "JOIN upsell_inline_replies r ON r.intent_id=i.intent_id AND r.parent_id=i.parent_id "
            "WHERE i.status IN ('queued','checking','ready') ORDER BY r.origin_turn_id LIMIT ?",
            (self._upsell_policy.maximum_pending_global + 1,),
        ).fetchall()
        if len(rows) > self._upsell_policy.maximum_pending_global:
            raise ParentChatError("literal_tariff_queue_overflow", 503)
        for row in rows:
            code = "literal_tariff_followups_disabled" if not self._literal_open() else None
            if code is None:
                try:
                    proof = self._derivation(db, row["parent_id"], row["origin_turn_id"])
                    if proof is None or proof.intent.model_dump_json() != row["intent"]:
                        raise ParentChatError("literal_tariff_proof_invalid", 409)
                except ParentChatError:
                    code = "literal_tariff_proof_invalid"
            if code:
                self._cancel_pending(db, row, now, code)

    async def _literal_fence(self, now: datetime) -> None:
        def fence() -> None:
            with self._transaction() as db:
                self._fence_literal(db, self._utc(now))

        await asyncio.to_thread(fence)

    async def claim_upsell(self, now: datetime) -> UpsellWork | None:
        await self._literal_fence(now)
        return await super().claim_upsell(now)

    async def upsell_active(self, work: UpsellWork, now: datetime) -> bool:
        await self._literal_fence(now)
        return await super().upsell_active(work, now)

    def _publish_quote(self, db: sqlite3.Connection, identity: str, now: datetime) -> bool:
        self._fence_literal(db, now)
        return super()._publish_quote(db, identity, now)


class SqliteClosedLiteralTariffFollowupStore(SqliteClosedTariffFollowupStore):
    def __init__(self, path: Path, **family: Any) -> None:
        super().__init__(path, **family)
        self._schema_version = 40

    def _supported_versions(self) -> set[int]:
        return {40}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
