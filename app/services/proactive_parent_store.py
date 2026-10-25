"""Private v8 proactive delivery and single-attempt notification outbox.

Only an already persisted assistant turn may queue a privacy-safe push. Network
dispatch is outside SQLite, after a durable, non-reclaimable claim. Neither reads,
restarts, consent renewals nor a lost provider receipt may submit that claim again.
"""

import asyncio
import hashlib
import sqlite3
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.domain.chat import ResponseLanguage, StoredChatTurn
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.conversion import (
    ConversionOffer,
    ConversionPolicy,
    ConversionProposal,
    ConversionSnapshot,
)
from app.mana_ai.domain.family_agents import ParentTouchDeliveryRequest
from app.mana_ai.domain.proactive_parent import (
    ParentContactContext,
    ParentPushClaim,
    ParentPushOutcome,
    ParentPushPage,
    ParentPushPurpose,
    ParentPushState,
)
from app.services.conversion_store import SqliteClosedConversionStore, SqliteConversionStore

PROACTIVE_TABLES = {
    "parent_contact_contexts",
    "parent_contact_context_events",
    "parent_contact_turns",
    "parent_push_outbox",
}


def _digest(context: ParentContactContext) -> str:
    return hashlib.sha256(context.model_dump_json().encode()).hexdigest()


def _current_context(
    connection: sqlite3.Connection, parent_id: str, now: datetime
) -> ParentContactContext | None:
    row = connection.execute(
        "SELECT * FROM parent_contact_contexts WHERE parent_id=?", (parent_id,)
    ).fetchone()
    if row is None:
        return None
    context = ParentContactContext.model_validate_json(row["payload"])
    if (
        context.parent_id != parent_id
        or context.revision != row["revision"]
        or _digest(context) != row["digest"]
    ):
        raise ParentChatError("parent_contact_context_changed", 503)
    if context.observed_at > now + timedelta(seconds=120) or context.valid_until <= now:
        return None
    return context


def _push(row: sqlite3.Row) -> ParentPushState:
    return ParentPushState(
        push_id=row["push_id"],
        parent_id=row["parent_id"],
        turn_id=row["turn_id"],
        purpose=row["purpose"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        queued_devices=row["queued_devices"],
        error_code=row["error_code"],
    )


def _notification(language: ResponseLanguage) -> tuple[str, str]:
    match language:
        case "ru":
            description = "В чате MANA появилось новое сообщение. Откройте приложение."
        case "uz-Latn":
            description = "MANA chatida yangi xabar bor. Ilovani oching."
        case "uz-Cyrl":
            description = "MANA чатида янги хабар бор. Иловани очинг."
        case "en":
            description = "You have a new message in MANA. Open the app."
    return "MANA", description


class _ProactiveReadAccess:
    def _connect(self) -> AbstractContextManager[sqlite3.Connection]:
        raise NotImplementedError

    @staticmethod
    def _utc(now: datetime) -> datetime:
        raise NotImplementedError

    async def contact_context(self, parent_id: str, now: datetime) -> ParentContactContext | None:
        def read() -> ParentContactContext | None:
            with self._connect() as connection:
                return _current_context(connection, parent_id, self._utc(now))

        return await asyncio.to_thread(read)

    async def language_hint(self, parent_id: str, turn_id: int) -> ResponseLanguage | None:
        def read() -> ResponseLanguage | None:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload,digest FROM parent_contact_turns "
                    "WHERE parent_id=? AND turn_id=?",
                    (parent_id, turn_id),
                ).fetchone()
                if row is None:
                    return None
                context = ParentContactContext.model_validate_json(row["payload"])
                if context.parent_id != parent_id or _digest(context) != row["digest"]:
                    raise ParentChatError("parent_contact_turn_context_changed", 503)
                return context.language

        return await asyncio.to_thread(read)

    async def push(self, parent_id: str, push_id: UUID) -> ParentPushState:
        def read() -> ParentPushState:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM parent_push_outbox WHERE parent_id=? AND push_id=?",
                    (parent_id, str(push_id)),
                ).fetchone()
                if row is None:
                    raise ParentChatError("parent_push_not_found", 404)
                return _push(row)

        return await asyncio.to_thread(read)

    async def pushes(
        self, parent_id: str, *, after: int | None = None, limit: int = 20
    ) -> ParentPushPage:
        if not 1 <= limit <= 100 or after is not None and after < 0:
            raise ParentChatError("invalid_parent_push_cursor", 422)

        def read() -> ParentPushPage:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM parent_push_outbox WHERE parent_id=? AND position>? "
                    "ORDER BY position LIMIT ?",
                    (parent_id, after or 0, limit + 1),
                ).fetchall()
                selected = rows[:limit]
                return ParentPushPage(
                    parent_id=parent_id,
                    pushes=[_push(row) for row in selected],
                    next_after=selected[-1]["position"] if len(rows) > limit else None,
                )

        return await asyncio.to_thread(read)


