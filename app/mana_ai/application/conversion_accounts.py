"""Account-only source port, deliberately separate from child ownership reads."""

from typing import Protocol

from app.mana_ai.domain.conversion_accounts import ConversionAccountFacts


class ConversionAccountSource(Protocol):
    async def read(self, parent_id: str) -> ConversionAccountFacts:
        """One explicit read; callers own durable admission and idempotency."""
        ...
