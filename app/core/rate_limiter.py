import asyncio
import time
from collections import deque

STALE_KEY_SWEEP_THRESHOLD = 1_024


class RequestRateLimiter:
    """Per-process sliding-window limiter for authenticated API traffic.

    Scope is one process and one client key: behind several replicas each replica enforces
    the budget independently. It bounds abuse from a single caller, not total provider spend.
    """

    def __init__(self, *, request_limit: int, window_seconds: int) -> None:
        self._request_limit = request_limit
        self._window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def consume(self, client_key: str) -> int | None:
        """Charge one request. Returns Retry-After seconds when the caller is over budget."""
        now = time.monotonic()
        cutoff = now - self._window_seconds
        async with self._lock:
            if len(self._hits) > STALE_KEY_SWEEP_THRESHOLD:
                self._sweep(cutoff)
            hits = self._hits.setdefault(client_key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self._request_limit:
                # Rejected requests are not charged, so a blocked caller cannot extend its own
                # penalty by continuing to retry.
                return max(int(self._window_seconds - (now - hits[0])), 1)
            hits.append(now)
            return None

    def _sweep(self, cutoff: float) -> None:
        for key in [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]
