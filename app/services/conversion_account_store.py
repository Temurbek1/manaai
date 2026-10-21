"""Private v10 source claims; no network or automatic recovery/re-dispatch."""

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.child_safety import ChildSafetyLimits
from app.mana_ai.domain.conversion import (
    ConversionAdmission,
    ConversionOffer,
    ConversionPolicy,
    ConversionSnapshot,
)
from app.mana_ai.domain.conversion_accounts import (
    ConversionAccountFacts,
    ConversionAccountRead,
    ConversionAccountReadLimits,
)
from app.services.commercial_conversation_store import (
    SqliteClosedCommercialConversationStore,
    SqliteCommercialConversationStore,
)

_TABLE = "conversion_account_reads"


class SqliteConversionAccountStore(SqliteCommercialConversationStore):
    _schema_version = 10

    def __init__(
        self,
        path: Path,
        conversion_policy: ConversionPolicy,
        conversion_offers: tuple[ConversionOffer, ...],
        limits: ChildSafetyLimits,
        daily_limit: int,
        timezone: str,
        *,
        account_source_enabled: bool,
        account_read_limits: ConversionAccountReadLimits,
        max_attempts: int = 20,
        question_limit: int = 100,
        push_queue_limit: int = 1000,
        push_max_age_seconds: int = 3600,
        push_daily_attempt_limit: int = 100,
        proactive_enabled: bool = True,
        push_enabled: bool = True,
        conversation_enabled: bool = True,
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
            push_queue_limit=push_queue_limit,
            push_max_age_seconds=push_max_age_seconds,
            push_daily_attempt_limit=push_daily_attempt_limit,
            proactive_enabled=proactive_enabled,
            push_enabled=push_enabled,
            conversation_enabled=conversation_enabled,
        )
        self._account_source_enabled = account_source_enabled
        self._account_read_limits = account_read_limits

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {9, 10}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
            CREATE TABLE IF NOT EXISTS conversion_account_reads (
                parent_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                observed_at TEXT NOT NULL,
                digest TEXT NOT NULL,
                payload TEXT NOT NULL,
                started_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('pending','verified','refused','unknown')),
                PRIMARY KEY(parent_id,event_id),
                UNIQUE(parent_id,revision)
            );
            CREATE INDEX IF NOT EXISTS conversion_account_read_budget
                ON conversion_account_reads(started_at);
            CREATE INDEX IF NOT EXISTS conversion_account_read_holds
                ON conversion_account_reads(parent_id,status);
        """
        )

    @staticmethod
    def _read_digest(snapshot: ConversionSnapshot) -> str:
        return hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest()

    async def claim_account_read(
        self, snapshot: ConversionSnapshot, now: datetime
    ) -> tuple[ConversionAdmission | None, bool]:
        return await asyncio.to_thread(self._claim_account_read, snapshot, self._utc(now))

    def _claim_account_read(
        self, snapshot: ConversionSnapshot, now: datetime
    ) -> tuple[ConversionAdmission | None, bool]:
        with self._transaction() as connection:
            known = self._event(connection, snapshot, "snapshot")
            if known:
                return ConversionAdmission.model_validate_json(known), False
            row = connection.execute(
                "SELECT digest,payload,status FROM conversion_account_reads "
                "WHERE parent_id=? AND event_id=?",
                (snapshot.parent_id, str(snapshot.event_id)),
            ).fetchone()
            if row:
                if row["digest"] != self._read_digest(snapshot):
                    raise ParentChatError("conversion_event_conflict", 409)
                if row["status"] == "pending":
                    return ConversionAdmission(
                        parent_id=snapshot.parent_id,
                        event_id=snapshot.event_id,
                        decision="account_read_pending",
                        proposal=None,
                    ), False
                return None, False  # SQL-only finalization, never another source call.
            if not self._account_source_enabled or not self._reason_eligible(
                self._conversion_reason(snapshot, now)
            ):
                return None, False
            account = connection.execute(
                "SELECT opted_out,converted FROM conversion_accounts WHERE parent_id=?",
                (snapshot.parent_id,),
            ).fetchone()
            if (
                account
                and (account["opted_out"] or account["converted"])
                or connection.execute(
                    "SELECT 1 FROM conversion_opt_outs WHERE parent_id=?", (snapshot.parent_id,)
                ).fetchone()
                or self._frequency_block(connection, snapshot.parent_id, now)
                or not any(
                    offer.valid_from <= now < offer.valid_until
                    and self._offer_eligible(offer, self._conversion_reason(snapshot, now))
                    and (offer.kind != "free_premium_days" or snapshot.agent_trial_given is False)
                    for offer in self._conversion_offers.values()
                )
            ):
                return None, False
            if connection.execute(
                "SELECT 1 FROM conversion_account_reads "
                "WHERE parent_id=? AND status IN ('pending','unknown') LIMIT 1",
                (snapshot.parent_id,),
            ).fetchone():
                raise ParentChatError("conversion_account_read_unresolved", 409)
            previous = connection.execute(
                "SELECT revision,observed_at FROM conversion_accounts WHERE parent_id=? "
                "UNION ALL SELECT revision,observed_at FROM conversion_account_reads "
                "WHERE parent_id=? ORDER BY revision DESC LIMIT 1",
                (snapshot.parent_id, snapshot.parent_id),
            ).fetchone()
            if previous and (
                snapshot.revision <= previous["revision"]
                or self._utc(snapshot.observed_at).isoformat() < previous["observed_at"]
            ):
                raise ParentChatError("conversion_snapshot_out_of_order", 409)
            latest = connection.execute(
                "SELECT started_at FROM conversion_account_reads WHERE parent_id=? "
                "ORDER BY started_at DESC LIMIT 1",
                (snapshot.parent_id,),
            ).fetchone()
            if (
                latest
                and (now - datetime.fromisoformat(latest["started_at"])).total_seconds()
                < self._account_read_limits.cooldown_seconds
            ):
                raise ParentChatError("conversion_account_read_cooldown", 429)
            # A rolling 24h ceiling cannot be reset by process restart or midnight.
            count = connection.execute(
                "SELECT COUNT(*) FROM conversion_account_reads WHERE started_at>?",
                ((now - timedelta(days=1)).isoformat(),),
            ).fetchone()[0]
            if count >= self._account_read_limits.daily_limit:
                raise ParentChatError("conversion_account_read_daily_limit", 429)
            observation = ConversionAccountRead(
                parent_id=snapshot.parent_id,
                event_id=snapshot.event_id,
                revision=snapshot.revision,
                status="pending",
                started_at=now,
            )
            connection.execute(
                "INSERT INTO conversion_account_reads "
                "(parent_id,event_id,revision,observed_at,digest,payload,started_at,status) "
                "VALUES(?,?,?,?,?,?,?,'pending')",
                (
                    snapshot.parent_id,
                    str(snapshot.event_id),
                    snapshot.revision,
                    self._utc(snapshot.observed_at).isoformat(),
                    self._read_digest(snapshot),
                    observation.model_dump_json(),
                    now.isoformat(),
                ),
            )
            self._close_queued(connection, snapshot.parent_id, "new_account_read_pending")
            return None, True

    async def finish_account_read(
        self,
        snapshot: ConversionSnapshot,
        now: datetime,
        *,
        status: str,
        facts: ConversionAccountFacts | None,
    ) -> None:
        def finish() -> None:
            current = self._utc(now)
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT digest,payload,status FROM conversion_account_reads "
                    "WHERE parent_id=? AND event_id=?",
                    (snapshot.parent_id, str(snapshot.event_id)),
                ).fetchone()
                if row is None or row["digest"] != self._read_digest(snapshot):
                    raise ParentChatError("conversion_account_read_not_admitted", 409)
                original = ConversionAccountRead.model_validate_json(row["payload"])
                if row["status"] != "pending":
                    return  # A terminal receipt never changes or dispatches again.
                if status not in {"verified", "refused", "unknown"}:
                    raise ValueError("Invalid account read settlement")
                if status == "verified" and (
                    facts is None
                    or facts.parent_id != snapshot.parent_id
                    or facts.collected_at < original.started_at - timedelta(seconds=120)
                    or facts.collected_at > current + timedelta(seconds=120)
                ):
                    status_value = "refused"
                    saved_facts = None
                else:
                    status_value = status
                    saved_facts = facts if status == "verified" else None
                completed = ConversionAccountRead.model_validate(
                    original.model_dump()
                    | {
                        "status": status_value,
                        "finished_at": current,
                        "facts": saved_facts,
                    }
                )
                connection.execute(
                    "UPDATE conversion_account_reads SET status=?,payload=? "
                    "WHERE parent_id=? AND event_id=?",
                    (
                        completed.status,
                        completed.model_dump_json(),
                        snapshot.parent_id,
                        str(snapshot.event_id),
                    ),
                )

        await asyncio.to_thread(finish)

    async def account_read(self, parent_id: str, event_id: UUID) -> ConversionAccountRead:
        def read() -> ConversionAccountRead:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM conversion_account_reads WHERE parent_id=? AND event_id=?",
                    (parent_id, str(event_id)),
                ).fetchone()
                if row is None:
                    raise ParentChatError("conversion_account_read_not_found", 404)
                return ConversionAccountRead.model_validate_json(row["payload"])

        return await asyncio.to_thread(read)

    def _account_verification_block(
        self, connection: sqlite3.Connection, snapshot: ConversionSnapshot, now: datetime
    ) -> str | None:
        held = connection.execute(
            "SELECT status FROM conversion_account_reads WHERE parent_id=? "
            "AND status IN ('pending','unknown') LIMIT 1",
            (snapshot.parent_id,),
        ).fetchone()
        if held:
            return "account_read_" + str(held["status"])
        row = connection.execute(
            "SELECT payload,digest FROM conversion_account_reads WHERE parent_id=? AND event_id=?",
            (snapshot.parent_id, str(snapshot.event_id)),
        ).fetchone()
        if row is None:
            captured = connection.execute(
                "SELECT 1 FROM conversion_account_reads WHERE parent_id=? LIMIT 1",
                (snapshot.parent_id,),
            ).fetchone()
            return (
                "account_source_not_verified" if self._account_source_enabled or captured else None
            )
        observation = ConversionAccountRead.model_validate_json(row["payload"])
        if row["digest"] != self._read_digest(snapshot):
            return "account_source_snapshot_mismatch"
        if observation.status != "verified" or observation.facts is None:
            return "account_read_" + observation.status
        facts = observation.facts
        if (
            not 0
            <= (now - facts.collected_at).total_seconds()
            <= (self._conversion_policy.snapshot_max_age_seconds)
        ):
            return "account_source_not_current"
        if facts.is_paid is not False:
            return "account_source_paid_or_unknown"
        if (
            snapshot.agent_trial_given is not None
            and facts.agent_trial_used is not snapshot.agent_trial_given
        ):
            return "account_source_trial_history_mismatch"
        if (
            snapshot.free_access_ends_at is not None
            and facts.valid_until != snapshot.free_access_ends_at
        ):
            return "account_source_period_mismatch"
        return None


class SqliteClosedConversionAccountStore(SqliteClosedCommercialConversationStore):
    """Same-code history reader, never a v9-image rollback or source dispatcher."""

    _schema_version = 10

    def _supported_versions(self) -> set[int]:
        return {10}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}
