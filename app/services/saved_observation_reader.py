"""Read-only inspection of an existing source ledger; no create/migrate/read-provider path."""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.family_day_usage import (
    DAY_USAGE_SOURCE,
    FamilyDayUsagePage,
    day_child_fingerprint,
)
from app.mana_ai.domain.family_sources import (
    ChildSourceFacts,
    FamilySourceLimits,
    ObservedSourceKey,
    source_facts,
)
from app.mana_ai.domain.saved_observations import (
    SavedObservationReason,
    SavedObservationReceipt,
    SavedObservationTarget,
)
from app.services.day_usage_cache import day_page_fingerprint
from app.services.family_source_store import _APPLICATION, _TABLES
from app.services.location_comparison_cache import SqliteLocationComparisonCache
from app.services.location_source_cache import SqliteLocationSourceCache
from app.services.usage_comparison_cache import SqliteUsageComparisonCache


class SqliteSavedObservationReader:
    def __init__(
        self,
        path: Path,
        *,
        binding: str,
        limits: FamilySourceLimits,
        allowed_sources: tuple[ObservedSourceKey, ...],
        maximum_age_seconds: int = 21600,
    ) -> None:
        if (
            not path.is_absolute()
            or not binding
            or not allowed_sources
            or len(set(allowed_sources)) != len(allowed_sources)
        ):
            raise ValueError(
                "Saved inspection requires an explicit source binding and absolute path"
            )
        if type(maximum_age_seconds) is not int or not 60 <= maximum_age_seconds <= 86400:
            raise ValueError("Saved inspection requires a bounded provider-check age")
        self._path, self._binding = path, binding
        self._limits = FamilySourceLimits.model_validate(limits.model_dump())
        self._allowed = allowed_sources
        self._maximum_age = maximum_age_seconds

    async def inspect(
        self, target: SavedObservationTarget, now: datetime
    ) -> SavedObservationReceipt:
        return await asyncio.to_thread(self._inspect, target, now)

    def _inspect(self, target: SavedObservationTarget, now: datetime) -> SavedObservationReceipt:
        target = SavedObservationTarget.model_validate(target.model_dump())
        if now.utcoffset() is None:
            raise ValueError("Saved observation inspection requires an aware clock")
        now = now.astimezone(UTC)

        def unavailable(reason: SavedObservationReason) -> SavedObservationReceipt:
            return SavedObservationReceipt(
                **target.model_dump(), status="unavailable", inspected_at=now, reason=reason
            )

        if target.source not in self._allowed:
            return unavailable("source_not_enabled")
        if self._path.is_symlink() or self._path.parent.is_symlink() or not self._path.is_file():
            raise ParentChatError("saved_observation_storage_unavailable", 503)
        try:
            with sqlite3.connect(self._path.as_uri() + "?mode=ro", uri=True, timeout=10) as db:
                db.row_factory = sqlite3.Row
                db.execute("BEGIN")
                version = db.execute("PRAGMA user_version").fetchone()[0]
                expected = {
                    7: SqliteLocationSourceCache._extra_tables,
                    8: SqliteUsageComparisonCache._extra_tables,
                    9: SqliteLocationComparisonCache._extra_tables,
                    10: SqliteLocationComparisonCache._extra_tables
                    | {"location_time_admissions", "location_time_heads"},
                }.get(version)
                tables = {
                    r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if (
                    expected is None
                    or tables != _TABLES | expected
                    or db.execute("PRAGMA application_id").fetchone()[0] != _APPLICATION
                ):
                    raise ParentChatError("saved_observation_storage_invalid", 503)
                policy = db.execute(
                    "SELECT binding,limits FROM source_policy WHERE id=1"
                ).fetchone()
                if (
                    policy is None
                    or policy["binding"] != self._binding
                    or policy["limits"] != self._limits.model_dump_json()
                ):
                    raise ParentChatError("saved_observation_storage_invalid", 503)
                table, heads, circuit = {
                    "firebase.child_battery.v1": (
                        "source_snapshots",
                        "source_heads",
                        "source_policy",
                    ),
                    "manakids.child_app_usage.v1": (
                        "usage_snapshots",
                        "usage_heads",
                        "usage_policy",
                    ),
                    "firebase.child_location.v1": (
                        "location_snapshots",
                        "location_heads",
                        "location_policy",
                    ),
                    DAY_USAGE_SOURCE: (
                        "day_usage_snapshots",
                        "day_usage_heads",
                        "day_usage_policy",
                    ),
                }[target.source]
                if db.execute(f"SELECT blocked FROM {circuit} WHERE id=1").fetchone()[0]:
                    return unavailable("source_stopped")
                if db.execute(
                    "SELECT 1 FROM source_reads WHERE child_id=? "
                    "AND json_extract(payload,'$.source')=? AND status IN ('pending','unknown')",
                    (target.child_id, target.source),
                ).fetchone():
                    return unavailable("source_unresolved")
                if target.source == DAY_USAGE_SOURCE:
                    if db.execute(
                        "SELECT 1 FROM day_usage_ownership WHERE parent_id=? "
                        "AND status IN ('pending','unknown')",
                        (target.parent_id,),
                    ).fetchone():
                        return unavailable("source_unresolved")
                    row = db.execute(
                        f"SELECT s.*,h.checked_at FROM {heads} h JOIN {table} s "
                        "ON s.snapshot_id=h.snapshot_id AND s.parent_id=h.parent_id "
                        "AND s.day=h.day WHERE h.parent_id=? AND h.day=?",
                        (
                            target.parent_id,
                            target.requested_day.isoformat() if target.requested_day else None,
                        ),
                    ).fetchone()
                else:
                    row = db.execute(
                        f"SELECT s.*,h.checked_at FROM {heads} h JOIN {table} s "
                        "ON s.snapshot_id=h.snapshot_id AND s.parent_id=h.parent_id "
                        "AND s.child_id=h.child_id WHERE h.parent_id=? AND h.child_id=?",
                        (target.parent_id, target.child_id),
                    ).fetchone()
                if row is None:
                    return unavailable("saved_observation_missing")
                if len(row["payload"].encode()) > (
                    1048576 if target.source == DAY_USAGE_SOURCE else 65536
                ):
                    raise ParentChatError("saved_observation_storage_invalid", 503)
                checked = datetime.fromisoformat(row["checked_at"])
                if checked.utcoffset() is None or checked > now:
                    raise ParentChatError("saved_observation_storage_invalid", 503)
                if checked < now - timedelta(seconds=self._maximum_age):
                    return unavailable("saved_observation_stale")
                identity = UUID(row["snapshot_id"])
                if target.source == DAY_USAGE_SOURCE:
                    page = FamilyDayUsagePage.model_validate_json(row["payload"])
                    if (
                        page.parent_id != target.parent_id
                        or page.requested_day != target.requested_day
                        or day_page_fingerprint(page) != row["fingerprint"]
                    ):
                        raise ParentChatError("saved_observation_storage_invalid", 503)
                    selected = next(
                        (c for c in page.children if c.child_id == target.child_id), None
                    )
                    if selected is None:
                        return unavailable("saved_child_not_returned")
                    facts: ChildSourceFacts = selected
                    assert target.requested_day is not None
                    fingerprint = day_child_fingerprint(selected, target.requested_day)
                    identity = uuid5(identity, str(target.child_id))
                else:
                    facts = source_facts(json.loads(row["payload"]), target.source)
                    fingerprint = facts.fingerprint()
                    if facts.child_id != target.child_id or fingerprint != row["fingerprint"]:
                        raise ParentChatError("saved_observation_storage_invalid", 503)
                return SavedObservationReceipt(
                    **target.model_dump(),
                    status="completed",
                    inspected_at=now,
                    provider_checked_at=checked,
                    snapshot_id=identity,
                    fingerprint=fingerprint,
                    facts=facts,
                )
        except (ValueError, sqlite3.Error, KeyError, TypeError):
            raise ParentChatError("saved_observation_storage_invalid", 503) from None
