"""Read only a terminal, already minimized collection publication for administrators."""

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.mana_ai.domain.family_collection import FamilyCollectionWindow
from app.mana_operation_ai.application.ports import ProviderPermanentError
from app.mana_operation_ai.domain.family_collection import (
    SavedCollectionFacts,
    SavedSourceCoverage,
)


class SavedFamilyCollectionAdapter:
    def __init__(self, path: Path, *, expected_binding: str) -> None:
        if not path.is_absolute() or not expected_binding.startswith("mana:"):
            raise ValueError("An explicit absolute MANA collection path and binding are required")
        self._path, self._binding = path, expected_binding

    async def collect(self, now: datetime, *, maximum_age_seconds: int) -> SavedCollectionFacts:
        try:
            return await asyncio.to_thread(self._read, now, maximum_age_seconds)
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
            # Never expose private paths, raw SQL, payloads or exception prose.
            raise ProviderPermanentError("saved_family_collection_unavailable") from None

    def _read(self, now: datetime, maximum_age_seconds: int) -> SavedCollectionFacts:
        if (
            now.utcoffset() is None
            or any(path.is_symlink() for path in (self._path, *self._path.parents))
            or not self._path.is_file()
        ):
            raise ValueError("A readable collection is required")
        with sqlite3.connect(self._path.as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA application_id").fetchone()[0] != 1296125527 or db.execute(
                "PRAGMA user_version"
            ).fetchone()[0] not in {1, 2, 3, 4}:
                raise ValueError("Unsupported collection storage")
            policy = db.execute("SELECT configuration FROM collection_policy WHERE id=1").fetchone()
            if policy is None or not isinstance(policy[0], str) or len(policy[0]) > 16384:
                raise ValueError("Invalid collection binding")
            if json.loads(policy[0])["binding"] != self._binding:
                raise ValueError("Collection binding mismatch")
            row = db.execute(
                "SELECT publication,scheduled_at,window_id,status,published_at,deadline "
                "FROM collection_windows "
                "WHERE publication IS NOT NULL ORDER BY scheduled_at DESC LIMIT 1"
            ).fetchone()
            if row is None or not isinstance(row[0], str) or len(row[0]) > 65536:
                raise ValueError("No bounded saved publication")
            window = FamilyCollectionWindow.model_validate_json(row[0], strict=True)
            if (
                window.scheduled_at.isoformat() != row[1]
                or str(window.window_id) != row[2]
                or window.status != row[3]
                or window.published_at is None
                or window.published_at.isoformat() != row[4]
                or window.deadline.isoformat() != row[5]
            ):
                raise ValueError("Publication identity mismatch")
        if window.published_at is None or window.status == "collecting":
            raise ValueError("Only terminal publications are available")
        # Host-owned allowlisted projection: discard free-form reasons/limitations.
        facts = SavedCollectionFacts(
            window_id=window.window_id,
            scheduled_at=window.scheduled_at,
            deadline=window.deadline,
            published_at=window.published_at,
            inspected_at=now,
            status=window.status,
            parents_seen=window.parents_seen,
            total_parents_reported=window.total_parents_reported,
            inventory_start_offset=window.inventory_start_offset,
            inventory_exhausted=window.inventory_exhausted,
            inventory_changed=window.inventory_changed,
            pages=window.pages,
            targets=window.targets,
            pending_targets=window.pending_targets,
            counts=tuple(
                SavedSourceCoverage.model_validate(
                    {key: getattr(item, key) for key in SavedSourceCoverage.model_fields}
                )
                for item in window.counts
            ),
        )
        if facts.age_seconds(now) > maximum_age_seconds:
            raise ValueError("Saved collection is stale")
        return facts
