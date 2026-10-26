"""Atomic conversion tracking and Parent-Touch outbox on the private family DB.

No network, child-data inspection, billing mutation or inference. Every publication
revalidates current authoritative account facts, catalog, consent and chat priority.
"""

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, cast
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.conversion import OfferRenderer
from app.mana_ai.domain.chat import ParentChatRequest
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.conversion import (
    ConversionAdmission,
    ConversionOffer,
    ConversionOutcome,
    ConversionPolicy,
    ConversionProposal,
    ConversionProposalPage,
    ConversionReason,
    ConversionSnapshot,
    conversion_reason,
)
from app.mana_ai.domain.conversion_grants import TrialAcceptance, TrialGrantState
from app.services.reviewed_message_store import (
    SqliteClosedReviewedBrokerStore,
    SqliteReviewedMessageStore,
)

CONVERSION_TABLES = {
    "conversion_accounts",
    "conversion_events",
    "conversion_proposals",
    "conversion_opt_outs",
    "conversion_trial_grants",
}


class SqliteConversionStore(SqliteReviewedMessageStore):
    _schema_version = 7

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
    ) -> None:
        super().__init__(
            path,
            limits=limits,
            daily_limit=daily_limit,
            timezone=timezone,
            max_attempts=max_attempts,
            question_limit=question_limit,
        )
        self._conversion_policy = conversion_policy
        self._conversion_offers = {offer.offer_id: offer for offer in conversion_offers}
        if len(self._conversion_offers) != len(conversion_offers):
            raise ValueError("Conversion offer identities must be unique")

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {6, 7}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | CONVERSION_TABLES

    def _conversion_reason(self, snapshot: ConversionSnapshot, now: datetime) -> str:
        return conversion_reason(snapshot, self._conversion_policy, now)

    def _account_verification_block(
        self, connection: sqlite3.Connection, snapshot: ConversionSnapshot, now: datetime
    ) -> str | None:
        """Captured source protocols may veto, never invent eligibility or grants."""
        return None

    def _capture_conversion_source(
        self, connection: sqlite3.Connection, snapshot: ConversionSnapshot
    ) -> None:
        """New compatible readers may freeze a stricter source check, never a grant."""

    def _reason_eligible(self, reason: str) -> bool:
        return reason in {"seven_day_free_use", "hot_free_account"}

    def _offer_eligible(self, offer: ConversionOffer, reason: str) -> bool:
        return True

    def _proposal_reason_matches(self, proposal: ConversionProposal, reason: str) -> bool:
        return True

    def _render_offer(
        self,
        proposal: ConversionProposal,
        snapshot: ConversionSnapshot,
        now: datetime,
        renderer: OfferRenderer,
    ) -> str:
        assert snapshot.free_started_at is not None
        days = int((now - snapshot.free_started_at).total_seconds() // 86400)
        return renderer(proposal.offer, days, snapshot.language)

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
            CREATE TABLE IF NOT EXISTS conversion_accounts (
                parent_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL,
                observed_at TEXT NOT NULL,
                snapshot TEXT NOT NULL,
                opted_out INTEGER NOT NULL DEFAULT 0,
                converted INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS conversion_events (
                parent_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                digest TEXT NOT NULL,
                result TEXT NOT NULL,
                payment_id TEXT UNIQUE,
                created_at TEXT NOT NULL,
                PRIMARY KEY(parent_id,event_id)
            );
            CREATE TABLE IF NOT EXISTS conversion_proposals (
                position INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id TEXT NOT NULL UNIQUE,
                parent_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                published_at TEXT,
                turn_id INTEGER UNIQUE
            );
            CREATE UNIQUE INDEX IF NOT EXISTS conversion_one_queued
                ON conversion_proposals(parent_id) WHERE status='queued';
            CREATE INDEX IF NOT EXISTS conversion_due
                ON conversion_proposals(status,checked_at,position);
            CREATE INDEX IF NOT EXISTS conversion_contact_history
                ON conversion_proposals(parent_id,published_at);
            CREATE TABLE IF NOT EXISTS conversion_opt_outs (
                parent_id TEXT PRIMARY KEY,
                recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversion_trial_grants (
                parent_id TEXT PRIMARY KEY,
                action_id TEXT NOT NULL UNIQUE,
                acceptance TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """
        )

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        request: ConversionSnapshot | ConversionOutcome,
        kind: Literal["snapshot", "outcome"],
    ) -> str | None:
        row = connection.execute(
            "SELECT kind,digest,result FROM conversion_events WHERE parent_id=? AND event_id=?",
            (request.parent_id, str(request.event_id)),
        ).fetchone()
        if row is None:
            return None
        if (
            row["kind"] != kind
            or row["digest"] != hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        ):
            raise ParentChatError("conversion_event_conflict", 409)
        return str(row["result"])

    @staticmethod
    def _save_event(
        connection: sqlite3.Connection,
        request: ConversionSnapshot | ConversionOutcome,
        kind: Literal["snapshot", "outcome"],
        result: str,
        now: datetime,
    ) -> None:
        connection.execute(
            "INSERT INTO conversion_events"
            "(parent_id,event_id,kind,digest,result,payment_id,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                request.parent_id,
                str(request.event_id),
                kind,
                hashlib.sha256(request.model_dump_json().encode()).hexdigest(),
                result,
                request.payment_id if isinstance(request, ConversionOutcome) else None,
                now.isoformat(),
            ),
        )

    @staticmethod
    def _save_proposal(connection: sqlite3.Connection, proposal: ConversionProposal) -> None:
        connection.execute(
            "UPDATE conversion_proposals SET status=?,payload=?,published_at=?,turn_id=? "
            "WHERE parent_id=? AND proposal_id=?",
            (
                proposal.status,
                proposal.model_dump_json(),
                proposal.published_at.isoformat() if proposal.published_at else None,
                proposal.turn_id,
                proposal.parent_id,
                str(proposal.proposal_id),
            ),
        )

    def _close_queued(self, connection: sqlite3.Connection, parent_id: str, reason: str) -> None:
        row = connection.execute(
            "SELECT payload FROM conversion_proposals WHERE parent_id=? AND status='queued'",
            (parent_id,),
        ).fetchone()
        if row:
            proposal = ConversionProposal.model_validate_json(row[0])
            self._save_proposal(
                connection,
                proposal.model_copy(update={"status": "cancelled", "closed_reason": reason}),
            )

    def _frequency_block(
        self, connection: sqlite3.Connection, parent_id: str, now: datetime
    ) -> str | None:
        policy = self._conversion_policy
        if connection.execute(
            "SELECT 1 FROM conversion_proposals WHERE parent_id=? AND published_at>? LIMIT 1",
            (parent_id, (now - timedelta(days=policy.cooldown_days)).isoformat()),
        ).fetchone():
            return "contact_cooldown"
        if (
            connection.execute(
                "SELECT COUNT(*) FROM conversion_proposals WHERE parent_id=? AND published_at>?",
                (parent_id, (now - timedelta(days=30)).isoformat()),
            ).fetchone()[0]
            >= policy.monthly_contact_limit
        ):
            return "monthly_contact_limit"
        return None

    async def ingest_conversion(
        self, snapshot: ConversionSnapshot, now: datetime
    ) -> ConversionAdmission:
        return await asyncio.to_thread(self._ingest_conversion, snapshot, self._utc(now))

    def _ingest_conversion(
        self, snapshot: ConversionSnapshot, now: datetime
    ) -> ConversionAdmission:
        with self._transaction() as connection:
            known = self._event(connection, snapshot, "snapshot")
            if known:
                return ConversionAdmission.model_validate_json(known)
            self._capture_conversion_source(connection, snapshot)
            previous = connection.execute(
                "SELECT * FROM conversion_accounts WHERE parent_id=?", (snapshot.parent_id,)
            ).fetchone()
            if previous and (
                snapshot.revision <= previous["revision"]
                or self._utc(snapshot.observed_at).isoformat() < previous["observed_at"]
            ):
                raise ParentChatError("conversion_snapshot_out_of_order", 409)
            if snapshot.observed_at > now + timedelta(seconds=120):
                raise ParentChatError("conversion_snapshot_in_future", 422)
            connection.execute(
                "INSERT INTO conversion_accounts(parent_id,revision,observed_at,snapshot) "
                "VALUES(?,?,?,?) "
                "ON CONFLICT(parent_id) DO UPDATE SET revision=excluded.revision,"
                "observed_at=excluded.observed_at,snapshot=excluded.snapshot",
                (
                    snapshot.parent_id,
                    snapshot.revision,
                    self._utc(snapshot.observed_at).isoformat(),
                    snapshot.model_dump_json(),
                ),
            )
            self._close_queued(connection, snapshot.parent_id, "superseded_account_snapshot")
            reason = self._conversion_reason(snapshot, now)
            if previous and previous["opted_out"]:
                reason = "parent_opted_out"
            if connection.execute(
                "SELECT 1 FROM conversion_opt_outs WHERE parent_id=?", (snapshot.parent_id,)
            ).fetchone():
                reason = "parent_opted_out"
            if previous and previous["converted"]:
                reason = "already_converted"
            source_block = (
                self._account_verification_block(connection, snapshot, now)
                if self._reason_eligible(reason)
                else None
            )
            reason = (
                source_block or self._frequency_block(connection, snapshot.parent_id, now) or reason
            )
            proposal = None
            offers = sorted(
                (
                    offer
                    for offer in self._conversion_offers.values()
                    if offer.valid_from <= now < offer.valid_until
                    and self._offer_eligible(offer, reason)
                    and (offer.kind != "free_premium_days" or snapshot.agent_trial_given is False)
                    and (
                        offer.kind != "free_premium_days"
                        or not connection.execute(
                            "SELECT 1 FROM conversion_trial_grants WHERE parent_id=?",
                            (snapshot.parent_id,),
                        ).fetchone()
                    )
                ),
                key=lambda offer: (-offer.priority, offer.offer_id),
            )
            if self._reason_eligible(reason):
                if not offers:
                    reason = "no_approved_offer"
                else:
                    proposal = ConversionProposal(
                        proposal_id=uuid5(snapshot.event_id, "mana-conversion-proposal-v1"),
                        parent_id=snapshot.parent_id,
                        snapshot_revision=snapshot.revision,
                        reason=cast(ConversionReason, reason),
                        status="queued",
                        offer=offers[0],
                        created_at=now,
                    )
                    connection.execute(
                        "INSERT INTO conversion_proposals"
                        "(proposal_id,parent_id,status,payload,checked_at) "
                        "VALUES(?,?,'queued',?,?)",
                        (
                            str(proposal.proposal_id),
                            snapshot.parent_id,
                            proposal.model_dump_json(),
                            now.isoformat(),
                        ),
                    )
            result = ConversionAdmission(
                parent_id=snapshot.parent_id,
                event_id=snapshot.event_id,
                decision=reason,
                proposal=proposal,
            )
            self._save_event(connection, snapshot, "snapshot", result.model_dump_json(), now)
            return result

    @staticmethod
    def _proposal(
        connection: sqlite3.Connection, parent_id: str, proposal_id: UUID
    ) -> ConversionProposal:
        row = connection.execute(
            "SELECT payload FROM conversion_proposals WHERE parent_id=? AND proposal_id=?",
            (parent_id, str(proposal_id)),
        ).fetchone()
        if row is None:
            raise ParentChatError("conversion_proposal_not_found", 404)
        return ConversionProposal.model_validate_json(row[0])

    async def conversion_proposal(self, parent_id: str, proposal_id: UUID) -> ConversionProposal:
        def read() -> ConversionProposal:
            with self._connect() as connection:
                return self._proposal(connection, parent_id, proposal_id)

        return await asyncio.to_thread(read)

    async def conversion_proposals(
        self, parent_id: str, after: int, limit: int
    ) -> ConversionProposalPage:
        if not after >= 0 or not 1 <= limit <= 100:
            raise ParentChatError("conversion_page_invalid", 422)

        def read() -> ConversionProposalPage:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT position,payload FROM conversion_proposals "
                    "WHERE parent_id=? AND position>? "
                    "ORDER BY position LIMIT ?",
                    (parent_id, after, limit + 1),
                ).fetchall()
                return ConversionProposalPage(
                    parent_id=parent_id,
                    proposals=[
                        ConversionProposal.model_validate_json(row["payload"])
                        for row in rows[:limit]
                    ],
                    next_after=rows[limit - 1]["position"] if len(rows) > limit else None,
                )

        return await asyncio.to_thread(read)

    async def conversion_outcome(
        self, outcome: ConversionOutcome, now: datetime
    ) -> ConversionProposal:
        return await asyncio.to_thread(self._conversion_outcome, outcome, self._utc(now))

    def _conversion_outcome(self, outcome: ConversionOutcome, now: datetime) -> ConversionProposal:
        with self._transaction() as connection:
            known = self._event(connection, outcome, "outcome")
            if known:
                return ConversionProposal.model_validate_json(known)
            proposal = self._proposal(connection, outcome.parent_id, outcome.proposal_id)
            if (
                outcome.observed_at > now + timedelta(seconds=120)
                or outcome.observed_at < proposal.created_at
            ):
                raise ParentChatError("conversion_outcome_date_invalid", 422)
            if proposal.status == "converted":
                raise ParentChatError("conversion_outcome_already_final", 409)
            if outcome.kind == "interested" and proposal.status in {
                "declined",
                "opted_out",
                "cancelled",
            }:
                raise ParentChatError("conversion_outcome_already_final", 409)
            if outcome.kind != "opted_out" and proposal.published_at is None:
                raise ParentChatError("conversion_offer_not_published", 409)
            if proposal.published_at and outcome.observed_at < proposal.published_at:
                raise ParentChatError("conversion_outcome_predates_contact", 422)
            if outcome.kind == "payment_confirmed":
                if proposal.offer.kind != "paid_subscription":
                    raise ParentChatError("free_days_are_not_a_paid_conversion", 422)
                if (
                    outcome.billing_offer_id != proposal.offer.billing_offer_id
                    or outcome.currency != proposal.offer.currency
                    or outcome.amount_minor != proposal.offer.price_minor
                    or not proposal.offer.valid_from
                    <= outcome.observed_at
                    < proposal.offer.valid_until
                ):
                    raise ParentChatError("conversion_payment_terms_mismatch", 422)
                if connection.execute(
                    "SELECT 1 FROM conversion_events WHERE payment_id=?", (outcome.payment_id,)
                ).fetchone():
                    raise ParentChatError("conversion_payment_already_recorded", 409)
            status = "converted" if outcome.kind == "payment_confirmed" else outcome.kind
            result = proposal.model_copy(update={"status": status})
            self._save_proposal(connection, result)
            if outcome.kind in {"opted_out", "payment_confirmed"}:
                if outcome.kind == "opted_out":
                    self._opt_out(connection, outcome.parent_id, now)
                    connection.execute(
                        "UPDATE conversion_accounts SET opted_out=1 WHERE parent_id=?",
                        (outcome.parent_id,),
                    )
                else:
                    connection.execute(
                        "UPDATE conversion_accounts SET converted=1 WHERE parent_id=?",
                        (outcome.parent_id,),
                    )
                self._close_queued(connection, outcome.parent_id, outcome.kind)
            self._save_event(connection, outcome, "outcome", result.model_dump_json(), now)
            return result

    def _chat_busy(self, connection: sqlite3.Connection, parent_id: str, now: datetime) -> bool:
        for query in (
            "SELECT 1 FROM parent_chat_turns WHERE parent_id=? "
            "AND status IN ('preparing','submitted','unknown') LIMIT 1",
            "SELECT 1 FROM child_safety_jobs WHERE parent_id=? "
            "AND status IN ('queued','preparing','submitted','unknown','metered') LIMIT 1",
        ):
            if connection.execute(query, (parent_id,)).fetchone():
                return True
        for query in (
            "SELECT 1 FROM family_questions WHERE parent_id=? "
            "AND (status IN ('offered','awaiting_reply','held') OR "
            "(status='queued' AND expires_at>?)) LIMIT 1",
            "SELECT 1 FROM family_notices WHERE parent_id=? "
            "AND (status IN ('offered','held') OR "
            "(status IN ('queued','deferred') AND expires_at>?)) LIMIT 1",
        ):
            if connection.execute(query, (parent_id, now.isoformat())).fetchone():
                return True
        return (
            connection.execute(
                "SELECT 1 FROM parent_chat_turns WHERE parent_id=? "
                "AND message!='' AND created_at>? LIMIT 1",
                (
                    parent_id,
                    (
                        now - timedelta(seconds=self._conversion_policy.conversation_idle_seconds)
                    ).isoformat(),
                ),
            ).fetchone()
            is not None
        )

    async def publish_conversion(self, now: datetime, renderer: OfferRenderer) -> bool:
        return await asyncio.to_thread(self._publish_conversion, self._utc(now), renderer)

    async def publish_trial_result(self, now: datetime) -> bool:
        return False

    def _publish_conversion(self, now: datetime, renderer: OfferRenderer) -> bool:
        with self._transaction() as connection:
            day, _ = self._period(now)
            day_start = datetime.combine(
                now.astimezone(self._zone).date(), datetime.min.time(), self._zone
            )
            if (
                connection.execute(
                    "SELECT COUNT(*) FROM conversion_proposals WHERE published_at>=?",
                    (self._utc(day_start).isoformat(),),
                ).fetchone()[0]
                >= self._conversion_policy.global_daily_contact_limit
            ):
                return False
            rows = connection.execute(
                "SELECT p.payload,a.snapshot,a.opted_out,a.converted FROM conversion_proposals p "
                "JOIN conversion_accounts a ON a.parent_id=p.parent_id WHERE p.status='queued' "
                "ORDER BY p.checked_at,p.position LIMIT 100"
            ).fetchall()
            for row in rows:
                proposal = ConversionProposal.model_validate_json(row["payload"])
                snapshot = ConversionSnapshot.model_validate_json(row["snapshot"])
                connection.execute(
                    "UPDATE conversion_proposals SET checked_at=? WHERE proposal_id=?",
                    (now.isoformat(), str(proposal.proposal_id)),
                )
                reason = self._conversion_reason(snapshot, now)
                catalog = self._conversion_offers.get(proposal.offer.offer_id)
                invalid = (
                    "parent_opted_out"
                    if row["opted_out"]
                    or connection.execute(
                        "SELECT 1 FROM conversion_opt_outs WHERE parent_id=?", (proposal.parent_id,)
                    ).fetchone()
                    else "already_converted"
                    if row["converted"]
                    else "account_no_longer_eligible"
                    if not self._reason_eligible(reason)
                    or not self._proposal_reason_matches(proposal, reason)
                    else "approved_offer_changed_or_expired"
                    if catalog != proposal.offer
                    or not self._offer_eligible(proposal.offer, reason)
                    or not proposal.offer.valid_from <= now < proposal.offer.valid_until
                    or proposal.offer.kind == "free_premium_days"
                    and snapshot.agent_trial_given is not False
                    else self._account_verification_block(connection, snapshot, now)
                    or self._frequency_block(connection, proposal.parent_id, now)
                )
                if invalid:
                    self._save_proposal(
                        connection,
                        proposal.model_copy(
                            update={"status": "cancelled", "closed_reason": invalid}
                        ),
                    )
                    continue
                local_hour = now.astimezone(ZoneInfo(snapshot.timezone)).hour
                start, end = (
                    self._conversion_policy.quiet_start_hour,
                    self._conversion_policy.quiet_end_hour,
                )
                quiet = (
                    (local_hour >= start or local_hour < end)
                    if start > end
                    else start <= local_hour < end
                )
                if quiet or self._chat_busy(connection, proposal.parent_id, now):
                    continue
                answer = self._render_offer(proposal, snapshot, now, renderer)
                request_id = uuid5(proposal.proposal_id, "parent-touch-commercial-template-v1")
                cursor = connection.execute(
                    "INSERT INTO parent_chat_turns(parent_id,request_id,message,request_digest,"
                    "day,status,reserved,created_at,updated_at,answer,model) "
                    "VALUES(?,?,'',?,?,'completed',0,?,?,?,'parent-touch-commercial-template-v1')",
                    (
                        proposal.parent_id,
                        str(request_id),
                        hashlib.sha256(proposal.model_dump_json().encode()).hexdigest(),
                        day,
                        now.isoformat(),
                        now.isoformat(),
                        answer,
                    ),
                )
                result = proposal.model_copy(
                    update={"status": "published", "published_at": now, "turn_id": cursor.lastrowid}
                )
                self._save_proposal(connection, result)
                self._on_conversion_published(connection, result, now)
                # Assistant-only, not a fabricated parent message, provider receipt,
                # specialist question or child-safety event. The same SQL commit
                # owns both the contact record and the one durable chat turn.
                return True
            return False

    def _on_conversion_published(
        self, connection: sqlite3.Connection, proposal: ConversionProposal, now: datetime
    ) -> None:
        """Optional private outbox shares the chat-publication transaction."""

    def _opt_out(self, connection: sqlite3.Connection, parent_id: str, now: datetime) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO conversion_opt_outs(parent_id,recorded_at) VALUES(?,?)",
            (parent_id, now.isoformat()),
        )
        self._close_queued(connection, parent_id, "parent_opted_out")

    async def suppress_conversion(self, parent_id: str, now: datetime) -> None:
        def write() -> None:
            with self._transaction() as connection:
                self._opt_out(connection, parent_id, self._utc(now))

        await asyncio.to_thread(write)

    async def suppress_from_message(self, request: ParentChatRequest, now: datetime) -> None:
        def write() -> None:
            with self._transaction() as connection:
                # A historical replay or conflicting nonce does not acquire a new
                # side effect before normal chat admission validates its digest.
                if connection.execute(
                    "SELECT 1 FROM parent_chat_turns WHERE parent_id=? AND request_id=?",
                    (request.parent_id, str(request.request_id)),
                ).fetchone():
                    return
                self._opt_out(connection, request.parent_id, self._utc(now))

        await asyncio.to_thread(write)

    async def claim_trial_grant(
        self, acceptance: TrialAcceptance, now: datetime
    ) -> tuple[TrialGrantState, bool]:
        def claim() -> tuple[TrialGrantState, bool]:
            current = self._utc(now)
            with self._transaction() as connection:
                existing = connection.execute(
                    "SELECT acceptance,payload FROM conversion_trial_grants WHERE parent_id=?",
                    (acceptance.parent_id,),
                ).fetchone()
                if existing:
                    original = TrialAcceptance.model_validate_json(existing["acceptance"])
                    if original != acceptance:
                        raise ParentChatError("trial_grant_already_admitted", 409)
                    return TrialGrantState.model_validate_json(existing["payload"]), False
                day_start = datetime.combine(
                    current.astimezone(self._zone).date(), datetime.min.time(), self._zone
                )
                count = connection.execute(
                    "SELECT COUNT(*) FROM conversion_trial_grants WHERE created_at>=?",
                    (self._utc(day_start).isoformat(),),
                ).fetchone()[0]
                if count >= self._conversion_policy.global_daily_trial_grant_limit:
                    raise ParentChatError("trial_grant_daily_limit", 429)
                proposal = self._proposal(connection, acceptance.parent_id, acceptance.proposal_id)
                if proposal.offer.kind != "free_premium_days" or proposal.status not in {
                    "published",
                    "interested",
                }:
                    raise ParentChatError("trial_offer_not_available", 409)
                if (
                    self._conversion_offers.get(proposal.offer.offer_id) != proposal.offer
                    or not proposal.offer.valid_from <= current < proposal.offer.valid_until
                ):
                    raise ParentChatError("trial_offer_expired_or_revoked", 409)
                account = connection.execute(
                    "SELECT snapshot,opted_out,converted FROM conversion_accounts "
                    "WHERE parent_id=?",
                    (acceptance.parent_id,),
                ).fetchone()
                assert account is not None
                snapshot = ConversionSnapshot.model_validate_json(account["snapshot"])
                if (
                    account["opted_out"]
                    or account["converted"]
                    or snapshot.agent_trial_given is not False
                    or conversion_reason(snapshot, self._conversion_policy, current)
                    not in {"seven_day_free_use", "hot_free_account"}
                ):
                    raise ParentChatError("trial_account_no_longer_eligible", 409)
                if self._account_verification_block(connection, snapshot, current):
                    raise ParentChatError("trial_account_source_not_verified", 409)
                if connection.execute(
                    "SELECT 1 FROM conversion_opt_outs WHERE parent_id=?", (acceptance.parent_id,)
                ).fetchone():
                    raise ParentChatError("trial_parent_opted_out", 409)
                reply = connection.execute(
                    "SELECT message,created_at FROM parent_chat_turns "
                    "WHERE parent_id=? AND id=? AND message!=''",
                    (acceptance.parent_id, acceptance.reply_turn_id),
                ).fetchone()
                if (
                    reply is None
                    or proposal.turn_id is None
                    or acceptance.reply_turn_id <= proposal.turn_id
                    or datetime.fromisoformat(reply["created_at"]) > current
                    or (current - datetime.fromisoformat(reply["created_at"])).total_seconds() > 900
                ):
                    raise ParentChatError("trial_parent_reply_not_bound", 409)
                normalized = str(reply["message"]).strip().strip(".!? ").casefold()
                if normalized not in {
                    "активировать бесплатные дни",
                    "bepul kunlarni faollashtiring",
                    "бепул кунларни фаоллаштиринг",
                    "activate free days",
                }:
                    raise ParentChatError("trial_parent_acceptance_not_explicit", 409)
                latest = connection.execute(
                    "SELECT proposal_id FROM conversion_proposals WHERE parent_id=? "
                    "AND turn_id<? AND published_at IS NOT NULL ORDER BY turn_id DESC LIMIT 1",
                    (acceptance.parent_id, acceptance.reply_turn_id),
                ).fetchone()
                if latest is None or latest["proposal_id"] != str(acceptance.proposal_id):
                    raise ParentChatError("trial_parent_reply_offer_mismatch", 409)
                self._validate_trial_reply(connection, acceptance, proposal, current)
                state = TrialGrantState(
                    action_id=uuid5(proposal.proposal_id, "one-time-non-paid-agent-tariff-v1"),
                    parent_id=acceptance.parent_id,
                    proposal_id=proposal.proposal_id,
                    days=proposal.offer.grant_days,
                    status="submitting",
                )
                connection.execute(
                    "INSERT INTO conversion_trial_grants"
                    "(parent_id,action_id,acceptance,payload,created_at) VALUES(?,?,?,?,?)",
                    (
                        state.parent_id,
                        str(state.action_id),
                        acceptance.model_dump_json(),
                        state.model_dump_json(),
                        current.isoformat(),
                    ),
                )
                self._on_trial_grant_claimed(connection, state, current)
                return state, True

        return await asyncio.to_thread(claim)

    def _validate_trial_reply(
        self,
        connection: sqlite3.Connection,
        acceptance: TrialAcceptance,
        proposal: ConversionProposal,
        now: datetime,
    ) -> None:
        """New private protocols can require a frozen offer, never infer it from prose."""

    def _on_trial_grant_claimed(
        self, connection: sqlite3.Connection, state: TrialGrantState, now: datetime
    ) -> None:
        """New private companions freeze their scope before any provider dispatch."""

    async def finish_trial_grant(self, state: TrialGrantState, now: datetime) -> TrialGrantState:
        def finish() -> TrialGrantState:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT payload FROM conversion_trial_grants WHERE parent_id=? AND action_id=?",
                    (state.parent_id, str(state.action_id)),
                ).fetchone()
                if row is None:
                    raise ParentChatError("trial_grant_claim_missing", 409)
                original = TrialGrantState.model_validate_json(row[0])
                if original.status != "submitting":
                    if original.model_dump_json() != state.model_dump_json():
                        raise ParentChatError("trial_grant_receipt_already_final", 409)
                    return original
                if original.proposal_id != state.proposal_id or original.days != state.days:
                    raise ParentChatError("trial_grant_receipt_mismatch", 409)
                connection.execute(
                    "UPDATE conversion_trial_grants SET payload=? WHERE parent_id=?",
                    (state.model_dump_json(), state.parent_id),
                )
                self._on_trial_grant_finished(connection, state, self._utc(now))
                # Private, nonserialized provider observations must not change
                # the first public receipt relative to exact replay.
                return TrialGrantState.model_validate_json(state.model_dump_json())

        return await asyncio.to_thread(finish)

    def _on_trial_grant_finished(
        self,
        connection: sqlite3.Connection,
        state: TrialGrantState,
        now: datetime,
    ) -> None:
        """Scoped adapters may queue a host-owned receipt notice atomically."""

    async def trial_grant(self, parent_id: str) -> TrialGrantState:
        def read() -> TrialGrantState:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM conversion_trial_grants WHERE parent_id=?", (parent_id,)
                ).fetchone()
                if row is None:
                    raise ParentChatError("trial_grant_not_found", 404)
                return TrialGrantState.model_validate_json(row[0])

        return await asyncio.to_thread(read)


class SqliteClosedConversionStore(SqliteClosedReviewedBrokerStore):
    """Current-code compatible deactivation; never downgrade populated v7 state."""

    _schema_version = 7

    def __init__(
        self,
        path: Path,
        *,
        history_only: bool = False,
        daily_limit: int,
        timezone: str,
        max_attempts: int = 20,
        question_limit: int = 100,
    ) -> None:
        super().__init__(
            path,
            daily_limit=daily_limit,
            timezone=timezone,
            max_attempts=max_attempts,
            question_limit=question_limit,
        )
        self._history_only = history_only

    def _supported_versions(self) -> set[int]:
        return {7}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | CONVERSION_TABLES

    def _on_admitted(
        self,
        connection: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        now: datetime,
    ) -> None:
        if self._history_only:
            raise ParentChatError("family_execution_disabled", 503)
        super()._on_admitted(connection, request, turn_id, now)
