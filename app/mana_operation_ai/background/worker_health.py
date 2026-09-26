import asyncio
import logging
import time
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def write_worker_heartbeat(path: Path, *, timestamp: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(str(timestamp if timestamp is not None else time.time()), encoding="utf-8")
    temporary.replace(path)


def worker_heartbeat_is_fresh(
    path: Path,
    *,
    max_age_seconds: float,
    timestamp: float | None = None,
) -> bool:
    try:
        recorded_at = float(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    age = (timestamp if timestamp is not None else time.time()) - recorded_at
    return -5.0 <= age <= max_age_seconds


async def run_worker_heartbeat(
    *,
    stop: asyncio.Event,
    path: Path,
    interval_seconds: float,
) -> None:
    while not stop.is_set():
        write_worker_heartbeat(path)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


def main() -> None:
    settings = get_settings()
    if not worker_heartbeat_is_fresh(
        settings.operation_worker_heartbeat_path,
        max_age_seconds=settings.operation_worker_heartbeat_max_age_seconds,
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
