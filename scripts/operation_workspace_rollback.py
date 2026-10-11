"""Inspect/pause native Goals before application-only rollback; no provider I/O."""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.mana_operation_ai.application.chat_ports import ChatError  # noqa: E402
from app.mana_operation_ai.application.runtime import SystemClock  # noqa: E402
from app.mana_operation_ai.infrastructure.persistence.database import (  # noqa: E402
    OperationDatabase,
)
from app.mana_operation_ai.infrastructure.persistence.goal_repository import (  # noqa: E402
    SqlAlchemyGoalRepository,
)


async def inspect_or_pause(*, apply_pause: bool) -> int:
    database: OperationDatabase | None = None
    try:
        url = get_settings().operation_database_url
        if not url:
            print("Set OPERATION_DATABASE_URL; no database has been changed.", file=sys.stderr)
            return 2
        database = OperationDatabase(url)
        repository = SqlAlchemyGoalRepository(database, SystemClock())
        report = await repository.workspace_rollback(apply_pause=apply_pause)
        print(json.dumps({"mode": "pause" if apply_pause else "inspect", **asdict(report)}))
        return 0
    except ChatError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        # Do not print DB URLs, connection errors or stored private Goal contents.
        print("Workspace rollback check failed; inspect protected server logs.", file=sys.stderr)
        return 2
    finally:
        if database is not None:
            await database.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-pause", action="store_true", help="Pause native Goals only")
    parser.add_argument(
        "--workers-stopped",
        action="store_true",
        help="Attest that all Goals workers have been stopped/drained",
    )
    args = parser.parse_args()
    if args.apply_pause and not args.workers_stopped:
        parser.error("--apply-pause requires --workers-stopped; never race a running worker")
    return asyncio.run(inspect_or_pause(apply_pause=args.apply_pause))


if __name__ == "__main__":
    raise SystemExit(main())
