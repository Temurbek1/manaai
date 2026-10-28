"""Family v38: immutable cache-only tools and a separate bounded SQL inspection ledger."""

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.child_safety import SafetyJob
from app.mana_ai.domain.saved_observations import (
    SavedObservationLimits,
    SavedObservationReceipt,
    SavedObservationTarget,
)
from app.mana_ai.domain.source_tools import SourceToolPreparedInput
from app.services.compact_family_input_store import _original_profile
from app.services.compact_parent_publication_store import _publication_profile
from app.services.location_comparison_safety_store import (
    SqliteClosedLocationComparisonSafetyStore,
    SqliteLocationComparisonSafetyStore,
)

_TABLES = {"saved_observation_turns", "saved_observation_policy", "saved_observation_inspections"}


def _saved_profile(payload: str) -> tuple[str, Literal[1] | None]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ParentChatError("saved_observation_capture_invalid", 409)
    marker = data.pop("saved_observations", None)
    if marker is not None and (type(marker) is not int or marker != 1):
        raise ParentChatError("saved_observation_capture_invalid", 409)
    return (
        json.dumps(data, sort_keys=True, separators=(",", ":")) if marker else payload,
        1 if marker else None,
    )


class SqliteSavedObservationSafetyStore(SqliteLocationComparisonSafetyStore):
    _schema_version = 38

    def __init__(
        self,
        path: Path,
        *,
        saved_observations_enabled: bool = False,
        saved_observation_limits: SavedObservationLimits | None = None,
        **family: Any,
    ) -> None:
        self._saved_observations_enabled = saved_observations_enabled
        self._saved_observation_limits = SavedObservationLimits.model_validate(
            (saved_observation_limits or SavedObservationLimits()).model_dump()
        )
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {37}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS saved_observation_turns(
          parent_id TEXT NOT NULL,turn_id INTEGER NOT NULL,profile_hash TEXT NOT NULL,
          limits TEXT NOT NULL,PRIMARY KEY(parent_id,turn_id));
        CREATE TABLE IF NOT EXISTS saved_observation_policy(id INTEGER PRIMARY KEY CHECK(id=1),
          payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS saved_observation_inspections(
          job_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,child_id INTEGER NOT NULL,
          source TEXT NOT NULL,started_at TEXT NOT NULL,
          target TEXT NOT NULL,target_hash TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('claimed','completed','unavailable')),
          receipt TEXT,receipt_hash TEXT);
        CREATE INDEX IF NOT EXISTS saved_observation_rolling
          ON saved_observation_inspections(started_at);
        CREATE UNIQUE INDEX IF NOT EXISTS saved_observation_unresolved
          ON saved_observation_inspections(parent_id,child_id,source) WHERE status='claimed';
        """
        )

    def _initialize(self) -> None:
        payload = self._saved_observation_limits.model_dump_json()
        if self._path.exists():
            with self._connect() as db:
                if db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='saved_observation_policy'"
                ).fetchone():
                    old = db.execute(
                        "SELECT payload FROM saved_observation_policy WHERE id=1"
                    ).fetchone()
                    if old is not None and old[0] != payload:
                        raise ValueError(
                            "Saved SQL inspection limits cannot reset existing admissions"
                        )
        super()._initialize()
        with self._transaction() as db:
            db.execute("INSERT OR IGNORE INTO saved_observation_policy VALUES(1,?)", (payload,))
            if (
                db.execute("SELECT payload FROM saved_observation_policy WHERE id=1").fetchone()[0]
                != payload
            ):
                raise ValueError("Saved SQL inspection limits cannot reset existing admissions")

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        super()._on_admitted(db, request, turn_id, now)
        row = db.execute(
            "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?",
            (request.parent_id, turn_id),
        ).fetchone()
        if not self._saved_observations_enabled or row is None:
            return
        if super()._captured_protocol(row[0]) != 3:
            return
        payload = json.dumps(
            json.loads(row[0]) | {"saved_observations": 1}, sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()
        db.execute(
            "UPDATE source_tool_turns SET profile=? WHERE parent_id=? AND turn_id=?",
            (payload, request.parent_id, turn_id),
        )
        # These rows were inserted above in this same new-turn transaction. Historical
        # turns are never visited or rehashed when the setting is enabled.
        for table in ("family_input_presentations", "parent_publication_captures"):
            db.execute(
                f"UPDATE {table} SET profile_hash=? WHERE parent_id=? AND turn_id=?",
                (digest, request.parent_id, turn_id),
            )
        db.execute(
            "INSERT INTO saved_observation_turns VALUES(?,?,?,?)",
            (request.parent_id, turn_id, digest, self._saved_observation_limits.model_dump_json()),
        )

    def _saved_capture(self, db: sqlite3.Connection, parent: str, turn: int | None) -> bool:
        row = db.execute(
            "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?", (parent, turn)
        ).fetchone()
        capture = db.execute(
            "SELECT profile_hash,limits FROM saved_observation_turns "
            "WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        marker = _saved_profile(row[0])[1] if row else None
        if marker is None and capture is None:
            return False
        if (
            row is None
            or marker != 1
            or capture is None
            or capture[0] != hashlib.sha256(row[0].encode()).hexdigest()
            or capture[1] != self._saved_observation_limits.model_dump_json()
        ):
            raise ParentChatError("saved_observation_capture_invalid", 409)
        if not self._saved_observations_enabled:
            raise ParentChatError("saved_observations_disabled", 503)
        return True

    def _captured_protocol(self, payload: str) -> int:
        original, marker = _saved_profile(payload)
        protocol = super()._captured_protocol(original)
        if marker:
            if not self._saved_observations_enabled:
                raise ParentChatError("saved_observations_disabled", 503)
            if protocol != 3:
                raise ParentChatError("saved_observation_capture_invalid", 409)
            return 4
        return protocol

    def _location_prompt(self, db: sqlite3.Connection, parent: str, turn: int) -> Literal[2] | None:
        row = db.execute(
            "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?", (parent, turn)
        ).fetchone()
        original = (
            _original_profile(_publication_profile(_saved_profile(row[0])[0])[0])[0]
            if row
            else None
        )
        return 2 if original == self._location_native_policy else None

    def _validate_native_scope(
        self, db: sqlite3.Connection, job: SafetyJob, prepared: SourceToolPreparedInput
    ) -> None:
        super()._validate_native_scope(db, job, prepared)
        captured = self._saved_capture(db, job.view.parent_id, job.view.parent_turn_cutoff)
        if prepared.scope.saved_observations_enabled is not (True if captured else None):
            raise ParentChatError("saved_observation_capture_invalid", 409)

    def _validate_safety_publication(
        self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> None:
        super()._validate_safety_publication(db, row, now)
        if row["kind"] == "parent_message":
            self._saved_capture(db, row["parent_id"], row["parent_turn_cutoff"])

    def _validate_chat_submission(
        self, db: sqlite3.Connection, turn: StoredChatTurn, now: datetime
    ) -> None:
        super()._validate_chat_submission(db, turn, now)
        self._saved_capture(db, turn.parent_id, turn.turn_id)

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        try:
            self._saved_capture(db, turn.parent_id, turn.turn_id)
        except ParentChatError:
            return False
        return super()._valid_decision(db, turn, receipt, now)

    def _claim_saved_observation(
        self, db: sqlite3.Connection, job: SafetyJob, target: SavedObservationTarget, now: datetime
    ) -> None:
        if not self._saved_capture(db, job.view.parent_id, job.view.parent_turn_cutoff):
            raise ParentChatError("saved_observation_capture_invalid", 409)
        if db.execute(
            "SELECT 1 FROM saved_observation_inspections WHERE parent_id=? "
            "AND child_id=? AND source=? AND status='claimed'",
            (target.parent_id, target.child_id, target.source),
        ).fetchone():
            raise ParentChatError("saved_observation_inspection_unresolved", 409)
        counts = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(parent_id=?),0) "
            "FROM saved_observation_inspections WHERE started_at>?",
            (target.parent_id, (now - timedelta(days=1)).isoformat()),
        ).fetchone()
        if (
            counts[0] >= self._saved_observation_limits.global_inspections_per_24h
            or counts[1] >= self._saved_observation_limits.parent_inspections_per_24h
        ):
            raise ParentChatError("saved_observation_inspection_limit", 429)
        payload = target.model_dump_json()
        db.execute(
            "INSERT INTO saved_observation_inspections VALUES(?,?,?,?,?,?,?,'claimed',NULL,NULL)",
            (
                str(job.view.job_id),
                target.parent_id,
                target.child_id,
                target.source,
                now.isoformat(),
                payload,
                hashlib.sha256(payload.encode()).hexdigest(),
            ),
        )

    def _record_saved_observation(
        self,
        db: sqlite3.Connection,
        job: SafetyJob,
        receipt: SavedObservationReceipt,
        now: datetime,
    ) -> None:
        row = db.execute(
            "SELECT * FROM saved_observation_inspections WHERE job_id=? AND parent_id=?",
            (str(job.view.job_id), job.view.parent_id),
        ).fetchone()
        if (
            row is None
            or row["status"] != "claimed"
            or row["target_hash"] != hashlib.sha256(row["target"].encode()).hexdigest()
            or SavedObservationTarget.model_validate_json(row["target"])
            != SavedObservationTarget.model_validate(
                receipt.model_dump(include=set(SavedObservationTarget.model_fields))
            )
            or not datetime.fromisoformat(row["started_at"]) <= receipt.inspected_at <= now
        ):
            raise ParentChatError("saved_observation_inspection_mismatch", 409)
        payload = receipt.model_dump_json()
        db.execute(
            "UPDATE saved_observation_inspections SET status=?,receipt=?,receipt_hash=? "
            "WHERE job_id=?",
            (
                receipt.status,
                payload,
                hashlib.sha256(payload.encode()).hexdigest(),
                str(job.view.job_id),
            ),
        )


class SqliteClosedSavedObservationSafetyStore(SqliteClosedLocationComparisonSafetyStore):
    _schema_version = 38

    def __init__(self, path: Path, **family: Any) -> None:
        super().__init__(path, **family)
        self._schema_version = 38

    def _supported_versions(self) -> set[int]:
        return {38}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | _TABLES