class SqliteProactiveParentStore(SqliteConversionStore, _ProactiveReadAccess):
    _schema_version = 8

    def __init__(
        self,
        path: Path,
        conversion_policy: ConversionPolicy,
        conversion_offers: tuple[ConversionOffer, ...],
        limits: ChildSafetyLimits,
        daily_limit: int,
        timezone: str,
        max_attempts: int = 20,
        question_limit: int = 100,
        push_queue_limit: int = 1000,
        push_max_age_seconds: int = 3600,
        push_daily_attempt_limit: int = 100,
        proactive_enabled: bool = True,
        push_enabled: bool = True,
    ) -> None:
        super().__init__(
            path,
            conversion_policy=conversion_policy,
            conversion_offers=conversion_offers,
            limits=limits,
            daily_limit=daily_limit,
            timezone=timezone,
            max_attempts=max_attempts,
            question_limit=question_limit,
        )
        if not 1 <= push_queue_limit <= 100_000:
            raise ValueError("Push queue limit must be between one and 100000")
        if not 60 <= push_max_age_seconds <= 86400:
            raise ValueError("Push observation validity must be between one minute and one day")
        if not 1 <= push_daily_attempt_limit <= 100_000:
            raise ValueError("Push daily attempt limit must be between one and 100000")
        self._push_queue_limit = push_queue_limit
        self._push_max_age_seconds = push_max_age_seconds
        self._push_daily_attempt_limit = push_daily_attempt_limit
        self._proactive_enabled = proactive_enabled
        self._push_enabled = push_enabled

    async def language_hint(self, parent_id: str, turn_id: int) -> ResponseLanguage | None:
        return await _ProactiveReadAccess.language_hint(self, parent_id, turn_id)

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | PROACTIVE_TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
            CREATE TABLE IF NOT EXISTS parent_contact_contexts (
                parent_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL,
                digest TEXT NOT NULL,
                payload TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                valid_until TEXT NOT NULL,
                safety_chat_consent INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS parent_contact_context_events (
                parent_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                digest TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(parent_id,event_id)
            );
            CREATE TABLE IF NOT EXISTS parent_contact_turns (
                parent_id TEXT NOT NULL,
                turn_id INTEGER NOT NULL UNIQUE,
                digest TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY(parent_id,turn_id)
            );
            CREATE TABLE IF NOT EXISTS parent_push_outbox (
                position INTEGER PRIMARY KEY AUTOINCREMENT,
                push_id TEXT NOT NULL UNIQUE,
                parent_id TEXT NOT NULL,
                turn_id INTEGER NOT NULL UNIQUE,
                purpose TEXT NOT NULL,
                status TEXT NOT NULL,
                contact_digest TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                scan_order INTEGER NOT NULL,
                claim_id TEXT UNIQUE,
                claimed_at TEXT,
                queued_devices INTEGER,
                error_code TEXT,
                outcome TEXT
            );
            CREATE INDEX IF NOT EXISTS parent_push_dispatch
                ON parent_push_outbox(status,scan_order,position);
            CREATE INDEX IF NOT EXISTS parent_push_history
                ON parent_push_outbox(parent_id,position);
            CREATE INDEX IF NOT EXISTS parent_push_attempts
                ON parent_push_outbox(claimed_at);
            CREATE INDEX IF NOT EXISTS parent_push_scan_order
                ON parent_push_outbox(scan_order);
        """
        )

    async def ingest_contact_context(
        self, context: ParentContactContext, now: datetime
    ) -> ParentContactContext:
        def write() -> ParentContactContext:
            current = self._utc(now)
            digest = _digest(context)
            with self._transaction() as connection:
                previous_event = connection.execute(
                    "SELECT digest,payload FROM parent_contact_context_events "
                    "WHERE parent_id=? AND event_id=?",
                    (context.parent_id, str(context.event_id)),
                ).fetchone()
                if previous_event is not None:
                    if previous_event["digest"] != digest:
                        raise ParentChatError("parent_contact_event_conflict", 409)
                    return ParentContactContext.model_validate_json(previous_event["payload"])
                if context.observed_at > current + timedelta(seconds=120):
                    raise ParentChatError("parent_contact_context_in_future", 422)
                if context.valid_until <= current:
                    raise ParentChatError("parent_contact_context_expired", 422)
                previous = connection.execute(
                    "SELECT revision,observed_at FROM parent_contact_contexts WHERE parent_id=?",
                    (context.parent_id,),
                ).fetchone()
                if previous is not None and (
                    context.revision <= previous["revision"]
                    or self._utc(context.observed_at).isoformat() < previous["observed_at"]
                ):
                    raise ParentChatError("parent_contact_context_out_of_order", 409)
                connection.execute(
                    "INSERT INTO parent_contact_contexts(parent_id,revision,digest,payload,"
                    "observed_at,valid_until,safety_chat_consent) VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(parent_id) DO UPDATE SET revision=excluded.revision,"
                    "digest=excluded.digest,payload=excluded.payload,observed_at=excluded.observed_at,"
                    "valid_until=excluded.valid_until,safety_chat_consent=excluded.safety_chat_consent",
                    (
                        context.parent_id,
                        context.revision,
                        digest,
                        context.model_dump_json(),
                        self._utc(context.observed_at).isoformat(),
                        self._utc(context.valid_until).isoformat(),
                        context.safety_chat_consent,
                    ),
                )
                connection.execute(
                    "INSERT INTO parent_contact_context_events VALUES(?,?,?,?)",
                    (context.parent_id, str(context.event_id), digest, context.model_dump_json()),
                )
                return context

        return await asyncio.to_thread(write)

    def _delivery_language(
        self,
        connection: sqlite3.Connection,
        parent_id: str,
        turn_id: int,
        now: datetime,
    ) -> tuple[int, str]:
        if not self._proactive_enabled:
            return super()._delivery_language(connection, parent_id, turn_id, now)
        context = _current_context(connection, parent_id, now)
        if context is None or not context.safety_chat_consent:
            raise ParentChatError("parent_proactive_chat_not_authorized", 409)
        connection.execute(
            "INSERT INTO parent_contact_turns(parent_id,turn_id,digest,payload) VALUES(?,?,?,?)",
            (parent_id, turn_id, _digest(context), context.model_dump_json()),
        )
        # A negative host anchor cannot be confused with a historical parent turn.
        # The literal locale is a separate prompt hint, never fabricated user text.
        return -context.revision, context.language

    def _valid_decision(
        self,
        connection: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        now: datetime,
    ) -> bool:
        row = connection.execute(
            "SELECT digest,payload FROM parent_contact_turns WHERE parent_id=? AND turn_id=?",
            (turn.parent_id, turn.turn_id),
        ).fetchone()
        if row is not None:
            if not self._proactive_enabled:
                return False
            context = _current_context(connection, turn.parent_id, now)
            if (
                context is None
                or not context.safety_chat_consent
                or _digest(context) != row["digest"]
                or context.model_dump_json() != row["payload"]
            ):
                return False
        return super()._valid_decision(connection, turn, receipt, now)

    async def next_delivery(self, now: datetime) -> ParentTouchDeliveryRequest | None:
        """Current explicit consent, including parents who have never spoken.

        SQL scope filters precede the bounded candidate page. A previous admission
        of the same specialist choice fences automatic retries across new days,
        contact revisions and failed/unknown model submissions.
        """
        if not self._proactive_enabled:
            return await super().next_delivery(now)

        def read() -> ParentTouchDeliveryRequest | None:
            current = self._utc(now)
            day, _ = self._period(current)
            with self._transaction() as connection:
                rows = connection.execute(
                    "SELECT c.parent_id,c.anchor,c.source_id FROM ("
                    "SELECT parent_id,'notice:'||notice_id AS anchor,notice_id AS source_id,"
                    "CASE kind WHEN 'urgent' THEN 4 ELSE 0 END AS priority,position "
                    "FROM family_notices n WHERE status='queued' AND expires_at>? "
                    "AND (kind='urgent' OR NOT EXISTS(SELECT 1 FROM family_questions q "
                    "WHERE q.parent_id=n.parent_id "
                    "AND q.status IN ('offered','awaiting_reply','held'))) "
                    "UNION ALL SELECT parent_id,question_id AS anchor,question_id AS source_id,"
                    "priority,position FROM family_questions q WHERE status='queued' "
                    "AND expires_at>? AND NOT EXISTS(SELECT 1 FROM family_questions a "
                    "WHERE a.parent_id=q.parent_id "
                    "AND a.status IN ('offered','awaiting_reply','held'))"
                    ") c JOIN parent_contact_contexts p ON p.parent_id=c.parent_id "
                    "LEFT JOIN parent_chat_quota b ON b.parent_id=c.parent_id AND b.day=? "
                    "WHERE p.safety_chat_consent=1 AND p.valid_until>? AND p.observed_at<=? "
                    "AND COALESCE(b.used,0)<? AND COALESCE(b.attempts,0)<? "
                    "AND NOT EXISTS(SELECT 1 FROM parent_chat_turns t "
                    "WHERE t.parent_id=c.parent_id "
                    "AND t.status IN ('preparing','submitted','unknown')) "
                    "AND NOT EXISTS(SELECT 1 FROM family_turn_metadata m "
                    "WHERE m.parent_id=c.parent_id AND m.offered_question_id=c.anchor) "
                    "ORDER BY c.priority DESC,c.position LIMIT 100",
                    (
                        current.isoformat(),
                        current.isoformat(),
                        day,
                        current.isoformat(),
                        (current + timedelta(seconds=120)).isoformat(),
                        self._limit - 31,
                        self._max_attempts,
                    ),
                ).fetchall()
                for row in rows:
                    context = _current_context(connection, row["parent_id"], current)
                    if context is not None and context.safety_chat_consent:
                        return ParentTouchDeliveryRequest(
                            parent_id=row["parent_id"],
                            request_id=uuid5(UUID(row["source_id"]), "first-contact-delivery-v1"),
                        )
                return None

        return await asyncio.to_thread(read)

    def _on_conversion_published(
        self, connection: sqlite3.Connection, proposal: ConversionProposal, now: datetime
    ) -> None:
        super()._on_conversion_published(connection, proposal, now)
        assert proposal.turn_id is not None
        self._queue_push(connection, proposal.parent_id, proposal.turn_id, "marketing", now)

    def _on_settled(
        self,
        connection: sqlite3.Connection,
        turn: StoredChatTurn,
        receipt: ChatModelReceipt,
        *,
        valid: bool,
    ) -> None:
        super()._on_settled(connection, turn, receipt, valid=valid)
        captured = connection.execute(
            "SELECT 1 FROM parent_contact_turns WHERE parent_id=? AND turn_id=?",
            (turn.parent_id, turn.turn_id),
        ).fetchone()
        if valid and not turn.message and captured is not None:
            row = connection.execute(
                "SELECT updated_at FROM parent_chat_turns WHERE parent_id=? AND id=?",
                (turn.parent_id, turn.turn_id),
            ).fetchone()
            assert row is not None
            self._queue_push(
                connection,
                turn.parent_id,
                turn.turn_id,
                "safety",
                datetime.fromisoformat(row["updated_at"]),
            )

    def _queue_push(
        self,
        connection: sqlite3.Connection,
        parent_id: str,
        turn_id: int,
        purpose: ParentPushPurpose,
        now: datetime,
    ) -> None:
        if not self._proactive_enabled or not self._push_enabled:
            return
        row = connection.execute(
            "SELECT request_id,message,answer,status FROM parent_chat_turns "
            "WHERE parent_id=? AND id=?",
            (parent_id, turn_id),
        ).fetchone()
        if row is None or row["status"] != "completed" or row["message"] or not row["answer"]:
            raise ParentChatError("parent_push_requires_published_message", 409)
        if connection.execute(
            "SELECT 1 FROM parent_push_outbox WHERE turn_id=?", (turn_id,)
        ).fetchone():
            return
        context = _current_context(connection, parent_id, now)
        if context is None or not (
            context.safety_push_consent
            if purpose == "safety"
            else context.retention_push_consent
            if purpose == "retention"
            else context.assistant_push_consent
            if purpose == "assistant"
            else context.marketing_push_consent
        ):
            return  # Notification permission is independent of durable chat publication.
        title, description = _notification(context.language)
        count = connection.execute(
            "SELECT COUNT(*) FROM parent_push_outbox WHERE status='queued'"
        ).fetchone()[0]
        scan_order = connection.execute(
            "SELECT COALESCE(MAX(scan_order),0)+1 FROM parent_push_outbox"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO parent_push_outbox(push_id,parent_id,turn_id,purpose,status,"
            "contact_digest,title,description,created_at,updated_at,expires_at,scan_order,"
            "error_code) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(
                    uuid5(
                        UUID(row["request_id"]), f"privacy-safe-parent-push:{parent_id}:{turn_id}"
                    )
                ),
                parent_id,
                turn_id,
                purpose,
                "queued" if count < self._push_queue_limit else "suppressed",
                _digest(context),
                title,
                description,
                now.isoformat(),
                now.isoformat(),
                self._utc(
                    min(context.valid_until, now + timedelta(seconds=self._push_max_age_seconds))
                ).isoformat(),
                scan_order,
                None if count < self._push_queue_limit else "parent_push_queue_full",
            ),
        )

    async def claim_push(self, now: datetime) -> ParentPushClaim | None:
        if not self._proactive_enabled or not self._push_enabled:
            return None

        def claim() -> ParentPushClaim | None:
            current = self._utc(now)
            with self._transaction() as connection:
                day_start = datetime.combine(
                    current.astimezone(self._zone).date(), datetime.min.time(), self._zone
                )
                attempts = connection.execute(
                    "SELECT COUNT(*) FROM parent_push_outbox WHERE claimed_at>=?",
                    (self._utc(day_start).isoformat(),),
                ).fetchone()[0]
                if attempts >= self._push_daily_attempt_limit:
                    return None
                rows = connection.execute(
                    "SELECT * FROM parent_push_outbox WHERE status='queued' "
                    "ORDER BY scan_order,position LIMIT 100"
                ).fetchall()
                scan_order = connection.execute(
                    "SELECT COALESCE(MAX(scan_order),0) FROM parent_push_outbox"
                ).fetchone()[0]
                for row in rows:
                    scan_order += 1
                    connection.execute(
                        "UPDATE parent_push_outbox SET scan_order=? WHERE push_id=?",
                        (scan_order, row["push_id"]),
                    )
                    context = _current_context(connection, row["parent_id"], current)
                    invalid = (
                        "parent_push_expired"
                        if datetime.fromisoformat(row["expires_at"]) <= current
                        else "parent_push_contact_changed"
                        if context is None or _digest(context) != row["contact_digest"]
                        else "parent_push_not_consented"
                        if not (
                            context.safety_push_consent
                            if row["purpose"] == "safety"
                            else context.retention_push_consent
                            if row["purpose"] == "retention"
                            else context.assistant_push_consent
                            if row["purpose"] == "assistant"
                            else context.marketing_push_consent
                        )
                        else None
                    )
                    if invalid is None and row["purpose"] == "marketing":
                        invalid = self._marketing_push_block(connection, row, current)
                    if invalid is not None:
                        connection.execute(
                            "UPDATE parent_push_outbox SET status='suppressed',updated_at=?,"
                            "error_code=? "
                            "WHERE push_id=?",
                            (current.isoformat(), invalid, row["push_id"]),
                        )
                        continue
                    assert context is not None
                    if not self._push_delivery_ready(connection, row, current):
                        continue
                    if row["purpose"] == "marketing":
                        hour = current.astimezone(ZoneInfo(context.timezone)).hour
                        start = self._conversion_policy.quiet_start_hour
                        end = self._conversion_policy.quiet_end_hour
                        quiet = hour >= start or hour < end if start > end else start <= hour < end
                        if quiet:
                            continue
                    claim_id = uuid4()
                    connection.execute(
                        "UPDATE parent_push_outbox SET status='submitting',claim_id=?,claimed_at=?,"
                        "updated_at=? WHERE push_id=? AND status='queued'",
                        (str(claim_id), current.isoformat(), current.isoformat(), row["push_id"]),
                    )
                    claimed = connection.execute(
                        "SELECT * FROM parent_push_outbox WHERE push_id=?", (row["push_id"],)
                    ).fetchone()
                    assert claimed is not None
                    return ParentPushClaim(
                        notification=_push(claimed),
                        claim_id=claim_id,
                        title=row["title"],
                        description=row["description"],
                    )
                return None

        return await asyncio.to_thread(claim)

    def _push_delivery_ready(
        self, connection: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> bool:
        """Owning private protocols may defer unsubmitted notifications only."""
        return True

    def _marketing_push_block(
        self, connection: sqlite3.Connection, push: sqlite3.Row, now: datetime
    ) -> str | None:
        """A saved offer does not retain permission after opt-out, payment or expiry.

        These are current local authoritative facts only, never a source refresh.
        Do not apply publication-frequency cooldown to its own notification.
        """
        parent_id = str(push["parent_id"])
        if connection.execute(
            "SELECT 1 FROM conversion_opt_outs WHERE parent_id=?", (parent_id,)
        ).fetchone():
            return "parent_push_marketing_opted_out"
        account = connection.execute(
            "SELECT snapshot,opted_out,converted FROM conversion_accounts WHERE parent_id=?",
            (parent_id,),
        ).fetchone()
        if account is None:
            return "parent_push_marketing_account_missing"
        if account["opted_out"] or account["converted"]:
            return "parent_push_marketing_account_closed"
        snapshot = ConversionSnapshot.model_validate_json(account["snapshot"])
        if self._account_verification_block(connection, snapshot, now):
            return "parent_push_marketing_source_not_verified"
        reason = self._conversion_reason(snapshot, now)
        if snapshot.parent_id != parent_id or not self._reason_eligible(reason):
            return "parent_push_marketing_account_not_eligible"
        row = connection.execute(
            "SELECT payload,status FROM conversion_proposals WHERE parent_id=? AND turn_id=?",
            (parent_id, push["turn_id"]),
        ).fetchone()
        if row is None:
            return "parent_push_marketing_offer_missing"
        proposal = ConversionProposal.model_validate_json(row["payload"])
        if (
            proposal.parent_id != parent_id
            or proposal.turn_id != push["turn_id"]
            or proposal.status != row["status"]
            or proposal.status not in {"published", "interested"}
            or proposal.published_at is None
            or proposal.published_at > now
        ):
            return "parent_push_marketing_offer_closed"
        if (
            self._conversion_offers.get(proposal.offer.offer_id) != proposal.offer
            or not self._offer_eligible(proposal.offer, reason)
            or not proposal.offer.valid_from <= now < proposal.offer.valid_until
            or proposal.offer.kind == "free_premium_days"
            and (
                snapshot.agent_trial_given is not False
                or connection.execute(
                    "SELECT 1 FROM conversion_trial_grants WHERE parent_id=?", (parent_id,)
                ).fetchone()
            )
        ):
            return "parent_push_marketing_offer_not_current"
        return None

    async def finish_push(
        self, claim: ParentPushClaim, outcome: ParentPushOutcome, now: datetime
    ) -> ParentPushState:
        def finish() -> ParentPushState:
            current = self._utc(now)
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM parent_push_outbox WHERE parent_id=? AND push_id=?",
                    (claim.notification.parent_id, str(claim.notification.push_id)),
                ).fetchone()
                if (
                    row is None
                    or row["turn_id"] != claim.notification.turn_id
                    or row["claim_id"] != str(claim.claim_id)
                    or row["title"] != claim.title
                    or row["description"] != claim.description
                ):
                    raise ParentChatError("parent_push_claim_mismatch", 409)
                if row["status"] != "submitting":
                    if row["outcome"] != outcome.model_dump_json():
                        raise ParentChatError("parent_push_receipt_already_final", 409)
                    return _push(row)
                connection.execute(
                    "UPDATE parent_push_outbox SET status=?,updated_at=?,queued_devices=?,"
                    "error_code=?,outcome=? WHERE push_id=?",
                    (
                        outcome.status,
                        current.isoformat(),
                        outcome.queued_devices,
                        outcome.error_code,
                        outcome.model_dump_json(),
                        row["push_id"],
                    ),
                )
                saved = connection.execute(
                    "SELECT * FROM parent_push_outbox WHERE push_id=?", (row["push_id"],)
                ).fetchone()
                assert saved is not None
                return _push(saved)

        return await asyncio.to_thread(finish)


class SqliteClosedProactiveParentStore(SqliteClosedConversionStore, _ProactiveReadAccess):
    """Current-code v8 history/broker reader; no push claims or source dispatch."""

    _schema_version = 8

    def _supported_versions(self) -> set[int]:
        return {8}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | PROACTIVE_TABLES

    async def language_hint(self, parent_id: str, turn_id: int) -> ResponseLanguage | None:
        return await _ProactiveReadAccess.language_hint(self, parent_id, turn_id)
