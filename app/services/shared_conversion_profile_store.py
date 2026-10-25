"""Family v20: reuse known profile acquisitions to veto stale commercial work."""

import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.mana_ai.domain.conversion import ConversionProposal, ConversionSnapshot
from app.mana_ai.domain.retention_expiry import RetentionTariffFact
from app.mana_ai.domain.shared_conversion_profile import SharedConversionProfilePolicy
from app.services.dated_review_safety_store import (
    SqliteClosedDatedReviewSafetyStore,
    SqliteDatedReviewSafetyStore,
)
from app.services.retention_expiry_store import _digest

_TABLES = {
    "conversion_profile_policy",
    "conversion_profile_heads",
    "conversion_profile_captures",
}


class SqliteSharedConversionProfileStore(SqliteDatedReviewSafetyStore):
    _schema_version = 20

    def __init__(
        self,
        path: Path,
        *,
        shared_profile_enabled: bool = False,
        shared_profile_policy: SharedConversionProfilePolicy | None = None,
        **family: Any,
    ) -> None:
        policy = shared_profile_policy or SharedConversionProfilePolicy()
        self._shared_profile_policy = SharedConversionProfilePolicy.model_validate(
            policy.model_dump()
        )
        self._shared_profile_enabled = shared_profile_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {19}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS conversion_profile_policy(
          id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL,
          circuit_open INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS conversion_profile_heads(
          parent_id TEXT PRIMARY KEY,payload TEXT,digest TEXT NOT NULL,collected_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS conversion_profile_captures(
          parent_id TEXT NOT NULL,event_id TEXT NOT NULL,revision INTEGER NOT NULL,
          enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),digest TEXT NOT NULL,
          expected_end TEXT,PRIMARY KEY(parent_id,event_id),UNIQUE(parent_id,revision));
        """
        )

    def _initialize(self) -> None:
        expected = self._shared_profile_policy.model_dump_json()
        if self._path.exists():
            with self._connect() as db:
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='conversion_profile_policy'"
                ).fetchone():
                    row = db.execute(
                        "SELECT payload FROM conversion_profile_policy WHERE id=1"
                    ).fetchone()
                    if row and row[0] != expected:
                        raise ValueError("Shared conversion policy cannot reset historical checks")
        super()._initialize()
        with self._transaction() as db:
            db.execute("INSERT OR IGNORE INTO conversion_profile_policy VALUES(1,?,0)", (expected,))
            if (
                db.execute("SELECT payload FROM conversion_profile_policy WHERE id=1").fetchone()[0]
                != expected
            ):
                raise ValueError("Shared conversion policy changed during initialization")

    def _capture_conversion_source(
        self, db: sqlite3.Connection, snapshot: ConversionSnapshot
    ) -> None:
        super()._capture_conversion_source(db, snapshot)
        db.execute(
            "INSERT INTO conversion_profile_captures VALUES(?,?,?,?,?,?)",
            (
                snapshot.parent_id,
                str(snapshot.event_id),
                snapshot.revision,
                int(self._shared_profile_enabled),
                hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest(),
                self._utc(snapshot.free_access_ends_at).isoformat()
                if snapshot.free_access_ends_at
                else None,
            ),
        )

    def _profile_check(
        self, db: sqlite3.Connection, capture: sqlite3.Row | None, now: datetime
    ) -> str | None:
        if capture is None or not capture["enabled"]:
            return None
        if not self._shared_profile_enabled or not self._expiry_enabled:
            return "shared_profile_disabled"
        if db.execute("SELECT circuit_open FROM conversion_profile_policy WHERE id=1").fetchone()[
            0
        ] or not self._expiry_open(db):
            return "shared_profile_source_closed"
        row = db.execute(
            "SELECT * FROM conversion_profile_heads WHERE parent_id=?", (capture["parent_id"],)
        ).fetchone()
        if row is None:
            return "shared_profile_not_current"
        try:
            collected = datetime.fromisoformat(row["collected_at"])
            fact = (
                RetentionTariffFact.model_validate_json(row["payload"]) if row["payload"] else None
            )
            if (
                _digest(fact) != row["digest"]
                or fact is not None
                and (
                    fact.parent_id != capture["parent_id"]
                    or self._utc(fact.collected_at).isoformat() != row["collected_at"]
                )
            ):
                raise ValueError("Shared profile integrity mismatch")
            if (
                not now - timedelta(seconds=self._shared_profile_policy.maximum_age_seconds)
                <= collected
                <= now
            ):
                return "shared_profile_not_current"
        except (ValueError, TypeError):
            db.execute("UPDATE conversion_profile_policy SET circuit_open=1 WHERE id=1")
            return "shared_profile_source_closed"
        if fact is None or fact.is_paid is None or fact.valid_until is None:
            return "shared_profile_unverified"
        if fact.is_paid:
            return "shared_profile_paid"
        if (
            capture["expected_end"] is None
            or self._utc(fact.valid_until).isoformat() != capture["expected_end"]
        ):
            return "shared_profile_term_mismatch"
        # A selected non-paid record is only a veto check. The authoritative
        # snapshot, approved offer, consent and independent account checks still apply.
        return None

    def _account_verification_block(
        self, db: sqlite3.Connection, snapshot: ConversionSnapshot, now: datetime
    ) -> str | None:
        capture = db.execute(
            "SELECT * FROM conversion_profile_captures WHERE parent_id=? AND event_id=?",
            (snapshot.parent_id, str(snapshot.event_id)),
        ).fetchone()
        if (
            capture is not None
            and capture["digest"] != hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest()
        ):
            db.execute("UPDATE conversion_profile_policy SET circuit_open=1 WHERE id=1")
            return "shared_profile_source_closed"
        return self._profile_check(db, capture, now) or super()._account_verification_block(
            db, snapshot, now
        )

    def _put_fact(
        self,
        db: sqlite3.Connection,
        parent: str,
        fact: RetentionTariffFact | None,
        collected: datetime,
    ) -> None:
        prior_observation = db.execute(
            "SELECT digest,collected_at FROM retention_tariff_heads WHERE parent_id=?", (parent,)
        ).fetchone()
        super()._put_fact(db, parent, fact, collected)
        if (
            not self._shared_profile_enabled
            or not self._expiry_enabled
            or not self._expiry_open(db)
        ):
            return
        original = db.execute(
            "SELECT digest,collected_at FROM retention_tariff_heads WHERE parent_id=?", (parent,)
        ).fetchone()
        if (
            original is None
            or original["digest"] != _digest(fact)
            or original["collected_at"] != collected.isoformat()
        ):
            return  # An older ignored observation cannot replace the current shared head.
        same_time = (
            prior_observation is not None
            and prior_observation["collected_at"] == collected.isoformat()
        )
        if same_time and prior_observation["digest"] == _digest(fact):
            return  # Replaying an old observation cannot acquire a newly enabled consumer.
        previous = db.execute(
            "SELECT * FROM conversion_profile_heads WHERE parent_id=?", (parent,)
        ).fetchone()
        if (
            same_time
            or (
                previous is not None
                and previous["collected_at"] == collected.isoformat()
                and previous["digest"] != _digest(fact)
            )
            or (
                previous is None
                and db.execute("SELECT COUNT(*) FROM conversion_profile_heads").fetchone()[0]
                >= self._shared_profile_policy.maximum_profiles
            )
        ):
            db.execute("UPDATE conversion_profile_policy SET circuit_open=1 WHERE id=1")
        elif not db.execute(
            "SELECT circuit_open FROM conversion_profile_policy WHERE id=1"
        ).fetchone()[0]:
            db.execute(
                "INSERT OR REPLACE INTO conversion_profile_heads VALUES(?,?,?,?)",
                (
                    parent,
                    fact.model_dump_json() if fact else None,
                    _digest(fact),
                    collected.isoformat(),
                ),
            )
        row = db.execute(
            "SELECT a.snapshot FROM conversion_accounts a JOIN conversion_proposals p "
            "ON p.parent_id=a.parent_id WHERE a.parent_id=? AND p.status='queued'",
            (parent,),
        ).fetchone()
        if row:
            snapshot = ConversionSnapshot.model_validate_json(row[0])
            capture = db.execute(
                "SELECT * FROM conversion_profile_captures WHERE parent_id=? AND event_id=?",
                (parent, str(snapshot.event_id)),
            ).fetchone()
            reason = self._profile_check(db, capture, collected)
            if reason:
                self._close_queued(db, parent, reason)

    def _push_delivery_ready(self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> bool:
        stored = db.execute(
            "SELECT payload FROM conversion_proposals WHERE parent_id=? AND turn_id=?",
            (row["parent_id"], row["turn_id"]),
        ).fetchone()
        if stored is not None:
            proposal = ConversionProposal.model_validate_json(stored[0])
            capture = db.execute(
                "SELECT c.*,e.digest AS event_digest FROM conversion_profile_captures c "
                "LEFT JOIN conversion_events e ON e.parent_id=c.parent_id "
                "AND e.event_id=c.event_id WHERE c.parent_id=? AND c.revision=?",
                (proposal.parent_id, proposal.snapshot_revision),
            ).fetchone()
            if (
                capture is not None
                and capture["enabled"]
                and (
                    capture["digest"] != capture["event_digest"]
                    or self._profile_check(db, capture, now)
                )
            ):
                return False
        return super()._push_delivery_ready(db, row, now)


class SqliteClosedSharedConversionProfileStore(SqliteClosedDatedReviewSafetyStore):
    _schema_version = 20

    def _supported_versions(self) -> set[int]:
        return {20}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
