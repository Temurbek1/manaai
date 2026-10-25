"""Family v14: local assistant drafts, exact human confirmation and one-shot chat delivery."""

import asyncio
import hashlib
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.application.reminder_dates import reminder_date_answer
from app.mana_ai.application.reminder_text import (
    reminder_ack,
    reminder_language,
    reminder_message,
    reminder_preview,
)
from app.mana_ai.domain.chat import (
    ChatTokens,
    ParentChatRequest,
    ParentChatResponse,
    ResponseLanguage,
    StoredChatTurn,
)
from app.mana_ai.domain.family_agents import (
    FamilyQuestion,
    ParentTouchMessageRequest,
    ParentTouchMessageState,
    ParentTouchResponse,
    ParentTouchReviewedTurn,
)
from app.mana_ai.domain.parent_reminders import (
    ParentReminder,
    ReminderCandidate,
    ReminderConfirmation,
    ReminderDeliveryClaim,
    ReminderPolicy,
    ReminderScope,
)
from app.services.proactive_parent_store import _current_context
from app.services.source_review_safety_store import (
    SqliteClosedSourceReviewSafetyStore,
    SqliteSourceReviewSafetyStore,
)

_TABLES = {
    "assistant_policy",
    "assistant_turns",
    "assistant_reminders",
    "assistant_events",
    "assistant_deliveries",
}
_YES = {
    "да",
    "подтверждаю",
    "да, подтверждаю",
    "ha",
    "tasdiqlayman",
    "ҳа",
    "тасдиқлайман",
    "yes",
    "confirm",
}
_NO = {"нет", "не надо", "отмена", "yo'q", "yo‘q", "yo’q", "bekor", "йўқ", "бекор", "no", "cancel"}
_CANCEL = {
    "отмени последнее напоминание",
    "отменить последнее напоминание",
    "oxirgi eslatmani bekor qil",
    "охирги эслатмани бекор қил",
    "cancel the last reminder",
    "cancel my last reminder",
}
_LIST = {
    "мои напоминания",
    "покажи напоминания",
    "eslatmalarim",
    "эслатмаларим",
    "my reminders",
    "list reminders",
}


def _normalized(text: str) -> str:
    return text.strip().rstrip(".!؟！？").casefold()


