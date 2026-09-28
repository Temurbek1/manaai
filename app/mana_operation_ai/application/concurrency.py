import asyncio
from collections.abc import Awaitable
from typing import Any


async def gather_or_cancel(*awaitables: Awaitable[Any]) -> list[Any]:
    """Preserve gather's result order, but never leave siblings running after failure."""
    tasks = [asyncio.ensure_future(awaitable) for awaitable in awaitables]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        # Cancellation must reach nested provider batches, and their cleanup must finish
        # before the caller releases its run lock or reports the collection as stopped.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
