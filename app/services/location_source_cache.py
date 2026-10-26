"""Source v7: exact child location shares existing budgets, holds and review ownership."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.child_location import LOCATION_SOURCE
from app.mana_ai.domain.family_sources import (
    FamilySourceChange,
    FamilySourceClaim,
    FamilySourceKey,
    FamilySourceTarget,
    ObservedSourceKey,
)
from app.services.day_review_cache import SqliteDayReviewCache

_TABLES = frozenset({"location_policy", "location_snapshots", "location_heads"})


class SqliteLocationSourceCache(SqliteDayReviewCache):
    _schema_version = 7
    _extra_tables = SqliteDayReviewCache._extra_tables | _TABLES

    def __init__(self, path: Path, *, location_enabled: bool = False, **source: Any) -> None:
        self._location_enabled = location_enabled
        super().__init__(path, **source)

    def _upgrade_versions(self) -> set[int]:
        return super()._upgrade_versions() | {6}

    def _version_tables(self, version: int) -> set[str]:
        return (
            super()._version_tables(version) | set(SqliteDayReviewCache._extra_tables)
            if version == 6
            else super()._version_tables(version)
        )

    def _check_source(self, source: FamilySourceKey) -> None:
        if source != LOCATION_SOURCE:
            super()._check_source(source)

    def _snapshots(self, source: FamilySourceKey) -> str:
        return "location_snapshots" if source == LOCATION_SOURCE else super()._snapshots(source)

    def _heads(self, source: FamilySourceKey) -> str:
        return "location_heads" if source == LOCATION_SOURCE else super()._heads(source)

    def _circuit(self, source: FamilySourceKey) -> str:
        return "location_policy" if source == LOCATION_SOURCE else super()._circuit(source)

    def _extra_schema(self) -> tuple[str, ...]:
        return super()._extra_schema() + (
            "CREATE TABLE IF NOT EXISTS location_policy(id INTEGER PRIMARY KEY CHECK(id=1),"
            "blocked INTEGER NOT NULL DEFAULT 0)",
            "INSERT OR IGNORE INTO location_policy(id) VALUES(1)",
            "CREATE TABLE IF NOT EXISTS location_snapshots(snapshot_id TEXT PRIMARY KEY,"
            "parent_id TEXT NOT NULL,child_id INTEGER NOT NULL,fingerprint TEXT NOT NULL,"
            "payload TEXT NOT NULL,UNIQUE(parent_id,child_id,fingerprint))",
            "CREATE TABLE IF NOT EXISTS location_heads(parent_id TEXT NOT NULL,"
            "child_id INTEGER NOT NULL,snapshot_id TEXT NOT NULL,checked_at TEXT NOT NULL,"
            "PRIMARY KEY(parent_id,child_id))",
        )

    def _claim(self, target: FamilySourceTarget, now: datetime) -> FamilySourceClaim:
        if target.source == LOCATION_SOURCE and not self._location_enabled:
            with self._connection() as db:
                known = self._known(db, target)
                if known is not None:
                    return FamilySourceClaim(receipt=known, admitted=False, read_provider=False)
            raise ParentChatError("family_source_not_enabled", 503)
        return super()._claim(target, now)

    def _review_sources(self) -> tuple[ObservedSourceKey, ...]:
        return super()._review_sources() + ((LOCATION_SOURCE,) if self._location_enabled else ())

    def _source_changed(self, db: sqlite3.Connection, event: FamilySourceChange) -> None:
        super()._source_changed(db, event)
        if event.source == LOCATION_SOURCE and not self._location_enabled:
            db.execute(
                "UPDATE review_events SET phase='disabled' WHERE event_id=? AND phase='queued'",
                (str(event.event_id),),
            )
