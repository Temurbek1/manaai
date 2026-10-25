"""Date-specific family acquisition ports, without source/action grants."""

from datetime import date
from typing import Protocol

from app.mana_ai.domain.family_day_usage import FamilyDayUsagePage, ParentUsageLookup


class ParentUsageIdentitySource(Protocol):
    async def read_usage_lookup(self, parent_id: str) -> ParentUsageLookup: ...


class FamilyDayUsageSource(Protocol):
    async def read(self, parent_id: str, requested_day: date) -> FamilyDayUsagePage:
        """Caller must durably admit the whole bounded read before provider I/O."""
        ...

    async def read_verified(
        self, lookup: ParentUsageLookup, requested_day: date
    ) -> FamilyDayUsagePage:
        """Use the just-verified ephemeral identity without a second profile GET."""
        ...
