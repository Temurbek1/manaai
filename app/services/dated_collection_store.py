"""Collection v3 captures one family/day acquisition in new 09:00/15:00 windows."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from app.mana_ai.domain.family_collection import (
    FamilyCollectionWindow,
    FamilyCollectionWork,
    FamilyInventoryPage,
)
from app.mana_ai.domain.family_day_usage import DAY_USAGE_SOURCE, DayUsageTarget
from app.mana_ai.domain.family_sources import FamilySourceKey, FamilySourceTarget, ObservedSourceKey
from app.services.family_collection_store import _TABLES
from app.services.inventory_tariff_store import _EXTRA_TABLES, SqliteInventoryTariffStore

_DAY_TABLES = {"collection_day_policy", "collection_day_windows", "collection_day_pages"}


class SqliteDatedCollectionStore(SqliteInventoryTariffStore):
    _schema_version = 3

    def __init__(
        self, path: Path, *, dated_enabled: bool = False, source_binding: str, **collection: Any
    ) -> None:
        if not source_binding or len(source_binding) > 512:
            raise ValueError("An immutable dated-source ledger binding is required")
        self._dated_enabled, self._day_binding = dated_enabled, source_binding
        super().__init__(path, **collection)

    def _valid_layout(self, tables: set[str], version: int) -> bool:
        return (
            super()._valid_layout(tables, version)
            or version == 3
            and tables == _TABLES | _EXTRA_TABLES | _DAY_TABLES
        )

    def _extra_schema(self, db: sqlite3.Connection) -> None:
        super()._extra_schema(db)
        db.execute(
            "CREATE TABLE IF NOT EXISTS collection_day_policy(id INTEGER PRIMARY KEY "
            "CHECK(id=1),source_binding TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS collection_day_windows(window_id TEXT PRIMARY "
            "KEY,enabled INTEGER NOT NULL CHECK(enabled IN (0,1)))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS collection_day_pages(page_id INTEGER PRIMARY "
            "KEY,enabled INTEGER NOT NULL CHECK(enabled IN (0,1)))"
        )
        db.execute("INSERT OR IGNORE INTO collection_day_policy VALUES(1,?)", (self._day_binding,))
        if (
            db.execute("SELECT source_binding FROM collection_day_policy WHERE id=1").fetchone()[0]
            != self._day_binding
        ):
            raise ValueError("Dated collection cannot switch the owning source ledger")
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS collection_one_day_family ON "
            "collection_queue(parent_id) WHERE source='manakids.family_day_app_usage.v1'"
        )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS collection_one_day_window ON "
            "collection_work(window_id,parent_id) WHERE "
            "source='manakids.family_day_app_usage.v1'"
        )

    @staticmethod
    def _captured(db: sqlite3.Connection, identity: str) -> bool:
        row = db.execute(
            "SELECT enabled FROM collection_day_windows WHERE window_id=?", (identity,)
        ).fetchone()
        return row is not None and bool(row[0])

    def _window_claimed(self, db: sqlite3.Connection, identity: str) -> None:
        db.execute(
            "INSERT INTO collection_day_windows VALUES(?,?)", (identity, int(self._dated_enabled))
        )

    def _page_claimed(self, db: sqlite3.Connection, page_id: int) -> None:
        super()._page_claimed(db, page_id)
        row = db.execute("SELECT window_id FROM collection_pages WHERE id=?", (page_id,)).fetchone()
        db.execute(
            "INSERT INTO collection_day_pages VALUES(?,?)",
            (page_id, int(self._dated_enabled and self._captured(db, row[0]))),
        )

    def _manifest_sources(
        self, db: sqlite3.Connection, identity: str
    ) -> tuple[ObservedSourceKey, ...]:
        if not self._captured(db, identity):
            return super()._manifest_sources(db, identity)
        return tuple(s for s in self.sources if s != "manakids.child_app_usage.v1") + (
            DAY_USAGE_SOURCE,
        )

    def _dispatch_sources(
        self, db: sqlite3.Connection, identity: str
    ) -> tuple[ObservedSourceKey, ...]:
        return self._manifest_sources(db, identity)

    def _inventory_sources(
        self, db: sqlite3.Connection, work: FamilyCollectionWork
    ) -> tuple[FamilySourceKey, ...]:
        return (
            tuple(s for s in self.sources if s != "manakids.child_app_usage.v1")
            if self._captured(db, str(work.window_id))
            else self.sources
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
            "SELECT enabled FROM collection_day_pages WHERE page_id=?", (work.position,)
        ).fetchone()
        if not self._dated_enabled or capture is None or not capture[0]:
            return
        fresh = [
            p
            for p in page.families
            if p.connected_child_ids
            and not db.execute(
                "SELECT 1 FROM collection_work WHERE window_id=? AND parent_id=? AND source=?",
                (str(work.window_id), p.parent_id, DAY_USAGE_SOURCE),
            ).fetchone()
        ]
        extra = sum(
            not db.execute(
                "SELECT 1 FROM collection_queue WHERE parent_id=? AND source=?",
                (p.parent_id, DAY_USAGE_SOURCE),
            ).fetchone()
            for p in fresh
        )
        if (
            db.execute("SELECT COUNT(*) FROM collection_queue").fetchone()[0] + extra
            > self.policy.maximum_queued_targets
        ):
            self._stop(db, str(work.window_id), "target_capacity", recorded_at)
            return
        for family in fresh:
            db.execute(
                "INSERT INTO collection_queue(parent_id,child_id,source,discovered_at) "
                "VALUES(?,?,?,?) ON CONFLICT(parent_id) WHERE "
                "source='manakids.family_day_app_usage.v1' DO UPDATE SET "
                "child_id=excluded.child_id,discovered_at=excluded.discovered_at",
                (
                    family.parent_id,
                    min(family.connected_child_ids),
                    DAY_USAGE_SOURCE,
                    recorded_at.isoformat(),
                ),
            )

    def _source_target(
        self, db: sqlite3.Connection, queued: sqlite3.Row, active: sqlite3.Row
    ) -> FamilySourceTarget | DayUsageTarget:
        if queued["source"] != DAY_USAGE_SOURCE:
            return super()._source_target(db, queued, active)
        if not self._dated_enabled or not self._captured(db, active["window_id"]):
            raise ValueError("Dated work requires its original enabled occurrence")
        day = datetime.fromisoformat(active["scheduled_at"]).astimezone(
            ZoneInfo("Asia/Tashkent")
        ).date() - timedelta(days=1)
        return DayUsageTarget(
            parent_id=queued["parent_id"],
            child_id=queued["child_id"],
            request_id=uuid5(
                UUID(active["window_id"]),
                "family-day-v1:" + queued["parent_id"] + ":" + day.isoformat(),
            ),
            requested_day=day,
        )

    def _claim_next(self, now: datetime) -> FamilyCollectionWork | FamilyCollectionWindow | None:
        if not self._dated_enabled:
            with self._connection() as db:
                active = db.execute(
                    "SELECT w.window_id FROM collection_windows w JOIN "
                    "collection_day_windows c ON c.window_id=w.window_id WHERE "
                    "w.status='collecting' AND c.enabled=1 LIMIT 1"
                ).fetchone()
                if active:
                    return self._stop(db, active[0], "dated_collection_disabled", now)
        return super()._claim_next(now)
