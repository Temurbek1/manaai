from pathlib import Path

from app.mana_operation_ai.background.worker_health import (
    worker_heartbeat_is_fresh,
    write_worker_heartbeat,
)


def test_worker_heartbeat_reports_fresh_and_stale_states(tmp_path: Path) -> None:
    path = tmp_path / "worker-heartbeat"

    assert not worker_heartbeat_is_fresh(path, max_age_seconds=60, timestamp=100)

    write_worker_heartbeat(path, timestamp=100)

    assert worker_heartbeat_is_fresh(path, max_age_seconds=60, timestamp=159)
    assert not worker_heartbeat_is_fresh(path, max_age_seconds=60, timestamp=161)


def test_worker_heartbeat_rejects_invalid_and_future_values(tmp_path: Path) -> None:
    path = tmp_path / "worker-heartbeat"
    path.write_text("invalid", encoding="utf-8")
    assert not worker_heartbeat_is_fresh(path, max_age_seconds=60, timestamp=100)

    write_worker_heartbeat(path, timestamp=106)
    assert not worker_heartbeat_is_fresh(path, max_age_seconds=60, timestamp=100)
