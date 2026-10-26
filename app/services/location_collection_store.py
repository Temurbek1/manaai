"""Collection v4 captures GPS only in new 09:00/15:00 occurrences, never a new timer."""

import sqlite3
from pathlib import Path
from typing import Any

from app.mana_ai.domain.child_location import LOCATION_SOURCE
from app.mana_ai.domain.family_collection import FamilyCollectionWork
from app.mana_ai.domain.family_sources import FamilySourceKey, ObservedSourceKey
from app.services.dated_collection_store import (
    _DAY_TABLES,
    SqliteDatedCollectionStore,
)
from app.services.family_collection_store import _TABLES
from app.services.inventory_tariff_store import _EXTRA_TABLES

_LOCATION_TABLE = "collection_location_windows"


class SqliteLocationCollectionStore(SqliteDatedCollectionStore):
    _schema_version = 4

    def __init__(self, path: Path, *, location_enabled: bool = False, **collection: Any) -> None:
        self._location_enabled = location_enabled
        super().__init__(path, **collection)

    def _valid_layout(self, tables: set[str], version: int) -> bool:
        return super()._valid_layout(tables, version) or (
            version == 4 and tables == _TABLES | _EXTRA_TABLES | _DAY_TABLES | {_LOCATION_TABLE}
        )

    def _extra_schema(self, db: sqlite3.Connection) -> None:
        super()._extra_schema(db)
        db.execute(
            "CREATE TABLE IF NOT EXISTS collection_location_windows(window_id TEXT PRIMARY "
            "KEY,enabled INTEGER NOT NULL CHECK(enabled IN (0,1)))"
        )

    def _window_claimed(self, db: sqlite3.Connection, identity: str) -> None:
        super()._window_claimed(db, identity)
        db.execute(
            "INSERT INTO collection_location_windows VALUES(?,?)",
            (identity, int(self._location_enabled)),
        )

    @staticmethod
    def _location_window(db: sqlite3.Connection, identity: str) -> bool:
        row = db.execute(
            "SELECT enabled FROM collection_location_windows WHERE window_id=?", (identity,)
        ).fetchone()
        return bool(row and row[0])

    def _manifest_sources(
        self, db: sqlite3.Connection, identity: str
    ) -> tuple[ObservedSourceKey, ...]:
        return super()._manifest_sources(db, identity) + (
            (LOCATION_SOURCE,) if self._location_window(db, identity) else ()
        )

    def _inventory_sources(
        self, db: sqlite3.Connection, work: FamilyCollectionWork
    ) -> tuple[FamilySourceKey, ...]:
        return super()._inventory_sources(db, work) + (
            (LOCATION_SOURCE,) if self._location_window(db, str(work.window_id)) else ()
        )
