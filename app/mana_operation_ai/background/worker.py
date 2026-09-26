import asyncio
import signal

from app.core.config import get_settings
from app.main import app
from app.mana_operation_ai.background.worker_health import run_worker_heartbeat


async def run_worker() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop.set)
    async with app.router.lifespan_context(app):
        settings = get_settings()
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(
                run_worker_heartbeat(
                    stop=stop,
                    path=settings.operation_worker_heartbeat_path,
                    interval_seconds=settings.operation_worker_heartbeat_interval_seconds,
                ),
            )
            await stop.wait()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
