"""Family v41: new native-v5 frames; old native reads retain exact captures."""

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.application.compact_source_tools import compact_source_frame_hash
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.child_safety import SafetyJob
from app.mana_ai.domain.source_tools import SourceToolPreparedInput
from app.services.compact_family_input_store import _original_profile
from app.services.compact_parent_publication_store import _publication_profile
from app.services.literal_tariff_followup_store import (
    SqliteClosedLiteralTariffFollowupStore,
    SqliteLiteralTariffFollowupStore,
)
from app.services.saved_observation_safety_store import _saved_profile

_TABLE = "compact_source_tool_turns"


def _compact_source_profile(payload: str) -> tuple[str, bool]:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ParentChatError("compact_source_capture_invalid", 409)
    marker = value.pop("compact_source_tools", None)
    if marker is not None and (type(marker) is not int or marker != 1):
        raise ParentChatError("compact_source_capture_invalid", 409)
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":")) if marker else payload,
        marker == 1,
    )


class SqliteCompactSourceToolStore(SqliteLiteralTariffFollowupStore):
    _schema_version = 41

    def __init__(
        self, path: Path, *, compact_source_tools_enabled: bool = False, **family: Any
    ) -> None:
        self._compact_source_tools_enabled = compact_source_tools_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {40}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS compact_source_tool_turns(
          parent_id TEXT NOT NULL,turn_id INTEGER NOT NULL,profile_hash TEXT NOT NULL,
          frame_hash TEXT NOT NULL,PRIMARY KEY(parent_id,turn_id));
        """
        )

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        super()._on_admitted(db, request, turn_id, now)
        native = db.execute(
            "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?",
            (request.parent_id, turn_id),
        ).fetchone()
        if not self._compact_source_tools_enabled or native is None:
            return
        if super()._captured_protocol(native[0]) != 4:
            raise ParentChatError("compact_source_capture_invalid", 409)
        payload = json.dumps(
            json.loads(native[0]) | {"compact_source_tools": 1},
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()
        db.execute(
            "UPDATE source_tool_turns SET profile=? WHERE parent_id=? AND turn_id=?",
            (payload, request.parent_id, turn_id),
        )
        for table in (
            "family_input_presentations",
            "parent_publication_captures",
            "saved_observation_turns",
        ):
            db.execute(
                f"UPDATE {table} SET profile_hash=? WHERE parent_id=? AND turn_id=?",
                (digest, request.parent_id, turn_id),
            )
        db.execute(
            "INSERT INTO compact_source_tool_turns VALUES(?,?,?,?)",
            (request.parent_id, turn_id, digest, compact_source_frame_hash()),
        )

    def _compact_source_capture(
        self, db: sqlite3.Connection, parent: str, turn: int | None
    ) -> bool:
        native = db.execute(
            "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?", (parent, turn)
        ).fetchone()
        row = db.execute(
            "SELECT profile_hash,frame_hash FROM compact_source_tool_turns "
            "WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        marker = _compact_source_profile(native[0])[1] if native else False
        if row is None and not marker:
            return False
        if (
            native is None
            or row is None
            or not marker
            or row[0] != hashlib.sha256(native[0].encode()).hexdigest()
            or row[1] != compact_source_frame_hash()
        ):
            raise ParentChatError("compact_source_capture_invalid", 409)
        if not self._compact_source_tools_enabled:
            raise ParentChatError("compact_source_tools_disabled", 503)
        return True

    def _captured_protocol(self, payload: str) -> int:
        original, marker = _compact_source_profile(payload)
        protocol = super()._captured_protocol(original)
        if marker:
            if not self._compact_source_tools_enabled:
                raise ParentChatError("compact_source_tools_disabled", 503)
            if protocol != 4:
                raise ParentChatError("compact_source_capture_invalid", 409)
            return 5
        return protocol

    def _location_prompt(self, db: sqlite3.Connection, parent: str, turn: int) -> Literal[2] | None:
        row = db.execute(
            "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?", (parent, turn)
        ).fetchone()
        original = (
            _original_profile(
                _publication_profile(_saved_profile(_compact_source_profile(row[0])[0])[0])[0]
            )[0]
            if row
            else None
        )
        return 2 if original == self._location_native_policy else None

    def _validate_native_scope(
        self, db: sqlite3.Connection, job: SafetyJob, prepared: SourceToolPreparedInput
    ) -> None:
        super()._validate_native_scope(db, job, prepared)
        captured = self._compact_source_capture(db, job.view.parent_id, job.view.parent_turn_cutoff)
        if prepared.scope.request_projection_hash != (
            compact_source_frame_hash() if captured else None
        ):
            raise ParentChatError("compact_source_capture_invalid", 409)

    def _validate_safety_publication(
        self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> None:
        super()._validate_safety_publication(db, row, now)
        if row["kind"] == "parent_message":
            self._compact_source_capture(db, row["parent_id"], row["parent_turn_cutoff"])

    def _validate_chat_submission(
        self, db: sqlite3.Connection, turn: StoredChatTurn, now: datetime
    ) -> None:
        super()._validate_chat_submission(db, turn, now)
        self._compact_source_capture(db, turn.parent_id, turn.turn_id)

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        try:
            self._compact_source_capture(db, turn.parent_id, turn.turn_id)
        except ParentChatError:
            return False
        return super()._valid_decision(db, turn, receipt, now)


class SqliteClosedCompactSourceToolStore(SqliteClosedLiteralTariffFollowupStore):
    _schema_version = 41

    def __init__(self, path: Path, **family: Any) -> None:
        super().__init__(path, **family)
        self._schema_version = 41

    def _supported_versions(self) -> set[int]:
        return {41}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}