class SqliteParentReminderStore(SqliteSourceReviewSafetyStore):
    _schema_version = 14

    def __init__(
        self, path: Path, *, reminder_policy: ReminderPolicy, **family_settings: Any
    ) -> None:
        # Existing native-family settings are forwarded unchanged; only the owning
        # assistant policy is added here. Providers never receive this mapping.
        super().__init__(path, **family_settings)
        self._reminder_policy = ReminderPolicy.model_validate(reminder_policy.model_dump())

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {13}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS assistant_policy (
            id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL,backend_blocked TEXT);
        CREATE TABLE IF NOT EXISTS assistant_turns (
            turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,scope TEXT,scope_hash TEXT,
            reply_confirmation_id TEXT,UNIQUE(parent_id,turn_id));
        CREATE TABLE IF NOT EXISTS assistant_reminders (
            position INTEGER PRIMARY KEY,reminder_id TEXT NOT NULL UNIQUE,parent_id TEXT NOT NULL,
            origin_turn_id INTEGER NOT NULL UNIQUE,digest TEXT NOT NULL,status TEXT NOT NULL,
            due_at TEXT,confirmation_turn_id INTEGER,payload TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS assistant_one_confirmation
            ON assistant_reminders(parent_id)
            WHERE status='draft' AND confirmation_turn_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS assistant_due ON assistant_reminders(status,due_at);
        CREATE TABLE IF NOT EXISTS assistant_events (
            position INTEGER PRIMARY KEY,reminder_id TEXT,parent_id TEXT NOT NULL,
            kind TEXT NOT NULL,at TEXT NOT NULL,turn_id INTEGER);
        CREATE TABLE IF NOT EXISTS assistant_deliveries (
            reminder_id TEXT PRIMARY KEY,claim_id TEXT NOT NULL,started_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,status TEXT NOT NULL,verified_at TEXT);
        """
        )

    def _initialize(self) -> None:
        if self._path.exists():
            with self._connect() as db:
                present = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='assistant_policy'"
                ).fetchone()
                if present:
                    prior = db.execute("SELECT payload FROM assistant_policy WHERE id=1").fetchone()
                    if prior and prior[0] != self._reminder_policy.model_dump_json():
                        raise ValueError(
                            "Reminder policy cannot reset existing actions or ceilings"
                        )
        super()._initialize()
        with self._transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO assistant_policy(id,payload) VALUES(1,?)",
                (self._reminder_policy.model_dump_json(),),
            )

    @staticmethod
    def _reminder(row: sqlite3.Row) -> ParentReminder:
        value = ParentReminder.model_validate_json(row["payload"])
        if (
            str(value.reminder_id) != row["reminder_id"]
            or value.parent_id != row["parent_id"]
            or value.origin_turn_id != row["origin_turn_id"]
            or value.status != row["status"]
            or value.confirmation_turn_id != row["confirmation_turn_id"]
            or value.candidate.digest() != row["digest"]
            or (
                value.candidate.due_at.astimezone(UTC).isoformat()
                if value.candidate.due_at
                else None
            )
            != row["due_at"]
        ):
            raise ParentChatError("assistant_state_invalid", 503)
        return value

    @staticmethod
    def _save(db: sqlite3.Connection, value: ParentReminder) -> None:
        value = ParentReminder.model_validate(value.model_dump())
        db.execute(
            "UPDATE assistant_reminders SET "
            "status=?,confirmation_turn_id=?,payload=? WHERE reminder_id=? AND "
            "parent_id=?",
            (
                value.status,
                value.confirmation_turn_id,
                value.model_dump_json(),
                str(value.reminder_id),
                value.parent_id,
            ),
        )

    @staticmethod
    def _assistant_event(
        db: sqlite3.Connection,
        parent: str,
        identity: UUID | None,
        kind: str,
        now: datetime,
        turn_id: int | None = None,
    ) -> None:
        db.execute(
            "INSERT INTO assistant_events(reminder_id,parent_id,kind,at,turn_id) VALUES(?,?,?,?,?)",
            (str(identity) if identity else None, parent, kind, now.isoformat(), turn_id),
        )

    def _on_admitted(
        self,
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        now: datetime,
    ) -> None:
        super()._on_admitted(connection, request, turn_id, now)
        if isinstance(request, ParentTouchReviewedTurn):
            connection.execute(
                "INSERT INTO assistant_turns(turn_id,parent_id,reply_confirmation_i"
                "d) VALUES(?,?,?)",
                (
                    turn_id,
                    request.parent_id,
                    str(request.reply_to_confirmation_id)
                    if request.reply_to_confirmation_id
                    else None,
                ),
            )

    def _active(
        self, db: sqlite3.Connection, parent_id: str, now: datetime
    ) -> list[ParentReminder]:
        return [
            self._reminder(row)
            for row in db.execute(
                "SELECT * FROM assistant_reminders WHERE parent_id=? AND status IN "
                "('draft','scheduled','checking','ready','unknown') ORDER BY position",
                (parent_id,),
            ).fetchall()
        ]

    def _expire_parent(self, db: sqlite3.Connection, parent_id: str, now: datetime) -> None:
        for value in self._active(db, parent_id, now):
            if value.status == "draft" and value.confirmation_expires_at <= now:
                self._save(
                    db,
                    value.model_copy(
                        update={
                            "status": "expired",
                            "updated_at": now,
                            "error_code": "confirmation_expired",
                        }
                    ),
                )
                self._assistant_event(db, parent_id, value.reminder_id, "draft_expired", now)

    def _pending(
        self, db: sqlite3.Connection, parent_id: str, now: datetime
    ) -> ParentReminder | None:
        # One managed question at a time; urgent safety keeps its existing lane.
        if db.execute(
            "SELECT 1 FROM family_questions WHERE parent_id=? AND status IN "
            "('offered','awaiting_reply','held')",
            (parent_id,),
        ).fetchone():
            return None
        row = db.execute(
            "SELECT * FROM assistant_reminders WHERE parent_id=? AND "
            "status='draft' AND confirmation_turn_id IS NOT NULL",
            (parent_id,),
        ).fetchone()
        if row is None:
            return None
        value = self._reminder(row)
        return value if value.confirmation_expires_at > now else None

    @staticmethod
    def _confirmation(value: ParentReminder) -> ReminderConfirmation:
        return ReminderConfirmation(
            confirmation_id=value.confirmation_id,
            reminder_id=value.reminder_id,
            kind="approval" if value.candidate.due_at else "details",
            candidate=value.candidate,
            expires_at=value.confirmation_expires_at,
        )

    async def reminder_scope(
        self, parent_id: str, turn_id: int, now: datetime
    ) -> ReminderScope | None:
        def capture() -> ReminderScope | None:
            with self._transaction() as db:
                self._expire_parent(db, parent_id, self._utc(now))
                row = db.execute(
                    "SELECT * FROM assistant_turns WHERE parent_id=? AND turn_id=?",
                    (parent_id, turn_id),
                ).fetchone()
                if row is None:
                    return None  # Older admitted turns never acquire the new action protocol.
                if row["scope"] is not None:
                    if hashlib.sha256(row["scope"].encode()).hexdigest() != row["scope_hash"]:
                        raise ParentChatError("assistant_scope_changed", 503)
                    return ReminderScope.model_validate_json(row["scope"])
                contact = _current_context(db, parent_id, self._utc(now))
                pending = self._pending(db, parent_id, self._utc(now))
                scope = ReminderScope(
                    now=self._utc(now),
                    default_timezone=contact.timezone if contact else self._zone.key,
                    timezone_basis="verified_contact"
                    if contact
                    else "application_default_requires_confirmation",
                    active=tuple(self._active(db, parent_id, self._utc(now))),
                    pending=self._confirmation(pending) if pending else None,
                )
                payload = scope.model_dump_json()
                db.execute(
                    "UPDATE assistant_turns SET scope=?,scope_hash=? WHERE turn_id=? "
                    "AND parent_id=?",
                    (payload, hashlib.sha256(payload.encode()).hexdigest(), turn_id, parent_id),
                )
                return scope

        return await asyncio.to_thread(capture)

    def _valid_decision(
        self,
        connection: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        now: datetime,
    ) -> bool:
        if receipt.reminder_candidate is None:
            return super()._valid_decision(connection, turn, receipt, now)
        self._expire_parent(connection, turn.parent_id, now)
        if not super()._valid_decision(
            connection, turn, replace(receipt, reminder_candidate=None), now
        ):
            return False
        row = connection.execute(
            "SELECT * FROM assistant_turns WHERE parent_id=? AND turn_id=?",
            (turn.parent_id, turn.turn_id),
        ).fetchone()
        if row is None or row["scope"] is None or not turn.message or receipt.notice_id is not None:
            return False
        scope = ReminderScope.model_validate_json(row["scope"])
        if hashlib.sha256(row["scope"].encode()).hexdigest() != row["scope_hash"]:
            return False
        candidate = receipt.reminder_candidate
        pending = self._pending(connection, turn.parent_id, now)
        if row["reply_confirmation_id"] is not None and (
            pending is None or str(pending.confirmation_id) != row["reply_confirmation_id"]
        ):
            return False
        if candidate.content not in turn.message and not (
            scope.pending
            and candidate.content == scope.pending.candidate.content
            and row["reply_confirmation_id"] == str(scope.pending.confirmation_id)
        ):
            return False
        if candidate.due_at is not None and not now + timedelta(
            seconds=60
        ) <= candidate.due_at <= now + timedelta(days=self._reminder_policy.maximum_delay_days):
            return False
        active = self._active(connection, turn.parent_id, now)
        total = connection.execute(
            "SELECT COUNT(*) FROM assistant_reminders WHERE status IN "
            "('draft','scheduled','checking','ready','unknown')"
        ).fetchone()[0]
        recent = connection.execute(
            "SELECT COUNT(*),SUM(parent_id=?) FROM assistant_events WHERE "
            "kind='draft_created' AND at>?",
            (turn.parent_id, (now - timedelta(days=1)).isoformat()),
        ).fetchone()
        return (
            len(active) < self._reminder_policy.maximum_active_per_parent
            and total < self._reminder_policy.maximum_active_global
            and recent[0] < self._reminder_policy.global_commands_per_24h
            and (recent[1] or 0) < self._reminder_policy.parent_commands_per_24h
        )

    def _create_draft(
        self,
        db: sqlite3.Connection,
        parent: str,
        turn_id: int,
        candidate: ReminderCandidate,
        language: ResponseLanguage,
        now: datetime,
        *,
        supersede: ParentReminder | None = None,
    ) -> ParentReminder:
        if supersede is not None:
            self._save(
                db,
                supersede.model_copy(
                    update={
                        "status": "cancelled",
                        "updated_at": now,
                        "error_code": "replaced_by_parent",
                    }
                ),
            )
            self._assistant_event(db, parent, supersede.reminder_id, "draft_replaced", now, turn_id)
        value = ParentReminder(
            reminder_id=uuid4(),
            parent_id=parent,
            origin_turn_id=turn_id,
            candidate=candidate,
            status="draft",
            created_at=now,
            updated_at=now,
            language=language,
            confirmation_id=uuid4(),
            confirmation_expires_at=now
            + timedelta(seconds=self._reminder_policy.confirmation_seconds),
        )
        due = candidate.due_at.astimezone(UTC).isoformat() if candidate.due_at else None
        db.execute(
            "INSERT INTO assistant_reminders(reminder_id,parent_id,origin_turn_"
            "id,digest,status,due_at,payload) VALUES(?,?,?,?,'draft',?,?)",
            (
                str(value.reminder_id),
                parent,
                turn_id,
                candidate.digest(),
                due,
                value.model_dump_json(),
            ),
        )
        self._assistant_event(db, parent, value.reminder_id, "draft_created", now, turn_id)
        return value

    def _rewrite_answer(
        self, db: sqlite3.Connection, turn_id: int, parent_id: str, answer: str
    ) -> None:
        row = db.execute(
            "SELECT result FROM parent_chat_turns WHERE id=? AND parent_id=?", (turn_id, parent_id)
        ).fetchone()
        result = ParentChatResponse.model_validate_json(row[0]).model_copy(
            update={"answer": answer}
        )
        db.execute(
            "UPDATE parent_chat_turns SET answer=?,result=? WHERE id=? AND parent_id=?",
            (answer, result.model_dump_json(), turn_id, parent_id),
        )

    def _on_settled(
        self,
        connection: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        super()._on_settled(
            connection, turn, replace(receipt, reminder_candidate=None), valid=valid
        )
        if not valid or receipt.reminder_candidate is None:
            return
        now = datetime.fromisoformat(
            connection.execute(
                "SELECT updated_at FROM parent_chat_turns WHERE id=?", (turn.turn_id,)
            ).fetchone()[0]
        )
        row = connection.execute(
            "SELECT scope,reply_confirmation_id FROM assistant_turns WHERE "
            "turn_id=? AND parent_id=?",
            (turn.turn_id, turn.parent_id),
        ).fetchone()
        pending = self._pending(connection, turn.parent_id, now)
        replace_pending = pending if pending and row[1] == str(pending.confirmation_id) else None
        contact = _current_context(connection, turn.parent_id, now)
        language = reminder_language(
            turn.message,
            replace_pending.language if replace_pending else contact.language if contact else "en",
        )
        value = self._create_draft(
            connection,
            turn.parent_id,
            turn.turn_id,
            receipt.reminder_candidate,
            language,
            now,
            supersede=replace_pending,
        )
        if receipt.question_id is None and self._pending(connection, turn.parent_id, now) is None:
            value = value.model_copy(update={"confirmation_turn_id": turn.turn_id})
            self._save(connection, value)
            answer = reminder_preview(value.candidate, value.language)
        else:
            answer = reminder_ack("queued", value.language)
            if receipt.reminder_question_text:
                answer += "\n\n" + receipt.reminder_question_text
        self._rewrite_answer(connection, turn.turn_id, turn.parent_id, answer)

    def _host_reply(
        self,
        db: sqlite3.Connection,
        request: ParentTouchMessageRequest | None,
        parent: str,
        request_id: UUID,
        answer: str,
        now: datetime,
    ) -> ParentTouchMessageState:
        day, _ = self._period(now)
        public = ParentTouchReviewedTurn(**request.model_dump()) if request else None
        digest = (
            self._digest(public)
            if public
            else hashlib.sha256((str(request_id) + answer).encode()).hexdigest()
        )
        result = ParentChatResponse(
            parent_id=parent,
            request_id=request_id,
            answer=answer,
            model="parent-touch-assistant-template-v1",
            usage=ChatTokens(input_tokens=0, output_tokens=0),
            quota=self._quota(db, parent, now),
            history_turns_included=0,
        )
        cursor = db.execute(
            "INSERT INTO parent_chat_turns(parent_id,request_id,message,request"
            "_digest,day,status,reserved,created_at,updated_at,answer,model,res"
            "ult) VALUES(?,?,?,?,?,'completed',0,?,?,?,'parent-touch-assistant-"
            "template-v1',?)",
            (
                parent,
                str(request_id),
                request.message if request else "",
                digest,
                day,
                now.isoformat(),
                now.isoformat(),
                answer,
                result.model_dump_json(),
            ),
        )
        assert cursor.lastrowid is not None
        turn_id = cursor.lastrowid
        if request:
            db.execute(
                "INSERT INTO family_reviewed_messages(turn_id,parent_id,request_id,"
                "request,phase,claimed_at) VALUES(?,?,?,?,'claimed',?)",
                (
                    turn_id,
                    parent,
                    str(request_id),
                    public.model_dump_json() if public else "",
                    now.isoformat(),
                ),
            )
        self._assistant_event(db, parent, None, "host_message_published", now, turn_id)
        return ParentTouchMessageState(
            parent_id=parent,
            request_id=request_id,
            turn_id=turn_id,
            phase="completed",
            response=ParentTouchResponse(**result.model_dump(), asked_question=None),
        )

    async def assistant_control(
        self, request: ParentTouchMessageRequest, now: datetime
    ) -> ParentTouchMessageState | None:
        return await asyncio.to_thread(self._control, request, self._utc(now))

    def _control(
        self, request: ParentTouchMessageRequest, now: datetime
    ) -> ParentTouchMessageState | None:
        value = _normalized(request.message)
        with self._transaction() as db:
            self._expire_parent(db, request.parent_id, now)
            prior = db.execute(
                "SELECT * FROM parent_chat_turns WHERE parent_id=? AND request_id=?",
                (request.parent_id, str(request.request_id)),
            ).fetchone()
            if prior:
                if prior["request_digest"] != self._digest(
                    ParentTouchReviewedTurn(**request.model_dump())
                ):
                    raise ParentChatError("request_id_conflict", 409)
                return None  # The normal exact-message observer returns its original result.
            pending = self._pending(db, request.parent_id, now)
            matching = (
                pending
                if pending and request.reply_to_confirmation_id == pending.confirmation_id
                else None
            )
            if request.reply_to_confirmation_id is not None and matching is None:
                raise ParentChatError("assistant_confirmation_not_active", 409)
            if not matching and value not in _CANCEL | _LIST:
                return None
            if request.reply_to_question_id is not None:
                raise ParentChatError("assistant_control_question_conflict", 409)
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
            active = self._active(db, request.parent_id, now)
            language = reminder_language(
                request.message,
                (matching.language if matching else active[-1].language if active else "en"),
            )
            if value in _LIST:
                answer = "\n".join(
                    reminder_message(r.candidate, language)
                    + " "
                    + (
                        r.candidate.due_at.astimezone(ZoneInfo(r.candidate.timezone)).isoformat()
                        if r.candidate.due_at
                        else "—"
                    )
                    for r in active
                )
                return self._host_reply(
                    db,
                    request,
                    request.parent_id,
                    request.request_id,
                    answer or reminder_ack("none", language),
                    now,
                )
            if value in _CANCEL:
                target = active[-1] if active else None
                if target:
                    self._save(
                        db,
                        target.model_copy(
                            update={
                                "status": "cancelled",
                                "updated_at": now,
                                "error_code": "parent_cancelled",
                            }
                        ),
                    )
                    self._assistant_event(
                        db, request.parent_id, target.reminder_id, "parent_cancelled", now
                    )
                    db.execute(
                        "UPDATE assistant_deliveries SET status='cancelled' WHERE reminder_id=?",
                        (str(target.reminder_id),),
                    )
                return self._host_reply(
                    db,
                    request,
                    request.parent_id,
                    request.request_id,
                    reminder_ack("cancelled" if target else "none", language),
                    now,
                )
            assert matching is not None
            if value in _NO:
                updated = matching.model_copy(
                    update={
                        "status": "cancelled",
                        "updated_at": now,
                        "error_code": "parent_declined",
                    }
                )
                self._save(db, updated)
                answer = reminder_ack("cancelled", language)
            elif matching.candidate.due_at is not None and value in _YES:
                if matching.candidate.due_at <= now or matching.confirmation_expires_at <= now:
                    self._save(
                        db, matching.model_copy(update={"status": "expired", "updated_at": now})
                    )
                    answer = reminder_ack("expired", language)
                else:
                    response = self._host_reply(
                        db,
                        request,
                        request.parent_id,
                        request.request_id,
                        reminder_ack("scheduled", language),
                        now,
                    )
                    self._save(
                        db,
                        matching.model_copy(
                            update={
                                "status": "scheduled",
                                "updated_at": now,
                                "confirmed_turn_id": response.turn_id,
                            }
                        ),
                    )
                    self._assistant_event(
                        db,
                        request.parent_id,
                        matching.reminder_id,
                        "parent_confirmed",
                        now,
                        response.turn_id,
                    )
                    return response
            elif matching.candidate.due_at is None:
                parsed = reminder_date_answer(
                    request.message, now=now, timezone=matching.candidate.timezone
                )
                if parsed is None or not now + timedelta(seconds=60) <= parsed <= now + timedelta(
                    days=self._reminder_policy.maximum_delay_days
                ):
                    return None  # Free-form conversation still uses the existing neural path.
                response = self._host_reply(
                    db, request, request.parent_id, request.request_id, "Reminder preview", now
                )
                candidate = ReminderCandidate(
                    content=matching.candidate.content,
                    due_at=parsed,
                    timezone=matching.candidate.timezone,
                )
                updated = self._create_draft(
                    db,
                    request.parent_id,
                    response.turn_id,
                    candidate,
                    matching.language,
                    now,
                    supersede=matching,
                )
                updated = updated.model_copy(update={"confirmation_turn_id": response.turn_id})
                self._save(db, updated)
                answer = reminder_preview(candidate, matching.language)
                self._rewrite_answer(db, response.turn_id, request.parent_id, answer)
                return response.model_copy(
                    update={
                        "response": response.response.model_copy(update={"answer": answer})
                        if response.response
                        else None
                    }
                )
            else:
                return None
            return self._host_reply(db, request, request.parent_id, request.request_id, answer, now)

    async def reminder_state(
        self, parent_id: str, now: datetime
    ) -> tuple[tuple[ParentReminder, ...], ReminderConfirmation | None]:
        def read() -> tuple[tuple[ParentReminder, ...], ReminderConfirmation | None]:
            with self._connect() as db:
                values = tuple(self._active(db, parent_id, self._utc(now)))
                pending = self._pending(db, parent_id, self._utc(now))
                return values, self._confirmation(pending) if pending else None

        return await asyncio.to_thread(read)

    def _offer_in_transaction(
        self, connection: sqlite3.Connection, parent_id: str, turn_id: int, now: datetime
    ) -> FamilyQuestion | None:
        self._expire_parent(connection, parent_id, now)
        pending = connection.execute(
            "SELECT 1 FROM assistant_reminders WHERE parent_id=? AND "
            "status='draft' "
            "AND confirmation_turn_id IS NOT NULL",
            (parent_id,),
        ).fetchone()
        urgent = connection.execute(
            "SELECT 1 FROM family_questions WHERE parent_id=? AND status='queued' AND priority=3",
            (parent_id,),
        ).fetchone()
        if pending and not urgent:
            return None
        return super()._offer_in_transaction(connection, parent_id, turn_id, now)

    async def publish_reminder_confirmation(self, now: datetime) -> bool:
        def publish() -> bool:
            with self._transaction() as db:
                rows = db.execute(
                    "SELECT * FROM assistant_reminders WHERE status='draft' "
                    "AND confirmation_turn_id IS NULL ORDER BY position LIMIT 100"
                ).fetchall()
                for row in rows:
                    value = self._reminder(row)
                    self._expire_parent(db, value.parent_id, self._utc(now))
                    if value.confirmation_expires_at <= now or self._pending(
                        db, value.parent_id, now
                    ):
                        continue
                    busy = db.execute(
                        "SELECT 1 FROM parent_chat_turns WHERE parent_id=? "
                        "AND status IN ('preparing','submitted','unknown')",
                        (value.parent_id,),
                    ).fetchone()
                    question = db.execute(
                        "SELECT 1 FROM family_questions WHERE parent_id=? "
                        "AND status IN ('offered','awaiting_reply','held')",
                        (value.parent_id,),
                    ).fetchone()
                    urgent = db.execute(
                        "SELECT 1 FROM family_notices WHERE parent_id=? AND kind='urgent' "
                        "AND status IN ('queued','offered','held')",
                        (value.parent_id,),
                    ).fetchone()
                    if busy or question or urgent:
                        continue
                    response = self._host_reply(
                        db,
                        None,
                        value.parent_id,
                        uuid5(value.reminder_id, "parent-touch-assistant-confirmation-v1"),
                        reminder_preview(value.candidate, value.language),
                        self._utc(now),
                    )
                    self._save(
                        db,
                        value.model_copy(
                            update={
                                "confirmation_turn_id": response.turn_id,
                                "updated_at": self._utc(now),
                            }
                        ),
                    )
                    self._queue_push(
                        db, value.parent_id, response.turn_id, "assistant", self._utc(now)
                    )
                    return True
                return False

        return await asyncio.to_thread(publish)

    async def claim_due_reminder(self, now: datetime) -> ReminderDeliveryClaim | None:
        return await asyncio.to_thread(self._claim_due, self._utc(now))

    def _claim_due(self, now: datetime) -> ReminderDeliveryClaim | None:
        with self._transaction() as db:
            for row in db.execute(
                "SELECT r.* FROM assistant_reminders r JOIN assistant_deliveries d "
                "ON d.reminder_id=r.reminder_id WHERE r.status='checking' AND "
                "d.expires_at<=?",
                (now.isoformat(),),
            ).fetchall():
                old = self._reminder(row)
                self._save(
                    db,
                    old.model_copy(
                        update={
                            "status": "unknown",
                            "updated_at": now,
                            "error_code": "ownership_unknown",
                        }
                    ),
                )
                db.execute(
                    "UPDATE assistant_deliveries SET status='unknown' WHERE reminder_id=?",
                    (str(old.reminder_id),),
                )
            if db.execute("SELECT backend_blocked FROM assistant_policy WHERE id=1").fetchone()[0]:
                return None
            count = db.execute(
                "SELECT COUNT(*) FROM assistant_deliveries WHERE started_at>?",
                ((now - timedelta(days=1)).isoformat(),),
            ).fetchone()[0]
            if count >= self._reminder_policy.deliveries_per_24h:
                return None
            rows = db.execute(
                "SELECT * FROM assistant_reminders WHERE status='scheduled' AND "
                "due_at<=? ORDER BY due_at,position LIMIT 100",
                (now.isoformat(),),
            ).fetchall()
            for row in rows:
                value = self._reminder(row)
                assert value.candidate.due_at is not None
                if (
                    value.candidate.due_at
                    + timedelta(seconds=self._reminder_policy.delivery_grace_seconds)
                    < now
                ):
                    self._save(
                        db,
                        value.model_copy(
                            update={
                                "status": "expired",
                                "updated_at": now,
                                "error_code": "missed_delivery_window",
                            }
                        ),
                    )
                    continue
                contact = _current_context(db, value.parent_id, now)
                if contact and contact.assistant_chat_consent is False:
                    self._save(
                        db,
                        value.model_copy(
                            update={
                                "status": "cancelled",
                                "updated_at": now,
                                "error_code": "assistant_chat_revoked",
                            }
                        ),
                    )
                    continue
                if self._delivery_blocked(db, value.parent_id):
                    continue
                claim, expiry = (
                    uuid4(),
                    now + timedelta(seconds=self._reminder_policy.ownership_lease_seconds),
                )
                value = value.model_copy(update={"status": "checking", "updated_at": now})
                self._save(db, value)
                db.execute(
                    "INSERT INTO assistant_deliveries "
                    "(reminder_id,claim_id,started_at,expires_at,status) "
                    "VALUES(?,?,?,?, 'checking')",
                    (str(value.reminder_id), str(claim), now.isoformat(), expiry.isoformat()),
                )
                self._assistant_event(
                    db, value.parent_id, value.reminder_id, "delivery_claimed", now
                )
                return ReminderDeliveryClaim(
                    reminder=value, claim_id=claim, lease_expires_at=expiry
                )
            return None

    @staticmethod
    def _delivery_blocked(db: sqlite3.Connection, parent: str) -> bool:
        return bool(
            db.execute(
                "SELECT 1 FROM parent_chat_turns WHERE parent_id=? AND status IN "
                "('preparing','submitted','unknown')",
                (parent,),
            ).fetchone()
            or db.execute(
                "SELECT 1 FROM family_questions WHERE parent_id=? AND status IN "
                "('offered','awaiting_reply','held')",
                (parent,),
            ).fetchone()
            or db.execute(
                "SELECT 1 FROM family_notices WHERE parent_id=? AND kind='urgent' "
                "AND status IN ('queued','offered','held')",
                (parent,),
            ).fetchone()
        )

    async def publish_ready_reminder(self, now: datetime) -> bool:
        def publish() -> bool:
            with self._transaction() as db:
                rows = db.execute(
                    "SELECT * FROM assistant_reminders WHERE status='ready' "
                    "ORDER BY position LIMIT 100"
                ).fetchall()
                for row in rows:
                    if self._publish_ready(db, self._reminder(row), self._utc(now)):
                        return True
                return False

        return await asyncio.to_thread(publish)

    def _publish_ready(self, db: sqlite3.Connection, value: ParentReminder, now: datetime) -> bool:
        row = db.execute(
            "SELECT * FROM assistant_deliveries WHERE reminder_id=? AND status='ready'",
            (str(value.reminder_id),),
        ).fetchone()
        if row is None or row["verified_at"] is None:
            raise ParentChatError("assistant_delivery_receipt_invalid", 503)
        context_at = datetime.fromisoformat(row["verified_at"])
        if context_at > now or now >= datetime.fromisoformat(row["expires_at"]):
            self._save(
                db,
                value.model_copy(
                    update={
                        "status": "unknown",
                        "updated_at": now,
                        "error_code": "ownership_expired",
                    }
                ),
            )
            db.execute(
                "UPDATE assistant_deliveries SET status='unknown' WHERE reminder_id=?",
                (str(value.reminder_id),),
            )
            self._assistant_event(db, value.parent_id, value.reminder_id, "ownership_expired", now)
            return True
        contact = _current_context(db, value.parent_id, now)
        if contact and contact.assistant_chat_consent is False:
            self._save(
                db,
                value.model_copy(
                    update={
                        "status": "cancelled",
                        "updated_at": now,
                        "error_code": "assistant_chat_revoked",
                    }
                ),
            )
            db.execute(
                "UPDATE assistant_deliveries SET status='cancelled' WHERE reminder_id=?",
                (str(value.reminder_id),),
            )
            self._assistant_event(
                db, value.parent_id, value.reminder_id, "assistant_chat_revoked", now
            )
            return True
        if self._delivery_blocked(db, value.parent_id):
            return False
        language = contact.language if contact else value.language
        response = self._host_reply(
            db,
            None,
            value.parent_id,
            uuid5(value.reminder_id, "parent-touch-reminder-delivery-v1"),
            reminder_message(value.candidate, language),
            now,
        )
        self._save(
            db,
            value.model_copy(
                update={
                    "status": "delivered",
                    "updated_at": now,
                    "delivered_turn_id": response.turn_id,
                }
            ),
        )
        db.execute(
            "UPDATE assistant_deliveries SET status='recorded' WHERE reminder_id=?",
            (str(value.reminder_id),),
        )
        self._assistant_event(
            db, value.parent_id, value.reminder_id, "chat_delivered", now, response.turn_id
        )
        self._queue_push(db, value.parent_id, response.turn_id, "assistant", now)
        return True

    async def finish_due_reminder(
        self,
        claim: ReminderDeliveryClaim,
        now: datetime,
        *,
        verified_parent: bool,
        context_at: datetime | None = None,
        error: str | None = None,
        unknown: bool = False,
    ) -> None:
        await asyncio.to_thread(
            self._finish_due, claim, self._utc(now), verified_parent, context_at, error, unknown
        )

    def _finish_due(
        self,
        claim: ReminderDeliveryClaim,
        now: datetime,
        verified: bool,
        context_at: datetime | None,
        error: str | None,
        unknown: bool,
    ) -> None:
        with self._transaction() as db:
            row = db.execute(
                "SELECT r.*,d.claim_id,d.expires_at FROM assistant_reminders r "
                "JOIN assistant_deliveries d ON d.reminder_id=r.reminder_id WHERE "
                "r.reminder_id=? AND r.parent_id=?",
                (str(claim.reminder.reminder_id), claim.reminder.parent_id),
            ).fetchone()
            if row is None or row["claim_id"] != str(claim.claim_id):
                raise ParentChatError("assistant_delivery_claim_invalid", 409)
            # A known auth failure closes further ownership reads even if the
            # parent cancelled this reminder while the HTTP request was in flight.
            if error == "backend_auth_denied":
                db.execute(
                    "UPDATE assistant_policy SET backend_blocked='backend_auth_denied' WHERE id=1"
                )
            value = self._reminder(row)
            if value.status != "checking":
                return
            if now >= datetime.fromisoformat(row["expires_at"]):
                verified, unknown, error = False, True, "ownership_unknown"
            if verified and (
                context_at is None or not now - timedelta(seconds=180) <= context_at <= now
            ):
                verified, error = False, "ownership_denied"
            contact = _current_context(db, value.parent_id, now)
            if contact and contact.assistant_chat_consent is False:
                verified, unknown, error = False, False, "assistant_chat_revoked"
            if not verified:
                self._save(
                    db,
                    value.model_copy(
                        update={
                            "status": "unknown" if unknown else "cancelled",
                            "updated_at": now,
                            "error_code": error,
                        }
                    ),
                )
                db.execute(
                    "UPDATE assistant_deliveries SET status=? WHERE reminder_id=?",
                    ("unknown" if unknown else "refused", str(value.reminder_id)),
                )
                self._assistant_event(
                    db, value.parent_id, value.reminder_id, error or "delivery_refused", now
                )
                return
            assert context_at is not None and value.candidate.due_at is not None
            expiry = min(
                context_at + timedelta(seconds=180),
                value.candidate.due_at
                + timedelta(seconds=self._reminder_policy.delivery_grace_seconds),
            )
            value = value.model_copy(update={"status": "ready", "updated_at": now})
            self._save(db, value)
            db.execute(
                "UPDATE assistant_deliveries SET status='ready',verified_at=?,"
                "expires_at=? WHERE reminder_id=?",
                (
                    context_at.astimezone(UTC).isoformat(),
                    expiry.isoformat(),
                    str(value.reminder_id),
                ),
            )
            self._assistant_event(db, value.parent_id, value.reminder_id, "ownership_verified", now)
            self._publish_ready(db, value, now)

    def _push_delivery_ready(
        self, connection: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> bool:
        if row["purpose"] != "assistant":
            return super()._push_delivery_ready(connection, row, now)
        contact = _current_context(connection, row["parent_id"], now)
        if contact is None:
            return False
        hour = now.astimezone(ZoneInfo(contact.timezone)).hour
        start, end = (
            self._conversion_policy.quiet_start_hour,
            self._conversion_policy.quiet_end_hour,
        )
        return not (hour >= start or hour < end if start > end else start <= hour < end)


class SqliteClosedParentReminderStore(SqliteClosedSourceReviewSafetyStore):
    _schema_version = 14

    def _supported_versions(self) -> set[int]:
        return {14}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
