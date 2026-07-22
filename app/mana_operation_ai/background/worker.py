import asyncio
import signal

from app.main import app


async def run_worker() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signal_name, stop.set)
    async with app.router.lifespan_context(app):
        await stop.wait()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
