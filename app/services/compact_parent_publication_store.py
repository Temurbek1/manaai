"""New-turn publication capture; prior native presentation and costs stay exact."""

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from app.mana_ai.application.chat_ports import ParentChatError
from app.mana_ai.domain.chat import ParentChatRequest
from app.services.compact_family_input_store import (
    SqliteClosedCompactFamilyInputStore,
    SqliteCompactFamilyInputStore,
    _original_profile,
)

_TABLE = "parent_publication_captures"


def _publication_profile(payload: str) -> tuple[str, Literal[1, 2, 3, 4, 5, 6] | None]:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ParentChatError("parent_publication_capture_invalid", 409)
    marker = value.pop("parent_publication", None)
    if marker is not None and (type(marker) is not int or marker not in {1, 2, 3, 4, 5, 6}):
        raise ParentChatError("parent_publication_capture_invalid", 409)
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":")) if marker else payload,
        cast(Literal[1, 2, 3, 4, 5, 6] | None, marker),
    )


class SqliteCompactParentPublicationStore(SqliteCompactFamilyInputStore):
    _schema_version = 36
    _publication_protocol: Literal[1, 2, 3, 4, 5, 6] = 4

    def __init__(
        self,
        path: Path,
        *,
        compact_publication_enabled: bool = False,
        compact_manager_enabled: bool = False,
        **family: Any,
    ) -> None:
        self._compact_publication_enabled = compact_publication_enabled
        self._compact_manager_enabled = compact_manager_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {35}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS parent_publication_captures(
          turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,
          version INTEGER NOT NULL CHECK(version=1),profile_hash TEXT NOT NULL,
          manager_binding TEXT NOT NULL);
        """
        )

    def _new_publication_protocol(
        self,
        db: sqlite3.Connection,
        request: ParentChatRequest,
        turn_id: int,
        now: datetime,
    ) -> Literal[1, 2, 3, 4, 5, 6]:
        return 5 if self._compact_manager_enabled else self._publication_protocol

    def _on_admitted(
        self, db: sqlite3.Connection, request: ParentChatRequest, turn_id: int, now: datetime
    ) -> None:
        super()._on_admitted(db, request, turn_id, now)
        manager = db.execute(
            "SELECT binding FROM parent_touch_manager_turns WHERE parent_id=? AND turn_id=?",
            (request.parent_id, turn_id),
        ).fetchone()
        native = db.execute(
            "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?",
            (request.parent_id, turn_id),
        ).fetchone()
        if not self._compact_publication_enabled or manager is None or native is None:
            return
        if super()._presentation(db, request.parent_id, turn_id) != 1:
            raise ParentChatError("parent_publication_capture_invalid", 409)
        payload = json.dumps(
            json.loads(native[0])
            | {"parent_publication": self._new_publication_protocol(db, request, turn_id, now)},
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()
        db.execute(
            "UPDATE source_tool_turns SET profile=? WHERE parent_id=? AND turn_id=?",
            (payload, request.parent_id, turn_id),
        )
        db.execute(
            "UPDATE family_input_presentations SET profile_hash=? WHERE parent_id=? AND turn_id=?",
            (fingerprint, request.parent_id, turn_id),
        )
        db.execute(
            "INSERT INTO parent_publication_captures VALUES(?,?,1,?,?)",
            (turn_id, request.parent_id, fingerprint, manager[0]),
        )

    def _publication(
        self, db: sqlite3.Connection, parent: str, turn: int | None
    ) -> Literal[1, 2, 3, 4, 5, 6] | None:
        native = db.execute(
            "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?", (parent, turn)
        ).fetchone()
        capture = db.execute(
            "SELECT version,profile_hash,manager_binding FROM parent_publication_captures "
            "WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        marker = _publication_profile(native[0])[1] if native else None
        if marker is None and capture is None:
            return None
        manager = db.execute(
            "SELECT binding FROM parent_touch_manager_turns WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        if (
            marker not in {1, 2, 3, 4, 5, 6}
            or capture is None
            or native is None
            or manager is None
            or capture[0] != 1
            or capture[1] != hashlib.sha256(native[0].encode()).hexdigest()
            or self._publication_manager_binding(db, parent, turn, capture[2]) != manager[0]
        ):
            raise ParentChatError("parent_publication_capture_invalid", 409)
        if marker in {5, 6} and not self._compact_manager_enabled:
            raise ParentChatError("compact_parent_manager_disabled", 503)
        if not self._compact_publication_enabled:
            raise ParentChatError("parent_publication_disabled", 503)
        return marker

    def _publication_manager_binding(
        self, db: sqlite3.Connection, parent: str, turn: int | None, binding: str
    ) -> str:
        """An owning captured extension may bind a new private decision protocol."""
        return binding

    def _presentation(
        self, db: sqlite3.Connection, parent: str, turn: int | None
    ) -> Literal[1] | None:
        result = super()._presentation(db, parent, turn)
        self._publication(db, parent, turn)
        return result

    async def parent_publication_version(
        self, parent_id: str, turn_id: int
    ) -> Literal[1, 2, 3, 4, 5, 6] | None:
        def read() -> Literal[1, 2, 3, 4, 5, 6] | None:
            with self._connect() as db:
                self._presentation(db, parent_id, turn_id)
                return self._publication(db, parent_id, turn_id)

        return await asyncio.to_thread(read)

    def _captured_protocol(self, payload: str) -> int:
        original, marker = _publication_profile(payload)
        if marker in {5, 6} and not self._compact_manager_enabled:
            raise ParentChatError("compact_parent_manager_disabled", 503)
        if marker and not self._compact_publication_enabled:
            raise ParentChatError("parent_publication_disabled", 503)
        return super()._captured_protocol(original)

    def _location_prompt(self, db: sqlite3.Connection, parent: str, turn: int) -> Literal[2] | None:
        row = db.execute(
            "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?", (parent, turn)
        ).fetchone()
        original = _original_profile(_publication_profile(row[0])[0])[0] if row else None
        return 2 if original == self._location_native_policy else None


class SqliteClosedCompactParentPublicationStore(SqliteClosedCompactFamilyInputStore):
    _schema_version = 36

    def __init__(self, path: Path, **family: Any) -> None:
        super().__init__(path, **family)
        self._schema_version = 36

    def _supported_versions(self) -> set[int]:
        return {36}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}
