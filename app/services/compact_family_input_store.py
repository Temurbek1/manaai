"""New-turn input presentation with immutable native/profile pairing."""

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from app.mana_ai.application.chat_ports import ChatModelReceipt, ParentChatError
from app.mana_ai.domain.chat import ParentChatRequest, StoredChatTurn
from app.mana_ai.domain.child_safety import SafetyJob
from app.mana_ai.domain.source_tools import SourceToolPreparedInput
from app.services.tariff_handoff_store import (
    SqliteClosedTariffHandoffStore,
    SqliteTariffHandoffStore,
)

_TABLE = "family_input_presentations"


def _original_profile(payload: str) -> tuple[str, int | None]:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ParentChatError("family_input_presentation_invalid", 409)
    marker = value.pop("input_presentation", None)
    if marker is not None and (type(marker) is not int or marker != 1):
        raise ParentChatError("family_input_presentation_invalid", 409)
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":")) if marker else payload,
        marker,
    )


class SqliteCompactFamilyInputStore(SqliteTariffHandoffStore):
    _schema_version = 35

    def __init__(self, path: Path, *, compact_inputs_enabled: bool = False, **family: Any) -> None:
        self._compact_inputs_enabled = compact_inputs_enabled
        super().__init__(path, **family)

    def _supported_versions(self) -> set[int]:
        return super()._supported_versions() | {34}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}

    def _extra_schema(self) -> str:
        return (
            super()._extra_schema()
            + """
        CREATE TABLE IF NOT EXISTS family_input_presentations(
            turn_id INTEGER PRIMARY KEY,parent_id TEXT NOT NULL,
            version INTEGER NOT NULL CHECK(version=1),profile_hash TEXT NOT NULL);
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
        if not self._compact_inputs_enabled or native is None:
            return
        payload = json.dumps(
            json.loads(native[0]) | {"input_presentation": 1},
            sort_keys=True,
            separators=(",", ":"),
        )
        db.execute(
            "UPDATE source_tool_turns SET profile=? WHERE parent_id=? AND turn_id=?",
            (payload, request.parent_id, turn_id),
        )
        db.execute(
            "INSERT INTO family_input_presentations VALUES(?,?,1,?)",
            (turn_id, request.parent_id, hashlib.sha256(payload.encode()).hexdigest()),
        )

    def _presentation(
        self, db: sqlite3.Connection, parent: str, turn: int | None
    ) -> Literal[1] | None:
        capture = db.execute(
            "SELECT version,profile_hash FROM family_input_presentations "
            "WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        native = db.execute(
            "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?",
            (parent, turn),
        ).fetchone()
        marker = _original_profile(native[0])[1] if native else None
        if capture is None and marker is None:
            return None
        if (
            capture is None
            or native is None
            or marker != 1
            or capture[0] != 1
            or hashlib.sha256(native[0].encode()).hexdigest() != capture[1]
        ):
            raise ParentChatError("family_input_presentation_invalid", 409)
        if not self._compact_inputs_enabled:
            raise ParentChatError("family_input_presentation_disabled", 503)
        return 1

    async def input_presentation(self, parent_id: str, turn_id: int) -> Literal[1] | None:
        def read() -> Literal[1] | None:
            with self._connect() as db:
                return self._presentation(db, parent_id, turn_id)

        return await asyncio.to_thread(read)

    async def native_input_presentation(self, job: SafetyJob) -> Literal[1] | None:
        return await self.input_presentation(job.view.parent_id, job.view.parent_turn_cutoff)

    def _captured_protocol(self, payload: str) -> int:
        original, marker = _original_profile(payload)
        if marker and not self._compact_inputs_enabled:
            raise ParentChatError("family_input_presentation_disabled", 503)
        return super()._captured_protocol(original)

    def _location_prompt(self, db: sqlite3.Connection, parent: str, turn: int) -> Literal[2] | None:
        row = db.execute(
            "SELECT profile FROM source_tool_turns WHERE parent_id=? AND turn_id=?", (parent, turn)
        ).fetchone()
        return 2 if row and _original_profile(row[0])[0] == self._location_native_policy else None

    def _validate_native_scope(
        self, db: sqlite3.Connection, job: SafetyJob, prepared: SourceToolPreparedInput
    ) -> None:
        super()._validate_native_scope(db, job, prepared)
        if prepared.scope.input_presentation != self._presentation(
            db, job.view.parent_id, job.view.parent_turn_cutoff
        ):
            raise ParentChatError("family_input_presentation_invalid", 409)

    def _validate_safety_publication(
        self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime
    ) -> None:
        super()._validate_safety_publication(db, row, now)
        if row["kind"] == "parent_message":
            self._presentation(db, row["parent_id"], row["parent_turn_cutoff"])

    async def submit(self, turn: StoredChatTurn, *, reserved_tokens: int, now: datetime) -> None:
        await self.input_presentation(turn.parent_id, turn.turn_id)
        await super().submit(turn, reserved_tokens=reserved_tokens, now=now)

    def _valid_decision(
        self, db: sqlite3.Connection, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> bool:
        try:
            self._presentation(db, turn.parent_id, turn.turn_id)
        except ParentChatError:
            return False
        return super()._valid_decision(db, turn, receipt, now)

    def _settle_handoff(
        self, turn: StoredChatTurn, receipt: ChatModelReceipt, now: datetime
    ) -> None:
        with self._connect() as db:
            try:
                self._presentation(db, turn.parent_id, turn.turn_id)
            except ParentChatError:
                receipt = replace(receipt, completed=False)
        super()._settle_handoff(turn, receipt, now)


class SqliteClosedCompactFamilyInputStore(SqliteClosedTariffHandoffStore):
    def __init__(self, path: Path, **family: Any) -> None:
        super().__init__(path, storage_version=34, **family)
        self._schema_version = 35

    def _supported_versions(self) -> set[int]:
        return {35}

    def _allowed_tables(self) -> set[str]:
        return super()._allowed_tables() | {_TABLE}
