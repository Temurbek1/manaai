"""Durable fictional linkage fixture; no provider, consent or device mutation."""

import json
from pathlib import Path

from app.mana_ai.application.chat_ports import ParentChildrenSource
from app.mana_ai.domain.chat import ParentChildContext


class LabSetupProfiles:
    def __init__(self, source: ParentChildrenSource, directory: Path) -> None:
        self._source, self._path = source, directory / "parent-setup-fixture.json"
        if self._path.is_symlink():
            raise ValueError("Setup fixture cannot use a symlink")
        if not self._path.exists():
            self._path.write_text(json.dumps({"version": 1, "linked": True}))
        self._linked()

    def _linked(self) -> bool:
        value = json.loads(self._path.read_text())
        if (
            not isinstance(value, dict)
            or set(value) != {"version", "linked"}
            or type(value["version"]) is not int
            or value["version"] != 1
            or type(value["linked"]) is not bool
        ):
            raise ValueError("Invalid fictional setup fixture")
        return bool(value["linked"])

    def set_unlinked(self) -> None:
        self._linked()
        self._path.write_text(json.dumps({"version": 1, "linked": False}))

    async def read(self, parent_id: str) -> ParentChildContext:
        value = await self._source.read(parent_id)
        return ParentChildContext.model_validate(
            value.model_dump()
            | {"children_complete": True, "children": value.children if self._linked() else []}
        )
