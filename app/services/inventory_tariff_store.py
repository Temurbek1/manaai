"""Collection v2: immutable page completion and one-shot local tariff fan-out."""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from app.mana_ai.domain.family_collection import (
    FamilyCollectionPolicy,
    FamilyCollectionWork,
    FamilyInventoryPage,
)
from app.mana_ai.domain.family_sources import FamilySourceKey
from app.mana_ai.domain.inventory_tariffs import (
    InventoryTariffPolicy,
    InventoryTariffWork,
    TariffInventoryPage,
)
from app.mana_ai.domain.retention_expiry import RetentionTariffFact
from app.services.family_collection_store import (
    _TABLES,
    SqliteFamilyCollectionStore,
    _digest,
    _utc,
)

_EXTRA_TABLES = {
    "collection_tariff_policy",
    "collection_tariff_captures",
    "collection_tariff_batches",
}
_FACTS = TypeAdapter(tuple[RetentionTariffFact, ...])
_AUTH_ERRORS = {"family_inventory_auth_denied", "child_source_auth_denied"}


class SqliteInventoryTariffStore(SqliteFamilyCollectionStore):
    _schema_version = 2

    def __init__(
        self,
        path: Path,
        *,
        tariff_policy: InventoryTariffPolicy,
        recipient_binding: str,
        tariffs_enabled: bool,
        binding: str,
        policy: FamilyCollectionPolicy,
        sources: tuple[FamilySourceKey, ...],
    ) -> None:
        if not recipient_binding or len(recipient_binding) > 512:
            raise ValueError("An explicit private tariff receiver binding is required")
        self._tariff_policy = InventoryTariffPolicy.model_validate(tariff_policy.model_dump())
        self._recipient_binding, self._tariffs_enabled = recipient_binding, tariffs_enabled
        super().__init__(path, binding=binding, policy=policy, sources=sources)

    def _valid_layout(self, tables: set[str], version: int) -> bool:
        return (version == 1 and tables == _TABLES) or (
            version == 2 and tables == _TABLES | _EXTRA_TABLES
        )

    def _extra_schema(self, db: sqlite3.Connection) -> None:
        db.execute(
            "CREATE TABLE IF NOT EXISTS collection_tariff_policy(id INTEGER PRIMARY KEY "
            "CHECK(id=1),configuration TEXT NOT NULL,blocked TEXT)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS collection_tariff_captures(page_id INTEGER PRIMARY KEY,"
            "enabled INTEGER NOT NULL CHECK(enabled IN (0,1)))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS collection_tariff_batches(page_id INTEGER PRIMARY KEY,"
            "window_id TEXT NOT NULL,page_hash TEXT NOT NULL,payload TEXT NOT NULL,"
            "facts_hash TEXT NOT NULL,collected_at TEXT NOT NULL,phase TEXT NOT NULL,"
            "claim_id TEXT,expires_at TEXT)"
        )
        config = json.dumps(
            {"policy": self._tariff_policy.model_dump(), "recipient": self._recipient_binding},
            sort_keys=True,
        )
        db.execute("INSERT OR IGNORE INTO collection_tariff_policy VALUES(1,?,NULL)", (config,))
        if db.execute("SELECT configuration FROM collection_tariff_policy").fetchone()[0] != config:
            raise ValueError("Tariff consumer policy/recipient cannot change behind page receipts")

    def _page_claimed(self, db: sqlite3.Connection, page_id: int) -> None:
        db.execute(
            "INSERT INTO collection_tariff_captures VALUES(?,?)",
            (page_id, int(self._tariffs_enabled)),
        )

    def _validated_page(self, page: FamilyInventoryPage) -> FamilyInventoryPage:
        if isinstance(page, TariffInventoryPage):
            return TariffInventoryPage.model_validate(page.model_dump())
        return super()._validated_page(page)

    def _page_recorded(
        self,
        db: sqlite3.Connection,
        work: FamilyCollectionWork,
        page: FamilyInventoryPage,
        *,
        recorded_at: datetime,
    ) -> None:
        captured = db.execute(
            "SELECT enabled FROM collection_tariff_captures WHERE page_id=?", (work.position,)
        ).fetchone()
        if not self._tariffs_enabled or not captured or not captured[0]:
            return
        if not isinstance(page, TariffInventoryPage):
            raise ValueError("A newly captured tariff page requires its exact minimized facts")
        if not page.tariff_facts:
            return
        if (
            db.execute("SELECT blocked FROM collection_tariff_policy").fetchone()[0]
            or db.execute("SELECT COUNT(*) FROM collection_tariff_batches").fetchone()[0]
            >= self._tariff_policy.maximum_batches
        ):
            db.execute(
                "UPDATE collection_tariff_policy SET blocked=COALESCE(blocked,'capacity') "
                "WHERE id=1"
            )
            return
        facts = tuple(
            f.model_copy(
                update={
                    "collected_at": f.collected_at.astimezone(UTC),
                    "valid_until": f.valid_until.astimezone(UTC) if f.valid_until else None,
                }
            )
            for f in page.tariff_facts
        )
        payload = _FACTS.dump_json(facts).decode()
        db.execute(
            "INSERT INTO collection_tariff_batches(page_id,window_id,page_hash,payload,"
            "facts_hash,collected_at,phase) VALUES(?,?,?,?,?,?,'waiting')",
            (
                work.position,
                str(work.window_id),
                _digest(page.model_dump_json()),
                payload,
                _digest(payload),
                page.collected_at.astimezone(UTC).isoformat(),
            ),
        )

    async def inventory_auth_revoked(self) -> bool:
        def read() -> bool:
            with self._connection() as db:
                return (
                    db.execute("SELECT inventory_blocked FROM collection_policy").fetchone()[0]
                    in _AUTH_ERRORS
                )

        return await asyncio.to_thread(read)

    async def claim_tariffs(self, now: datetime) -> InventoryTariffWork | None:
        return await asyncio.to_thread(self._claim_tariffs, _utc(now))

    def _claim_tariffs(self, now: datetime) -> InventoryTariffWork | None:
        if not self._tariffs_enabled:
            return None
        with self._connection() as db:
            db.execute(
                "UPDATE collection_tariff_batches SET phase='unknown' WHERE phase='claimed' "
                "AND expires_at<=?",
                (now.isoformat(),),
            )
            if db.execute("SELECT blocked FROM collection_tariff_policy").fetchone()[0]:
                return None
            if (
                db.execute("SELECT inventory_blocked FROM collection_policy").fetchone()[0]
                in _AUTH_ERRORS
            ):
                return None
            earliest = now - timedelta(seconds=self._tariff_policy.maximum_age_seconds)
            db.execute(
                "UPDATE collection_tariff_batches SET phase='stale' WHERE phase='waiting' "
                "AND collected_at<?",
                (earliest.isoformat(),),
            )
            row = db.execute(
                "SELECT b.*,p.phase AS page_phase,p.payload_hash AS original_hash,"
                "p.window_id AS original_window,c.enabled FROM collection_tariff_batches b "
                "JOIN collection_pages p ON p.id=b.page_id JOIN collection_tariff_captures c "
                "ON c.page_id=b.page_id WHERE b.phase='waiting' ORDER BY b.page_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            try:
                if len(row["payload"]) > 65536:
                    raise ValueError("Tariff page payload exceeds its retained ceiling")
                facts = _FACTS.validate_json(row["payload"])
                if (
                    row["page_phase"] != "recorded"
                    or not row["enabled"]
                    or row["page_hash"] != row["original_hash"]
                    or row["window_id"] != row["original_window"]
                    or _digest(row["payload"]) != row["facts_hash"]
                    or not 1 <= len(facts) <= 100
                    or len({f.parent_id for f in facts}) != len(facts)
                    or any(f.collected_at.isoformat() != row["collected_at"] for f in facts)
                    or not earliest <= datetime.fromisoformat(row["collected_at"]) <= now
                ):
                    raise ValueError("Invalid durable tariff page pairing")
            except ValueError:
                db.execute("UPDATE collection_tariff_policy SET blocked='integrity' WHERE id=1")
                return None
            claim = uuid4()
            expires = min(
                now + timedelta(seconds=self._tariff_policy.claim_seconds),
                datetime.fromisoformat(row["collected_at"])
                + timedelta(seconds=self._tariff_policy.maximum_age_seconds),
            )
            db.execute(
                "UPDATE collection_tariff_batches SET phase='claimed',claim_id=?,expires_at=? "
                "WHERE page_id=?",
                (str(claim), expires.isoformat(), row["page_id"]),
            )
            return InventoryTariffWork(
                page_id=row["page_id"],
                window_id=row["window_id"],
                claim_id=claim,
                page_hash=row["page_hash"],
                facts_hash=row["facts_hash"],
                facts=facts,
                expires_at=expires,
            )

    async def finish_tariffs(
        self, work: InventoryTariffWork, now: datetime, *, accepted: bool | None
    ) -> None:
        def finish() -> None:
            with self._connection() as db:
                row = db.execute(
                    "SELECT * FROM collection_tariff_batches WHERE page_id=? AND claim_id=?",
                    (work.page_id, str(work.claim_id)),
                ).fetchone()
                if (
                    row is None
                    or row["window_id"] != str(work.window_id)
                    or row["facts_hash"] != work.facts_hash
                    or row["page_hash"] != work.page_hash
                ):
                    raise ValueError("Tariff completion requires its original page claim")
                if row["phase"] != "claimed":
                    return
                phase = (
                    "unknown"
                    if accepted is None or _utc(now) >= datetime.fromisoformat(row["expires_at"])
                    else "applied"
                    if accepted
                    else "refused"
                )
                db.execute(
                    "UPDATE collection_tariff_batches SET phase=? WHERE page_id=?",
                    (phase, work.page_id),
                )

        await asyncio.to_thread(finish)
