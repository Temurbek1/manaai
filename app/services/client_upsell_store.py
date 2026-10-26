"""Family v16 tariff enquiries; one shared catalog claim, exact quotes and no billing writes."""

import asyncio
import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4, uuid5

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.application.client_upsell import select_tariffs
from app.mana_ai.application.upsell_text import upsell_ack, upsell_language, upsell_result
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.client_upsell import (
    CatalogAdmission,
    CatalogReadClaim,
    ClientUpsellPolicy,
    UpsellIntent,
    UpsellQuote,
    UpsellScope,
    UpsellWork,
)
from app.mana_ai.domain.conversion_catalog import ConversionCatalogObservation
from app.mana_ai.domain.family_agents import (
    ParentTouchMessageRequest,
    ParentTouchMessageState,
    ParentTouchReviewedTurn,
)
from app.services.client_retention_store import (
    SqliteClientRetentionStore,
    SqliteClosedClientRetentionStore,
)
from app.services.proactive_parent_store import _current_context

_TABLES = {
    "upsell_policy",
    "upsell_turns",
    "upsell_intents",
    "upsell_catalog_reads",
    "upsell_catalog",
    "upsell_events",
}


class SqliteClientUpsellStore(SqliteClientRetentionStore):
    _schema_version = 16

    async def upsell_currency_control(
        self, request: ParentTouchMessageRequest, now: datetime
    ) -> ParentTouchMessageState | None:
        return None

    def __init__(
        self, path: Path, *, upsell_policy: ClientUpsellPolicy, catalog_binding: str, **family: Any
    ) -> None:
        if not catalog_binding or len(catalog_binding) > 256:
            raise ValueError("An explicit server catalog identity is required")
        self._catalog_binding = catalog_binding
        self._upsell_policy = ClientUpsellPolicy.model_validate(upsell_policy.model_dump())
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {15}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS upsell_policy(
            id INTEGER PRIMARY KEY,payload TEXT NOT NULL,binding TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS upsell_turns(
            turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,language TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS upsell_intents(
            position INTEGER PRIMARY KEY,intent_id TEXT NOT NULL UNIQUE,parent_id TEXT NOT NULL,
            origin_turn_id INTEGER NOT NULL UNIQUE,status TEXT NOT NULL,payload TEXT NOT NULL,
            claim_id TEXT,expires_at TEXT,quote TEXT,context_at TEXT,delivered_turn_id INTEGER);
        CREATE TABLE IF NOT EXISTS upsell_catalog_reads(
            claim_id TEXT PRIMARY KEY,started_at TEXT NOT NULL,expires_at TEXT NOT NULL,
            status TEXT NOT NULL,reserved_http_attempts INTEGER NOT NULL,payload TEXT,digest TEXT);
        CREATE TABLE IF NOT EXISTS upsell_catalog(
            id INTEGER PRIMARY KEY,collected_at TEXT NOT NULL,
            payload TEXT NOT NULL,digest TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS upsell_events(
            position INTEGER PRIMARY KEY,intent_id TEXT,kind TEXT NOT NULL,at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS upsell_pending ON upsell_intents(status,position);
        """
        )

    def _initialize(self) -> None:
        if self._path.exists():
            with self._connect() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='upsell_policy'").fetchone():
                    prior = db.execute(
                        "SELECT payload,binding FROM upsell_policy WHERE id=1"
                    ).fetchone()
                    if prior and (prior[0], prior[1]) != (
                        self._upsell_policy.model_dump_json(),
                        self._catalog_binding,
                    ):
                        raise ValueError(
                            "Upsell policy/binding cannot reset previous reads or quotes"
                        )
        super()._initialize()
        with self._transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO upsell_policy VALUES(1,?,?)",
                (self._upsell_policy.model_dump_json(), self._catalog_binding),
            )
            prior = db.execute("SELECT payload,binding FROM upsell_policy WHERE id=1").fetchone()
            if tuple(prior) != (self._upsell_policy.model_dump_json(), self._catalog_binding):
                raise ValueError("Upsell policy/binding cannot reset previous reads or quotes")

    @staticmethod
    def _upsell_event(
        db: sqlite3.Connection, identity: str | None, kind: str, now: datetime
    ) -> None:
        db.execute(
            "INSERT INTO upsell_events(intent_id,kind,at) VALUES(?,?,?)",
            (identity, kind, now.isoformat()),
        )

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        super()._on_admitted(db, request, turn_id, now)
        if isinstance(request, ParentTouchReviewedTurn):
            if request.reply_to_question_id is None:
                db.execute(
                    "UPDATE upsell_intents SET status='cancelled' WHERE parent_id=? "
                    "AND status IN ('queued','checking','ready')",
                    (request.parent_id,),
                )
            contact = _current_context(db, request.parent_id, now)
            language = upsell_language(request.message, contact.language if contact else "en")
            db.execute(
                "INSERT INTO upsell_turns VALUES(?,?,?)", (turn_id, request.parent_id, language)
            )

    async def upsell_scope(self, parent_id: str, turn_id: int) -> UpsellScope | None:
        def read() -> UpsellScope | None:
            with self._connect() as db:
                known = db.execute(
                    "SELECT 1 FROM upsell_turns WHERE turn_id=? AND parent_id=?",
                    (turn_id, parent_id),
                ).fetchone()
                return UpsellScope() if known else None

        return await asyncio.to_thread(read)

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        if receipt.upsell_enquiry is not None:
            return False
        if receipt.upsell_choice is None:
            return super()._valid_decision(db, turn, receipt, now)
        if receipt.notice_id is not None or receipt.reminder_candidate is not None:
            return False
        if not db.execute(
            "SELECT 1 FROM upsell_turns WHERE turn_id=? AND parent_id=?",
            (turn.turn_id, turn.parent_id),
        ).fetchone():
            return False
        if not turn.message or receipt.upsell_choice.parent_quote not in turn.message:
            return False
        if not super()._valid_decision(db, turn, replace(receipt, upsell_choice=None), now):
            return False
        row = db.execute(
            "SELECT COUNT(*),SUM(parent_id=?) FROM upsell_intents WHERE status "
            "IN ('queued','checking','ready')",
            (turn.parent_id,),
        ).fetchone()
        return (
            row[0] < self._upsell_policy.maximum_pending_global
            and (row[1] or 0) < self._upsell_policy.maximum_pending_per_parent
        )

    def _on_settled(
        self,
        db: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        super()._on_settled(db, turn, replace(receipt, upsell_choice=None), valid=valid)
        if not valid or receipt.upsell_choice is None:
            return
        now = datetime.fromisoformat(
            db.execute(
                "SELECT updated_at FROM parent_chat_turns WHERE id=?", (turn.turn_id,)
            ).fetchone()[0]
        )
        language = db.execute(
            "SELECT language FROM upsell_turns WHERE turn_id=? AND parent_id=?",
            (turn.turn_id, turn.parent_id),
        ).fetchone()[0]
        intent = UpsellIntent(
            intent_id=uuid4(),
            parent_id=turn.parent_id,
            origin_turn_id=turn.turn_id,
            choice=receipt.upsell_choice,
            language=language,
            created_at=now,
        )
        db.execute(
            "INSERT INTO upsell_intents(intent_id,parent_id,origin_turn_id,stat"
            "us,payload) VALUES(?,?,?,'queued',?)",
            (str(intent.intent_id), turn.parent_id, turn.turn_id, intent.model_dump_json()),
        )
        answer = upsell_ack(language)
        if receipt.upsell_question_text:
            answer += "\n\n" + receipt.upsell_question_text
        self._rewrite_answer(db, turn.turn_id, turn.parent_id, answer)
        self._upsell_event(db, str(intent.intent_id), "enquiry_admitted", now)

    async def claim_upsell(self, now: datetime) -> UpsellWork | None:
        def claim() -> UpsellWork | None:
            current = self._utc(now)
            with self._transaction() as db:
                db.execute(
                    "UPDATE upsell_intents SET status='unknown' WHERE "
                    "status='checking' AND expires_at<=?",
                    (current.isoformat(),),
                )
                for row in db.execute(
                    "SELECT * FROM upsell_intents WHERE status='queued' ORDER BY position LIMIT 100"
                ).fetchall():
                    intent = UpsellIntent.model_validate_json(row["payload"])
                    if self._priority_waiting(db, intent.parent_id, current):
                        continue
                    identity = uuid4()
                    expiry = current + timedelta(seconds=self._upsell_policy.claim_seconds)
                    db.execute(
                        "UPDATE upsell_intents SET "
                        "status='checking',claim_id=?,expires_at=? WHERE intent_id=?",
                        (str(identity), expiry.isoformat(), str(intent.intent_id)),
                    )
                    self._upsell_event(
                        db, str(intent.intent_id), "source_preparation_claimed", current
                    )
                    return UpsellWork(intent=intent, claim_id=identity, expires_at=expiry)
                return None

        return await asyncio.to_thread(claim)

    async def upsell_active(self, work: UpsellWork, now: datetime) -> bool:
        def read() -> bool:
            with self._connect() as db:
                row = db.execute(
                    "SELECT * FROM upsell_intents WHERE intent_id=? AND parent_id=?",
                    (str(work.intent.intent_id), work.intent.parent_id),
                ).fetchone()
                return bool(
                    row
                    and row["status"] == "checking"
                    and row["claim_id"] == str(work.claim_id)
                    and self._utc(now) < datetime.fromisoformat(row["expires_at"])
                )

        return await asyncio.to_thread(read)

    async def catalog_admission(self, now: datetime) -> CatalogAdmission:
        def claim() -> CatalogAdmission:
            current = self._utc(now)
            with self._transaction() as db:
                if db.execute(
                    "SELECT 1 FROM upsell_catalog_reads WHERE status IN ('unknown','blocked')"
                ).fetchone():
                    return CatalogAdmission(refusal="blocked")
                row = db.execute(
                    "SELECT * FROM upsell_catalog_reads WHERE status='reading'"
                ).fetchone()
                if row:
                    if datetime.fromisoformat(row["expires_at"]) <= current:
                        db.execute(
                            "UPDATE upsell_catalog_reads SET status='unknown' WHERE claim_id=?",
                            (row["claim_id"],),
                        )
                        return CatalogAdmission(refusal="blocked")
                    return CatalogAdmission(refusal="busy")
                saved = db.execute("SELECT * FROM upsell_catalog WHERE id=1").fetchone()
                if saved:
                    if hashlib.sha256(saved["payload"].encode()).hexdigest() != saved["digest"]:
                        raise ParentChatError("upsell_catalog_invalid", 503)
                    snapshot = ConversionCatalogObservation.model_validate_json(saved["payload"])
                    if current - timedelta(hours=6) <= snapshot.collected_at <= current:
                        return CatalogAdmission(snapshot=snapshot)
                recent = db.execute(
                    "SELECT started_at FROM upsell_catalog_reads ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
                if recent and current < datetime.fromisoformat(recent[0]) + timedelta(
                    seconds=self._upsell_policy.catalog_cooldown_seconds
                ):
                    return CatalogAdmission(refusal="cooldown")
                count = db.execute(
                    "SELECT COUNT(*) FROM upsell_catalog_reads WHERE started_at>?",
                    ((current - timedelta(days=1)).isoformat(),),
                ).fetchone()[0]
                if count >= self._upsell_policy.catalog_reads_per_24h:
                    return CatalogAdmission(refusal="daily_limit")
                identity = uuid4()
                expiry = current + timedelta(seconds=self._upsell_policy.claim_seconds)
                db.execute(
                    "INSERT INTO upsell_catalog_reads(claim_id,started_at,expires_at,st"
                    "atus,reserved_http_attempts) "
                    "VALUES(?,?,?,'reading',2)",
                    (str(identity), current.isoformat(), expiry.isoformat()),
                )
                return CatalogAdmission(
                    claim=CatalogReadClaim(claim_id=identity, expires_at=expiry)
                )

        return await asyncio.to_thread(claim)

    async def catalog_result(self, claim: CatalogReadClaim) -> ConversionCatalogObservation | None:
        def read() -> ConversionCatalogObservation | None:
            with self._connect() as db:
                row = db.execute(
                    "SELECT payload,digest FROM upsell_catalog_reads WHERE claim_id=? "
                    "AND status='recorded'",
                    (str(claim.claim_id),),
                ).fetchone()
                if row is None:
                    return None
                if not row[0] or hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
                    raise ParentChatError("upsell_catalog_receipt_invalid", 503)
                return ConversionCatalogObservation.model_validate_json(row[0])

        return await asyncio.to_thread(read)

    async def finish_catalog(
        self,
        claim: CatalogReadClaim,
        now: datetime,
        *,
        snapshot: ConversionCatalogObservation | None,
    ) -> None:
        def finish() -> None:
            current = self._utc(now)
            with self._transaction() as db:
                row = db.execute(
                    "SELECT * FROM upsell_catalog_reads WHERE claim_id=?", (str(claim.claim_id),)
                ).fetchone()
                if row is None:
                    raise ParentChatError("upsell_catalog_claim_missing", 409)
                if row["status"] != "reading":
                    return
                if snapshot is None or current >= datetime.fromisoformat(row["expires_at"]):
                    db.execute(
                        "UPDATE upsell_catalog_reads SET status='unknown' WHERE claim_id=?",
                        (str(claim.claim_id),),
                    )
                    return
                checked = ConversionCatalogObservation.model_validate(snapshot.model_dump())
                if (
                    not current - timedelta(seconds=self._upsell_policy.claim_seconds)
                    <= checked.collected_at
                    <= current
                ):
                    raise ParentChatError("upsell_catalog_invalid", 503)
                payload = checked.model_dump_json()
                db.execute(
                    "INSERT OR REPLACE INTO upsell_catalog VALUES(1,?,?,?)",
                    (
                        checked.collected_at.astimezone(UTC).isoformat(),
                        payload,
                        hashlib.sha256(payload.encode()).hexdigest(),
                    ),
                )
                db.execute(
                    "UPDATE upsell_catalog_reads SET "
                    "status='recorded',payload=?,digest=? WHERE claim_id=?",
                    (payload, hashlib.sha256(payload.encode()).hexdigest(), str(claim.claim_id)),
                )

        await asyncio.to_thread(finish)

    async def finish_upsell(
        self,
        work: UpsellWork,
        now: datetime,
        *,
        quote: UpsellQuote | None,
        context_at: datetime | None,
        error: str | None = None,
    ) -> None:
        def finish() -> None:
            current = self._utc(now)
            with self._transaction() as db:
                row = db.execute(
                    "SELECT * FROM upsell_intents WHERE intent_id=?", (str(work.intent.intent_id),)
                ).fetchone()
                if row is None or row["claim_id"] != str(work.claim_id):
                    raise ParentChatError("upsell_claim_invalid", 409)
                if row["status"] != "checking":
                    return
                intent = UpsellIntent.model_validate_json(row["payload"])
                if intent != work.intent:
                    raise ParentChatError("upsell_claim_scope_invalid", 409)
                if quote is not None:
                    saved = db.execute(
                        "SELECT payload,digest FROM upsell_catalog WHERE id=1"
                    ).fetchone()
                    if saved is None or hashlib.sha256(saved[0].encode()).hexdigest() != saved[1]:
                        raise ParentChatError("upsell_catalog_receipt_invalid", 503)
                    catalog = ConversionCatalogObservation.model_validate_json(saved[0])
                    if select_tariffs(intent.choice, catalog, now=current) != quote:
                        raise ParentChatError("upsell_quote_changed", 409)

                if (
                    current >= datetime.fromisoformat(row["expires_at"])
                    or context_at is None
                    or not current - timedelta(seconds=180) <= context_at <= current
                ):
                    db.execute(
                        "UPDATE upsell_intents SET status='unknown' WHERE intent_id=?",
                        (row["intent_id"],),
                    )
                    return
                db.execute(
                    "UPDATE upsell_intents SET "
                    "status='ready',quote=?,context_at=?,expires_at=? WHERE intent_id=?",
                    (
                        quote.model_dump_json() if quote else None,
                        context_at.astimezone(UTC).isoformat(),
                        min(work.expires_at, context_at + timedelta(seconds=180)).isoformat(),
                        row["intent_id"],
                    ),
                )
                self._publish_quote(db, row["intent_id"], current)

        await asyncio.to_thread(finish)

    def _publish_quote(self, db: sqlite3.Connection, identity: str, now: datetime) -> bool:
        row = db.execute("SELECT * FROM upsell_intents WHERE intent_id=?", (identity,)).fetchone()
        if row["status"] != "ready":
            return False
        intent = UpsellIntent.model_validate_json(row["payload"])
        if now >= datetime.fromisoformat(row["expires_at"]):
            db.execute("UPDATE upsell_intents SET status='unknown' WHERE intent_id=?", (identity,))
            return True
        if self._priority_waiting(db, intent.parent_id, now):
            return False
        quote = UpsellQuote.model_validate_json(row["quote"]) if row["quote"] else None
        result = self._host_reply(
            db,
            None,
            intent.parent_id,
            uuid5(intent.intent_id, "price-quote-v1"),
            upsell_result(quote, intent.language),
            now,
        )
        db.execute(
            "UPDATE upsell_intents SET status='published',delivered_turn_id=? WHERE intent_id=?",
            (result.turn_id, identity),
        )
        self._upsell_event(
            db, identity, "quote_published" if quote else "unavailable_published", now
        )
        return True

    async def publish_ready_upsell(self, now: datetime) -> bool:
        def publish() -> bool:
            with self._transaction() as db:
                for row in db.execute(
                    "SELECT intent_id FROM upsell_intents WHERE status='ready' ORDER "
                    "BY position LIMIT 100"
                ).fetchall():
                    if self._publish_quote(db, row[0], self._utc(now)):
                        return True
                return False

        return await asyncio.to_thread(publish)


class SqliteClosedClientUpsellStore(SqliteClosedClientRetentionStore):
    _schema_version = 16

    def _supported_versions(self) -> set[int]:
        return {16}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
