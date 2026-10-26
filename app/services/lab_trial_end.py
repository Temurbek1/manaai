"""Declared fictional clock for inspecting a free period after its known end."""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.mana_ai.application.chat_ports import ParentChatError


class LabTrialEndClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 10, 26, 9, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance_to_end(self) -> None:
        self._now = datetime(2026, 10, 28, 9, tzinfo=UTC)

    def restore(self, directory: Path) -> None:
        path = directory / "fictional-trial-end.json"
        if path.is_symlink():
            raise ValueError("The fictional trial clock cannot follow a symlink")
        if path.exists():
            if json.loads(path.read_text()) != {"version": 1, "status": "completed"}:
                raise ParentChatError("lab_trial_end_fixture_unresolved", 409)
            self.advance_to_end()
