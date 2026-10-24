"""Networkless packaged collection reconstruction, using fictional sources/model only."""

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.lab_collection import LabCollectionClock
from app.services.mana_chat_lab import ChatLab, LabOptions


def fingerprint(path: Path) -> str:
    with sqlite3.connect(path) as db:
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return hashlib.sha256(
            repr(
                [
                    (name, db.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall())
                    for (name,) in tables
                ]
            ).encode()
        ).hexdigest()


def options(directory: Path) -> LabOptions:
    return LabOptions(
        directory,
        clock=LabCollectionClock(),
        worker_enabled=False,
        native_sources=True,
        native_observations=True,
        scheduled_collection=True,
    )


async def main() -> None:
    with TemporaryDirectory(prefix="mana-collection-") as temporary:
        directory = Path(temporary) / "lab"
        lab = ChatLab(options(directory))
        await lab.start()
        assert lab.collection is not None
        morning = await lab.collection.collect(9)
        assert morning.status == "completed" and morning.targets == 2
        afternoon = await lab.collection.collect(15)
        assert afternoon.status == "completed"
        assert lab.battery.calls == lab.app_usage.calls == 2
        original = {
            name: fingerprint(directory / name)
            for name in ("collection.sqlite3", "family.sqlite3", "sources.sqlite3")
        }
        await lab.close()
        restarted = ChatLab(options(directory))
        await restarted.start()
        assert restarted.collection is not None
        assert await restarted.collection.collect(9) == morning
        assert await restarted.collection.collect(15) == afternoon
        assert restarted.battery.calls == restarted.app_usage.calls == 0
        assert all(fingerprint(directory / name) == digest for name, digest in original.items())
        await restarted.close()
        print(
            json.dumps(
                {
                    "two_windows": True,
                    "source_targets_per_window": 2,
                    "reconstruction_and_replay_reads": 0,
                    "all_table_fingerprints_preserved": True,
                    "live_sources_or_models_or_contacts": 0,
                    "full_population_verified": False,
                    "production_rollback_verified": False,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
