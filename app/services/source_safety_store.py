"""Private source-cache v2: frozen specialist intent and SQL-only reconciliation."""

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.application.source_safety import battery_safety_intent, battery_semantics
from app.mana_ai.domain.family_sources import (
    ChildBatteryFacts,
    FamilySourceChange,
    FamilySourceLimits,
)
from app.mana_ai.domain.source_safety import (
    SourceSafetyIntent,
    SourceSafetyPolicy,
    SourceSafetyReason,
    SourceSafetyReceipt,
    SourceSafetyWork,
)
from app.services.family_source_store import SqliteFamilySourceStore


class SqliteSourceSafetyStore(SqliteFamilySourceStore):
    _schema_version = 2
    _extra_tables = frozenset(
        {"source_safety_policy", "source_safety_dispatches", "source_safety_admissions"}
    )

    def __init__(
        self,
        path: Path,
        *,
        binding: str,
        limits: FamilySourceLimits,
        policy: SourceSafetyPolicy,
        enabled: bool = False,
    ) -> None:
        super().__init__(path, binding=binding, limits=limits)
        self._policy = SourceSafetyPolicy.model_validate(policy.model_dump())
        self._dispatch_enabled = enabled

    def _extra_schema(self) -> tuple[str, ...]:
        return (
            "CREATE TABLE IF NOT EXISTS source_safety_policy ("
            "id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, "
            "after_event INTEGER NOT NULL)",
            "CREATE TABLE IF NOT EXISTS source_safety_dispatches ("
            "event_id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, child_id INTEGER NOT NULL, "
            "phase TEXT NOT NULL CHECK(phase IN "
            "('preparing','prepared','dispatching','admitted','skipped','unknown')), "
            "semantic_key TEXT, payload TEXT NOT NULL, intent TEXT, intent_hash TEXT, "
            "UNIQUE(parent_id,child_id,semantic_key))",
            "CREATE UNIQUE INDEX IF NOT EXISTS source_safety_one_unresolved "
            "ON source_safety_dispatches(child_id) "
            "WHERE phase IN ('preparing','prepared','dispatching','unknown')",
            "CREATE INDEX IF NOT EXISTS source_safety_ready ON source_safety_dispatches(phase)",
            "CREATE TABLE IF NOT EXISTS source_safety_admissions ("
            "event_id TEXT PRIMARY KEY, allowed INTEGER NOT NULL CHECK(allowed IN (0,1)), "
            "policy TEXT NOT NULL)",
        )

    def _source_changed(self, connection: sqlite3.Connection, event: FamilySourceChange) -> None:
        if event.source != "firebase.child_battery.v1":
            return  # Usage counters do not supply a current protective measurement.
        connection.execute(
            "INSERT INTO source_safety_admissions VALUES(?,?,?)",
            (str(event.event_id), int(self._dispatch_enabled), self._policy.model_dump_json()),
        )

    def _initialize_additional(self, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT payload FROM source_safety_policy WHERE id=1").fetchone()
        payload = self._policy.model_dump_json()
        if row is not None and row[0] != payload:
            raise ValueError("Existing source-consumer policy cannot be replaced")
        # A v1 cache upgrade never auto-captures historical changes for inference.
        connection.execute(
            "INSERT OR IGNORE INTO source_safety_policy VALUES"
            "(1,?,(SELECT COALESCE(MAX(id),0) FROM source_changes))",
            (payload,),
        )

    @staticmethod
    def _receipt(row: sqlite3.Row) -> SourceSafetyReceipt:
        receipt = SourceSafetyReceipt.model_validate_json(row["payload"])
        if (
            str(receipt.event_id) != row["event_id"]
            or receipt.parent_id != row["parent_id"]
            or receipt.child_id != row["child_id"]
            or receipt.phase != row["phase"]
        ):
            raise ParentChatError("source_safety_state_invalid", 503)
        return receipt

    def _work(self, connection: sqlite3.Connection, row: sqlite3.Row) -> SourceSafetyWork:
        receipt = self._receipt(row)
        event_row = connection.execute(
            "SELECT payload FROM source_changes WHERE event_id=? AND parent_id=?",
            (str(receipt.event_id), receipt.parent_id),
        ).fetchone()
        snapshot = connection.execute(
            "SELECT payload,fingerprint FROM source_snapshots "
            "WHERE snapshot_id=? AND parent_id=? AND child_id=?",
            (str(receipt.snapshot_id), receipt.parent_id, receipt.child_id),
        ).fetchone()
        if event_row is None or snapshot is None:
            raise ParentChatError("source_safety_state_invalid", 503)
        event = FamilySourceChange.model_validate_json(event_row[0])
        facts = ChildBatteryFacts.model_validate_json(snapshot["payload"])
        if (
            event.snapshot_id != receipt.snapshot_id
            or event.child_id != receipt.child_id
            or event.fingerprint != snapshot["fingerprint"]
            or facts.fingerprint() != snapshot["fingerprint"]
            or facts.child_id != receipt.child_id
        ):
            raise ParentChatError("source_safety_state_invalid", 503)
        work = SourceSafetyWork(receipt=receipt, event=event, facts=facts)
        if row["intent"] is not None:
            if hashlib.sha256(row["intent"].encode()).hexdigest() != row["intent_hash"]:
                raise ParentChatError("source_safety_intent_changed", 503)
            intent = SourceSafetyIntent.model_validate_json(row["intent"])
            if intent != battery_safety_intent(
                work,
                self._policy,
                age=intent.child_age,
                profile_collected_at=intent.profile_collected_at,
            ):
                raise ParentChatError("source_safety_intent_changed", 503)
            work = work.model_copy(update={"intent": intent})
        elif receipt.phase in {"prepared", "dispatching", "admitted"}:
            raise ParentChatError("source_safety_intent_changed", 503)
        return work

    @staticmethod
    def _save(connection: sqlite3.Connection, receipt: SourceSafetyReceipt) -> None:
        connection.execute(
            "UPDATE source_safety_dispatches SET phase=?,payload=? WHERE event_id=?",
            (receipt.phase, receipt.model_dump_json(), str(receipt.event_id)),
        )

    def _skip(self, facts: ChildBatteryFacts, now: datetime) -> SourceSafetyReason | None:
        if facts.status != "available":
            return "no_observation"
        if facts.observed_at is None:
            return "undated"
        if (
            not now - timedelta(seconds=self._policy.maximum_age_seconds)
            <= facts.observed_at
            <= now
        ):
            return "stale"
        return None

    async def claim_next_dispatch(self, now: datetime) -> SourceSafetyWork | None:
        if not self._dispatch_enabled:
            return None
        return await asyncio.to_thread(self._claim_dispatch, self._time(now))

    def _claim_dispatch(self, now: datetime) -> SourceSafetyWork | None:
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT * FROM source_safety_dispatches WHERE phase IN ('prepared','dispatching') "
                "ORDER BY CASE phase WHEN 'dispatching' THEN 0 ELSE 1 END,rowid LIMIT 1"
            ).fetchone()
            if existing is not None:
                work = self._work(connection, existing)
                if work.receipt.phase == "dispatching":
                    return work  # Observe exact local admission; never issue it again.
                if self._skip(work.facts, now) is not None:
                    receipt = work.receipt.model_copy(
                        update={"phase": "skipped", "reason": "stale", "updated_at": now}
                    )
                    self._save(connection, receipt)
                    return work.model_copy(update={"receipt": receipt})
                receipt = work.receipt.model_copy(
                    update={"phase": "dispatching", "updated_at": now}
                )
                self._save(connection, receipt)
                return work.model_copy(update={"receipt": receipt, "dispatch_now": True})
            cursor = connection.execute(
                "SELECT after_event FROM source_safety_policy WHERE id=1"
            ).fetchone()[0]
            row = connection.execute(
                "SELECT id,payload FROM source_changes WHERE id>? "
                "AND COALESCE(json_extract(payload,'$.source'),'firebase.child_battery.v1')="
                "'firebase.child_battery.v1' ORDER BY id LIMIT 1",
                (cursor,),
            ).fetchone()
            if row is None:
                return None
            event = FamilySourceChange.model_validate_json(row["payload"])
            facts_row = connection.execute(
                "SELECT payload,fingerprint FROM source_snapshots "
                "WHERE snapshot_id=? AND parent_id=? AND child_id=?",
                (str(event.snapshot_id), event.parent_id, event.child_id),
            ).fetchone()
            if facts_row is None:
                raise ParentChatError("source_safety_state_invalid", 503)
            facts = ChildBatteryFacts.model_validate_json(facts_row["payload"])
            if (
                facts.fingerprint() != event.fingerprint
                or facts_row["fingerprint"] != event.fingerprint
            ):
                raise ParentChatError("source_safety_state_invalid", 503)
            admission = connection.execute(
                "SELECT allowed,policy FROM source_safety_admissions WHERE event_id=?",
                (str(event.event_id),),
            ).fetchone()
            reason: SourceSafetyReason | None = (
                "not_admitted"
                if admission is None
                or not admission["allowed"]
                or admission["policy"] != self._policy.model_dump_json()
                else self._skip(facts, now)
            )
            semantic = (
                battery_semantics(facts.percent, facts.observed_at)
                if facts.percent is not None and facts.observed_at is not None
                else None
            )
            if (
                reason is None
                and connection.execute(
                    "SELECT 1 FROM source_safety_dispatches WHERE child_id=? AND "
                    "phase IN ('preparing','prepared','dispatching','unknown')",
                    (event.child_id,),
                ).fetchone()
            ):
                reason = "prior_unresolved"
            if (
                reason is None
                and connection.execute(
                    "SELECT 1 FROM source_safety_dispatches "
                    "WHERE parent_id=? AND child_id=? AND semantic_key=?",
                    (event.parent_id, event.child_id, semantic),
                ).fetchone()
            ):
                reason = "duplicate"
            receipt = SourceSafetyReceipt(
                event_id=event.event_id,
                parent_id=event.parent_id,
                child_id=event.child_id,
                snapshot_id=event.snapshot_id,
                phase="skipped" if reason else "preparing",
                reason=reason,
                started_at=now,
                updated_at=now,
            )
            connection.execute(
                "INSERT INTO source_safety_dispatches VALUES(?,?,?,?,?,?,NULL,NULL)",
                (
                    str(event.event_id),
                    event.parent_id,
                    event.child_id,
                    receipt.phase,
                    semantic if reason is None else None,
                    receipt.model_dump_json(),
                ),
            )
            connection.execute(
                "UPDATE source_safety_policy SET after_event=? WHERE id=1", (row["id"],)
            )
            return SourceSafetyWork(receipt=receipt, event=event, facts=facts)

    async def prepare_dispatch(
        self, event_id: UUID, intent: SourceSafetyIntent, now: datetime
    ) -> SourceSafetyReceipt:
        return await asyncio.to_thread(self._prepare_dispatch, event_id, intent, self._time(now))

    def _prepare_dispatch(
        self, event_id: UUID, intent: SourceSafetyIntent, now: datetime
    ) -> SourceSafetyReceipt:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM source_safety_dispatches WHERE event_id=?", (str(event_id),)
            ).fetchone()
            if row is None:
                raise ParentChatError("source_safety_dispatch_not_found", 404)
            work = self._work(connection, row)
            if work.receipt.phase != "preparing":
                return work.receipt
            if (
                intent
                != battery_safety_intent(
                    work,
                    self._policy,
                    age=intent.child_age,
                    profile_collected_at=intent.profile_collected_at,
                )
                or not now - timedelta(seconds=180) <= intent.profile_collected_at <= now
            ):
                raise ParentChatError("source_safety_intent_changed", 503)
            reason = self._skip(work.facts, now)
            receipt = work.receipt.model_copy(
                update={
                    "phase": "skipped" if reason else "prepared",
                    "reason": reason,
                    "updated_at": now,
                }
            )
            if reason is None:
                payload = intent.model_dump_json()
                connection.execute(
                    "UPDATE source_safety_dispatches SET intent=?,intent_hash=? WHERE event_id=?",
                    (payload, hashlib.sha256(payload.encode()).hexdigest(), str(event_id)),
                )
            self._save(connection, receipt)
            return receipt

    async def finish_dispatch(
        self,
        event_id: UUID,
        now: datetime,
        *,
        reason: SourceSafetyReason | None = None,
        unknown: bool = False,
        job_id: UUID | None = None,
    ) -> SourceSafetyReceipt:
        def finish() -> SourceSafetyReceipt:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM source_safety_dispatches WHERE event_id=?", (str(event_id),)
                ).fetchone()
                if row is None:
                    raise ParentChatError("source_safety_dispatch_not_found", 404)
                work = self._work(connection, row)
                if work.receipt.phase in {"admitted", "skipped"}:
                    return work.receipt
                if job_id is not None and (
                    work.intent is None or work.receipt.phase not in {"dispatching", "unknown"}
                ):
                    raise ParentChatError("source_safety_dispatch_not_claimed", 409)
                receipt = SourceSafetyReceipt.model_validate(
                    work.receipt.model_dump()
                    | {
                        "phase": "admitted" if job_id else "unknown" if unknown else "skipped",
                        "reason": reason,
                        "job_id": job_id,
                        "updated_at": self._time(now),
                    }
                )
                self._save(connection, receipt)
                return receipt

        return await asyncio.to_thread(finish)

    async def dispatch_work(self, parent_id: str, event_id: UUID) -> SourceSafetyWork:
        def read() -> SourceSafetyWork:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT * FROM source_safety_dispatches WHERE event_id=? AND parent_id=?",
                    (str(event_id), parent_id),
                ).fetchone()
                if row is None:
                    raise ParentChatError("source_safety_dispatch_not_found", 404)
                return self._work(connection, row)

        return await asyncio.to_thread(read)

    async def dispatch_receipts(
        self, parent_id: str, *, limit: int = 100
    ) -> list[SourceSafetyReceipt]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid source-consumer page")

        def read() -> list[SourceSafetyReceipt]:
            with self._connection() as connection:
                return [
                    self._receipt(row)
                    for row in connection.execute(
                        "SELECT * FROM source_safety_dispatches WHERE parent_id=? "
                        "ORDER BY rowid LIMIT ?",
                        (parent_id, limit),
                    )
                ]

        return await asyncio.to_thread(read)
