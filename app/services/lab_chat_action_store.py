"""Lab-only family v24: atomic same-chat cards and one-shot simulated actions."""

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4, uuid5

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ParentChatRequest
from app.mana_ai.domain.chat_actions import (
    ChatActionCard,
    ChatActionClaim,
    ChatActionClick,
    ChatActionCreate,
    ChatActionPage,
    ChatActionResult,
)
from app.mana_ai.domain.family_agents import FamilyQuestion
from app.services.location_safety_store import SqliteLocationSafetyStore


class SimulatedChatActionExecutor:
    """No provider, network, tariff, notification or model access."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, claim: ChatActionClaim) -> ChatActionResult:
        self.calls += 1
        return ChatActionResult(execution_id=claim.execution_id)


class SqliteLabChatActionStore(SqliteLocationSafetyStore):
    _schema_version = 24

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {23}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {"lab_action_cards", "lab_action_events"}

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS lab_action_cards(
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,card_id TEXT NOT NULL UNIQUE,
          parent_id TEXT NOT NULL,request_id TEXT NOT NULL,definition TEXT NOT NULL,
          definition_hash TEXT NOT NULL,turn_id INTEGER NOT NULL UNIQUE,
          created_at TEXT NOT NULL,expires_at TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('pending','executing','completed',
             'cancelled','unknown')),
          selected_button TEXT,click_id TEXT,execution_id TEXT,result TEXT,
          UNIQUE(parent_id,request_id));
        CREATE INDEX IF NOT EXISTS lab_action_parent ON lab_action_cards(parent_id,sequence);
        CREATE TABLE IF NOT EXISTS lab_action_events(
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,card_id TEXT NOT NULL,
          kind TEXT NOT NULL,occurred_at TEXT NOT NULL);
        """
        )

    def _card(self, row: sqlite3.Row, now: datetime) -> ChatActionCard:
        definition = ChatActionCreate.model_validate_json(row["definition"])
        status = row["status"]
        if status == "pending" and datetime.fromisoformat(row["expires_at"]) <= now:
            status = "expired"
        return ChatActionCard(
            sequence=row["sequence"],
            card_id=row["card_id"],
            parent_id=row["parent_id"],
            request_id=row["request_id"],
            turn_id=row["turn_id"],
            action_type=definition.action_type,
            title=definition.title,
            text=definition.text,
            buttons=definition.buttons,
            definition_hash=row["definition_hash"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            status=status,
            selected_button=row["selected_button"],
            result=ChatActionResult.model_validate_json(row["result"]) if row["result"] else None,
        )

    def _action_event(self, db: sqlite3.Connection, card: UUID, kind: str, now: datetime) -> None:
        db.execute(
            "INSERT INTO lab_action_events(card_id,kind,occurred_at) VALUES(?,?,?)",
            (str(card), kind, now.isoformat()),
        )

    def _action_pending(self, db: sqlite3.Connection, parent: str, now: datetime) -> bool:
        return bool(
            db.execute(
                "SELECT 1 FROM lab_action_cards WHERE parent_id=? AND "
                "((status='pending' AND expires_at>?) OR status IN ('executing','unknown'))",
                (parent, now.isoformat()),
            ).fetchone()
        )

    def _priority_waiting(
        self, db: sqlite3.Connection, parent: str, now: datetime, turn_id: int = 0
    ) -> bool:
        return self._action_pending(db, parent, now) or super()._priority_waiting(
            db, parent, now, turn_id
        )

    def _card_priority(self, db: sqlite3.Connection, parent: str, now: datetime) -> bool:
        return super()._priority_waiting(db, parent, now) or bool(
            db.execute(
                "SELECT 1 FROM child_safety_jobs WHERE parent_id=? AND status IN "
                "('queued','preparing','submitted','unknown','metered')",
                (parent,),
            ).fetchone()
        )

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        pending = db.execute(
            "SELECT 1 FROM lab_action_cards WHERE parent_id=? AND status='pending' "
            "AND expires_at>?",
            (request.parent_id, now.isoformat()),
        ).fetchone()
        urgent_reply = db.execute(
            "SELECT 1 FROM family_questions WHERE parent_id=? AND question_id=? "
            "AND priority=3 AND status IN ('offered','awaiting_reply')",
            (request.parent_id, str(getattr(request, "reply_to_question_id", None))),
        ).fetchone()
        if pending and not urgent_reply:
            raise ParentChatError("action_card_requires_button", 409)
        super()._on_admitted(db, request, turn_id, now)

    def _offer_in_transaction(
        self, connection: sqlite3.Connection, parent_id: str, turn_id: int, now: datetime
    ) -> FamilyQuestion | None:
        if self._action_pending(connection, parent_id, now):
            urgent = connection.execute(
                "SELECT 1 FROM family_questions WHERE parent_id=? AND status='queued' "
                "AND priority=3",
                (parent_id,),
            ).fetchone()
            if not urgent:
                return None
        return super()._offer_in_transaction(connection, parent_id, turn_id, now)

    async def create_card(self, request: ChatActionCreate, now: datetime) -> ChatActionCard:
        return await asyncio.to_thread(self._create_card, request, self._utc(now))

    def _create_card(self, request: ChatActionCreate, now: datetime) -> ChatActionCard:
        definition = request.model_dump_json()
        digest = hashlib.sha256(definition.encode()).hexdigest()
        with self._transaction() as db:
            prior = db.execute(
                "SELECT * FROM lab_action_cards WHERE parent_id=? AND request_id=?",
                (request.parent_id, str(request.request_id)),
            ).fetchone()
            if prior:
                if prior["definition_hash"] != digest:
                    raise ParentChatError("action_card_idempotency_conflict", 409)
                return self._card(prior, now)
            if self._action_pending(db, request.parent_id, now) or self._card_priority(
                db, request.parent_id, now
            ):
                raise ParentChatError("action_card_chat_busy", 409)
            count = db.execute(
                "SELECT count(*) FROM lab_action_cards WHERE parent_id=? AND created_at>=?",
                (request.parent_id, (now - timedelta(days=1)).isoformat()),
            ).fetchone()[0]
            if (
                count >= 20
                or db.execute("SELECT count(*) FROM lab_action_cards").fetchone()[0] >= 500
            ):
                raise ParentChatError("action_card_capacity_exceeded", 429)
            card = uuid4()
            message = self._host_reply(
                db,
                None,
                request.parent_id,
                uuid5(card, "action-card"),
                request.title + "\n\n" + request.text,
                now,
            )
            db.execute(
                "INSERT INTO lab_action_cards(card_id,parent_id,request_id,definition,"
                "definition_hash,turn_id,created_at,expires_at,status) "
                "VALUES(?,?,?,?,?,?,?,?,'pending')",
                (
                    str(card),
                    request.parent_id,
                    str(request.request_id),
                    definition,
                    digest,
                    message.turn_id,
                    now.isoformat(),
                    (now + timedelta(seconds=request.expires_in_seconds)).isoformat(),
                ),
            )
            self._action_event(db, card, "created", now)
            return self._read_card(db, request.parent_id, card, now)

    def _read_card(
        self, db: sqlite3.Connection, parent: str, card: UUID, now: datetime
    ) -> ChatActionCard:
        row = db.execute(
            "SELECT * FROM lab_action_cards WHERE parent_id=? AND card_id=?",
            (parent, str(card)),
        ).fetchone()
        if row is None:
            raise ParentChatError("action_card_not_found", 404)
        return self._card(row, now)

    async def action_card(self, parent: str, card: UUID, now: datetime) -> ChatActionCard:
        def read() -> ChatActionCard:
            with self._connect() as db:
                return self._read_card(db, parent, card, self._utc(now))

        return await asyncio.to_thread(read)

    async def action_cards(
        self, parent: str, after: int, limit: int, now: datetime
    ) -> ChatActionPage:
        if not after >= 0 or not 1 <= limit <= 100:
            raise ParentChatError("action_card_invalid_page", 422)

        def read() -> ChatActionPage:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT * FROM lab_action_cards WHERE parent_id=? AND sequence>? "
                    "ORDER BY sequence LIMIT ?",
                    (parent, after, limit + 1),
                ).fetchall()
                cards = tuple(self._card(row, self._utc(now)) for row in rows[:limit])
                return ChatActionPage(
                    parent_id=parent,
                    cards=cards,
                    next_after=cards[-1].sequence if len(rows) > limit else None,
                )

        return await asyncio.to_thread(read)

    async def claim_card(
        self, card: UUID, click: ChatActionClick, now: datetime
    ) -> ChatActionCard | ChatActionClaim:
        return await asyncio.to_thread(self._claim_card, card, click, self._utc(now))

    def _claim_card(
        self, card: UUID, click: ChatActionClick, now: datetime
    ) -> ChatActionCard | ChatActionClaim:
        with self._transaction() as db:
            value = self._read_card(db, click.parent_id, card, now)
            if value.definition_hash != click.definition_hash:
                raise ParentChatError("action_card_definition_changed", 409)
            row = db.execute(
                "SELECT click_id FROM lab_action_cards WHERE card_id=?", (str(card),)
            ).fetchone()
            if value.selected_button is not None:
                if value.selected_button != click.button_id:
                    raise ParentChatError("action_card_already_decided", 409)
                return value  # Even a new nonce can only observe the committed choice.
            if row[0] is not None or value.status != "pending":
                raise ParentChatError("action_card_not_pending", 409)
            if click.button_id == "confirm" and self._card_priority(db, click.parent_id, now):
                raise ParentChatError("action_card_chat_busy", 409)
            execution = uuid4() if click.button_id == "confirm" else None
            status: Literal["executing", "cancelled"] = "executing" if execution else "cancelled"
            db.execute(
                "UPDATE lab_action_cards SET status=?,selected_button=?,click_id=?,execution_id=? "
                "WHERE card_id=?",
                (
                    status,
                    click.button_id,
                    str(click.request_id),
                    str(execution) if execution else None,
                    str(card),
                ),
            )
            self._action_event(db, card, status, now)
            value = self._read_card(db, click.parent_id, card, now)
            return ChatActionClaim(card=value, execution_id=execution) if execution else value

    async def finish_card(
        self, claim: ChatActionClaim, result: ChatActionResult | None, now: datetime
    ) -> ChatActionCard:
        def finish() -> ChatActionCard:
            with self._transaction() as db:
                row = db.execute(
                    "SELECT status,execution_id FROM lab_action_cards "
                    "WHERE card_id=? AND parent_id=?",
                    (str(claim.card.card_id), claim.card.parent_id),
                ).fetchone()
                if row is None or row[1] != str(claim.execution_id):
                    raise ParentChatError("action_card_claim_mismatch", 409)
                if result is not None and result.execution_id != claim.execution_id:
                    raise ParentChatError("action_card_receipt_mismatch", 409)
                if row[0] == "executing":
                    status = "completed" if result else "unknown"
                    db.execute(
                        "UPDATE lab_action_cards SET status=?,result=? WHERE card_id=?",
                        (
                            status,
                            result.model_dump_json() if result else None,
                            str(claim.card.card_id),
                        ),
                    )
                    self._action_event(db, claim.card.card_id, status, self._utc(now))
                return self._read_card(db, claim.card.parent_id, claim.card.card_id, self._utc(now))

        return await asyncio.to_thread(finish)
