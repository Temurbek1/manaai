"""Collection v5: one durable local setup consumer per newly captured known page."""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.mana_ai.domain.family_collection import FamilyCollectionWork, FamilyInventoryPage
from app.mana_ai.domain.parent_setup import (
    ParentSetupBatch,
    ParentSetupFact,
    ParentSetupPolicy,
    SetupInventoryWork,
)
from app.services.family_collection_store import _digest, _utc
from app.services.location_collection_store import SqliteLocationCollectionStore

_TABLES = {"collection_setup_policy", "collection_setup_captures", "collection_setup_batches"}


class SqliteSetupCollectionStore(SqliteLocationCollectionStore):
    _schema_version = 5

    def __init__(
        self,
        path: Path,
        *,
        setup_enabled: bool = False,
        setup_policy: ParentSetupPolicy | None = None,
        setup_recipient_binding: str,
        **collection: Any,
    ) -> None:
        if not setup_recipient_binding or len(setup_recipient_binding) > 512:
            raise ValueError("An exact setup recipient binding is required")
        self._setup_enabled = setup_enabled
        self._setup_policy = ParentSetupPolicy.model_validate(
            (setup_policy or ParentSetupPolicy()).model_dump()
        )
        self._setup_recipient = setup_recipient_binding
        super().__init__(path, **collection)

    def _valid_layout(self, tables: set[str], version: int) -> bool:
        return super()._valid_layout(tables, version) or (
            version == 5 and tables >= _TABLES and super()._valid_layout(tables - _TABLES, 4)
        )

    def _extra_schema(self, db: sqlite3.Connection) -> None:
        super()._extra_schema(db)
        db.execute(
            "CREATE TABLE IF NOT EXISTS collection_setup_policy("
            "id INTEGER PRIMARY KEY CHECK(id=1),configuration TEXT NOT NULL,blocked TEXT)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS collection_setup_captures("
            "page_id INTEGER PRIMARY KEY,enabled INTEGER NOT NULL CHECK(enabled IN(0,1)))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS collection_setup_batches("
            "page_id INTEGER PRIMARY KEY,window_id TEXT NOT NULL,page_hash TEXT NOT NULL,"
            "payload TEXT NOT NULL,digest TEXT NOT NULL,collected_at TEXT NOT NULL,"
            "phase TEXT NOT NULL,claim_id TEXT,deadline TEXT)"
        )
        config = json.dumps(
            {"recipient": self._setup_recipient, "policy": self._setup_policy.model_dump()},
            sort_keys=True,
        )
        db.execute("INSERT OR IGNORE INTO collection_setup_policy VALUES(1,?,NULL)", (config,))
        if db.execute("SELECT configuration FROM collection_setup_policy").fetchone()[0] != config:
            raise ValueError("Setup policy/recipient cannot reset captured pages")

    def _page_claimed(self, db: sqlite3.Connection, page_id: int) -> None:
        super()._page_claimed(db, page_id)
        db.execute(
            "INSERT INTO collection_setup_captures VALUES(?,?)", (page_id, int(self._setup_enabled))
        )

    def _page_recorded(
        self,
        db: sqlite3.Connection,
        work: FamilyCollectionWork,
        page: FamilyInventoryPage,
        *,
        recorded_at: datetime,
    ) -> None:
        super()._page_recorded(db, work, page, recorded_at=recorded_at)
        capture = db.execute(
            "SELECT enabled FROM collection_setup_captures WHERE page_id=?", (work.position,)
        ).fetchone()
        if not self._setup_enabled or not capture or not capture[0] or not page.families:
            return
        if (
            db.execute("SELECT blocked FROM collection_setup_policy").fetchone()[0]
            or db.execute("SELECT COUNT(*) FROM collection_setup_batches").fetchone()[0]
            >= self._setup_policy.maximum_batches
        ):
            db.execute("UPDATE collection_setup_policy SET blocked=COALESCE(blocked,'capacity')")
            return
        facts = tuple(
            ParentSetupFact(
                parent_id=f.parent_id,
                collected_at=page.collected_at.astimezone(UTC),
                connected_child_ids=f.connected_child_ids,
            )
            for f in page.families
            if f.children_complete is True
        )
        batch = ParentSetupBatch(
            facts=facts,
            unknown_parent_ids=tuple(
                f.parent_id for f in page.families if f.children_complete is not True
            ),
            collected_at=page.collected_at.astimezone(UTC),
        )
        payload = batch.model_dump_json()
        if len(payload.encode()) > 65536:
            db.execute("UPDATE collection_setup_policy SET blocked='capacity'")
            return
        db.execute(
            "INSERT INTO collection_setup_batches VALUES(?,?,?,?,?,?,'waiting',NULL,NULL)",
            (
                work.position,
                str(work.window_id),
                _digest(page.model_dump_json()),
                payload,
                _digest(payload),
                page.collected_at.astimezone(UTC).isoformat(),
            ),
        )

    async def claim_setup(self, now: datetime) -> SetupInventoryWork | None:
        return await asyncio.to_thread(self._claim_setup, _utc(now))

    def _claim_setup(self, now: datetime) -> SetupInventoryWork | None:
        with self._connection() as db:
            db.execute(
                "UPDATE collection_setup_batches SET phase='unknown' "
                "WHERE phase='claimed' AND deadline<=?",
                (now.isoformat(),),
            )
            if not self._setup_enabled:
                db.execute(
                    "UPDATE collection_setup_batches SET phase='disabled' WHERE phase='waiting'"
                )
                return None
            if (
                db.execute("SELECT blocked FROM collection_setup_policy").fetchone()[0]
                or db.execute("SELECT inventory_blocked FROM collection_policy").fetchone()[0]
            ):
                return None
            earliest = now - timedelta(seconds=self._setup_policy.maximum_age_seconds)
            db.execute(
                "UPDATE collection_setup_batches SET phase='stale' "
                "WHERE phase='waiting' AND collected_at<?",
                (earliest.isoformat(),),
            )
            row = db.execute(
                "SELECT b.*,p.phase AS page_phase,p.payload_hash AS original_hash,"
                "p.window_id AS original_window,c.enabled FROM collection_setup_batches b "
                "JOIN collection_pages p ON p.id=b.page_id "
                "JOIN collection_setup_captures c ON c.page_id=b.page_id "
                "WHERE b.phase='waiting' ORDER BY b.page_id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            try:
                batch = ParentSetupBatch.model_validate_json(row["payload"])
                if (
                    len(row["payload"].encode()) > 65536
                    or row["page_phase"] != "recorded"
                    or not row["enabled"]
                    or row["page_hash"] != row["original_hash"]
                    or row["window_id"] != row["original_window"]
                    or _digest(row["payload"]) != row["digest"]
                    or batch.collected_at.isoformat() != row["collected_at"]
                    or not earliest <= datetime.fromisoformat(row["collected_at"]) <= now
                ):
                    raise ValueError("Setup page pairing changed")
            except ValueError:
                db.execute("UPDATE collection_setup_policy SET blocked='integrity'")
                return None
            claim = uuid4()
            deadline = min(
                now + timedelta(seconds=self._setup_policy.batch_claim_seconds),
                datetime.fromisoformat(row["collected_at"])
                + timedelta(seconds=self._setup_policy.maximum_age_seconds),
            )
            db.execute(
                "UPDATE collection_setup_batches SET phase='claimed',claim_id=?,deadline=? "
                "WHERE page_id=?",
                (str(claim), deadline.isoformat(), row["page_id"]),
            )
            return SetupInventoryWork(
                page_id=row["page_id"],
                window_id=row["window_id"],
                claim_id=claim,
                facts=batch.facts,
                unknown_parent_ids=batch.unknown_parent_ids,
                collected_at=batch.collected_at,
                deadline=deadline,
            )

    async def finish_setup(
        self, work: SetupInventoryWork, now: datetime, *, accepted: bool | None
    ) -> None:
        def finish() -> None:
            with self._connection() as db:
                row = db.execute(
                    "SELECT * FROM collection_setup_batches WHERE page_id=? AND claim_id=?",
                    (work.page_id, str(work.claim_id)),
                ).fetchone()
                if (
                    row is None
                    or row["window_id"] != str(work.window_id)
                    or _digest(
                        ParentSetupBatch(
                            facts=work.facts,
                            unknown_parent_ids=work.unknown_parent_ids,
                            collected_at=work.collected_at,
                        ).model_dump_json()
                    )
                    != row["digest"]
                    or work.deadline.isoformat() != row["deadline"]
                ):
                    raise ValueError("Setup completion requires its exact original claim")
                if row["phase"] != "claimed":
                    return
                phase = (
                    "unknown"
                    if accepted is None or _utc(now) >= work.deadline
                    else "applied"
                    if accepted
                    else "refused"
                )
                db.execute(
                    "UPDATE collection_setup_batches SET phase=? WHERE page_id=?",
                    (phase, work.page_id),
                )

        await asyncio.to_thread(finish)
