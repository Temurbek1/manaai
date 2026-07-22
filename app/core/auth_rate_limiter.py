import asyncio
import time
from collections import deque


class AuthenticationRateLimiter:
    """Per-process limiter for repeated authentication failures by client address."""

    def __init__(self, *, failure_limit: int, window_seconds: int) -> None:
        self._failure_limit = failure_limit
        self._window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def record_failure(self, client_key: str) -> int | None:
        now = time.monotonic()
        cutoff = now - self._window_seconds
        async with self._lock:
            attempts = self._failures.setdefault(client_key, deque())
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            attempts.append(now)
            if len(attempts) < self._failure_limit:
                return None
            return max(int(self._window_seconds - (now - attempts[0])), 1)

    async def clear(self, client_key: str) -> None:
        async with self._lock:
            self._failures.pop(client_key, None)
