"""Source-cache v3: shared request budget, independent provider caches/circuits."""

import sqlite3

from app.mana_ai.domain.family_sources import FamilySourceKey
from app.services.source_safety_store import SqliteSourceSafetyStore

_USAGE_TABLES = frozenset({"usage_snapshots", "usage_heads", "usage_policy"})


class SqliteMultiFamilySourceStore(SqliteSourceSafetyStore):
    _schema_version = 3
    _extra_tables = SqliteSourceSafetyStore._extra_tables | _USAGE_TABLES

    def _upgrade_versions(self) -> set[int]:
        return {1, 2}

    def _version_tables(self, version: int) -> set[str]:
        base = super()._version_tables(version)
        return base | set(SqliteSourceSafetyStore._extra_tables) if version == 2 else base

    def _check_source(self, source: FamilySourceKey) -> None:
        if source not in {"firebase.child_battery.v1", "manakids.child_app_usage.v1"}:
            raise ValueError("Unsupported family source")

    def _snapshots(self, source: FamilySourceKey) -> str:
        return "source_snapshots" if source == "firebase.child_battery.v1" else "usage_snapshots"

    def _heads(self, source: FamilySourceKey) -> str:
        return "source_heads" if source == "firebase.child_battery.v1" else "usage_heads"

    def _circuit(self, source: FamilySourceKey) -> str:
        return "source_policy" if source == "firebase.child_battery.v1" else "usage_policy"

    def _extra_schema(self) -> tuple[str, ...]:
        return super()._extra_schema() + (
            "CREATE TABLE IF NOT EXISTS usage_policy "
            "(id INTEGER PRIMARY KEY CHECK(id=1), blocked INTEGER NOT NULL DEFAULT 0)",
            "INSERT OR IGNORE INTO usage_policy(id) VALUES(1)",
            "CREATE TABLE IF NOT EXISTS usage_snapshots ("
            "snapshot_id TEXT PRIMARY KEY, parent_id TEXT NOT NULL, child_id INTEGER NOT NULL, "
            "fingerprint TEXT NOT NULL, payload TEXT NOT NULL, "
            "UNIQUE(parent_id,child_id,fingerprint))",
            "CREATE TABLE IF NOT EXISTS usage_heads ("
            "parent_id TEXT NOT NULL, child_id INTEGER NOT NULL, snapshot_id TEXT NOT NULL, "
            "checked_at TEXT NOT NULL, PRIMARY KEY(parent_id,child_id))",
        )

    def _initialize_additional(self, connection: sqlite3.Connection) -> None:
        super()._initialize_additional(connection)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS source_change_kind_cursor ON source_changes"
            "(COALESCE(json_extract(payload,'$.source'),'firebase.child_battery.v1'),id)"
        )
        connection.execute("DROP INDEX IF EXISTS source_one_unresolved")
        connection.execute(
            "CREATE UNIQUE INDEX source_one_unresolved ON source_reads"
            "(child_id,json_extract(payload,'$.source')) WHERE status IN ('pending','unknown')"
        )
